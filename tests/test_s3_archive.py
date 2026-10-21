"""Synthetic format/failure tests: no cloud, credentials, Docker or live backups."""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.recovery import s3_archive as s3
from src.recovery.archive import Archive, MANDATORY, SERVING_TABLES, load_archive
from src.recovery.runtime import RecoveryError, digest, encoded


class BoundedStream:
    def __init__(self, size, *, short_reads=False):
        self.remaining = size
        self.maximum_request = 0
        self.short_reads = short_reads

    def read(self, size=-1):
        if size <= 0 or size > 65536:
            raise AssertionError('unbounded source read')
        self.maximum_request = max(size, self.maximum_request)
        n = min(size, self.remaining, 997 if self.short_reads else size)
        self.remaining -= n
        return b'x' * n


class S3ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / 'archives'
        self.parent.mkdir()
        self.key = os.urandom(32)
        for name in ('socket.socket', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('external IO forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def create(self, objects=None, *, chunk_size=16):
        if objects is None:
            objects = [('sample.json', b'{"synthetic":true}', {'source': 'fixture'})]
        with s3.S3ArchiveWriter(self.parent, self.key, expected_objects=len(objects), chunk_size=chunk_size) as writer:
            for key, raw, metadata in objects:
                writer.add_object(key, io.BytesIO(raw), size_bytes=len(raw), metadata=metadata)
            writer.seal()
        return writer.directory

    def reader(self, directory):
        return s3.verify_archive(directory, self.key)

    def rewrite_index(self, directory, change):
        """Authenticated malformed fixtures, to test beyond outer hash/HMAC gates."""
        envelope = json.loads((directory / 'manifest.json').read_bytes())
        core = {field: envelope[field] for field in s3.CORE_FIELDS}
        _, index_key, mac_key = s3._keys(self.key, core)
        raw = (directory / 'index.json.enc').read_bytes()
        index = json.loads(s3._decrypt(raw, index_key, s3._aad(core, 'index')))
        change(index)
        nonce = os.urandom(12)
        raw = s3.MAGIC + nonce + AESGCM(index_key).encrypt(nonce, encoded(index), s3._aad(core, 'index'))
        (directory / 'index.json.enc').write_bytes(raw)
        envelope.update(index_size=len(raw), index_sha256=digest(raw))
        unsigned = {k: v for k, v in envelope.items() if k != 'authentication'}
        envelope['authentication'] = hmac.new(mac_key, encoded(unsigned), hashlib.sha256).hexdigest()
        (directory / 'manifest.json').write_bytes(encoded(envelope))

    def test_json_binary_empty_and_metadata_roundtrip(self):
        objects = [('sample.json', b'{"home_score":2}', {'ContentType': 'application/json', 'source': 'local-sample'}),
                   ('binary', bytes(range(256)), {'ContentType': 'application/octet-stream'}),
                   ('zero/', b'', {'note': 'empty object'})]
        directory = self.create(objects)
        destination = self.root / 'restored'
        result = s3.restore_synthetic(directory, self.key, destination)
        self.assertEqual((result['objects'], result['bytes']), (3, sum(len(o[1]) for o in objects)))
        mapping = json.loads((destination / 'index.json').read_bytes())['objects']
        for item, (key, raw, metadata) in zip(mapping, objects):
            self.assertEqual(item['key'], key)
            self.assertEqual(item['metadata'], metadata)
            self.assertEqual(item['sha256'], digest(raw))
            self.assertEqual((destination / item['file']).read_bytes(), raw)

    def test_unicode_special_keys_and_colliding_local_names_are_opaque(self):
        keys = ['a/data.json', 'b/data.json', 'A/DATA.json', 'a\\data.json', 'CON:?.json',
                '../outside', '/absolute/file', 'матчи/⚽?x=1&y=%2F', 'e\u0301', '\u00e9']
        objects = [(key, str(n).encode(), {'имя': 'значение'}) for n, key in enumerate(keys)]
        directory = self.create(objects)
        destination = self.root / 'restored'
        s3.restore_synthetic(directory, self.key, destination)
        mapping = json.loads((destination / 'index.json').read_bytes())['objects']
        self.assertEqual([r['key'] for r in mapping], keys)
        self.assertEqual(len({r['file'].casefold() for r in mapping}), len(keys))
        self.assertEqual({p.name for p in destination.iterdir()}, {'index.json'} | {r['file'] for r in mapping})
        self.assertFalse((self.root / 'outside').exists())

    def test_streaming_large_object_short_reads_and_chunk_limit(self):
        size = 2 * 1024 * 1024 + 17
        source = BoundedStream(size, short_reads=True)
        with s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1, chunk_size=65536) as writer:
            writer.add_object('large', source, size_bytes=size)
            writer.seal()
        archive = self.reader(writer.directory)
        item = archive.index['objects'][0]
        self.assertEqual(len(item['chunks']), 33)
        self.assertLessEqual(source.maximum_request, 65536)
        self.assertTrue(all(c['ciphertext_size'] <= 65536 + s3.OVERHEAD for c in item['chunks']))
        expected = hashlib.sha256()
        for _ in range(32):
            expected.update(b'x' * 65536)
        expected.update(b'x' * 17)
        self.assertEqual(item['sha256'], expected.hexdigest())
        s3.restore_synthetic(writer.directory, self.key, self.root / 'restored')

    def test_nonsecret_summary_and_encrypted_index(self):
        secret = 'synthetic-private-key-name-and-metadata'
        directory = self.create([(secret, secret.encode(), {'private': secret})])
        summary = s3.inspect_archive(directory, self.key)
        self.assertNotIn(secret, encoded(summary).decode())
        self.assertFalse(summary['live_s3_backup_verified'])
        self.assertFalse(summary['remote_s3_restore_verified'])
        for path in directory.iterdir():
            self.assertNotIn(secret.encode(), path.read_bytes())
            self.assertNotIn(self.key, path.read_bytes())

    def test_unique_sessions_salts_and_nonces(self):
        first = self.create()
        second = self.create()
        a, b = self.reader(first), self.reader(second)
        self.assertNotEqual(a.core['session_id'], b.core['session_id'])
        self.assertNotEqual(a.core['salt'], b.core['salt'])
        self.assertNotEqual(s3._keys(self.key, a.core), s3._keys(self.key, b.core))
        nonces = [path.read_bytes()[8:20] for path in first.glob('*.enc')]
        self.assertEqual(len(nonces), len(set(nonces)))
        self.assertEqual(len({p.name for p in self.parent.iterdir()}), 2)

    def test_corrupt_ciphertext_refused_before_plaintext_destination(self):
        directory = self.create()
        path = next(directory.glob('object-*.enc'))
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        destination = self.root / 'restored'
        with self.assertRaisesRegex(RecoveryError, 'CIPHERTEXT_CHECKSUM'):
            s3.restore_synthetic(directory, self.key, destination)
        self.assertFalse(destination.exists())

    def test_gcm_detects_corruption_even_with_authenticated_updated_hash(self):
        directory = self.create()
        path = next(directory.glob('object-*.enc'))
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        def change(index):
            index['objects'][0]['chunks'][0]['ciphertext_sha256'] = digest(raw)
        self.rewrite_index(directory, change)
        with self.assertRaisesRegex(RecoveryError, 'GCM_AUTHENTICATION'):
            self.reader(directory)

    def test_corrupt_index(self):
        directory = self.create()
        path = directory / 'index.json.enc'
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(RecoveryError, 'INDEX_CHECKSUM'):
            self.reader(directory)

    def test_index_gcm_rejects_tampering_after_updated_outer_authentication(self):
        directory = self.create()
        path = directory / 'index.json.enc'
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        envelope = json.loads((directory / 'manifest.json').read_bytes())
        core = {field: envelope[field] for field in s3.CORE_FIELDS}
        _, _, mac_key = s3._keys(self.key, core)
        envelope['index_sha256'] = digest(raw)
        unsigned = {k: v for k, v in envelope.items() if k != 'authentication'}
        envelope['authentication'] = hmac.new(mac_key, encoded(unsigned), hashlib.sha256).hexdigest()
        (directory / 'manifest.json').write_bytes(encoded(envelope))
        with self.assertRaisesRegex(RecoveryError, 'GCM_AUTHENTICATION'):
            self.reader(directory)

    def test_index_cannot_be_substituted_between_sessions(self):
        first, second = self.create(), self.create()
        (first / 'index.json.enc').write_bytes((second / 'index.json.enc').read_bytes())
        with self.assertRaisesRegex(RecoveryError, 'INDEX_CHECKSUM'):
            self.reader(first)

    def test_wrong_key(self):
        directory = self.create()
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_AUTHENTICATION'):
            s3.verify_archive(directory, os.urandom(32))

    def test_manifest_tampering(self):
        directory = self.create()
        path = directory / 'manifest.json'
        envelope = json.loads(path.read_bytes())
        envelope['index_sha256'] = '0' * 64
        path.write_bytes(encoded(envelope))
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_AUTHENTICATION'):
            self.reader(directory)

    def test_missing_chunk(self):
        directory = self.create()
        next(directory.glob('object-*.enc')).unlink()
        with self.assertRaisesRegex(RecoveryError, 'ARTIFACT_SET'):
            self.reader(directory)

    def test_truncated_ciphertext(self):
        directory = self.create()
        path = next(directory.glob('object-*.enc'))
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(RecoveryError, 'ARTIFACT_SIZE'):
            self.reader(directory)

    def test_early_eof_and_extra_source_bytes_abort_without_sealed_manifest(self):
        for raw, declared in ((b'a', 2), (b'ab', 1)):
            writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1)
            with self.subTest(declared=declared), self.assertRaises(RecoveryError):
                writer.add_object('fixture', io.BytesIO(raw), size_bytes=declared)
            self.assertEqual(writer.state, 'ABORTED')
            self.assertFalse((writer.directory / 'manifest.json').exists())
            with self.assertRaises(RecoveryError):
                self.reader(writer.directory)

    def test_source_read_error_does_not_expose_raw_exception(self):
        class Broken:
            def read(self, size):
                raise OSError('synthetic-private-value')
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1)
        with self.assertRaises(RecoveryError) as caught:
            writer.add_object('fixture', Broken(), size_bytes=1)
        self.assertNotIn('synthetic-private-value', str(caught.exception))
        self.assertFalse((writer.directory / 'manifest.json').exists())

    def test_unsealed_context_is_aborted(self):
        with s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1) as writer:
            writer.add_object('fixture', io.BytesIO(b'a'), size_bytes=1)
        self.assertEqual(writer.state, 'ABORTED')
        self.assertTrue((writer.directory / 'aborted.json').exists())
        with self.assertRaises(RecoveryError):
            self.reader(writer.directory)
        with self.assertRaisesRegex(RecoveryError, 'SESSION_NOT_OPEN'):
            writer.seal()

    def test_seal_checks_on_disk_artifacts_before_status(self):
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1)
        writer.add_object('fixture', io.BytesIO(b'a'), size_bytes=1)
        next(writer.directory.glob('object-*.enc')).write_bytes(b'broken')
        with self.assertRaises(RecoveryError):
            writer.seal()
        self.assertNotEqual(writer.state, 'SEALED')
        self.assertFalse((writer.directory / 'manifest.json').exists())

    def test_partial_manifest_write_never_produces_a_usable_sealed_session(self):
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1)
        writer.add_object('fixture', io.BytesIO(b'a'), size_bytes=1)
        write = s3._write
        def interrupted(directory, name, raw):
            if name == 'manifest.json':
                write(directory, name, raw[:20])
                raise OSError('synthetic-sensitive-write-error')
            write(directory, name, raw)
        with patch.object(s3, '_write', side_effect=interrupted):
            with self.assertRaises(RecoveryError) as caught:
                writer.seal()
        self.assertNotIn('sensitive', str(caught.exception))
        self.assertEqual(writer.state, 'ABORTED')
        with self.assertRaises(RecoveryError):
            self.reader(writer.directory)

    def test_seal_requires_expected_count(self):
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=2)
        writer.add_object('fixture', io.BytesIO(b'a'), size_bytes=1)
        with self.assertRaisesRegex(RecoveryError, 'OBJECT_COUNT'):
            writer.seal()
        self.assertFalse((writer.directory / 'manifest.json').exists())

    def test_no_reseal_or_append_after_success(self):
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1)
        writer.add_object('fixture', io.BytesIO(b'a'), size_bytes=1)
        writer.seal()
        before = {p.name: p.read_bytes() for p in writer.directory.iterdir()}
        with self.assertRaises(RecoveryError):
            writer.seal()
        with self.assertRaises(RecoveryError):
            writer.add_object('next', io.BytesIO(b'a'), size_bytes=1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in writer.directory.iterdir()})

    def test_existing_artifact_is_never_overwritten(self):
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1)
        path = writer.directory / 'object-00000001-chunk-00000001.enc'
        path.write_bytes(b'keep this synthetic file')
        with self.assertRaises(RecoveryError):
            writer.add_object('fixture', io.BytesIO(b'a'), size_bytes=1)
        self.assertEqual(path.read_bytes(), b'keep this synthetic file')
        self.assertFalse((writer.directory / 'manifest.json').exists())

    def test_existing_destination_including_empty_directory_refused(self):
        directory = self.create()
        for name, as_file in (('empty', False), ('occupied', False), ('file', True)):
            destination = self.root / name
            if as_file:
                destination.write_bytes(b'keep')
            else:
                destination.mkdir()
                if name == 'occupied':
                    (destination / 'keep').write_bytes(b'keep')
            with self.subTest(name=name), self.assertRaisesRegex(RecoveryError, 'DESTINATION_EXISTS'):
                s3.restore_synthetic(directory, self.key, destination)
        self.assertEqual((self.root / 'occupied' / 'keep').read_bytes(), b'keep')

    def test_restore_rejects_traversal_inside_archive_and_outside_temp(self):
        directory = self.create()
        for path in (self.root / 'a' / '..' / 'escape', directory / 'restored', Path(tempfile.gettempdir()).anchor):
            with self.subTest(path=path), self.assertRaises(RecoveryError):
                s3.restore_synthetic(directory, self.key, path)

    def test_authenticated_chunk_path_traversal_is_rejected(self):
        directory = self.create()
        outside = self.root / 'outside.enc'
        outside.write_bytes(b'do not read')
        self.rewrite_index(directory, lambda index: index['objects'][0]['chunks'][0].update(file='../outside.enc'))
        with self.assertRaisesRegex(RecoveryError, 'UNSAFE_ARTIFACT_PATH'):
            self.reader(directory)
        self.assertEqual(outside.read_bytes(), b'do not read')

    def test_hardlinked_chunk_is_refused(self):
        directory = self.create()
        chunk = next(directory.glob('object-*.enc'))
        os.link(chunk, self.root / 'linked-chunk')
        with self.assertRaisesRegex(RecoveryError, 'UNSAFE_ARTIFACT_FILE'):
            self.reader(directory)

    def test_aad_binds_original_key(self):
        directory = self.create()
        self.rewrite_index(directory, lambda index: index['objects'][0].update(key='other-key'))
        with self.assertRaisesRegex(RecoveryError, 'GCM_AUTHENTICATION'):
            self.reader(directory)

    def test_object_sha_and_chunk_sha_are_both_checked(self):
        for whole in (False, True):
            directory = self.create()
            def change(index):
                target = index['objects'][0] if whole else index['objects'][0]['chunks'][0]
                target['sha256'] = '0' * 64
            self.rewrite_index(directory, change)
            with self.subTest(whole=whole), self.assertRaisesRegex(RecoveryError, 'OBJECT_CHECKSUM|PLAINTEXT_CHECKSUM'):
                self.reader(directory)

    def test_duplicate_keys_and_invalid_limits_abort(self):
        writer = s3.S3ArchiveWriter(self.parent, self.key, expected_objects=2)
        writer.add_object('same', io.BytesIO(b'a'), size_bytes=1)
        with self.assertRaisesRegex(RecoveryError, 'DUPLICATE_OBJECT_KEY'):
            writer.add_object('same', io.BytesIO(b'b'), size_bytes=1)
        for chunk_size in (0, True, s3.MAX_CHUNK + 1):
            with self.subTest(chunk_size=chunk_size), self.assertRaises(RecoveryError):
                s3.S3ArchiveWriter(self.parent, self.key, expected_objects=1, chunk_size=chunk_size)

    def test_empty_archive(self):
        directory = self.create([])
        self.assertEqual(self.reader(directory).summary()['objects'], 0)
        s3.restore_synthetic(directory, self.key, self.root / 'restored')

    def test_duplicate_json_fields_and_unexpected_artifacts_refused(self):
        directory = self.create()
        path = directory / 'manifest.json'
        raw = path.read_bytes()
        path.write_bytes(b'{"state":"SEALED",' + raw[1:])
        with self.assertRaisesRegex(RecoveryError, 'DUPLICATE_JSON'):
            self.reader(directory)
        path.write_bytes(raw)
        (directory / 'unexpected.enc').write_bytes(b'extra')
        with self.assertRaisesRegex(RecoveryError, 'ARTIFACT_SET'):
            self.reader(directory)

    def test_existing_database_v1_profile_still_loads(self):
        identity = '20261020T000000Z-0123456789ab'
        directory = self.root / 'backups' / identity
        directory.mkdir(parents=True)
        keys = self.root / '.recovery-keys'
        keys.mkdir()
        (keys / (identity + '.key')).write_bytes(self.key)
        archive = Archive(directory, self.key, {'backup_id': identity, 'schema_version': 1,
                          'artifacts': [], 'consistency_status': 'PASS'})
        for name in MANDATORY - {'details.json.enc'}:
            raw = b'PGDMPsynthetic' if name.endswith('.dump.enc') else b'synthetic'
            archive.add(name, raw, component='fixture', method='synthetic', version='1')
        for table in SERVING_TABLES:
            archive.add('ch-' + table + '.native.enc', b'synthetic', component='fixture', method='synthetic', version='1')
        details = {'serving': dict.fromkeys(SERVING_TABLES, {}), 'clickhouse_version': '25.8.23.13',
                   'postgres': {k: {'version': '17.6'} for k in ('platform', 'airflow', 'superset')}}
        archive.add('details.json.enc', encoded(details), component='fixture', method='synthetic', version='1')
        archive.seal()
        loaded, actual = load_archive(self.root, identity)
        self.assertEqual(actual, details)
        self.assertEqual(loaded.read('platform.dump.enc'), b'PGDMPsynthetic')
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_SCHEMA'):
            self.reader(directory)


if __name__ == '__main__':
    unittest.main()
