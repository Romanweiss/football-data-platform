"""Host handoff/TLS security tests: public CA fixture, fake transport, no network."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.httpsession import get_cert_path

from scripts import check_s3_host_readiness as cli
from src.common.s3 import create_s3_client
from src.recovery import s3_host as host
from src.recovery.runtime import RecoveryError


class HostReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ca = Path(self.temp.name) / 'public-ca.pem'
        # Reuse a PUBLIC CA, never generate a real key or use project secrets.
        self.raw = re.search(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                             Path(get_cert_path(True)).read_bytes(), re.S).group() + b'\n'
        self.ca.write_bytes(self.raw)
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.raw.decode())).hexdigest()
        self.enterContext(patch.object(host, 'R6_SHA256', fingerprint))
        self.enterContext(patch.dict(os.environ))
        for name in host.ENVIRONMENT:
            os.environ.pop(name, None)
        self.parameters = dict(zip(host.NAMES, ('https://fixture.invalid', 'fixture-region',
                                               'fixture-bucket', 'synthetic-access', 'synthetic-secret')))
        self.transport = Mock()
        self.transport.docker.return_value = json.dumps(self.parameters).encode()
        self.out, self.err = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        self.enterContext(redirect_stderr(self.err))

    def assert_restored(self):
        self.assertTrue(all(n not in os.environ for n in host.ENVIRONMENT))
        self.assertNotIn('synthetic-secret', self.out.getvalue() + self.err.getvalue())
        self.assertNotIn('synthetic-access', self.out.getvalue() + self.err.getvalue())

    def test_whitelist_only_in_memory_and_removed_on_success(self):
        with host.process_environment('fixture-container', self.ca, transport=self.transport):
            self.assertEqual(os.environ['S3_SECRET_KEY'], 'synthetic-secret')
            self.assertEqual(os.environ['AWS_CA_BUNDLE'], str(self.ca.resolve()))
            self.assertFalse(logging.getLogger('botocore').isEnabledFor(logging.CRITICAL))
        self.assert_restored()
        args, kwargs = self.transport.docker.call_args
        self.assertEqual(kwargs, {'timeout': 30})
        self.assertEqual(args, ('exec', 'fixture-container', '/usr/bin/python3', '-c', host.EXPORT))
        self.assertNotIn('synthetic-secret', repr(args))
        self.assertEqual(list(Path(self.temp.name).iterdir()), [self.ca])

    def test_existing_environment_and_logging_restored_on_error(self):
        os.environ['S3_SECRET_KEY'] = 'prior-synthetic-value'
        previous = logging.root.manager.disable
        with self.assertRaisesRegex(ValueError, 'fixture-error'):
            with host.process_environment('fixture', self.ca, transport=self.transport):
                raise ValueError('fixture-error')
        self.assertEqual(os.environ.pop('S3_SECRET_KEY'), 'prior-synthetic-value')
        self.assertEqual(logging.root.manager.disable, previous)
        self.assert_restored()

    def test_invalid_or_extra_parameters_fail_closed_without_leak(self):
        for value in ([], 'synthetic-secret', {'S3_SECRET_KEY': 'synthetic-secret'},
                      self.parameters | {'POSTGRES_PASSWORD': 'synthetic-secret'},
                      self.parameters | {'S3_SECRET_KEY': 'unsafe\nvalue'}):
            with self.subTest(kind=type(value).__name__):
                self.transport.docker.return_value = json.dumps(value).encode()
                with self.assertRaisesRegex(RecoveryError, '^S3_HOST_PARAMETER_HANDOFF_FAILED$'):
                    with host.process_environment('fixture', self.ca, transport=self.transport):
                        self.fail('must not enter')
                self.assert_restored()

    def test_raw_transport_exception_is_suppressed(self):
        self.transport.docker.side_effect = RuntimeError('synthetic-secret')
        with self.assertRaisesRegex(RecoveryError, '^S3_HOST_PARAMETER_HANDOFF_FAILED$'):
            with host.process_environment('fixture', self.ca, transport=self.transport):
                self.fail('must not enter')
        self.assert_restored()

    def test_invalid_bundle_fails_before_credentials(self):
        self.ca.write_bytes(b'not a CA')
        with self.assertRaises(RecoveryError):
            with host.process_environment('fixture', self.ca, transport=self.transport):
                self.fail('must not enter')
        self.transport.docker.assert_not_called()
        self.assert_restored()

    def test_only_public_pem_and_pinned_r6_accepted(self):
        result = host.validate_ca(self.raw)
        self.assertTrue(result['certificate_verification'])
        self.assertTrue(result['hostname_verification'])
        for raw in (self.raw + b'unexpected data', b'not pem', self.raw + b'-----BEGIN ' + b'PRIVATE KEY-----'):
            with self.assertRaises(RecoveryError):
                host.validate_ca(raw)
        with patch.object(host, 'R6_SHA256', '0' * 64):
            with self.assertRaisesRegex(RecoveryError, 'S3_HOST_CA_R6_MISSING'):
                host.validate_ca(self.raw)

    def test_public_bundle_exclusive_and_idempotent_same_bytes(self):
        self.transport.docker.return_value = self.raw
        destination = self.ca.parent / 'new.pem'
        host.prepare_ca('fixture', destination, transport=self.transport)
        host.prepare_ca('fixture', destination, transport=self.transport)
        self.assertEqual(destination.read_bytes(), self.raw)
        destination.write_bytes(b'existing fixture')
        with self.assertRaisesRegex(RecoveryError, 'S3_HOST_CA_EXISTS_DIFFERENT'):
            host.prepare_ca('fixture', destination, transport=self.transport)
        self.assertEqual(destination.read_bytes(), b'existing fixture')

    def test_actual_sdk_resolves_host_bundle_and_keeps_safe_client_contract(self):
        with host.process_environment('fixture', self.ca, transport=self.transport):
            client = create_s3_client()  # Explicit synthetic credentials; no request.
        self.addCleanup(client.close)
        self.assertEqual(client._endpoint.http_session._verify, str(self.ca.resolve()))
        config = client.meta.config
        self.assertEqual(config.signature_version, 's3v4')
        self.assertEqual(config.s3['addressing_style'], 'virtual')
        self.assertEqual(config.retries, {'mode': 'standard', 'total_max_attempts': 6})
        self.assertEqual((config.connect_timeout, config.read_timeout), (10, 60))
        self.assert_restored()

    def test_audit_removes_temporary_environment_before_metadata_subprocesses(self):
        client = Mock()
        client._endpoint.http_session._verify = str(self.ca.resolve())
        metadata = Mock()
        metadata.snapshot.return_value = {'catalog': {}, 'serving': {}}
        with patch('src.recovery.s3_operator.require_live_runtime'), \
             patch.object(host.runtime, 'docker', self.transport.docker), \
             patch('src.common.s3.create_s3_client', return_value=client), \
             patch('src.recovery.s3_readonly.S3ReadOnly'), \
             patch.object(host.runtime, 'source_container', side_effect=lambda _: self.assert_restored()), \
             patch('src.recovery.s3_metadata.DockerMetadataSource', return_value=metadata), \
             patch('src.recovery.s3_dry_run.audit_source', return_value={'bytes': 7, 'objects': 1}) as audit:
            result = host.readonly_preflight('fixture', self.ca)
        self.assertTrue(result['temporary_environment_restored'])
        self.assertFalse(result['live_backup_executed'])
        self.assertEqual(metadata.snapshot.call_count, 2)
        audit.assert_called_once()
        client.close.assert_called_once()
        self.assert_restored()

    def test_cli_suppresses_raw_exception_and_has_no_backup_or_key_command(self):
        with patch('src.recovery.s3_operator.require_live_runtime'), \
             patch.object(host.runtime, 'source_container', return_value='fixture'), \
             patch.object(host, 'readonly_preflight', side_effect=RuntimeError('synthetic-secret')):
            self.assertEqual(cli.main(['--check-source', '--ca-bundle', str(self.ca)]), 1)
        self.assertEqual(json.loads(self.err.getvalue())['error'], 'S3_HOST_READINESS_FAILED')
        self.assert_restored()
        with self.assertRaises(SystemExit):
            cli.main(['create', '--ca-bundle', str(self.ca)])

    def test_metadata_fence_failure_does_not_pass_and_closes_sdk(self):
        client = Mock()
        client._endpoint.http_session._verify = str(self.ca.resolve())
        metadata = Mock()
        metadata.snapshot.side_effect = [{'catalog': {}, 'serving': {}},
                                         {'catalog': {}, 'serving': {}, 'fixture': 'changed'}]
        with patch('src.recovery.s3_operator.require_live_runtime'), \
             patch.object(host.runtime, 'docker', self.transport.docker), \
             patch('src.common.s3.create_s3_client', return_value=client), \
             patch('src.recovery.s3_readonly.S3ReadOnly'), \
             patch.object(host.runtime, 'source_container', return_value='fixture'), \
             patch('src.recovery.s3_metadata.DockerMetadataSource', return_value=metadata), \
             patch('src.recovery.s3_dry_run.audit_source', return_value={'bytes': 7, 'objects': 1}):
            with self.assertRaisesRegex(RecoveryError, 'S3_METADATA_BASELINE_CHANGED'):
                host.readonly_preflight('fixture', self.ca)
        client.close.assert_called_once()
        self.assert_restored()
