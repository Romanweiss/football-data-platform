"""Authenticated encrypted local artifacts; keys never enter the backup directory."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.recovery.runtime import RecoveryError, digest, encoded, require, run

SCHEMA_VERSION = 1
MAGIC = b'FDP8C01\x00'
MANDATORY = {'platform.dump.enc', 'airflow.dump.enc', 'superset.dump.enc',
             'platform.roles.enc', 'airflow.roles.enc', 'superset.roles.enc',
             'grafana.sqlite.enc', 'details.json.enc'}
SERVING_TABLES = {'event_core', 'match_results', 'match_squads', 'matches', 'pass_events',
                  'player_match_stats', 'player_match_stats_v2', 'players', 'shot_events',
                  'team_match_stats', 'team_match_stats_v2', 'teams'}


def backup_id(value):
    require(bool(re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{12}', value)), 'INVALID_BACKUP_ID')
    return value


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not path.is_symlink(), 'SYMLINK_DIRECTORY_REFUSED')
    if os.name == 'nt':
        sid = run(['powershell', '-NoProfile', '-Command',
                   '[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value']).decode().strip()
        require(bool(re.fullmatch(r'S-\d+(?:-\d+)+', sid)), 'WINDOWS_ACL_IDENTITY_FAILED')
        run(['icacls', str(path.resolve()), '/inheritance:r', '/grant:r', '*' + sid + ':(OI)(CI)F'])
    else:
        path.chmod(0o700)


def exclusive_write(path, raw):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(raw)


def artifact_path(directory, name):
    require(bool(re.fullmatch(r'[a-z0-9_.-]+\.enc', name)), 'UNSAFE_ARTIFACT_PATH')
    path = directory / name
    require(not path.is_symlink() and path.resolve().parent == directory.resolve(), 'UNSAFE_ARTIFACT_PATH')
    return path


class Archive:
    def __init__(self, directory, key, manifest):
        self.directory, self.key, self.manifest = Path(directory), key, manifest

    def add(self, name, raw, *, component, method, version):
        require(len(raw) < 512 * 1024 * 1024, 'ARTIFACT_EXCEEDS_LOCAL_MEMORY_BUDGET')
        aad = (self.manifest['backup_id'] + '/' + name).encode()
        nonce = os.urandom(12)
        encrypted = MAGIC + nonce + AESGCM(self.key).encrypt(nonce, raw, aad)
        exclusive_write(artifact_path(self.directory, name), encrypted)
        self.manifest['artifacts'].append({'path': name, 'source_component': component,
            'backup_method': method, 'source_version': version, 'file_size': len(encrypted),
            'sha256': digest(encrypted), 'plaintext_size': len(raw), 'plaintext_sha256': digest(raw)})

    def read(self, name):
        entry = next((a for a in self.manifest['artifacts'] if a['path'] == name), None)
        require(entry is not None, 'MISSING_ARTIFACT_ENTRY')
        path = artifact_path(self.directory, name)
        require(path.is_file(), 'MISSING_BACKUP_ARTIFACT')
        require(path.stat().st_size == entry['file_size'], 'ARTIFACT_SIZE_MISMATCH')
        raw = path.read_bytes()
        require(digest(raw) == entry['sha256'] and raw.startswith(MAGIC), 'ARTIFACT_CHECKSUM_OR_FORMAT')
        try:
            plain = AESGCM(self.key).decrypt(raw[8:20], raw[20:], (self.manifest['backup_id'] + '/' + name).encode())
        except Exception:
            raise RecoveryError('ARTIFACT_AUTHENTICATION_FAILED') from None
        require(len(plain) == entry['plaintext_size'] and digest(plain) == entry['plaintext_sha256'], 'PLAINTEXT_CHECKSUM')
        return plain

    def seal(self):
        self.manifest['authentication'] = hmac.new(self.key, encoded(self.manifest), hashlib.sha256).hexdigest()
        exclusive_write(self.directory / 'manifest.json', encoded(self.manifest))


def load_archive(root, identity):
    identity = backup_id(identity)
    directory = root / 'backups' / identity
    require(directory.is_dir() and not directory.is_symlink(), 'BACKUP_NOT_FOUND')
    manifest_path = directory / 'manifest.json'
    require(manifest_path.is_file() and not manifest_path.is_symlink(), 'MANIFEST_NOT_FOUND')
    require(manifest_path.stat().st_size < 1024 * 1024, 'MANIFEST_TOO_LARGE')
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest.get('schema_version') == SCHEMA_VERSION, 'INCOMPATIBLE_BACKUP_SCHEMA')
    require(manifest.get('backup_id') == identity, 'BACKUP_ID_MISMATCH')
    key_path = root / '.recovery-keys' / (identity + '.key')
    require(key_path.is_file() and not key_path.is_symlink(), 'RECOVERY_KEY_NOT_FOUND')
    key = key_path.read_bytes()
    require(len(key) == 32, 'INVALID_RECOVERY_KEY')
    unsigned = {k: v for k, v in manifest.items() if k != 'authentication'}
    expected = hmac.new(key, encoded(unsigned), hashlib.sha256).hexdigest()
    require(hmac.compare_digest(expected, manifest.get('authentication', '')), 'MANIFEST_AUTHENTICATION_FAILED')
    paths = [a['path'] for a in manifest['artifacts']]
    require(len(paths) == len(set(paths)) and MANDATORY <= set(paths), 'INCOMPLETE_COMPONENT_SET')
    archive = Archive(directory, key, manifest)
    # Authenticate every component before planning or creating any restore target.
    for name in paths:
        plain = archive.read(name)
        if name.endswith('.dump.enc'):
            require(plain.startswith(b'PGDMP'), 'INVALID_POSTGRES_DUMP')
    details = json.loads(archive.read('details.json.enc'))
    require(set(details['serving']) == SERVING_TABLES, 'INCOMPLETE_SERVING_SET')
    expected_paths = MANDATORY | {f'ch-{t}.native.enc' for t in details['serving']}
    require(set(paths) == expected_paths, 'INCOMPLETE_COMPONENT_SET')
    require(manifest['consistency_status'] == 'PASS', 'INCONSISTENT_BACKUP')
    require(all(details['postgres'][n]['version'] == '17.6' for n in ('platform', 'airflow', 'superset')),
            'INCOMPATIBLE_POSTGRES_VERSION')
    require(details['clickhouse_version'] == '25.8.23.13', 'INCOMPATIBLE_CLICKHOUSE_VERSION')
    return archive, details


def verified_drills(archive):
    reports = []
    for path in sorted(archive.directory.glob('drill-*.json')):
        require(not path.is_symlink() and path.stat().st_size < 1024 * 1024, 'UNSAFE_DRILL_REPORT')
        report = json.loads(path.read_bytes())
        unsigned = {k: v for k, v in report.items() if k != 'authentication'}
        expected = hmac.new(archive.key, encoded(unsigned), hashlib.sha256).hexdigest()
        require(hmac.compare_digest(expected, report.get('authentication', '')), 'DRILL_REPORT_AUTHENTICATION_FAILED')
        require(report['backup_id'] == archive.manifest['backup_id'] and
                report['manifest_sha256'] == digest((archive.directory / 'manifest.json').read_bytes()),
                'DRILL_REPORT_BACKUP_MISMATCH')
        reports.append({key: report[key] for key in ('target', 'status', 'scope', 'restore_seconds')})
    return reports
