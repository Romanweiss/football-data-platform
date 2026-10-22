"""R2.3-D safety gates and shared full workflow with ONLY fake SDK/data/keys."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import s3_backup as cli
from src.recovery import s3_archive, s3_operator as operator
from src.recovery.archive import private_directory
from src.recovery.runtime import RecoveryError, digest, encoded
from src.recovery.s3_readonly import FullReadBudget, S3ReadOnly
from src.recovery.s3_storage import SyntheticObject
from src.recovery.s3_safety import (
    assert_private, check_space, generate_key, load_key, locations, prepare_directory, safe_path, space_plan,
)
from src.recovery.s3_workflow import backup_live, inventory, verify_backup
from tests.test_s3_readonly import FakeSDK
from tests.test_s3_workflow import fixture

SUPPORTED = {'python': '3.12.14', 'live_python_supported': True, 'required_live_python': '3.12.14',
             'dependencies': {'cryptography': True, 'boto3': True}, 'docker_cli': True,
             'sqlite_required_for_s3': False, 'host_runtime': True}


class S3OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent, self.vault = self.root / 'archives', self.root / 'key-vault'
        for path in (self.parent, self.vault):
            prepare_directory(path, confirmed=True)
        self.key_path = self.vault / 'synthetic.key'
        generate_key(self.key_path, confirmed=True)
        self.store, self.metadata = fixture()
        self.source = S3ReadOnly(FakeSDK(self.store), self.store.identity.bucket)
        self.observed = inventory(self.source, allow_live_read=True)
        self.options = {'destination': self.parent, 'key_file': self.key_path,
                        'expected_source_id': self.source.identity.resource_id,
                        'expected_inventory_sha256': digest(encoded(self.observed)),
                        'confirmed': True, 'key_recoverable': True, 'independent_media': True, 'quiet_window': True}
        for name in ('socket.socket', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('NO REAL NETWORK'))
            guard.start()
            self.addCleanup(guard.stop)
        for name, value in (('runtime_report', lambda: deepcopy(SUPPORTED)),
                            ('build_sources', lambda: (self.source, self.metadata))):
            guard = patch.object(operator, name, side_effect=value)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch('src.recovery.s3_safety.docker_volume_roots', return_value=())
        guard.start()
        self.addCleanup(guard.stop)

    def create(self, **kwargs):
        return operator.create(**(self.options | kwargs))

    def assert_no_seal(self):
        self.assertFalse(any(self.parent.glob('*/manifest.json')))

    def test_full_fake_sdk_workflow_and_safe_verify_inspect(self):
        # Explicit full-read quota must support payloads above the dry-run cap.
        self.store.objects['opaque/large-binary'] = SyntheticObject(b'x' * (1024 * 1024 + 17))
        self.options['expected_inventory_sha256'] = digest(encoded(inventory(self.source, allow_live_read=True)))
        result = self.create()
        self.assertEqual(result['status'], 'SEALED_LIVE_ARCHIVE')
        self.assertFalse(result['independent_storage_verified'])
        report = operator.verify(result['directory'], self.key_path)
        self.assertEqual(report['source_objects'], len(self.store.objects))
        self.assertEqual(report['scope'], 'LIVE_CURRENT_OBJECTS_ARCHIVE')
        self.assertEqual(report['lineage']['published_builds'], 4)
        self.assertFalse(report['remote_s3_restore_verified'])
        self.assertTrue(all(s.closed for s in self.source._client.streams))
        encoded_report = encoded(report)
        self.assertNotIn(load_key(self.key_path), encoded_report)
        self.assertNotIn(b'source.json', encoded_report)
        self.assertEqual(s3_archive.verify_archive(result['directory'], load_key(self.key_path)).core['schema_version'], 2)

    def test_read_only_preflight_does_not_create_session(self):
        with patch.dict(os.environ, {n: 'synthetic-presence-only' for n in
                        ('S3_ENDPOINT', 'S3_REGION', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET', 'AWS_CA_BUNDLE')}):
            result = operator.preflight(destination=self.parent, key_file=self.key_path, check_source=True)
        self.assertEqual(result['status'], 'PREFLIGHT_PASS_OPERATOR_CONFIRMATIONS_STILL_REQUIRED')
        self.assertEqual(result['plan']['source_objects'], len(self.store.objects))
        self.assertFalse(result['writes_performed'])
        self.assertEqual(list(self.parent.iterdir()), [])
        self.assertNotIn(b'synthetic-presence-only', encoded(result))

    def test_default_cli_no_sdk_or_destination_writes(self):
        out = io.StringIO()
        with patch.object(operator, 'build_sources', side_effect=AssertionError('no SDK by default')), redirect_stdout(out):
            self.assertEqual(cli.main([]), 1)
        self.assertIn('S3_DESTINATION_AND_SEPARATE_KEY_REQUIRED', out.getvalue())
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_estimate_is_not_fresh_inventory(self):
        result = operator.preflight(source_bytes=356383409, source_objects=315)
        self.assertIn('S3_FRESH_SOURCE_PREFLIGHT_REQUIRED', result['blockers'])
        self.assertEqual(result['source_basis'], 'OPERATOR_ESTIMATE_NOT_FRESH_INVENTORY')
        self.assertGreater(result['plan']['required_free_bytes'], 356383409)

    def test_confirmations_fail_before_key_or_source_io(self):
        for option in ('confirmed', 'key_recoverable', 'independent_media', 'quiet_window'):
            with self.subTest(option=option), patch.object(operator, 'build_sources', side_effect=AssertionError('no SDK')):
                with self.assertRaisesRegex(RecoveryError, 'S3_OPERATOR_CONFIRMATIONS_REQUIRED'):
                    self.create(**{option: False})
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_missing_destination_and_invalid_source_identity(self):
        for destination in (None, self.root / 'missing'):
            with self.subTest(destination=destination), self.assertRaises(RecoveryError):
                self.create(destination=destination)
        with self.assertRaisesRegex(RecoveryError, 'S3_SOURCE_IDENTITY_MISMATCH'):
            self.create(expected_source_id='different-bucket')
        self.assert_no_seal()

    def test_workspace_traversal_secrets_roots_and_volumes_refused(self):
        from src.recovery.s3_safety import WORKSPACE
        for path in (WORKSPACE / 'backups', WORKSPACE.parent, self.root / '..' / 'outside',
                     self.root / 'secrets' / 'output', Path(self.root.anchor)):
            with self.subTest(path=path), self.assertRaises(RecoveryError):
                safe_path(path)
        with self.assertRaisesRegex(RecoveryError, 'S3_DOCKER_VOLUME_PATH_REFUSED'):
            safe_path(self.parent, forbidden_roots=(self.root,))
        with self.assertRaises(RecoveryError):
            safe_path('relative/backup')
        other_repository = self.root / 'other-repository'
        other_repository.mkdir()
        (other_repository / '.git').mkdir()
        with self.assertRaisesRegex(RecoveryError, 'S3_GIT_WORKSPACE_PATH_REFUSED'):
            safe_path(other_repository / 'archive')

    def test_key_inside_or_above_archive_tree_refused(self):
        for key in (self.parent / 'inside.key', self.root / 'too-broad.key'):
            with self.subTest(key=key), self.assertRaisesRegex(RecoveryError, 'S3_KEY_MUST_BE_SEPARATE'):
                locations(self.parent, key)

    def test_no_key_generation_or_overwrite_by_default(self):
        with self.assertRaisesRegex(RecoveryError, 'S3_KEY_GENERATION_CONFIRMATION_REQUIRED'):
            generate_key(self.vault / 'never-created.key')
        self.assertFalse((self.vault / 'never-created.key').exists())
        with self.assertRaisesRegex(RecoveryError, 'S3_NEW_KEY_FILE_REQUIRED'):
            generate_key(self.key_path, confirmed=True)
        with self.assertRaisesRegex(RecoveryError, 'S3_NEW_DIRECTORY_REQUIRED'):
            prepare_directory(self.parent, confirmed=True)

    def test_new_directory_setup_and_permissions_are_checked(self):
        target = self.root / 'new-private'
        with self.assertRaisesRegex(RecoveryError, 'S3_DIRECTORY_CREATION_CONFIRMATION_REQUIRED'):
            prepare_directory(target)
        self.assertFalse(target.exists())
        prepare_directory(target, confirmed=True)
        assert_private(target)
        with patch('src.recovery.s3_safety.private_directory', side_effect=OSError('private-secret-error')):
            with self.assertRaises(RecoveryError):
                prepare_directory(self.root / 'failed-private', confirmed=True)
        self.assertTrue((self.root / 'failed-private').exists())  # No cleanup of uncertain state.

    def test_insufficient_space_prevents_session_and_full_get(self):
        with patch('src.recovery.s3_safety.shutil.disk_usage', return_value=shutil._ntuple_diskusage(1, 1, 0)):
            with self.assertRaisesRegex(RecoveryError, 'S3_INSUFFICIENT_FREE_SPACE'):
                self.create()
        self.assertEqual(self.source.calls['get'], 0)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_unverifiable_permissions_fail_closed(self):
        with patch('src.recovery.s3_safety.assert_private', side_effect=RecoveryError('S3_UNSAFE_PERMISSIONS')):
            with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                self.create()
        self.assertEqual(list(self.parent.iterdir()), [])
        from src.recovery.s3_safety import session_permissions
        def late_failure(path, *, initialize=False):
            if (path / 'index.json.enc').exists():
                raise RecoveryError('S3_UNSAFE_PERMISSIONS')
            return session_permissions(path, initialize=initialize)
        with patch('src.recovery.s3_safety.session_permissions', side_effect=late_failure):
            with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                self.create()
        self.assert_no_seal()

    def test_posix_other_read_permissions_are_rejected(self):
        if os.name == 'nt':
            # The Windows ACL path is exercised by every real fixture gate above.
            with patch('src.recovery.s3_safety.run', return_value=b'{"safe":false}'):
                with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                    assert_private(self.parent)
        else:
            self.parent.chmod(0o755)
            with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                assert_private(self.parent)
            self.parent.chmod(0o700)

    def test_wrong_key_and_safe_manifest_are_rejected(self):
        result = self.create()
        wrong = self.vault / 'wrong-synthetic.key'
        generate_key(wrong, confirmed=True)
        with self.assertRaisesRegex(RecoveryError, 'AUTHENTICATION'):
            operator.verify(result['directory'], wrong)

    def test_interrupted_backup_is_unsealed_and_new_session_can_restart(self):
        with patch.object(self.source, 'get_object', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.create()
        self.assert_no_seal()
        first = set(self.parent.iterdir())
        self.assertEqual(len(first), 1)
        self.assertTrue(all((p / 'aborted.json').exists() for p in first))
        self.source = S3ReadOnly(FakeSDK(self.store), self.store.identity.bucket)
        result = self.create()
        self.assertNotIn(Path(result['directory']), first)
        self.assertEqual(len(list(self.parent.iterdir())), 2)

    def test_repeated_run_new_uuid_no_overwrite(self):
        one = self.create()
        original = (Path(one['directory']) / 'manifest.json').read_bytes()
        self.source = S3ReadOnly(FakeSDK(self.store), self.store.identity.bucket)
        two = self.create()
        self.assertNotEqual(one['directory'], two['directory'])
        self.assertEqual((Path(one['directory']) / 'manifest.json').read_bytes(), original)

    def test_bronze_original_sha_mismatch_never_seals(self):
        key = next(k for k in self.store.objects if '/match_events/' in k)
        self.store.objects[key].payload = bytes([self.store.objects[key].payload[0] ^ 1]) + self.store.objects[key].payload[1:]
        self.options['expected_inventory_sha256'] = digest(encoded(inventory(self.source, allow_live_read=True)))
        with self.assertRaisesRegex(RecoveryError, 'S3_BRONZE_BYTES_MISMATCH'):
            self.create()
        self.assert_no_seal()

    def test_prefight_inventory_change_never_starts_full_get(self):
        with self.assertRaisesRegex(RecoveryError, 'S3_PREFLIGHT_INVENTORY_CHANGED'):
            self.create(expected_inventory_sha256='0' * 64)
        self.assertEqual(self.source.calls['get'], 0)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_metadata_receipt_change_never_seals(self):
        before = self.metadata.snapshot()
        after = deepcopy(before)
        after['catalog']['clickhouse_loads'][0]['row_count'] += 1
        with patch.object(self.metadata, 'snapshot', side_effect=[before, after]):
            with self.assertRaisesRegex(RecoveryError, 'S3_METADATA_BASELINE_CHANGED'):
                self.create()
        self.assert_no_seal()

    def test_source_metadata_mutation_never_seals(self):
        original = self.source.authorize_full_read
        def mutate(*args, **kwargs):
            original(*args, **kwargs)
            self.store.objects[next(iter(self.store.objects))].metadata['changed'] = 'fixture'
        with patch.object(self.source, 'authorize_full_read', side_effect=mutate):
            with self.assertRaisesRegex(RecoveryError, 'GET_HEAD_STATE_CHANGED'):
                self.create()
        self.assert_no_seal()

    def test_final_inventory_mutation_never_seals(self):
        original = s3_archive.S3ArchiveWriter.verify_pending
        def mutate(writer):
            result = original(writer)
            self.store.objects[next(iter(self.store.objects))].metadata['after-get'] = 'synthetic'
            return result
        with patch.object(s3_archive.S3ArchiveWriter, 'verify_pending', mutate):
            with self.assertRaisesRegex(RecoveryError, 'S3_SOURCE_CHANGED'):
                self.create()
        self.assert_no_seal()

    def test_missing_object_unavailable_source_and_ignored_condition(self):
        original = self.source.list_page
        with patch.object(self.source, 'list_page', side_effect=OSError('provider-sensitive-data')):
            with self.assertRaisesRegex(RecoveryError, '^S3_WORKFLOW_OPERATION_FAILED$'):
                self.create()
        self.source._client.ignore_conditions = True
        with self.assertRaisesRegex(RecoveryError, 'CONDITIONAL_GET_NOT_ENFORCED'):
            self.create()
        self.source._client.ignore_conditions = False
        self.store.objects.pop(next(iter(self.store.objects)))
        self.options['expected_inventory_sha256'] = digest(encoded(inventory(self.source, allow_live_read=True)))
        with self.assertRaisesRegex(RecoveryError, 'REGISTERED_OBJECT_MISSING'):
            self.create()
        self.assertEqual(self.source.list_page, original)
        self.assert_no_seal()

    def test_short_stream_never_seals(self):
        original = self.source.get_object
        def short(*args, **kwargs):
            result = original(*args, **kwargs)
            result.body.raw.close()
            result.body.raw = io.BytesIO(b'')
            return result
        with patch.object(self.source, 'get_object', side_effect=short):
            with self.assertRaisesRegex(RecoveryError, 'S3_STREAM_TRUNCATED'):
                self.create()
        self.assert_no_seal()

    def test_ciphertext_readback_checksum_failure_never_seals(self):
        original = s3_archive.S3ArchiveWriter.verify_pending
        def corrupt(writer):
            path = next(writer.directory.glob('object-*.enc'))
            raw = bytearray(path.read_bytes())
            raw[-1] ^= 1
            path.write_bytes(raw)
            return original(writer)
        with patch.object(s3_archive.S3ArchiveWriter, 'verify_pending', corrupt):
            with self.assertRaisesRegex(RecoveryError, 'CIPHERTEXT_CHECKSUM'):
                self.create()
        self.assert_no_seal()

    def test_cannot_seal_and_key_changed_during_collection(self):
        with patch.object(s3_archive.S3ArchiveWriter, 'seal', side_effect=OSError('cannot seal')):
            with self.assertRaises(RecoveryError):
                self.create()
        self.assert_no_seal()
        self.source = S3ReadOnly(FakeSDK(self.store), self.store.identity.bucket)
        original = self.source.authorize_full_read
        def change_key(*args, **kwargs):
            original(*args, **kwargs)
            self.key_path.write_bytes(b'x' * 32)
        with patch.object(self.source, 'authorize_full_read', side_effect=change_key):
            with self.assertRaisesRegex(RecoveryError, 'S3_KEY_CHANGED_DURING_BACKUP'):
                self.create()
        self.assert_no_seal()

    def test_full_budget_is_explicit_bounded_and_read_only(self):
        with self.assertRaisesRegex(RecoveryError, 'CONFIRMATION'):
            self.source.authorize_full_read(self.observed)
        self.source.authorize_full_read(self.observed, confirmed=True)
        self.assertIsInstance(self.source.budget, FullReadBudget)
        self.assertEqual(self.source.budget.max_total_bytes, sum(v['head']['size_bytes'] for v in self.observed.values()))
        with self.assertRaises(RecoveryError):
            S3ReadOnly(FakeSDK(self.store), self.store.identity.bucket, budget=FullReadBudget())

    def test_live_archive_not_accepted_by_synthetic_restore(self):
        result = self.create()
        with self.assertRaisesRegex(RecoveryError, 'S3_SYNTHETIC_ONLY'):
            s3_archive.restore_synthetic(result['directory'], load_key(self.key_path), self.root / 'no-restore')
        self.assertFalse((self.root / 'no-restore').exists())

    def test_hardlinked_or_symlinked_key_refused(self):
        alias = self.vault / 'alias.key'
        os.link(self.key_path, alias)
        with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PRIVATE_FILE'):
            load_key(alias)
        alias.unlink()
        # Symlink setup is unavailable without privileges on some Windows hosts.
        try:
            alias.symlink_to(self.key_path)
        except OSError:
            return
        with self.assertRaisesRegex(RecoveryError, 'S3_LINK_REFUSED'):
            safe_path(alias)

    def test_runtime_guard_not_any_matrix_python_and_sqlite_not_required(self):
        unsupported = SUPPORTED | {'live_python_supported': False, 'python': '3.10.12'}
        with patch.object(operator, 'runtime_report', return_value=unsupported):
            with self.assertRaisesRegex(RecoveryError, 'S3_LIVE_PYTHON_UNSUPPORTED'):
                self.create()
        self.assertEqual(list(self.parent.iterdir()), [])
        self.assertFalse(operator.runtime_report()['sqlite_required_for_s3'])
        with patch.object(operator, 'runtime_report', return_value=SUPPORTED | {'host_runtime': False}):
            with self.assertRaisesRegex(RecoveryError, 'S3_OPERATOR_HOST_RUNTIME_REQUIRED'):
                self.create()

    def test_cli_confirmation_failures_are_safe_and_no_resume_cleanup_command(self):
        for action in ('create', 'keygen', 'init-directory'):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main([action]), 1)
            self.assertIn('CONFIRMATION', err.getvalue())
            self.assertNotIn(str(self.key_path), out.getvalue() + err.getvalue())
        self.assert_no_seal()


class S3RuntimePolicyTests(unittest.TestCase):
    """Exact host policy; no SDK, Docker, key or directory setup is required."""

    def test_exact_platform_patch_and_architecture_allowlist(self):
        versions = ((3, 10, 12), (3, 11, 9), (3, 12, 9), (3, 12, 10),
                    (3, 12, 11), (3, 12, 14), (3, 12, 15), (3, 13, 7), (3, 14, 3))
        for system in ('win32', 'linux', 'darwin'):
            for machine, pointer_size in (('AMD64', 8), ('x86_64', 8), ('AMD64', 4), ('ARM64', 8), ('x86', 4)):
                for version in versions:
                    with self.subTest(system=system, machine=machine, version=version), \
                         patch.object(operator.sys, 'platform', system), \
                         patch.object(operator.sys, 'version_info', version), \
                         patch.object(operator.platform, 'machine', return_value=machine), \
                         patch.object(operator.struct, 'calcsize', return_value=pointer_size), \
                         patch.object(operator.shutil, 'which', return_value='synthetic-docker'):
                        expected = version == (3, 12, 14) or (
                            system == 'win32' and machine in ('AMD64', 'x86_64')
                            and pointer_size == 8 and version == (3, 12, 10))
                        report = operator.runtime_report()
                        self.assertEqual(report['live_python_supported'], expected)
                        self.assertFalse(report['sqlite_required_for_s3'])
                        if system != 'win32':
                            self.assertEqual(report['required_live_python'], '3.12.14')

    def test_non_cpython_is_not_supported(self):
        with patch.object(operator.sys.implementation, 'name', 'pypy'), \
             patch.object(operator.sys, 'version_info', (3, 12, 14)):
            self.assertFalse(operator.runtime_report()['live_python_supported'])

    def test_unsupported_runtime_blocks_source_io_and_reports_same_error(self):
        report = SUPPORTED | {'python': '3.14.3', 'live_python_supported': False}
        with patch.object(operator, 'runtime_report', return_value=report), \
             patch.object(operator, 'build_sources', side_effect=AssertionError('NO SOURCE IO')) as source:
            estimate = operator.preflight()
            self.assertIn('S3_LIVE_PYTHON_UNSUPPORTED', estimate['blockers'])
            with self.assertRaisesRegex(RecoveryError, 'S3_LIVE_PYTHON_UNSUPPORTED'):
                operator.preflight(check_source=True)
            source.assert_not_called()

    def test_supported_version_does_not_bypass_host_or_dependency_gates(self):
        for change, error in (
            ({'host_runtime': False}, 'S3_OPERATOR_HOST_RUNTIME_REQUIRED'),
            ({'docker_cli': False}, 'S3_LIVE_DEPENDENCIES_MISSING'),
            ({'dependencies': {'boto3': False, 'cryptography': True}}, 'S3_LIVE_DEPENDENCIES_MISSING'),
            ({'dependencies': {'boto3': True, 'cryptography': False}}, 'S3_LIVE_DEPENDENCIES_MISSING'),
        ):
            with self.subTest(change=change), \
                 patch.object(operator, 'runtime_report', return_value=SUPPORTED | change):
                with self.assertRaisesRegex(RecoveryError, error):
                    operator.require_live_runtime()
