"""Scheduler -> static SDK -> gated create. Fake transports/synthetic bytes ONLY."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from botocore.awsrequest import AWSResponse
from botocore.credentials import Credentials, DeferredRefreshableCredentials, RefreshableCredentials
from botocore.exceptions import NoCredentialsError, ReadTimeoutError, SSLError
from botocore.httpsession import get_cert_path

from scripts import s3_backup as cli
from src.recovery import s3_host as host, s3_operator as operator
from src.recovery.runtime import RecoveryError, digest, encoded
from src.recovery.s3_safety import prepare_directory
from src.recovery.s3_workflow import inventory, verify_backup
from tests.test_s3_readonly import FakeSDK
from tests.test_s3_workflow import fixture


class HostCreateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='football-synthetic-handoff-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ca = self.root / 'public.pem'
        raw = re.search(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                        Path(get_cert_path(True)).read_bytes(), re.S).group() + b'\n'
        self.ca.write_bytes(raw)
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(raw.decode())).hexdigest()
        self.enterContext(patch.object(host, 'R6_SHA256', fingerprint))
        self.enterContext(patch.dict(os.environ))
        for name in host.INHERITED_CREDENTIALS:
            os.environ.pop(name, None)
        self.parameters = dict(zip(host.NAMES, ('https://fixture.invalid', 'fixture-region',
                                               'fixture-bucket', 'synthetic-access', 'synthetic-secret')))
        self.transport = self.enterContext(patch.object(host.runtime, 'docker',
                         return_value=json.dumps(self.parameters).encode()))
        self.enterContext(patch.object(operator, 'require_live_runtime'))
        self.store, self.metadata = fixture()
        self.client = FakeSDK(self.store)
        self.parameters['S3_BUCKET'] = self.store.identity.bucket
        self.transport.return_value = json.dumps(self.parameters).encode()
        self.client._endpoint = SimpleNamespace(http_session=SimpleNamespace(_verify=str(self.ca.resolve())))
        self.client._request_signer = SimpleNamespace(_credentials=Credentials('synthetic-access', 'synthetic-secret'))
        self.client.close = Mock()
        from src.common.s3 import create_s3_client
        self._sdk_factory = create_s3_client
        self.factory = self.enterContext(patch('src.common.s3.create_s3_client', return_value=self.client))
        self.selection = self.enterContext(patch.object(host.runtime, 'source_container',
                             side_effect=self.select_container))
        self.metadata_factory = self.enterContext(patch('src.recovery.s3_metadata.DockerMetadataSource',
                                                       return_value=self.metadata))
        self.out, self.err = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        self.enterContext(redirect_stderr(self.err))
        self.logging_before = logging.root.manager.disable
        for name in ('socket.socket', 'socket.create_connection'):
            self.enterContext(patch(name, side_effect=AssertionError('NO REAL NETWORK')))

    def clean_environment(self):
        self.assertFalse(any(n in os.environ for n in host.INHERITED_CREDENTIALS))

    def select_container(self, service):
        self.clean_environment()
        self.assertIn(service, ('football-airflow-scheduler', 'football-postgres', 'football-clickhouse'))
        return 'synthetic-' + service

    def assert_safe(self):
        self.clean_environment()
        self.assertEqual(logging.root.manager.disable, self.logging_before)
        text = self.out.getvalue() + self.err.getvalue()
        for value in ('synthetic-access', 'synthetic-secret', 'sensitive-provider-message'):
            self.assertNotIn(value, text)

    def options(self):
        # No production key or file: only a test-owned random in-memory value.
        self.master = os.urandom(32)
        self.parent = self.root / 'synthetic-archives'
        prepare_directory(self.parent, confirmed=True)
        self.enterContext(patch('src.recovery.s3_safety.docker_volume_roots', return_value=()))
        self.enterContext(patch('src.recovery.s3_safety.locations',
                               return_value=(self.parent, self.root / 'synthetic.key')))
        self.enterContext(patch('src.recovery.s3_safety.load_key', return_value=self.master))
        from src.recovery.s3_readonly import S3ReadOnly
        source = S3ReadOnly(self.client, self.store.identity.bucket)
        return dict(destination=self.parent, key_file=self.root / 'synthetic.key',
                    expected_source_id=source.identity.resource_id,
                    expected_inventory_sha256=digest(encoded(inventory(source, allow_live_read=True))),
                    confirmed=True, key_recoverable=True, independent_media=True, quiet_window=True,
                    host_ca_bundle=self.ca)

    def test_handoff_cleared_before_metadata_and_workflow_and_client_closed(self):
        with host.scheduler_sources(self.ca) as (source, metadata):
            self.clean_environment()
            self.assertIs(source._client, self.client)
            self.assertIs(metadata, self.metadata)
            self.assertFalse(logging.getLogger('botocore').isEnabledFor(logging.CRITICAL))
        self.client.close.assert_called_once()
        self.assertEqual(self.selection.call_args_list[0].args, ('football-airflow-scheduler',))
        args = self.transport.call_args.args
        self.assertEqual(args, ('exec', 'synthetic-football-airflow-scheduler', '/usr/bin/python3', '-c', host.EXPORT))
        self.assertNotIn('synthetic-secret', repr(args))
        self.assert_safe()

    def test_metadata_child_inherits_no_source_or_aws_secrets(self):
        with host.scheduler_sources(self.ca):
            code = 'import os,json; print(json.dumps(any(n in os.environ for n in ' + repr(host.INHERITED_CREDENTIALS) + ')))'
            result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, check=True)
            self.assertIs(json.loads(result.stdout), False)
        self.assert_safe()

    def test_failure_before_client_creation_cleans_and_does_not_enter_workflow(self):
        self.transport.side_effect = RuntimeError('synthetic-secret')
        with self.assertRaisesRegex(RecoveryError, '^S3_HOST_PARAMETER_HANDOFF_FAILED$'):
            with host.scheduler_sources(self.ca):
                self.fail('must not enter')
        self.factory.assert_not_called()
        self.client.close.assert_not_called()
        self.assert_safe()

    def test_failure_after_client_creation_closes_and_cleans(self):
        with patch('src.recovery.s3_readonly.S3ReadOnly', side_effect=RuntimeError('synthetic-secret')):
            with self.assertRaisesRegex(RecoveryError, '^S3_READ_HTTP_FAILED$'):
                with host.scheduler_sources(self.ca):
                    self.fail('must not enter')
        self.client.close.assert_called_once()
        self.assert_safe()

    def test_metadata_selection_failure_closes_and_no_raw_diagnostic(self):
        def fail_metadata(service):
            self.clean_environment()
            if service == 'football-postgres':
                raise RuntimeError('synthetic-secret')
            return 'synthetic-scheduler'
        self.selection.side_effect = fail_metadata
        with self.assertRaisesRegex(RecoveryError, '^S3_READ_HTTP_FAILED$'):
            with host.scheduler_sources(self.ca):
                self.fail('must not enter')
        self.client.close.assert_called_once()
        self.assert_safe()

    def test_workflow_exception_cleans_and_closes(self):
        with self.assertRaisesRegex(RecoveryError, '^S3_READ_HTTP_FAILED$'):
            with host.scheduler_sources(self.ca):
                self.clean_environment()
                raise RuntimeError('synthetic-secret')
        self.client.close.assert_called_once()
        self.assert_safe()

    def test_sdk_read_errors_after_cleanup_keep_safe_diagnostics_and_close(self):
        for exc, code in ((NoCredentialsError(), 'S3_READ_CREDENTIALS_FAILED'),
                          (SSLError(endpoint_url='https://fixture.invalid', error='synthetic-secret'), 'S3_READ_TLS_FAILED'),
                          (ReadTimeoutError(endpoint_url='https://fixture.invalid', error='synthetic-secret'), 'S3_READ_TIMEOUT')):
            with self.subTest(code=code), patch.object(self.client, 'list_objects_v2', side_effect=exc):
                with self.assertRaisesRegex(RecoveryError, '^' + code + '$') as caught:
                    with host.scheduler_sources(self.ca) as (source, _):
                        self.clean_environment()
                        source.list_page()
                self.assertEqual(caught.exception.operation, 'list_objects_v2')
                self.assert_safe()
        self.assertEqual(self.client.close.call_count, 3)

    def test_close_error_is_suppressed_and_logging_restored(self):
        self.client.close.side_effect = RuntimeError('synthetic-secret')
        with self.assertRaisesRegex(RecoveryError, '^S3_HOST_CLIENT_CLOSE_FAILED$'):
            with host.scheduler_sources(self.ca):
                pass
        self.assert_safe()

    def test_credential_tls_timeout_sdk_errors_have_fixed_safe_codes(self):
        for exc, code in ((NoCredentialsError(), 'S3_READ_CREDENTIALS_FAILED'),
                          (SSLError(endpoint_url='https://fixture.invalid', error='synthetic-secret'), 'S3_READ_TLS_FAILED'),
                          (ReadTimeoutError(endpoint_url='https://fixture.invalid', error='synthetic-secret'), 'S3_READ_TIMEOUT')):
            with self.subTest(code=code):
                self.factory.side_effect = exc
                with self.assertRaisesRegex(RecoveryError, '^' + code + '$') as caught:
                    with host.scheduler_sources(self.ca):
                        self.fail('must not enter')
                self.assertNotIn('synthetic-secret', str(caught.exception))
                self.assert_safe()

    def test_bad_ca_fails_before_handoff_and_tls_mismatch_closes(self):
        self.ca.write_bytes(b'not PEM')
        with self.assertRaises(RecoveryError):
            with host.scheduler_sources(self.ca):
                self.fail('must not enter')
        self.transport.assert_not_called()
        self.factory.assert_not_called()
        self.assert_safe()

    def test_sdk_tls_verification_cannot_be_disabled_or_changed(self):
        for verify in (False, True, 'other.pem'):
            with self.subTest(verify=verify):
                self.client._endpoint.http_session._verify = verify
                with self.assertRaisesRegex(RecoveryError, 'S3_HOST_TLS_REQUIRED'):
                    with host.scheduler_sources(self.ca):
                        self.fail('must not enter')
                self.assert_safe()
        self.assertEqual(self.client.close.call_count, 3)

    def test_refreshable_and_deferred_providers_fail_without_refresh(self):
        refresh = Mock(side_effect=AssertionError('MUST NOT REFRESH'))
        credentials = (RefreshableCredentials('synthetic-access', 'synthetic-secret', None,
                          datetime(2099, 1, 1, tzinfo=timezone.utc), refresh, 'synthetic-refresh'),
                       DeferredRefreshableCredentials(refresh, 'synthetic-deferred'))
        for value in credentials:
            with self.subTest(kind=type(value).__name__):
                self.client._request_signer._credentials = value
                with self.assertRaisesRegex(RecoveryError, 'S3_HOST_STATIC_CREDENTIALS_REQUIRED'):
                    with host.scheduler_sources(self.ca):
                        self.fail('must not enter')
                self.assert_safe()
        refresh.assert_not_called()

    def test_wrong_static_credential_binding_or_nonexplicit_provider_is_refused(self):
        for value, code in ((Credentials('other', 'synthetic-secret'), 'S3_HOST_CREDENTIAL_BINDING_FAILED'),
                            (Credentials('synthetic-access', 'other'), 'S3_HOST_CREDENTIAL_BINDING_FAILED'),
                            (Credentials('synthetic-access', 'synthetic-secret', token='synthetic-token'), 'S3_HOST_CREDENTIAL_BINDING_FAILED'),
                            (Credentials('synthetic-access', 'synthetic-secret', method='env'), 'S3_HOST_STATIC_CREDENTIALS_REQUIRED')):
            self.client._request_signer._credentials = value
            with self.assertRaisesRegex(RecoveryError, code):
                with host.scheduler_sources(self.ca):
                    self.fail('must not enter')
            self.assert_safe()

    def test_existing_environment_refused_before_docker_no_fallback(self):
        for name in host.INHERITED_CREDENTIALS:
            with self.subTest(name=name), patch.dict(os.environ, {name: 'synthetic-secret'}):
                with self.assertRaisesRegex(RecoveryError, 'S3_HOST_CLEAN_ENVIRONMENT_REQUIRED'):
                    with host.scheduler_sources(self.ca):
                        self.fail('must not enter')
                self.assertEqual(os.environ[name], 'synthetic-secret')
        self.selection.assert_not_called()
        self.transport.assert_not_called()
        self.assert_safe()

    def test_real_botocore_signs_after_environment_clear_without_provider_reload(self):
        # Undo ONLY the fake factory; real SDK, fake HTTP send, sockets still blocked.
        self.factory.side_effect = self._sdk_factory
        self.enterContext(patch('botocore.credentials.CredentialResolver.load_credentials',
                                side_effect=AssertionError('NO PROVIDER RESOLUTION OR RELOAD')))
        with host.scheduler_sources(self.ca) as (source, _):
            client = source._client
            self.clean_environment()
            self.assertEqual(client.meta.config.signature_version, 's3v4')
            self.assertEqual(client.meta.config.s3['addressing_style'], 'virtual')
            class Raw:
                def stream(self, *args, **kwargs):
                    yield b'<ListBucketResult><KeyCount>0</KeyCount><IsTruncated>false</IsTruncated></ListBucketResult>'
            def send(request):
                self.clean_environment()
                self.assertIn(b'Credential=synthetic-access/', request.headers['Authorization'])
                return AWSResponse(request.url, 200, {'content-type': 'application/xml'}, Raw())
            with patch.object(client._endpoint.http_session, 'send', side_effect=send) as transport:
                page = source.list_page()
                source.list_page()
            self.assertEqual(page.key_count, 0)
            self.assertEqual(transport.call_count, 2)
        self.assert_safe()

    def test_all_confirmations_and_expected_inventory_required_before_handoff(self):
        options = dict(destination='synthetic', key_file='synthetic', expected_source_id='synthetic',
                       expected_inventory_sha256='a' * 64, confirmed=True, key_recoverable=True,
                       independent_media=True, quiet_window=True, host_ca_bundle=self.ca)
        for name in ('confirmed', 'key_recoverable', 'independent_media', 'quiet_window'):
            with self.subTest(name=name), self.assertRaisesRegex(RecoveryError, 'S3_OPERATOR_CONFIRMATIONS_REQUIRED'):
                operator.create(**(options | {name: False}))
        with self.assertRaisesRegex(RecoveryError, 'S3_EXPECTED_SOURCE_AND_INVENTORY_REQUIRED'):
            operator.create(**(options | {'expected_inventory_sha256': 'stale-placeholder'}))
        self.selection.assert_not_called()
        self.transport.assert_not_called()

    def test_host_environment_conflict_blocks_before_mount_discovery_or_key_reads(self):
        options = dict(destination='synthetic', key_file='synthetic', expected_source_id='synthetic',
                       expected_inventory_sha256='a' * 64, confirmed=True, key_recoverable=True,
                       independent_media=True, quiet_window=True, host_ca_bundle=self.ca)
        with patch.dict(os.environ, {'S3_SECRET_KEY': 'synthetic-secret'}), \
             patch('src.recovery.s3_safety.docker_volume_roots') as roots, \
             patch('src.recovery.s3_safety.load_key') as key:
            with self.assertRaisesRegex(RecoveryError, 'S3_HOST_CLEAN_ENVIRONMENT_REQUIRED'):
                operator.create(**options)
        roots.assert_not_called()
        key.assert_not_called()
        self.transport.assert_not_called()
        self.assert_safe()

    def test_full_fake_create_keeps_fences_and_encrypted_archive_verification(self):
        options = self.options()
        original = self.metadata.snapshot
        def snapshot():
            self.clean_environment()
            return original()
        self.metadata.snapshot = snapshot
        with patch.object(operator, 'build_sources', side_effect=AssertionError('NO LEGACY FALLBACK')):
            result = operator.create(**options)
        self.assertEqual(result['status'], 'SEALED_LIVE_ARCHIVE')  # Fake source only.
        report = verify_backup(result['directory'], self.master)
        self.assertEqual(report['source_objects'], len(self.store.objects))
        self.client.close.assert_called_once()
        self.assert_safe()

    def test_stale_inventory_or_identity_closes_client_without_session(self):
        options = self.options()
        for change, error in (({'expected_source_id': 'other'}, 'S3_SOURCE_IDENTITY_MISMATCH'),
                              ({'expected_inventory_sha256': '0' * 64}, 'S3_PREFLIGHT_INVENTORY_CHANGED')):
            with self.subTest(error=error), self.assertRaisesRegex(RecoveryError, error):
                operator.create(**(options | change))
            self.assertEqual(list(self.parent.iterdir()), [])
            self.assert_safe()
        self.assertEqual(self.client.close.call_count, 2)

    def test_final_metadata_mutation_never_seals_and_closes_host_client(self):
        options = self.options()
        baseline = self.metadata.snapshot()
        self.metadata.snapshot = Mock(side_effect=[baseline, {'catalog': {}, 'serving': {}}])
        with self.assertRaisesRegex(RecoveryError, 'S3_METADATA_BASELINE_CHANGED'):
            operator.create(**options)
        self.assertFalse(any(self.parent.glob('*/manifest.json')))
        self.client.close.assert_called_once()
        self.assert_safe()

    def test_cli_host_flag_does_not_implicitly_create_or_bypass_gates(self):
        with patch.object(operator, 'create', side_effect=AssertionError('NO AUTOMATIC CREATE')) as create, \
             patch.object(operator, 'preflight', return_value={'status': 'BLOCKED'}):
            self.assertEqual(cli.main([]), 1)
            self.assertEqual(cli.main(['--host-ca-bundle', str(self.ca)]), 1)
            create.assert_not_called()
        self.assertIn('S3_HOST_HANDOFF_CREATE_ONLY', self.err.getvalue())
        self.assertEqual(cli.main(['create', '--host-ca-bundle', str(self.ca)]), 1)
        self.assertIn('S3_OPERATOR_CONFIRMATIONS_REQUIRED', self.err.getvalue())
        self.transport.assert_not_called()
        self.assert_safe()

    def test_cli_explicit_host_route_passes_paths_not_secret_material(self):
        with patch.object(operator, 'create', return_value={'status': 'SYNTHETIC_STUB_ONLY'}) as create:
            self.assertEqual(cli.main(['create', '--host-ca-bundle', str(self.ca)]), 0)
        self.assertEqual(create.call_args.kwargs['host_ca_bundle'], self.ca)
        self.assertFalse(create.call_args.kwargs['confirmed'])
        self.transport.assert_not_called()
        self.assert_safe()
