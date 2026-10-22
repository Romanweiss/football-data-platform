"""Phone-input simulations with synthetic temp keys ONLY; never actual key/vault."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import receive_s3_recovery_key as receiver
from src.recovery import s3_key_escrow as escrow
from src.recovery.runtime import RecoveryError
from src.recovery.s3_safety import load_key, prepare_directory


class ProductionKeyRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='football-synthetic-key-recovery-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vault, self.archives = self.root / 'test-vault', self.root / 'test-archives'
        for directory in (self.vault, self.archives):
            prepare_directory(directory, confirmed=True)
        self.enterContext(patch.object(escrow, '_host'))
        self.enterContext(patch.object(escrow, 'key_directory', return_value=self.vault))
        self.enterContext(patch('socket.socket', side_effect=AssertionError('NETWORK_FORBIDDEN')))
        self.enterContext(patch('socket.create_connection', side_effect=AssertionError('NETWORK_FORBIDDEN')))
        self.enterContext(patch('src.recovery.runtime.docker', side_effect=AssertionError('DOCKER_FORBIDDEN')))
        self.report = escrow.prepare(archive_directory=self.archives, confirmed=True)
        self.key_file = Path(self.report['key_file'])
        self.material = load_key(self.key_file)  # Synthetic fixture only, not a phone-recovery claim.

    def begin(self):
        return escrow.begin_recovery(self.report['key_id'], saved_and_viewer_closed=True)

    def receipts(self):
        return list(self.vault.glob('*.recovery-*.json'))

    def test_match_preserves_original_and_writes_only_safe_receipt(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            context = self.begin()
            result = escrow.confirm_recovered(context, self.material.hex(), phone_attested=True)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertTrue(self.material.hex() not in repr(context))
        self.assertTrue(context._fingerprint.hex() not in repr(context))
        self.assertEqual(result['status'], 'MATCH')
        self.assertEqual(result['source'], 'OPERATOR_ATTESTED_BITWARDEN_PHONE')
        self.assertTrue(result['independent_route_verified'])
        self.assertTrue(result['original_preserved'])
        self.assertFalse(result['live_backup_executed'])
        self.assertTrue(load_key(self.key_file) == self.material)
        self.assertEqual(list(self.archives.iterdir()), [])
        self.assertEqual(len(list(self.vault.glob('*.key'))), 1)
        self.assertEqual(len(self.receipts()), 1)
        raw = self.receipts()[0].read_bytes()
        self.assertTrue(self.material.hex().encode() not in raw)
        self.assertTrue(hashlib.sha256(self.material).hexdigest().encode() not in raw)
        self.assertEqual(json.loads(raw), result)
        escrow._protected_file(self.receipts()[0])  # Actual protected DACL on Windows.

    def test_wrong_key_has_no_fallback_or_receipt(self):
        context = self.begin()
        wrong = bytes([self.material[0] ^ 1]) + self.material[1:]
        with self.assertRaisesRegex(RecoveryError, '^S3_ESCROW_KEY_MISMATCH$'):
            escrow.confirm_recovered(context, wrong.hex(), phone_attested=True)
        self.assertEqual(self.receipts(), [])
        self.assertTrue(load_key(self.key_file) == self.material)

    def test_confirmations_and_invalid_input_fail_before_original_read(self):
        context = self.begin()
        with patch.object(escrow, 'load_key', side_effect=AssertionError('NO ORIGINAL READ')) as read:
            with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_SAVED_AND_VIEWER_CLOSED_REQUIRED'):
                escrow.begin_recovery(self.report['key_id'])
            with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_PHONE_ATTESTATION_REQUIRED'):
                escrow.confirm_recovered(context, self.material.hex())
            for value in ('', '0' * 63, '0' * 65, 'x' * 64, '0' * 64 + '\n', None):
                with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_KEY_HEX_INVALID'):
                    escrow.confirm_recovered(context, value, phone_attested=True)
            read.assert_not_called()
        self.assertEqual(self.receipts(), [])

    def test_original_change_blocks_even_if_input_matches_new_value(self):
        context = self.begin()
        replacement = bytes([self.material[0] ^ 1]) + self.material[1:]
        self.key_file.write_bytes(replacement)  # This test owns ONLY this synthetic fixture.
        with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_ORIGINAL_CHANGED'):
            escrow.confirm_recovered(context, replacement.hex(), phone_attested=True)
        self.assertEqual(self.receipts(), [])

    def test_repeated_submission_cannot_overwrite_receipt(self):
        context = self.begin()
        escrow.confirm_recovered(context, self.material.hex(), phone_attested=True)
        original_receipt = self.receipts()[0].read_bytes()
        with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_RECOVERY_ALREADY_RECORDED'):
            escrow.confirm_recovered(context, self.material.hex(), phone_attested=True)
        self.assertEqual(self.receipts()[0].read_bytes(), original_receipt)

    def test_bad_context_cannot_select_other_paths(self):
        context = self.begin()
        for invalid in (None, replace(context, key_id='../unsafe'), replace(context, attempt_id='../unsafe'),
                        replace(context, _fingerprint=b'wrong-length')):
            with self.assertRaises(RecoveryError):
                escrow.confirm_recovered(invalid, self.material.hex(), phone_attested=True)
        self.assertEqual(self.receipts(), [])

    def test_insecure_existing_key_acl_is_refused_without_repair(self):
        context = self.begin()
        with patch.object(escrow, 'assert_private', side_effect=RecoveryError('S3_UNSAFE_PERMISSIONS')):
            with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                escrow.confirm_recovered(context, self.material.hex(), phone_attested=True)
        self.assertEqual(self.receipts(), [])

    def test_desktop_match_is_not_independent_recovery(self):
        result = escrow.confirm_recovered(self.begin(), self.material.hex(), desktop_attested=True)
        self.assertEqual(result['status'], 'MATCH')
        self.assertEqual(result['source'], 'OPERATOR_ATTESTED_DESKTOP_NOTE_DIAGNOSTIC_ONLY')
        self.assertEqual(result['method'], 'MANUAL_DESKTOP_INPUT_SHA256_IN_MEMORY')
        self.assertFalse(result['independent_route_verified'])
        self.assertFalse(result['live_backup_executed'])
        self.assertTrue(load_key(self.key_file) == self.material)

    def test_ambiguous_source_is_refused_before_original_read(self):
        context = self.begin()
        with patch.object(escrow, 'load_key', side_effect=AssertionError('NO ORIGINAL READ')):
            with self.assertRaisesRegex(RecoveryError, 'S3_ESCROW_AMBIGUOUS_SOURCE'):
                escrow.confirm_recovered(context, self.material.hex(), phone_attested=True, desktop_attested=True)
        self.assertEqual(self.receipts(), [])

    def test_masked_gui_manual_paste_visibility_toggle_and_no_automatic_backup(self):
        context = self.begin()
        tk = Mock()
        value, status, source = Mock(), Mock(), Mock()
        tk.StringVar.side_effect = [value, status, source]
        value.get.return_value = self.material.hex()
        source.get.return_value = 'phone'
        def submit():
            toggle = tk.Checkbutton.call_args.kwargs['command']
            tk.BooleanVar.return_value.get.return_value = True
            toggle()
            tk.BooleanVar.return_value.get.return_value = False
            toggle()
            tk.Button.call_args.kwargs['command']()
        tk.Tk.return_value.mainloop.side_effect = submit
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), patch.dict('sys.modules', {'tkinter': tk}), \
             patch.object(escrow, 'begin_recovery', return_value=context), patch.object(escrow, 'prepare') as prepare:
            self.assertEqual(receiver.main(['--key-id', context.key_id, '--confirm-saved-and-viewer-closed']), 0)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assertEqual(tk.Entry.call_args.kwargs['show'], '*')
        self.assertFalse(tk.BooleanVar.call_args.kwargs['value'])
        tk.Entry.return_value.bind.assert_not_called()  # Native user copy/paste is not blocked.
        configurations = [call.kwargs['show'] for call in tk.Entry.return_value.configure.call_args_list]
        self.assertIn('', configurations)
        self.assertIn('*', configurations)
        self.assertEqual(tk.StringVar.call_args_list[2].kwargs['value'], '')  # No source preselected.
        self.assertEqual([call.kwargs['value'] for call in tk.Radiobutton.call_args_list], ['phone', 'desktop'])
        value.set.assert_any_call('')
        tk.Tk.return_value.clipboard_append.assert_not_called()
        tk.Tk.return_value.clipboard_get.assert_not_called()
        tk.Tk.return_value.clipboard_clear.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(len(self.receipts()), 1)

    def test_gui_exception_suppresses_material_and_fingerprint(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch.object(escrow, 'begin_recovery', side_effect=RuntimeError('synthetic-sensitive-sentinel')):
            self.assertEqual(receiver.main(['--key-id', 'invalid']), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue().strip(), 'S3_PRODUCTION_KEY_RECOVERY_FAILED')


class KeyInputFeedbackTests(unittest.TestCase):
    def test_length_and_hex_feedback_never_echo_input(self):
        for value in ('', 'a' * 63, 'a' * 65, 'a' * 64, 'a' * 63 + ' ', 'а' * 64):
            status = receiver.input_status(value)
            self.assertIn(str(len(value)) + '/64', status)
            if value:
                self.assertTrue(value not in status)
        self.assertIn('format OK', receiver.input_status('aB01' * 16))
        self.assertNotIn('format OK', receiver.input_status('а' * 64))  # Cyrillic a, not ASCII a.
        self.assertIn('non-hex', receiver.input_status('a' * 63 + '\n'))
