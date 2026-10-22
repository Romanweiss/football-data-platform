"""Local synthetic fixture preparation ONLY; no vault, network or production CLI.

The one retained original key is displayed only by the operator's local GUI.
Never print DisplayMaterial fields or use this module for real recovery material.
"""
from dataclasses import dataclass
import hmac
import io
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from src.recovery.archive import exclusive_write
from src.recovery.runtime import encoded, require
from src.recovery.s3_archive import S3ArchiveWriter, verify_archive
from src.recovery.s3_safety import assert_private, generate_key, load_key, prepare_directory, safe_path, session_permissions

PREFIX = 'football-bitwarden-synthetic-'
KIND = 'MANUAL_BITWARDEN_SYNTHETIC_V1'
PAYLOADS = {'sample.json': b'{"source":"manual-synthetic-escrow","match_id":1}',
            'binary.bin': bytes(range(64)), 'empty.bin': b''}


def fixture_root(value):
    root = safe_path(value)
    require(root.parent == Path(tempfile.gettempdir()).resolve()
            and re.fullmatch(PREFIX + r'[a-f0-9]{32}', root.name) is not None
            and root.drive.casefold() != 'k:', 'SYNTHETIC_DRILL_TEMP_ROOT_REQUIRED')
    return root


def prepare():
    """Retain a new test-only session for the explicit human escrow checkpoint."""
    root = fixture_root(Path(tempfile.gettempdir()) / (PREFIX + uuid.uuid4().hex))
    for path in (root, root / 'archives', root / 'original', root / 'recovered'):
        prepare_directory(path, confirmed=True)
    key_file = root / 'original' / 'synthetic.key'
    generate_key(key_file, confirmed=True)
    key = load_key(key_file)
    with S3ArchiveWriter(root / 'archives', key, expected_objects=len(PAYLOADS),
                         chunk_size=64, permission_guard=session_permissions) as writer:
        for name, payload in PAYLOADS.items():
            writer.add_object(name, io.BytesIO(payload), size_bytes=len(payload),
                              metadata={'purpose': 'SYNTHETIC_BITWARDEN_TEST_ONLY'})
        writer.seal()
        session_id = writer.core['session_id']
    exclusive_write(root / 'prepared.json', encoded({'kind': KIND, 'session_id': session_id}))
    assert_private(root, children=True)
    return {'status': 'WAITING_FOR_MANUAL_BITWARDEN_ESCROW', 'session_id': session_id,
            'fixture_root': str(root), 'external_recovery': 'NOT_VERIFIED'}


@dataclass(repr=False)
class DisplayMaterial:
    session_id: str
    hex_key: str


def read_for_display(value):
    """GUI ONLY. No clipboard/print/file encoding; rejects live-scope archives."""
    root, record = session_record(value)
    key = load_key(root / 'original' / 'synthetic.key')
    archive = verify_archive(root / 'archives' / record['session_id'], key)
    require(archive.core['scope'] == 'synthetic-local'
            and archive.core['session_id'] == record['session_id']
            and {item['key']: item['size_bytes'] for item in archive.index['objects']}
            == {name: len(payload) for name, payload in PAYLOADS.items()}, 'SYNTHETIC_DRILL_SCOPE_REQUIRED')
    return DisplayMaterial(record['session_id'], key.hex())


def session_record(value):
    """Read public synthetic markers/header only, NEVER the original key bytes."""
    root = fixture_root(value)
    assert_private(root, children=True)
    require({p.name for p in root.iterdir()} <= {
        'archives', 'original', 'recovered', 'prepared.json', 'original-excluded.json',
        'recovered-from-phone.json'}, 'SYNTHETIC_UNEXPECTED_FIXTURE_FILES')
    marker = root / 'prepared.json'
    require(marker.is_file() and marker.stat().st_size <= 4096, 'SYNTHETIC_DRILL_MARKER_REQUIRED')
    record = json.loads(marker.read_bytes())
    require(isinstance(record, dict) and set(record) == {'kind', 'session_id'}
            and record['kind'] == KIND and isinstance(record['session_id'], str)
            and re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{32}', record['session_id']) is not None,
            'SYNTHETIC_DRILL_MARKER_INVALID')
    archive = root / 'archives' / record['session_id']
    require({p.name for p in (root / 'archives').iterdir()} == {record['session_id']},
            'SYNTHETIC_SESSION_MISMATCH')
    assert_private(archive, children=True)
    manifest = archive / 'manifest.json'
    require(manifest.stat().st_size <= 65536, 'SYNTHETIC_DRILL_SCOPE_REQUIRED')
    header = json.loads(manifest.read_bytes())
    require(header.get('scope') == 'synthetic-local' and header.get('profile') == 's3-current-objects'
            and header.get('session_id') == record['session_id'] and header.get('state') == 'SEALED',
            'SYNTHETIC_DRILL_SCOPE_REQUIRED')
    return root, record


def exclude_original(value, expected_session_id, *, phone_confirmed=False, viewer_closed=False):
    """Explicit operator checkpoint. Unlink only the original disposable test key.

    Ordinary removal is not forensic erasure. No original key read/copy occurs here.
    """
    require(phone_confirmed is True and viewer_closed is True, 'SYNTHETIC_OPERATOR_CONFIRMATION_REQUIRED')
    root, record = session_record(value)
    require(record['session_id'] == expected_session_id, 'SYNTHETIC_SESSION_MISMATCH')
    original, recovered = root / 'original', root / 'recovered'
    assert_private(original, children=True)
    assert_private(recovered, children=True)
    require(not any(recovered.iterdir()), 'SYNTHETIC_RECOVERY_ALREADY_STARTED')
    key_file = original / 'synthetic.key'
    require({p.name for p in original.iterdir()} <= {'synthetic.key'}, 'SYNTHETIC_UNEXPECTED_ORIGINAL_FILES')
    if key_file.exists():
        require(key_file.stat().st_size == 32, 'SYNTHETIC_INVALID_ORIGINAL_KEY')
        key_file.unlink()  # Exact validated fixture file only. Never recursive.
    require(not key_file.exists(), 'SYNTHETIC_ORIGINAL_STILL_PRESENT')
    evidence = {'kind': KIND, 'session_id': record['session_id'], 'phone_visibility': 'OPERATOR_CONFIRMED',
                'original_absent': True}
    checkpoint = root / 'original-excluded.json'
    if checkpoint.exists():
        require(json.loads(checkpoint.read_bytes()) == evidence, 'SYNTHETIC_CHECKPOINT_MISMATCH')
    else:
        exclusive_write(checkpoint, encoded(evidence))
    return {'status': 'ORIGINAL_EXCLUDED_WAITING_FOR_PHONE_INPUT', 'session_id': record['session_id']}


def recovery_record(value):
    root, record = session_record(value)
    require(not any((root / 'original').iterdir()), 'SYNTHETIC_ORIGINAL_STILL_PRESENT')
    assert_private(root / 'original')
    assert_private(root / 'recovered', children=True)
    checkpoint = root / 'original-excluded.json'
    require(checkpoint.is_file() and checkpoint.stat().st_size <= 4096, 'SYNTHETIC_EXCLUSION_CHECKPOINT_REQUIRED')
    require(json.loads(checkpoint.read_bytes()) == {
        'kind': KIND, 'session_id': record['session_id'], 'phone_visibility': 'OPERATOR_CONFIRMED',
        'original_absent': True}, 'SYNTHETIC_CHECKPOINT_MISMATCH')
    return root, record


def receive_from_phone(value, hex_key, *, phone_attested=False):
    """Local masked GUI input ONLY. No vault access, original-key fallback or overwrite."""
    require(phone_attested is True, 'SYNTHETIC_PHONE_ATTESTATION_REQUIRED')
    root, record = recovery_record(value)
    require(isinstance(hex_key, str) and re.fullmatch(r'[0-9A-Fa-f]{64}', hex_key) is not None,
            'SYNTHETIC_KEY_HEX_INVALID')
    key_file = root / 'recovered' / 'synthetic.key'
    require(not any((root / 'recovered').iterdir()), 'SYNTHETIC_RECOVERED_KEY_EXISTS')
    key = bytes.fromhex(hex_key)
    archive = verify_archive(root / 'archives' / record['session_id'], key)
    require(archive.core['scope'] == 'synthetic-local', 'SYNTHETIC_DRILL_SCOPE_REQUIRED')
    # Authenticate before writing: a typo/wrong key leaves the recovery directory empty.
    exclusive_write(key_file, key)
    assert_private(key_file)
    with key_file.open('r+b') as stream:
        os.fsync(stream.fileno())
    require(hmac.compare_digest(load_key(key_file), key), 'SYNTHETIC_KEY_READBACK_FAILED')
    evidence = {'kind': KIND, 'session_id': record['session_id'], 'phone_source': 'OPERATOR_ATTESTED',
                'original_absent': True, 'offline_verify': 'PASS'}
    exclusive_write(root / 'recovered-from-phone.json', encoded(evidence))
    return {'status': 'SYNTHETIC_KEY_RECEIVED_OFFLINE_VERIFY_PASS', 'session_id': record['session_id']}
