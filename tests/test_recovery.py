"""Synthetic failure injection: no Docker, real backups, credentials or S3."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.recovery.archive import Archive, MANDATORY, SERVING_TABLES, artifact_path, load_archive, verified_drills
from src.recovery.operations import (
    assert_isolated, canonical_columns, canonical_database_acl, restore_drill,
    require_sqlite_serialization, restore_plan, sqlite_connection_summary, sqlite_summary, validate_target,
)
from src.recovery.runtime import RecoveryError, digest, encoded, reconcile, run

IDENTITY = '20261020T000000Z-0123456789ab'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'backups' / IDENTITY
        self.folder.mkdir(parents=True)
        (self.root / '.recovery-keys').mkdir()
        self.key = os.urandom(32)
        (self.root / '.recovery-keys' / (IDENTITY + '.key')).write_bytes(self.key)
        self.details = {'serving': dict.fromkeys(sorted(SERVING_TABLES), {}),
                        'postgres': {k: {'version': '17.6'} for k in ('platform', 'airflow', 'superset')},
                        'clickhouse_version': '25.8.23.13'}
        self.archive = Archive(self.folder, self.key, {'backup_id': IDENTITY, 'schema_version': 1,
            'artifacts': [], 'consistency_status': 'PASS', 'contexts': []})
        for name in sorted(MANDATORY - {'details.json.enc'}):
            raw = b'PGDMPsynthetic' if name.endswith('.dump.enc') else b'synthetic-private-value'
            self.add(name, raw)
        for name in SERVING_TABLES:
            self.add('ch-' + name + '.native.enc', b'synthetic-native')

    def add(self, name, raw):
        self.archive.add(name, raw, component='synthetic', method='fixture', version='test')

    def seal(self):
        self.add('details.json.enc', encoded(self.details))
        self.archive.seal()

    def test_encrypted_roundtrip_no_plaintext_or_key_in_artifacts(self):
        self.seal()
        archive, _ = load_archive(self.root, IDENTITY)
        self.assertEqual(archive.read('platform.roles.enc'), b'synthetic-private-value')
        for path in self.folder.iterdir():
            raw = path.read_bytes()
            self.assertNotIn(b'synthetic-private-value', raw)
            self.assertNotIn(self.key, raw)

    def test_absent_backup(self):
        with self.assertRaisesRegex(RecoveryError, 'BACKUP_NOT_FOUND'):
            load_archive(self.root, '20261020T000000Z-abcdef012345')

    def test_absent_manifest(self):
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_NOT_FOUND'):
            load_archive(self.root, IDENTITY)

    def test_missing_artifact(self):
        self.seal()
        (self.folder / 'airflow.dump.enc').unlink()
        with self.assertRaisesRegex(RecoveryError, 'MISSING_BACKUP_ARTIFACT'):
            load_archive(self.root, IDENTITY)

    def test_corrupt_artifact_before_target_mutation(self):
        self.seal()
        path = self.folder / 'platform.dump.enc'
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with patch('src.recovery.operations.ROOT', self.root), patch('src.recovery.operations.docker') as docker:
            with self.assertRaisesRegex(RecoveryError, 'ARTIFACT_CHECKSUM'):
                restore_drill(IDENTITY, 'football-drill-fixture01', True)
            docker.assert_not_called()

    def test_wrong_checksum(self):
        self.archive.manifest['artifacts'][0]['sha256'] = '0' * 64
        self.seal()
        with self.assertRaisesRegex(RecoveryError, 'ARTIFACT_CHECKSUM'):
            load_archive(self.root, IDENTITY)

    def test_aead_rejects_ciphertext_even_with_updated_outer_checksum(self):
        path = self.folder / 'platform.dump.enc'
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        next(a for a in self.archive.manifest['artifacts'] if a['path'] == path.name)['sha256'] = digest(raw)
        self.seal()
        with self.assertRaisesRegex(RecoveryError, 'ARTIFACT_AUTHENTICATION_FAILED'):
            load_archive(self.root, IDENTITY)

    def test_missing_component(self):
        self.archive.manifest['artifacts'] = [a for a in self.archive.manifest['artifacts'] if a['path'] != 'superset.dump.enc']
        self.seal()
        with self.assertRaisesRegex(RecoveryError, 'INCOMPLETE_COMPONENT_SET'):
            load_archive(self.root, IDENTITY)

    def test_missing_serving_table(self):
        self.details['serving'].pop('event_core')
        self.seal()
        with self.assertRaisesRegex(RecoveryError, 'INCOMPLETE_SERVING_SET'):
            load_archive(self.root, IDENTITY)

    def test_incompatible_schema(self):
        self.archive.manifest['schema_version'] = 2
        self.seal()
        with self.assertRaisesRegex(RecoveryError, 'INCOMPATIBLE_BACKUP_SCHEMA'):
            load_archive(self.root, IDENTITY)

    def test_incompatible_server_version(self):
        self.details['clickhouse_version'] = '26.1'
        self.seal()
        with self.assertRaisesRegex(RecoveryError, 'INCOMPATIBLE_CLICKHOUSE_VERSION'):
            load_archive(self.root, IDENTITY)

    def test_manifest_tampering(self):
        self.seal()
        path = self.folder / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['consistency_status'] = 'untrusted'
        path.write_bytes(encoded(manifest))
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_AUTHENTICATION_FAILED'):
            load_archive(self.root, IDENTITY)

    def test_fake_restore_pass_report_is_not_trusted(self):
        self.seal()
        (self.folder / 'drill-forged.json').write_bytes(encoded({'status': 'PASS', 'authentication': '0' * 64}))
        with self.assertRaisesRegex(RecoveryError, 'DRILL_REPORT_AUTHENTICATION_FAILED'):
            verified_drills(self.archive)

    def test_wrong_key(self):
        self.seal()
        (self.root / '.recovery-keys' / (IDENTITY + '.key')).write_bytes(os.urandom(32))
        with self.assertRaisesRegex(RecoveryError, 'MANIFEST_AUTHENTICATION_FAILED'):
            load_archive(self.root, IDENTITY)

    def test_path_traversal(self):
        for name in ('../outside.enc', 'F:/other.enc', '/root.enc', 'nested/file.enc'):
            with self.subTest(name=name), self.assertRaisesRegex(RecoveryError, 'UNSAFE_ARTIFACT_PATH'):
                artifact_path(self.folder, name)

    def test_no_implicit_or_active_target(self):
        with patch('src.recovery.operations.docker') as docker:
            for target in ('football-data-platform', '', 'football-clickhouse', 'football-drill-../bad'):
                with self.subTest(target=target), self.assertRaisesRegex(RecoveryError, 'ISOLATED_TARGET_REQUIRED'):
                    validate_target(target)
            docker.assert_not_called()

    def test_target_collision(self):
        with patch('src.recovery.operations.docker', return_value=b'football-drill-fixture01-platform\n'):
            with self.assertRaisesRegex(RecoveryError, 'TARGET_RESOURCE_ALREADY_EXISTS'):
                validate_target('football-drill-fixture01')

    def test_target_requires_explicit_confirmation(self):
        with patch('src.recovery.operations.docker') as docker:
            with self.assertRaisesRegex(RecoveryError, 'EXPLICIT_ISOLATION_CONFIRMATION_REQUIRED'):
                restore_drill(IDENTITY, 'football-drill-fixture01')
            docker.assert_not_called()

    def test_network_and_mount_fences(self):
        safe = {'labels': {'com.docker.compose.project': 'football-drill-fixture01', 'football.recovery': '8c'},
                'network': 'none', 'ports': {}, 'mounts': [{'Type': 'tmpfs'}]}
        for override in ({'network': 'football-network'}, {'ports': {'5432': []}}, {'mounts': [{'Type': 'volume'}]}):
            with patch('src.recovery.operations.container_info', return_value=safe | override):
                with self.assertRaises(RecoveryError):
                    assert_isolated('synthetic', 'football-drill-fixture01')

    def test_command_failure_never_exposes_stderr(self):
        import subprocess
        result = subprocess.CompletedProcess([], 1, b'synthetic-password', b'postgres://secret@host')
        with patch('src.recovery.runtime.subprocess.run', return_value=result):
            with self.assertRaises(RecoveryError) as caught:
                run(['synthetic'])
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('password', str(caught.exception))

    def test_cli_suppresses_raw_exception(self):
        from scripts.backup import main
        output = io.StringIO()
        with patch('scripts.backup.create_backup', side_effect=ValueError('synthetic-password')):
            with contextlib.redirect_stderr(output):
                self.assertEqual(main(['create']), 1)
        self.assertNotIn('synthetic-password', output.getvalue())

    def test_valid_plan_does_not_start_containers(self):
        self.seal()
        with patch('src.recovery.operations.ROOT', self.root), patch('src.recovery.operations.docker', return_value=b'') as docker:
            result = restore_plan(IDENTITY, 'football-drill-fixture01')
        self.assertEqual(result['status'], 'PLAN_VALIDATED')
        self.assertTrue(all(call.args[0] in ('ps', 'volume', 'network') for call in docker.call_args_list))

    def test_synthetic_sqlite_restore(self):
        import sqlite3
        source = sqlite3.connect(':memory:')
        self.addCleanup(source.close)
        source.execute('CREATE TABLE dashboard(id INTEGER PRIMARY KEY,title TEXT)')
        source.execute("INSERT INTO dashboard VALUES (1,'synthetic')")
        self.assertEqual(sqlite_connection_summary(source), {'dashboard': 1})
        if hasattr(source, 'serialize') and hasattr(source, 'deserialize'):
            self.assertEqual(sqlite_summary(source.serialize()), {'dashboard': 1})
            with self.assertRaises(sqlite3.DatabaseError):
                sqlite_summary(b'not a sqlite database')
        else:
            with self.assertRaisesRegex(RecoveryError, 'RECOVERY_REQUIRES_SQLITE_SERIALIZATION'):
                sqlite_summary(b'not read on an unsupported runtime')

    def test_missing_sqlite_serialization_fails_before_source_io(self):
        from src.recovery.operations import create_backup
        with patch('sqlite3.Connection', object):
            with self.assertRaisesRegex(RecoveryError, 'RECOVERY_REQUIRES_SQLITE_SERIALIZATION'):
                require_sqlite_serialization()
            with patch('src.recovery.operations.source_inventory') as inventory:
                with self.assertRaisesRegex(RecoveryError, 'RECOVERY_REQUIRES_SQLITE_SERIALIZATION'):
                    create_backup()
                inventory.assert_not_called()

    def test_synthetic_local_object_restore_preserves_bytes_and_refuses_overwrite(self):
        from src.recovery.archive import exclusive_write
        raw = b'{"source":"synthetic","match_id":1}\n'
        self.add('synthetic-bronze.enc', raw)
        target = self.root / 'isolated-object-store' / 'football' / 'bronze' / 'sample.json'
        target.parent.mkdir(parents=True)
        exclusive_write(target, self.archive.read('synthetic-bronze.enc'))
        self.assertEqual(digest(target.read_bytes()), digest(raw))
        with self.assertRaises(FileExistsError):
            exclusive_write(target, raw)

    def test_s3_permission_denied_is_unknown_not_disabled(self):
        from src.recovery.s3_inventory import check

        class Denied(Exception):
            response = {'ResponseMetadata': {'HTTPStatusCode': 403}}

        class FakeS3:
            def get_bucket_versioning(self, **kwargs):
                raise Denied('synthetic-sensitive-provider-message')

            get_object_lock_configuration = get_bucket_versioning

            def head_object(self, **kwargs):
                return {'ContentLength': 2, 'Metadata': {'sha256': 'a' * 64}}

        catalog = {'ingestion_objects': [{'s3_bucket': 'fixture', 'object_key': 'football/bronze/fixture',
                   'sha256': 'a' * 64, 'size_bytes': 2}], 'silver_builds': [], 'gold_builds': []}
        result = check(FakeS3(), catalog)
        self.assertEqual(result['capabilities']['fixture']['versioning'], {'available': False, 'http_status': 403})
        self.assertNotIn('synthetic-sensitive-provider-message', str(result))
        self.assertFalse(result['remote_restore_tested'])
        catalog['ingestion_objects'][0]['sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'BRONZE_METADATA_MISMATCH'):
            check(FakeS3(), catalog)

    def test_reconciliation_does_not_accept_order_by_as_uniqueness(self):
        catalog = {k: [] for k in ('silver_builds', 'gold_builds', 'clickhouse_loads', 'clickhouse_gold_loads')}
        with self.assertRaisesRegex(RecoveryError, 'SERVING_DUPLICATE_KEYS'):
            reconcile(catalog, {'events': {'duplicate_keys': 1}})

    def test_backup_and_keys_ignored_by_git_and_docker(self):
        root = Path(__file__).resolve().parents[1]
        for file in ('.gitignore', '.dockerignore'):
            lines = (root / file).read_text().splitlines()
            for name in ('backups/', '.recovery-keys/', '.env', '.passes', 'keys.txt'):
                self.assertIn(name, lines)

    def test_acl_entry_order_not_grant_changes(self):
        a = [{'acl': '{=c/owner,owner=CTc/owner}'}]
        b = [{'acl': '{owner=CTc/owner,=c/owner}'}]
        self.assertEqual(canonical_database_acl(a), canonical_database_acl(b))
        self.assertNotEqual(canonical_database_acl(a), canonical_database_acl([{'acl': '{owner=CTc/owner,=CTc/owner}'}]))

    def test_dropped_attnum_holes_not_logical_column_reordering(self):
        a = [{'table_schema': 'public', 'table_name': 'fixture', 'column_name': 'id', 'ordinal_position': 1},
             {'table_schema': 'public', 'table_name': 'fixture', 'column_name': 'value', 'ordinal_position': 3}]
        b = [dict(a[0]), dict(a[1], ordinal_position=2)]
        self.assertEqual(canonical_columns(a), canonical_columns(b))
        b[0]['ordinal_position'] = 4
        self.assertNotEqual(canonical_columns(a), canonical_columns(b))


if __name__ == '__main__':
    unittest.main()
