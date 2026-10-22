"""LOCAL SYNTHETIC drill only. No independent store, production key or cloud IO."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import hmac
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.recovery.archive import exclusive_write
from src.recovery.runtime import RecoveryError, require
from src.recovery.s3_archive import S3ArchiveWriter, restore_synthetic, verify_archive
from src.recovery.s3_operator import create
from src.recovery.s3_safety import generate_key, load_key, locations, prepare_directory, session_permissions


def local_synthetic_drill():
    """Return ONLY PASS/session ID. All fixtures are disposable system-temp data.

    Local retrieved-copy simulation is NOT independent/off-machine escrow evidence.
    No transport plugin, vault integration, automatic upload or real CLI command.
    """
    with tempfile.TemporaryDirectory(prefix='football-synthetic-escrow-') as temporary:
        root = Path(temporary)
        archives, runtime_keys, local_copy, retrieved_keys = (root / n for n in
            ('archives', 'synthetic-runtime-keys', 'LOCAL-NOT-INDEPENDENT', 'retrieved-test-keys'))
        for directory in (archives, runtime_keys, local_copy, retrieved_keys):
            prepare_directory(directory, confirmed=True)
        original = runtime_keys / 'synthetic.key'
        generate_key(original, confirmed=True)
        master = load_key(original)
        objects = {'sample.json': b'{"source":"synthetic-escrow"}',
                   'binary.bin': bytes(range(256)), 'empty': b''}
        with S3ArchiveWriter(archives, master, expected_objects=len(objects), chunk_size=64,
                             permission_guard=session_permissions) as writer:
            for key, payload in objects.items():
                writer.add_object(key, io.BytesIO(payload), size_bytes=len(payload),
                                  metadata={'source': 'synthetic-escrow-test'})
            writer.seal()
            archive, session_id = writer.directory, writer.core['session_id']
        copy = local_copy / (session_id + '.key')
        locations(archives, copy)
        exclusive_write(copy, master)
        require(hmac.compare_digest(load_key(copy), master), 'SYNTHETIC_KEY_COPY_MISMATCH')
        original.unlink()  # Only our disposable fixture, never an actual vault key.
        del master, writer
        retrieved = retrieved_keys / (session_id + '.key')
        locations(archives, retrieved)
        exclusive_write(retrieved, load_key(copy))
        copy.unlink()  # Simulate using only the retrieved route, not the original.
        recovered = load_key(retrieved)
        verify_archive(archive, recovered)  # Offline authentication + byte verification.
        wrong = bytes([recovered[0] ^ 1]) + recovered[1:]
        wrong_destination = root / 'wrong-key-restore'
        try:
            restore_synthetic(archive, wrong, wrong_destination)
        except RecoveryError as exc:
            require(str(exc) == 'S3_MANIFEST_AUTHENTICATION_FAILED', 'SYNTHETIC_WRONG_KEY_UNEXPECTED_ERROR')
        else:
            raise RecoveryError('SYNTHETIC_WRONG_KEY_ACCEPTED')
        require(not wrong_destination.exists(), 'SYNTHETIC_WRONG_KEY_WROTE_PLAINTEXT')
        restored = root / 'restored'
        restore_synthetic(archive, recovered, restored)
        mapping = json.loads((restored / 'index.json').read_bytes())['objects']
        require({row['key'] for row in mapping} == set(objects), 'SYNTHETIC_OBJECT_SET_MISMATCH')
        for row in mapping:
            actual = hashlib.sha256((restored / row['file']).read_bytes()).digest()
            expected = hashlib.sha256(objects[row['key']]).digest()
            require(hmac.compare_digest(actual, expected), 'SYNTHETIC_RESTORE_SHA256_MISMATCH')
        # No secret values, key hashes, paths, decrypted index or payload in evidence.
        return {'status': 'PASS', 'session_id': session_id}


class EscrowReadinessTests(unittest.TestCase):
    def test_local_retrieved_synthetic_key_restores_and_verifies_without_secret_output(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
             patch('socket.socket', side_effect=AssertionError('NETWORK_FORBIDDEN')), \
             patch('socket.create_connection', side_effect=AssertionError('NETWORK_FORBIDDEN')):
            evidence = local_synthetic_drill()
        self.assertEqual(set(evidence), {'status', 'session_id'})
        self.assertEqual(evidence['status'], 'PASS')
        self.assertRegex(evidence['session_id'], r'^\d{8}T\d{6}Z-[a-f0-9]{32}$')
        self.assertEqual(output.getvalue() + errors.getvalue(), '')

    def test_no_escrow_confirmation_blocks_before_any_runtime_key_or_source_access(self):
        with patch('src.recovery.s3_operator.require_live_runtime') as runtime, \
             patch('src.recovery.s3_safety.load_key') as key, \
             patch('src.recovery.s3_operator.build_sources') as source:
            with self.assertRaisesRegex(RecoveryError, '^S3_OPERATOR_CONFIRMATIONS_REQUIRED$'):
                create(destination=None, key_file=None, expected_source_id=None,
                       expected_inventory_sha256=None, confirmed=True, key_recoverable=False,
                       independent_media=True, quiet_window=True)
        runtime.assert_not_called()
        key.assert_not_called()
        source.assert_not_called()

    def test_key_beside_archive_and_overlapping_trees_are_refused(self):
        with tempfile.TemporaryDirectory(prefix='football-synthetic-location-') as temporary:
            root = Path(temporary)
            archive = root / 'archives'
            archive.mkdir()
            nested = archive / 'nested'
            nested.mkdir()
            for key in (archive / 'fixture.key', nested / 'fixture.key', root / 'fixture.key'):
                with self.subTest(overlap=True), self.assertRaisesRegex(RecoveryError, 'S3_KEY_MUST_BE_SEPARATE'):
                    locations(archive, key)

    def test_insecure_key_acl_fails_without_key_bytes_or_path_in_error(self):
        with patch('src.recovery.s3_safety.assert_private', side_effect=RecoveryError('S3_UNSAFE_PERMISSIONS')):
            with self.assertRaisesRegex(RecoveryError, '^S3_UNSAFE_PERMISSIONS$'):
                load_key(Path(tempfile.gettempdir()) / 'nonexistent-synthetic.key')


if __name__ == '__main__':
    unittest.main()
