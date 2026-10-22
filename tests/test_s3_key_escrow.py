"""Disposable synthetic material ONLY; never use the operator's actual vault/key."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from scripts import show_s3_recovery_key as viewer
from src.recovery import s3_key_escrow as escrow
from src.recovery.runtime import RecoveryError
from src.recovery.s3_archive import S3ArchiveWriter, verify_archive
from src.recovery.s3_safety import assert_private, load_key, prepare_directory, session_permissions

PROFILE_DIRECTORY = escrow.key_directory


class ProductionEscrowContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='football-synthetic-production-escrow-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vault, self.archives = self.root / 'private-test-vault', self.root / 'test-archives'
        for directory in (self.vault, self.archives):
            prepare_directory(directory, confirmed=True)
        self.host = self.enterContext(patch.object(escrow, '_host'))
        self.enterContext(patch.object(escrow, 'key_directory', return_value=self.vault))
        self.enterContext(patch('socket.socket', side_effect=AssertionError('NETWORK_FORBIDDEN')))
        self.enterContext(patch('socket.create_connection', side_effect=AssertionError('NETWORK_FORBIDDEN')))
        self.docker = self.enterContext(patch('src.recovery.runtime.docker', side_effect=AssertionError('DOCKER_FORBIDDEN')))

    def prepare(self):
        return escrow.prepare(archive_directory=self.archives, confirmed=True)

    def test_key_record_and_display_are_private_silent_pending_and_format_compatible(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            report = self.prepare()
            material = escrow.read_for_display(report['key_id'], confirmed=True)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertRegex(report['key_id'], '^' + escrow.ID_PATTERN + '$')
        self.assertIsNone(report['session_id'])
        self.assertEqual(report['live_backup'], 'BLOCKED')
        self.assertEqual(list(self.archives.iterdir()), [])
        key = load_key(Path(report['key_file']))
        self.assertEqual(len(key), 32)
        self.assertTrue(bytes.fromhex(material.hex_key) == key)
        self.assertTrue(material.hex_key not in repr(material))
        self.assertTrue(material.hex_key not in json.dumps(report))
        raw = (self.vault / (report['key_id'] + '.json')).read_bytes()
        self.assertTrue(material.hex_key.encode() not in raw)
        record = json.loads(raw)
        self.assertEqual(set(record), escrow.RECORD_FIELDS)
        self.assertEqual(record['backup_sessions'], [])
        self.assertEqual(record['independent_recovery'], 'NOT_VERIFIED')
        self.assertEqual(record['escrow_status'], 'PENDING_OPERATOR_CONFIRMATION')
        assert_private(self.vault, children=True)
        self.docker.assert_not_called()
        # The same *synthetic* fixture key can be supplied to a subsequent session
        # without altering the existing archive format or deriving/replacing it.
        with S3ArchiveWriter(self.archives, key, expected_objects=1,
                             permission_guard=session_permissions) as writer:
            writer.add_object('synthetic', io.BytesIO(b'test'), size_bytes=4)
            writer.seal()
            archive = verify_archive(writer.directory, key)
        self.assertNotEqual(archive.core['session_id'], report['key_id'])
        self.assertEqual(archive.core['schema_version'], 2)

    def test_absent_confirmations_fail_before_key_reads_or_generation(self):
        with patch.object(escrow, 'generate_key') as generate, patch.object(escrow, 'load_key') as load:
            with self.assertRaisesRegex(RecoveryError, 'S3_KEY_GENERATION_CONFIRMATION_REQUIRED'):
                escrow.prepare(archive_directory=self.archives)
            with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_DISPLAY_CONFIRMATION_REQUIRED'):
                escrow.read_for_display('invalid')
        generate.assert_not_called()
        load.assert_not_called()
        self.host.assert_not_called()
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_fixed_reference_collision_never_overwrites_or_regenerates_key(self):
        with patch.object(escrow, 'datetime') as clock, patch.object(escrow.uuid, 'uuid4', return_value=uuid.UUID(int=1)):
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            report = self.prepare()
            original = load_key(Path(report['key_file']))
            with patch.object(escrow, 'generate_key') as generate:
                with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_REFERENCE_EXISTS'):
                    self.prepare()
                generate.assert_not_called()
        self.assertTrue(load_key(Path(report['key_file'])) == original)

    def test_second_preparation_has_distinct_key_identifier(self):
        first, second = self.prepare(), self.prepare()
        self.assertNotEqual(first['key_id'], second['key_id'])
        self.assertTrue(load_key(Path(first['key_file'])) != load_key(Path(second['key_file'])))

    def test_invalid_identity_and_traversal_cannot_select_arbitrary_key(self):
        for key_id in ('../production', 'synthetic.key', '', 's3-recovery-../unsafe'):
            with self.subTest(key_id=key_id), patch.object(escrow, 'load_key') as load:
                with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_KEY_ID_INVALID'):
                    escrow.read_for_display(key_id, confirmed=True)
                load.assert_not_called()

    def test_existing_unsafe_directory_is_not_repaired_and_no_key_is_written(self):
        with patch.object(escrow, 'assert_private', side_effect=RecoveryError('S3_UNSAFE_PERMISSIONS')), \
             patch.object(escrow, 'generate_key') as generate:
            with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                self.prepare()
            generate.assert_not_called()
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_archive_and_key_locations_cannot_overlap(self):
        with self.assertRaisesRegex(RecoveryError, 'S3_KEY_MUST_BE_SEPARATE'):
            escrow.prepare(archive_directory=self.vault, confirmed=True)
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_acl_setup_failure_retains_partial_key_but_creates_no_archive_or_record(self):
        with patch.object(escrow, '_protected_file', side_effect=RecoveryError('SYNTHETIC_ACL_FAILURE')):
            with self.assertRaisesRegex(RecoveryError, 'SYNTHETIC_ACL_FAILURE'):
                self.prepare()
        self.assertEqual(len(list(self.vault.glob('*.key'))), 1)
        self.assertEqual(list(self.vault.glob('*.json')), [])
        self.assertEqual(list(self.archives.iterdir()), [])

    def test_record_cannot_redirect_to_another_key_or_assert_recoverability(self):
        report = self.prepare()
        path = self.vault / (report['key_id'] + '.json')
        original = json.loads(path.read_bytes())
        for changed in (original | {'key_file': '../other.key'},
                        original | {'escrow_status': 'PASS'}, original | {'unexpected': 'field'}):
            path.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_RECORD_INVALID'):
                escrow.read_for_display(report['key_id'], confirmed=True)

    def test_viewer_suppresses_raw_errors_and_never_generates_material(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch.object(escrow, 'read_for_display', side_effect=RuntimeError('synthetic-sensitive-sentinel')), \
             patch.object(escrow, 'generate_key') as generate:
            self.assertEqual(viewer.main(['--key-id', 'invalid', '--confirm-local-display']), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue().strip(), 'S3_PRODUCTION_KEY_VIEW_FAILED')
        generate.assert_not_called()

    def test_viewer_displays_only_locally_and_closing_cannot_confirm_escrow(self):
        # A fixed synthetic value and fake Tk: no GUI, real key, vault or clipboard.
        material = escrow.KeyDisplay('synthetic-ui-id', '2026-01-01T00:00:00Z', 'ab' * 32)
        tk = Mock()
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch.dict('sys.modules', {'tkinter': tk}), \
             patch.object(escrow, 'read_for_display', return_value=material) as read, \
             patch.object(escrow, 'prepare') as prepare:
            self.assertEqual(viewer.main(['--key-id', material.key_id, '--confirm-local-display']), 0)
        read.assert_called_once_with(material.key_id, confirmed=True)
        prepare.assert_not_called()
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        labels = [call.kwargs.get('text') for call in tk.Label.call_args_list]
        self.assertIn('\n'.join(material.hex_key[n:n + 16] for n in range(0, 64, 16)), labels)
        tk.Tk.return_value.clipboard_append.assert_not_called()
        tk.Tk.return_value.clipboard_clear.assert_not_called()
        self.assertIn('Close (does NOT confirm escrow)', tk.Button.call_args.kwargs['text'])

    def test_profile_directory_uses_current_user_home(self):
        with patch.object(escrow.Path, 'home', return_value=self.root):
            self.assertEqual(PROFILE_DIRECTORY(), self.root / 'FootballRecoveryVault' / 's3')
