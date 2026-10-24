"""Offline restore contracts using ONLY fake SDK bytes/keys, including live scope.

Media identity is mocked for same-device temporary fixtures; Windows ACLs are
REAL. The real media function is tested separately, never bypassed by CLI flags.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import restore_s3_offline as cli
from src.recovery import s3_offline_restore as restore
from src.recovery.archive import exclusive_write, private_directory
from src.recovery.runtime import RecoveryError, digest, encoded, run
from src.recovery.s3_readonly import S3ReadOnly
from src.recovery.s3_safety import assert_private, prepare_directory, session_permissions
from src.recovery.s3_storage import SyntheticObject
from src.recovery.s3_workflow import backup_live, backup_synthetic
from tests.test_s3_readonly import FakeSDK
from tests.test_s3_workflow import fixture


class OfflineRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='football-synthetic-offline-restore-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.archive_parent, cls.targets = cls.root / 'archives', cls.root / 'targets'
        for path in (cls.archive_parent, cls.targets):
            prepare_directory(path, confirmed=True)
        cls.key = os.urandom(32)
        store, metadata = fixture()
        for name, payload in {'../outside': b'traversal-as-data', 'a/same': b'one', 'b/same': b'two',
                              'CON:stream\\name?': b'windows-reserved', 'unicode/\u043a\u043b\u044e\u0447': bytes(range(256)),
                              '/absolute/empty/': b'', 'large': b'x' * 8193}.items():
            store.objects[name] = SyntheticObject(payload, {'note': 'synthetic-only'})
        cls.store = store
        def fixture_permissions(path):
            private_directory(path)
            session_permissions(path, initialize=True)
        with patch('src.recovery.s3_archive.private_directory', side_effect=fixture_permissions):
            synthetic = backup_synthetic(store, metadata, cls.archive_parent, cls.key, chunk_size=1024)
        cls.synthetic_archive = Path(synthetic['directory'])
        # Real schema-2 live workflow on a fake SDK ONLY. No services or real keys.
        source = S3ReadOnly(FakeSDK(store), store.identity.bucket)
        with patch('src.recovery.s3_operator.require_live_runtime'):
            live = backup_live(source, metadata, cls.archive_parent, cls.key, confirmed=True,
                               before_write=lambda *args, **kwargs: None,
                               permission_guard=session_permissions, chunk_size=1024)
        cls.archive, cls.sid = Path(live['directory']), Path(live['directory']).name

    def setUp(self):
        self.destination = self.targets / self._testMethodName
        self.enterContext(patch.object(restore, 'independent_media', return_value={'synthetic_media': True}))
        for name in ('socket.socket', 'socket.create_connection', 'src.recovery.runtime.docker',
                     'src.recovery.s3_safety.load_key', 'src.recovery.s3_key_escrow.key_directory'):
            self.enterContext(patch(name, side_effect=AssertionError('SOURCE_OR_ORIGINAL_KEY_FORBIDDEN')))

    def invoke(self, **kwargs):
        options = dict(expected_session=self.sid, confirmed=True, phone_attested=True,
                       independent_media_confirmed=True)
        options.update(kwargs)
        return restore.restore_local(self.archive, self.key, self.destination, **options)

    def damaged_copy(self):
        parent = self.targets / (self._testMethodName + '-copy')
        prepare_directory(parent, confirmed=True)
        target = parent / self.sid
        prepare_directory(target, confirmed=True)
        for path in self.archive.iterdir():
            exclusive_write(target / path.name, path.read_bytes())
        return target

    def test_full_live_scope_fake_archive_binary_empty_unicode_metadata_multichunk(self):
        before = {p.name: digest(p.read_bytes()) for p in self.archive.iterdir()}
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            report = self.invoke()
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertEqual(report['status'], 'RESTORED_LIVE_OFFLINE_LOCAL')
        self.assertEqual(report['source_objects'], len(self.store.objects))
        self.assertEqual(report['source_bytes'], sum(len(v.payload) for v in self.store.objects.values()))
        self.assertEqual(report['sha256_verified_objects'], len(self.store.objects))
        self.assertFalse(report['source_services_used'])
        self.assertFalse(report['original_key_file_read'])
        self.assertFalse(report['remote_s3_restore_verified'])
        mapping = json.loads((self.destination / 'object-map.json').read_bytes())
        self.assertEqual({r['key'] for r in mapping['objects']}, set(self.store.objects))
        for item in mapping['objects']:
            self.assertEqual((self.destination / item['file']).read_bytes(), self.store.objects[item['key']].payload)
            if item['key'] in ('large', '../outside'):
                self.assertEqual(item['metadata']['note'], 'synthetic-only')
            self.assertIn('s3:ContentType', item['metadata'])
            self.assertEqual(digest((self.destination / item['file']).read_bytes()), item['sha256'])
        self.assertNotIn('__recovery_evidence__', json.dumps(mapping))
        self.assertFalse((self.targets / 'outside').exists())
        self.assertEqual({p.name: digest(p.read_bytes()) for p in self.archive.iterdir()}, before)
        self.assertNotIn(self.key.hex(), json.dumps(report))
        assert_private(self.destination, children=True)  # Actual Windows ACLs.

    def test_plan_is_authenticated_and_never_creates_destination(self):
        report = restore.plan_restore(self.archive, self.key, self.destination,
                                      expected_session=self.sid, phone_attested=True)
        self.assertFalse(report['restore_executed'])
        self.assertEqual(report['source_objects'], len(self.store.objects))
        self.assertGreater(report['required_free_bytes'], report['source_bytes'])
        self.assertFalse(self.destination.exists())

    def test_completion_report_readback_failure_never_publishes_success(self):
        prepare_directory(self.destination, confirmed=True)
        report = {'status': 'RESTORED_SYNTHETIC_OFFLINE_LOCAL'}
        with patch.object(restore, '_json', return_value={}):
            with self.assertRaisesRegex(RecoveryError, 'S3_RESTORE_REPORT_READBACK'):
                restore._publish_report(self.destination, report)
        self.assertFalse((self.destination / 'restore-report.json').exists())
        self.assertTrue((self.destination / 'restore-report.pending.json').exists())

    def test_completion_report_no_overwrite_and_link_failure(self):
        prepare_directory(self.destination, confirmed=True)
        final = self.destination / 'restore-report.json'
        exclusive_write(final, b'synthetic-existing-report')
        with self.assertRaises(FileExistsError):
            restore._publish_report(self.destination, {'status': 'RESTORED_SYNTHETIC_OFFLINE_LOCAL'})
        self.assertEqual(final.read_bytes(), b'synthetic-existing-report')
        self.assertTrue((self.destination / 'restore-report.pending.json').exists())

    def test_completion_report_failed_commit_retains_incomplete_pending_marker(self):
        prepare_directory(self.destination, confirmed=True)
        report = {'status': 'RESTORED_SYNTHETIC_OFFLINE_LOCAL'}
        with patch.object(Path, 'unlink', side_effect=OSError('synthetic-unlink-failed')):
            with self.assertRaises(OSError):
                restore._publish_report(self.destination, report)
        self.assertTrue((self.destination / 'restore-report.pending.json').exists())
        self.assertTrue((self.destination / 'restore-report.json').exists())
        self.assertEqual((self.destination / 'restore-report.json').stat().st_nlink, 2)
        with self.assertRaisesRegex(RecoveryError, 'UNSAFE_PRIVATE_FILE'):
            assert_private(self.destination, children=True)

    def test_completion_report_acl_failure_precedes_publication(self):
        prepare_directory(self.destination, confirmed=True)
        with patch.object(restore, 'assert_private', side_effect=RecoveryError('S3_UNSAFE_PERMISSIONS')):
            with self.assertRaisesRegex(RecoveryError, 'UNSAFE_PERMISSIONS'):
                restore._publish_report(self.destination, {'status': 'RESTORED_SYNTHETIC_OFFLINE_LOCAL'})
        self.assertFalse((self.destination / 'restore-report.json').exists())

    def test_manifest_change_during_authentication_is_rejected_before_writes(self):
        verified = restore._verified_workflow
        copied = self.damaged_copy()
        def change(*args, **kwargs):
            result = verified(*args, **kwargs)
            p = copied / 'manifest.json'
            p.write_bytes(p.read_bytes() + b'\n')
            return result
        with patch.object(restore, '_verified_workflow', side_effect=change):
            with self.assertRaisesRegex(RecoveryError, 'S3_RESTORE_ARCHIVE_CHANGED'):
                restore.restore_local(copied, self.key, self.destination, expected_session=self.sid,
                          confirmed=True, phone_attested=True, independent_media_confirmed=True)
        self.assertFalse(self.destination.exists())

    def test_synthetic_scope_is_not_reported_as_production_restore(self):
        result = restore.restore_local(self.synthetic_archive, self.key, self.destination,
                         expected_session=self.synthetic_archive.name, confirmed=True,
                         phone_attested=True, independent_media_confirmed=True)
        self.assertEqual(result['status'], 'RESTORED_SYNTHETIC_OFFLINE_LOCAL')

    def test_all_confirmations_required_before_io(self):
        for field in ('confirmed', 'phone_attested', 'independent_media_confirmed'):
            with self.subTest(field=field), patch.object(restore, 'check_paths') as check:
                with self.assertRaisesRegex(RecoveryError, 'CONFIRMATIONS_REQUIRED'):
                    self.invoke(**{field: False})
                check.assert_not_called()

    def test_wrong_key_and_session_fail_before_destination_creation(self):
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_AUTHENTICATION_FAILED'):
            restore.restore_local(self.archive, os.urandom(32), self.destination, expected_session=self.sid,
                                  confirmed=True, phone_attested=True, independent_media_confirmed=True)
        with self.assertRaisesRegex(RecoveryError, 'SESSION_MISMATCH'):
            self.invoke(expected_session='20000101T000000Z-' + '0' * 32)
        self.assertFalse(self.destination.exists())

    def test_phone_input_validation_is_silent(self):
        self.assertEqual(restore.phone_key(self.key.hex(), phone_attested=True), self.key)
        for value in ('', '../key', self.key.hex() + ' ', 'x' * 64):
            with self.assertRaisesRegex(RecoveryError, '^S3_RESTORE_KEY_HEX_INVALID$'):
                restore.phone_key(value, phone_attested=True)
        with self.assertRaisesRegex(RecoveryError, 'PHONE_ATTESTATION_REQUIRED'):
            restore.phone_key(self.key.hex())

    def test_existing_destination_never_overwritten(self):
        prepare_directory(self.destination, confirmed=True)
        keep = self.destination / 'keep'
        keep.write_bytes(b'synthetic-existing')
        with self.assertRaisesRegex(RecoveryError, 'NEW_DESTINATION_REQUIRED'):
            self.invoke()
        self.assertEqual(keep.read_bytes(), b'synthetic-existing')

    def test_corrupt_ciphertext_index_and_missing_chunk_fail_without_writes(self):
        copied = self.damaged_copy()
        chunk = next(copied.glob('object-*.enc'))
        original = chunk.read_bytes()
        variants = ('ciphertext', 'index', 'missing')
        for variant in variants:
            with self.subTest(variant=variant):
                index = copied / 'index.json.enc'
                original_index = index.read_bytes()
                if variant == 'ciphertext':
                    chunk.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                elif variant == 'index':
                    index.write_bytes(original_index[:-1] + bytes([original_index[-1] ^ 1]))
                else:
                    chunk.unlink()  # Own synthetic fixture only.
                with self.assertRaises(RecoveryError):
                    restore.restore_local(copied, self.key, self.destination, expected_session=self.sid,
                           confirmed=True, phone_attested=True, independent_media_confirmed=True)
                self.assertFalse(self.destination.exists())
                if chunk.exists():
                    chunk.write_bytes(original)
                else:
                    exclusive_write(chunk, original)
                index.write_bytes(original_index)

    def test_partial_failure_retained_no_completion_report_no_retry(self):
        write = restore._write_payload
        def fail(path, archive, item):
            write(path, archive, item)
            raise OSError('synthetic-sensitive-error-do-not-log')
        with patch.object(restore, '_write_payload', side_effect=fail):
            with self.assertRaisesRegex(RecoveryError, '^S3_WORKFLOW_OPERATION_FAILED$'):
                self.invoke()
        self.assertTrue(any(self.destination.iterdir()))
        self.assertFalse((self.destination / 'restore-report.json').exists())
        with self.assertRaisesRegex(RecoveryError, 'NEW_DESTINATION_REQUIRED'):
            self.invoke()

    def test_output_corruption_extra_files_and_metadata_tampering_detected(self):
        validate = restore._validate_plaintext
        for variant in ('payload', 'extra', 'metadata'):
            dest = self.targets / (self._testMethodName + variant)
            def damage(target, archive, records, mapping):
                if variant == 'payload':
                    p = next(target.glob('object-*.bin'))
                    p.write_bytes(bytes([0]) * p.stat().st_size)
                elif variant == 'extra':
                    (target / 'extra').write_bytes(b'synthetic')
                else:
                    (target / 'object-map.json').write_bytes(b'{}')
                validate(target, archive, records, mapping)
            with self.subTest(variant=variant), patch.object(restore, '_validate_plaintext', side_effect=damage):
                with self.assertRaisesRegex(RecoveryError, 'S3_RESTORE_'):
                    restore.restore_local(self.archive, self.key, dest, expected_session=self.sid,
                              confirmed=True, phone_attested=True, independent_media_confirmed=True)
            self.assertFalse((dest / 'restore-report.json').exists())

    def test_low_space_media_failure_and_traversal_are_fail_closed(self):
        with patch.object(restore.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(10, 10, 0)):
            with self.assertRaisesRegex(RecoveryError, 'INSUFFICIENT_SPACE'):
                self.invoke()
        with patch.object(restore, 'independent_media', side_effect=RecoveryError('S3_RESTORE_INDEPENDENT_DISK_REQUIRED')):
            with self.assertRaisesRegex(RecoveryError, 'INDEPENDENT_DISK_REQUIRED'):
                self.invoke()
        with self.assertRaisesRegex(RecoveryError, 'NONTRAVERSING_PATH_REQUIRED'):
            restore.check_paths(self.archive, self.targets / '..' / 'escaped')
        self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows ACL and junction test')
    def test_real_insecure_parent_and_junction_refused_without_repair(self):
        parent = self.targets / (self._testMethodName + '-parent')
        prepare_directory(parent, confirmed=True)
        run(['icacls', str(parent), '/grant', '*S-1-1-0:(OI)(CI)R'])
        with self.assertRaisesRegex(RecoveryError, 'UNSAFE_PERMISSIONS'):
            restore.check_paths(self.archive, parent / 'new')
        # Exact grant cleanup only on our synthetic empty parent.
        session_permissions(parent, initialize=True)
        junction = self.targets / (self._testMethodName + '-junction')
        from src.recovery.s3_safety import _powershell
        literal = lambda p: str(p).replace("'", "''")
        _powershell("New-Item -ItemType Junction -Path '" + literal(junction) + "' -Target '" + literal(parent) + "' | Out-Null")
        with self.assertRaisesRegex(RecoveryError, 'LINK_REFUSED'):
            restore.check_paths(self.archive, junction / 'new')


class OfflineCLIContracts(unittest.TestCase):
    def arguments(self):
        return ['--archive', '/synthetic/archive', '--destination', '/synthetic/new',
                '--expect-session', '20000101T000000Z-' + '0' * 32]

    def test_default_never_opens_key_dialog_or_restores(self):
        with patch.object(cli, '_run_gui') as gui, redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(self.arguments()), 1)
        gui.assert_not_called()

    def test_cli_has_no_key_file_key_argument_or_credential_switch(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit):
            cli.main(['--help'])
        for forbidden in ('--key-file', '--key-hex', '--access-key', '--secret-key'):
            self.assertNotIn(forbidden, output.getvalue())

    def test_cli_errors_never_expose_raw_exception(self):
        with patch.object(restore, 'check_paths', side_effect=ValueError('sensitive-fixture')), \
             redirect_stderr(io.StringIO()) as output:
            self.assertEqual(cli.main(self.arguments() + ['--confirm-restore', '--confirm-phone-key',
                                  '--confirm-independent-media']), 1)
        self.assertNotIn('sensitive-fixture', output.getvalue())

    def test_offline_module_has_no_source_or_original_key_io(self):
        text = Path(restore.__file__).read_text()
        for forbidden in ('load_key(', 'build_sources(', 'scheduler_sources(', 'DockerMetadataSource(',
                          'create_s3_client(', 'requests.', 'key_directory(', 'BitwardenClient'):
            self.assertNotIn(forbidden, text)

    @unittest.skipUnless(os.name == 'nt', 'Windows disk identities')
    def test_media_check_compares_physical_disks_not_drive_letters(self):
        rows = [{'disk': 4, 'filesystem': 'NTFS', 'healthy': True, 'online': True, 'writable': True},
                {'disk': 2, 'filesystem': 'NTFS', 'healthy': True, 'online': True, 'writable': True}]
        with patch.object(restore, '_powershell', return_value=encoded(rows)):
            self.assertEqual(restore.independent_media(Path('K:/archive'), Path('F:/new'))['destination_disk'], 2)
        rows[1]['disk'] = 4
        with patch.object(restore, '_powershell', return_value=encoded(rows)):
            with self.assertRaisesRegex(RecoveryError, 'INDEPENDENT_DISK_REQUIRED'):
                restore.independent_media(Path('K:/archive'), Path('F:/new'))


if __name__ == '__main__':
    unittest.main()
