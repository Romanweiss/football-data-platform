"""Disposable synthetic preparation; external Bitwarden is NEVER contacted."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import show_synthetic_escrow_key as viewer
from scripts import receive_synthetic_escrow_key as receiver
from src.recovery.runtime import RecoveryError
from src.recovery.s3_manual_drill import (
    DisplayMaterial, exclude_original, fixture_root, prepare, read_for_display, receive_from_phone,
)


class ManualDrillTests(unittest.TestCase):
    def fixture(self):
        evidence = prepare()
        root = Path(evidence['fixture_root'])
        def cleanup():
            verified = fixture_root(root)
            self.assertEqual(verified, root.resolve())
            shutil.rmtree(verified)  # Only this test's validated UUID tree.
        self.addCleanup(cleanup)
        return evidence, root

    def test_prepare_and_gui_material_are_private_synthetic_and_silent(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch('socket.socket', side_effect=AssertionError('NETWORK_FORBIDDEN')), \
             patch('socket.create_connection', side_effect=AssertionError('NETWORK_FORBIDDEN')):
            evidence, root = self.fixture()
            material = read_for_display(root)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertEqual(evidence['external_recovery'], 'NOT_VERIFIED')
        self.assertEqual(material.session_id, evidence['session_id'])
        self.assertTrue(len(material.hex_key) == 64 and len(bytes.fromhex(material.hex_key)) == 32)
        self.assertTrue(material.hex_key not in repr(material))  # Never echo a random key on assertion failure.
        self.assertEqual(list((root / 'recovered').iterdir()), [])
        self.assertEqual({p.name for p in (root / 'original').iterdir()}, {'synthetic.key'})

    def test_wrong_root_cannot_open_a_real_key_or_workspace(self):
        for root in (Path.cwd(), Path(tempfile.gettempdir()), Path(tempfile.gettempdir()) / 'unrelated-folder'):
            with self.assertRaises(RecoveryError):
                read_for_display(root)

    def test_no_secret_in_default_material_representation(self):
        material = DisplayMaterial('synthetic-session', 'synthetic-sensitive-value')
        self.assertNotIn('synthetic-sensitive-value', str(material))

    def test_viewer_failure_never_formats_secret_exception(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch('src.recovery.s3_manual_drill.read_for_display', side_effect=RuntimeError('synthetic-sensitive-value')):
            self.assertEqual(viewer.main(['--session-root', 'invalid']), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue().strip(), 'SYNTHETIC_KEY_VIEW_FAILED')

    def test_phone_input_waits_for_confirmations_and_original_exclusion(self):
        evidence, root = self.fixture()
        with self.assertRaisesRegex(RecoveryError, 'SYNTHETIC_OPERATOR_CONFIRMATION_REQUIRED'):
            exclude_original(root, evidence['session_id'])
        with self.assertRaisesRegex(RecoveryError, 'SYNTHETIC_SESSION_MISMATCH'):
            exclude_original(root, 'wrong-session', phone_confirmed=True, viewer_closed=True)
        with self.assertRaisesRegex(RecoveryError, 'SYNTHETIC_ORIGINAL_STILL_PRESENT'):
            receive_from_phone(root, '0' * 64, phone_attested=True)
        self.assertTrue((root / 'original' / 'synthetic.key').is_file())
        self.assertEqual(list((root / 'recovered').iterdir()), [])

    def test_simulated_manual_capture_never_reads_original_or_overwrites_recovered_key(self):
        # Unit simulation ONLY, not evidence of real Bitwarden/mobile retrieval.
        evidence, root = self.fixture()
        material = read_for_display(root)
        with patch('src.recovery.s3_manual_drill.load_key', side_effect=AssertionError('ORIGINAL_READ_FORBIDDEN')):
            exclude_original(root, evidence['session_id'], phone_confirmed=True, viewer_closed=True)
        self.assertFalse((root / 'original' / 'synthetic.key').exists())
        with self.assertRaises(RecoveryError):
            read_for_display(root)
        for value, attested, expected in (
                (material.hex_key, False, 'SYNTHETIC_PHONE_ATTESTATION_REQUIRED'),
                ('invalid', True, 'SYNTHETIC_KEY_HEX_INVALID'),
                (('1' if material.hex_key[0] != '1' else '2') + material.hex_key[1:], True,
                 'S3_MANIFEST_AUTHENTICATION_FAILED')):
            with self.assertRaisesRegex(RecoveryError, expected):
                receive_from_phone(root, value, phone_attested=attested)
            self.assertEqual(list((root / 'recovered').iterdir()), [])
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = receive_from_phone(root, material.hex_key, phone_attested=True)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertEqual(result['status'], 'SYNTHETIC_KEY_RECEIVED_OFFLINE_VERIFY_PASS')
        self.assertEqual((root / 'recovered' / 'synthetic.key').stat().st_size, 32)
        with self.assertRaisesRegex(RecoveryError, 'SYNTHETIC_RECOVERED_KEY_EXISTS'):
            receive_from_phone(root, material.hex_key, phone_attested=True)

    def test_receiver_failure_never_formats_secret_exception(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch('src.recovery.s3_manual_drill.recovery_record', side_effect=RuntimeError('synthetic-sensitive-value')):
            self.assertEqual(receiver.main(['--session-root', 'invalid']), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue().strip(), 'SYNTHETIC_PHONE_INPUT_FAILED')
