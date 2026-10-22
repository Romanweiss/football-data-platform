"""Fault-injected SDK/CLI diagnostics, never a real S3 call or real secret."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import ssl
import unittest
from unittest.mock import patch

from botocore import exceptions as sdk

from scripts import check_s3_host_readiness as cli
from src.recovery.runtime import RecoveryError
from src.recovery.s3_diagnostics import S3ReadError, read_error, safe_diagnostic
from src.recovery.s3_readonly import S3ReadOnly
from tests.test_s3_readonly import FakeSDK, ProviderError
from tests.test_s3_workflow import fixture

SENTINEL = 'synthetic-sensitive-value-must-not-appear'


class S3DiagnosticTests(unittest.TestCase):
    def test_tls_timeout_credentials_and_403_are_distinguishable_without_raw_text(self):
        cases = (
            (ssl.SSLCertVerificationError(SENTINEL), 'TLS_FAILURE', 'S3_READ_TLS_FAILED'),
            (sdk.SSLError(endpoint_url='https://fixture.invalid', error=SENTINEL), 'TLS_FAILURE', 'S3_READ_TLS_FAILED'),
            (TimeoutError(SENTINEL), 'TIMEOUT', 'S3_READ_TIMEOUT'),
            (sdk.ConnectTimeoutError(endpoint_url='https://fixture.invalid'), 'TIMEOUT', 'S3_READ_TIMEOUT'),
            (sdk.ReadTimeoutError(endpoint_url='https://fixture.invalid'), 'TIMEOUT', 'S3_READ_TIMEOUT'),
            (sdk.NoCredentialsError(), 'CREDENTIAL_FAILURE', 'S3_READ_CREDENTIALS_FAILED'),
            (sdk.PartialCredentialsError(provider=SENTINEL, cred_var=SENTINEL),
             'CREDENTIAL_FAILURE', 'S3_READ_CREDENTIALS_FAILED'),
            (sdk.CredentialRetrievalError(provider=SENTINEL, error_msg=SENTINEL),
             'CREDENTIAL_FAILURE', 'S3_READ_CREDENTIALS_FAILED'),
            (ProviderError(403), 'ACCESS_DENIED', 'S3_READ_HTTP_403'),
            (RuntimeError(SENTINEL), 'TRANSPORT_FAILURE', 'S3_READ_HTTP_FAILED'),
        )
        for error, category, code in cases:
            with self.subTest(category=category):
                result = safe_diagnostic(read_error(error, 'head_object'))
                self.assertEqual(result, {'category': category, 'code': code, 'operation': 'head_object'})
                self.assertNotIn(SENTINEL, json.dumps(result))

    def test_provider_credential_code_is_not_confused_with_generic_access_denied(self):
        for code in ('InvalidAccessKeyId', 'SignatureDoesNotMatch', 'ExpiredToken'):
            error = sdk.ClientError({'Error': {'Code': code, 'Message': SENTINEL},
                                     'ResponseMetadata': {'HTTPStatusCode': 403}}, 'HeadObject')
            result = safe_diagnostic(read_error(error, 'head_object'))
            self.assertEqual(result['category'], 'CREDENTIAL_FAILURE')
            self.assertEqual(result['code'], 'S3_READ_HTTP_403')  # Legacy control flow stays compatible.
            self.assertNotIn(SENTINEL, json.dumps(result))

    def test_404_412_and_optional_403_semantics_remain_unchanged(self):
        for status in (403, 404, 412):
            self.assertEqual(str(read_error(ProviderError(status), 'get_object')), f'S3_READ_HTTP_{status}')
        storage, _ = fixture()
        source = S3ReadOnly(FakeSDK(storage), storage.identity.bucket)
        self.assertTrue(all(item == {'access': 'HTTP_403', 'state': 'UNKNOWN'}
                            for item in source.optional_capabilities().values()))

    def test_adapter_and_stream_preserve_type_diagnostics_through_existing_guards(self):
        storage, _ = fixture()
        client = FakeSDK(storage)
        source = S3ReadOnly(client, storage.identity.bucket)
        key = next(iter(storage.objects))
        with patch.object(client, 'head_object', side_effect=sdk.ReadTimeoutError(endpoint_url='https://fixture.invalid')):
            with self.assertRaises(S3ReadError) as raised:
                source.head_object(key)
        self.assertEqual(safe_diagnostic(raised.exception)['category'], 'TIMEOUT')
        head = source.head_object(key)
        with source.get_object(key, expected=head) as result:
            with patch.object(result.body.raw, 'read', side_effect=TimeoutError(SENTINEL)):
                with self.assertRaises(S3ReadError) as raised:
                    result.body.read(1)
            self.assertTrue(result.body.closed)
        report = safe_diagnostic(raised.exception)
        self.assertEqual(report, {'code': 'S3_STREAM_READ_FAILED', 'category': 'TIMEOUT', 'operation': 'read_body'})
        self.assertNotIn(SENTINEL, json.dumps(report))

    def test_metadata_inconsistency_remains_distinct_from_transport_errors(self):
        for code in ('S3_METADATA_BASELINE_CHANGED', 'S3_CATALOG_BUCKET', 'S3_DETERMINISTIC_BUILD_ID',
                     'S3_BRONZE_BYTES_MISMATCH'):
            result = safe_diagnostic(RecoveryError(code))
            self.assertEqual(result['category'], 'METADATA_INCONSISTENCY')
            self.assertEqual(result['code'], code)

    def test_unknown_messages_and_malformed_error_attributes_fail_closed(self):
        errors = [RuntimeError(SENTINEL), RecoveryError(SENTINEL),
                  S3ReadError(SENTINEL, 'TIMEOUT', 'head_object'),
                  S3ReadError('S3_READ_TIMEOUT', SENTINEL, 'head_object'),
                  S3ReadError('S3_READ_TIMEOUT', 'TIMEOUT', SENTINEL),
                  S3ReadError('S3_READ_TIMEOUT', [], 'head_object')]
        for error in errors:
            with self.subTest(kind=type(error).__name__):
                result = safe_diagnostic(error)
                self.assertEqual(result['category'], 'UNKNOWN')
                self.assertNotIn(SENTINEL, json.dumps(result))

    def test_cli_exposes_safe_category_and_operation_without_secret_text(self):
        for error in (read_error(sdk.SSLError(endpoint_url='https://fixture.invalid', error=SENTINEL), 'get_object'),
                      read_error(ProviderError(403), 'head_object'),
                      read_error(TimeoutError(SENTINEL), 'list_objects_v2'),
                      RecoveryError('S3_METADATA_BASELINE_CHANGED'), RuntimeError(SENTINEL)):
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors), \
                 patch('src.recovery.s3_operator.require_live_runtime'), \
                 patch('src.recovery.runtime.source_container', return_value='fixture'), \
                 patch('src.recovery.s3_host.readonly_preflight', side_effect=error):
                self.assertEqual(cli.main(['--check-source', '--ca-bundle', 'fixture.pem']), 1)
            report = json.loads(errors.getvalue())
            self.assertEqual(report['diagnostic'], safe_diagnostic(error))
            self.assertEqual(report['stage'], 'bounded-host-source-audit')
            self.assertNotIn(SENTINEL, output.getvalue() + errors.getvalue())
