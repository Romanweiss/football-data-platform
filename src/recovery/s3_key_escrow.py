"""Offline production-key preparation and GUI-only access. No vault or S3 IO.

The private record is an operator register, NOT authorization or authenticated
archive metadata. A backup session does not exist yet. Never print KeyDisplay.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import uuid

from src.recovery.archive import exclusive_write
from src.recovery.runtime import encoded, require
from src.recovery.s3_operator import require_live_runtime
from src.recovery.s3_safety import _powershell, assert_private, generate_key, load_key, locations, safe_path
from src.recovery.s3_workflow import guarded

PURPOSE = 'production-s3-backup'
NOTE = 'Football Platform | S3 Recovery | Production'
ID_PATTERN = r's3-recovery-\d{8}T\d{6}Z-[a-f0-9]{32}'
RECORD_FIELDS = {'schema_version', 'purpose', 'key_id', 'created_at', 'encoding',
                 'key_file', 'backup_sessions', 'escrow_status', 'independent_recovery'}


def key_directory():
    """Current profile, never a hardcoded username or the archive medium."""
    return Path.home() / 'FootballRecoveryVault' / 's3'


def _host():
    require(os.name == 'nt', 'S3_ESCROW_WINDOWS_HOST_REQUIRED')
    require_live_runtime()


def _directory():
    path = safe_path(key_directory())
    require(path.drive.casefold() != 'k:', 'S3_ESCROW_KEY_ON_BACKUP_MEDIA')
    assert_private(path)
    return path


def _id(value):
    require(isinstance(value, str) and re.fullmatch(ID_PATTERN, value) is not None,
            'S3_ESCROW_KEY_ID_INVALID')
    return value


def _protected_file(path, *, newly_created=False):
    # Never alter an existing operator key. Called with True only immediately
    # after this function's caller exclusively creates its own new file.
    if os.name == 'nt':
        literal = str(path).replace("'", "''")
        setup = r'''
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls $p /inheritance:r /grant:r ('*'+$sid+':F') | Out-Null
if($LASTEXITCODE -ne 0){throw 'ACL_SETUP_FAILED'}
''' if newly_created else ''
        raw = _powershell("$ErrorActionPreference='Stop'; $p='" + literal + "'; " + setup
                          + '@{protected=(Get-Acl -LiteralPath $p).AreAccessRulesProtected}|ConvertTo-Json -Compress')
        require(json.loads(raw).get('protected') is True, 'S3_ESCROW_FILE_DACL_NOT_PROTECTED')
    assert_private(path)


@guarded
def prepare(*, archive_directory, confirmed=False):
    """Exclusive generation only. No display, backup, escrow attestation or cleanup.

    Failure retains any partial files and never authorizes a backup. Do not retry
    generation blindly after an interrupted/failed preparation.
    """
    require(confirmed is True, 'S3_KEY_GENERATION_CONFIRMATION_REQUIRED')
    _host()
    directory = _directory()
    created = datetime.now(timezone.utc)
    key_id = 's3-recovery-' + created.strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
    key_file, record_file = directory / (key_id + '.key'), directory / (key_id + '.json')
    locations(archive_directory, key_file)  # Read-only audit of both separate trees.
    require(not key_file.exists() and not record_file.exists(), 'S3_ESCROW_REFERENCE_EXISTS')
    generate_key(key_file, confirmed=True)
    _protected_file(key_file, newly_created=True)
    record = {'schema_version': 1, 'purpose': PURPOSE, 'key_id': key_id,
              'created_at': created.strftime('%Y-%m-%dT%H:%M:%SZ'), 'encoding': 'hex',
              'key_file': key_file.name, 'backup_sessions': [],
              'escrow_status': 'PENDING_OPERATOR_CONFIRMATION', 'independent_recovery': 'NOT_VERIFIED'}
    exclusive_write(record_file, encoded(record))  # NO material or fingerprint.
    _protected_file(record_file, newly_created=True)
    with record_file.open('r+b') as stream:
        os.fsync(stream.fileno())
    require(_record(directory, key_id) == record, 'S3_ESCROW_RECORD_READBACK_FAILED')
    require(len(load_key(key_file)) == 32, 'S3_INVALID_KEY_FILE')
    return {'status': 'KEY_PREPARED_ESCROW_PENDING', 'key_id': key_id,
            'key_file': str(key_file), 'created_at': record['created_at'],
            'acl': 'PASS_PROTECTED_OWNER_ONLY', 'session_id': None,
            'independent_recovery': 'NOT_VERIFIED', 'live_backup': 'BLOCKED'}


def _record(directory, key_id):
    _id(key_id)
    path = directory / (key_id + '.json')
    _protected_file(path)
    require(path.is_file() and path.stat().st_size <= 4096, 'S3_ESCROW_RECORD_INVALID')
    record = json.loads(path.read_bytes())
    require(isinstance(record, dict) and set(record) == RECORD_FIELDS
            and type(record['schema_version']) is int and record['schema_version'] == 1
            and record['purpose'] == PURPOSE and record['key_id'] == key_id
            and record['key_file'] == key_id + '.key' and record['encoding'] == 'hex'
            and record['backup_sessions'] == []
            and record['escrow_status'] == 'PENDING_OPERATOR_CONFIRMATION'
            and record['independent_recovery'] == 'NOT_VERIFIED'
            and isinstance(record['created_at'], str)
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', record['created_at']) is not None,
            'S3_ESCROW_RECORD_INVALID')
    return record


@dataclass(repr=False)
class KeyDisplay:
    key_id: str
    created_at: str
    hex_key: str


@guarded
def read_for_display(key_id, *, confirmed=False):
    """GUI ONLY, with explicit consent. Never show synthetic keys or arbitrary files."""
    require(confirmed is True, 'S3_ESCROW_DISPLAY_CONFIRMATION_REQUIRED')
    _host()
    directory = _directory()
    record = _record(directory, key_id)
    path = directory / (_id(key_id) + '.key')
    _protected_file(path)  # Audit only; no repair, regeneration, copy or unlink.
    material = load_key(path)
    require(hmac.compare_digest(material, load_key(path)), 'S3_ESCROW_KEY_CHANGED')
    return KeyDisplay(key_id, record['created_at'], material.hex())


@dataclass(repr=False, frozen=True)
class KeyRecovery:
    """Private in-memory comparison baseline, never a saved key or public report."""
    key_id: str
    attempt_id: str
    _fingerprint: bytes


@guarded
def begin_recovery(key_id, *, saved_and_viewer_closed=False):
    require(saved_and_viewer_closed is True, 'S3_ESCROW_SAVED_AND_VIEWER_CLOSED_REQUIRED')
    _host()
    directory = _directory()
    _record(directory, key_id)
    path = directory / (_id(key_id) + '.key')
    _protected_file(path)
    # Original bytes establish only a comparison baseline, NEVER the input value.
    fingerprint = hashlib.sha256(load_key(path)).digest()
    return KeyRecovery(key_id, uuid.uuid4().hex, fingerprint)


@guarded
def confirm_recovered(context, hex_key, *, phone_attested=False, desktop_attested=False):
    """GUI input only. Keep both values/digests in memory; retain the original.

    No recovered-key file, fallback to the original, vault access or backup call.
    A receipt proves this local comparison plus an operator attestation, not a
    forensic audit of Bitwarden or recovery after loss of all devices.
    """
    require(phone_attested is True or desktop_attested is True, 'S3_ESCROW_PHONE_ATTESTATION_REQUIRED')
    require(not (phone_attested is True and desktop_attested is True), 'S3_ESCROW_AMBIGUOUS_SOURCE')
    require(isinstance(context, KeyRecovery), 'S3_ESCROW_RECOVERY_CONTEXT_INVALID')
    _id(context.key_id)
    require(isinstance(context.attempt_id, str) and re.fullmatch(r'[a-f0-9]{32}', context.attempt_id) is not None
            and isinstance(context._fingerprint, bytes) and len(context._fingerprint) == 32,
            'S3_ESCROW_RECOVERY_CONTEXT_INVALID')
    require(isinstance(hex_key, str) and re.fullmatch(r'[a-fA-F0-9]{64}', hex_key) is not None,
            'S3_ESCROW_KEY_HEX_INVALID')
    _host()
    directory = _directory()
    _record(directory, context.key_id)
    original = directory / (context.key_id + '.key')
    receipt = directory / (context.key_id + '.recovery-' + context.attempt_id + '.json')
    require(not receipt.exists(), 'S3_ESCROW_RECOVERY_ALREADY_RECORDED')
    _protected_file(original)
    require(hmac.compare_digest(hashlib.sha256(load_key(original)).digest(), context._fingerprint),
            'S3_ESCROW_ORIGINAL_CHANGED')
    supplied_fingerprint = hashlib.sha256(bytes.fromhex(hex_key)).digest()
    require(hmac.compare_digest(supplied_fingerprint, context._fingerprint), 'S3_ESCROW_KEY_MISMATCH')
    evidence = {'schema_version': 1, 'purpose': 'production-s3-key-equivalence',
                'key_id': context.key_id, 'attempt_id': context.attempt_id,
                'matched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'status': 'MATCH', 'method': ('MANUAL_PHONE_INPUT_SHA256_IN_MEMORY' if phone_attested is True
                                             else 'MANUAL_DESKTOP_INPUT_SHA256_IN_MEMORY'),
                'source': ('OPERATOR_ATTESTED_BITWARDEN_PHONE' if phone_attested is True
                           else 'OPERATOR_ATTESTED_DESKTOP_NOTE_DIAGNOSTIC_ONLY'),
                'independent_route_verified': phone_attested is True,
                'original_preserved': True, 'live_backup_executed': False}
    exclusive_write(receipt, encoded(evidence))
    _protected_file(receipt, newly_created=True)
    with receipt.open('r+b') as stream:
        os.fsync(stream.fileno())
    require(json.loads(receipt.read_bytes()) == evidence, 'S3_ESCROW_RECEIPT_READBACK_FAILED')
    return evidence
