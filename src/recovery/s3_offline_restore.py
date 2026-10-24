"""Offline local restore of an authenticated workflow archive; no key-file IO.

Reuses schema 2 crypto and embedded lineage, never source services. Object keys
are map DATA, not filesystem paths. Restored payloads and the map are sensitive.
Only an explicitly confirmed NEW private destination may receive plaintext.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil

from src.recovery.archive import exclusive_write, private_directory
from src.recovery.runtime import digest, encoded, require
from src.recovery.s3_archive import MAX_INDEX, _json, _no_links
from src.recovery.s3_safety import _powershell, assert_private, safe_path, session_permissions
from src.recovery.s3_workflow import _verified_workflow, guarded


@guarded
def independent_media(archive, destination):
    """Read-only disk identity check; a different Windows letter is insufficient."""
    archive, destination = Path(archive), Path(destination)
    if os.name == 'nt':
        drives = [p.drive for p in (archive, destination)]
        require(all(re.fullmatch(r'[A-Za-z]:', d) for d in drives), 'S3_RESTORE_LOCAL_DRIVES_REQUIRED')
        raw = _powershell("$ErrorActionPreference='Stop'; @('" + drives[0][0] + "','" + drives[1][0] + "') | " + r'''
ForEach-Object {
 $v=Get-Volume -DriveLetter $_
 $d=Get-Partition -DriveLetter $_ | Get-Disk
 @{disk=[int]$d.Number;filesystem=[string]$v.FileSystem;
   healthy=($d.HealthStatus -eq 'Healthy' -and $v.HealthStatus -eq 'Healthy');
   online=(-not $d.IsOffline);writable=(-not $d.IsReadOnly)}
} | ConvertTo-Json -Compress
''')
        rows = _json(raw)
        require(isinstance(rows, list) and len(rows) == 2
                and all(isinstance(r, dict) and type(r.get('disk')) is int
                        and r.get('filesystem') == 'NTFS' and r.get('healthy') is True
                        and r.get('online') is True for r in rows)
                and rows[1].get('writable') is True, 'S3_RESTORE_MEDIA_UNSAFE')
        require(rows[0]['disk'] != rows[1]['disk'], 'S3_RESTORE_INDEPENDENT_DISK_REQUIRED')
        return {'source_disk': rows[0]['disk'], 'destination_disk': rows[1]['disk']}
    require(archive.stat().st_dev != destination.parent.stat().st_dev,
            'S3_RESTORE_INDEPENDENT_DEVICE_REQUIRED')
    return {'independent_device': True}


@guarded
def check_paths(directory, destination):
    """Audit only; do not create directories or repair existing permissions."""
    archive, target = safe_path(directory), safe_path(destination)
    require(archive.is_dir(), 'S3_DIRECTORY_REQUIRED')
    require(not target.exists() and target.parent.is_dir(), 'S3_RESTORE_NEW_DESTINATION_REQUIRED')
    require(archive != target and archive not in target.parents and target not in archive.parents,
            'S3_RESTORE_ARCHIVE_OVERLAP')
    require(not any(p.casefold() == 'footballrecoveryvault' for p in target.parts),
            'S3_RESTORE_KEY_VAULT_REFUSED')
    assert_private(archive, children=True)
    assert_private(target.parent)
    media = independent_media(archive, target)
    return archive, target, media


def _session(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{32}', value) is not None,
            'S3_RESTORE_EXPECTED_SESSION_REQUIRED')


@guarded
def phone_key(hex_key, *, phone_attested=False):
    require(phone_attested is True, 'S3_RESTORE_PHONE_ATTESTATION_REQUIRED')
    require(isinstance(hex_key, str) and re.fullmatch(r'[a-fA-F0-9]{64}', hex_key) is not None,
            'S3_RESTORE_KEY_HEX_INVALID')
    return bytes.fromhex(hex_key)


def _verified(directory, key, expected_session):
    _session(expected_session)
    require(Path(directory).name == expected_session, 'S3_RESTORE_SESSION_MISMATCH')
    manifest_digest = digest((Path(directory) / 'manifest.json').read_bytes())
    archive, source, records, lineage = _verified_workflow(Path(directory), key, allow_live=True)
    require(digest((Path(directory) / 'manifest.json').read_bytes()) == manifest_digest,
            'S3_RESTORE_ARCHIVE_CHANGED')
    require(archive.core['session_id'] == expected_session, 'S3_RESTORE_SESSION_MISMATCH')
    return archive, source, records, lineage, manifest_digest


def _mapping(archive, records):
    return {'schema_version': 1, 'purpose': 'offline-s3-object-map',
            'session_id': archive.core['session_id'],
            'objects': [{**{k: item[k] for k in ('key', 'metadata', 'size_bytes', 'sha256')},
                         'file': f'object-{n:08d}.bin'} for n, item in enumerate(records, 1)]}


def _space(target, records, mapping):
    total = sum(r['size_bytes'] for r in records)
    map_bytes = len(encoded(mapping))
    require(map_bytes <= MAX_INDEX, 'S3_RESTORE_MAP_TOO_LARGE')
    reserve = max(64 * 1024 * 1024, (total + 3) // 4)
    required = total + map_bytes + 4096 + reserve
    free = shutil.disk_usage(target.parent).free
    require(free >= required, 'S3_RESTORE_INSUFFICIENT_SPACE')
    return {'source_bytes': total, 'required_free_bytes': required, 'free_bytes': free}


@guarded
def plan_restore(directory, key, destination, *, expected_session, phone_attested=False):
    require(phone_attested is True, 'S3_RESTORE_PHONE_ATTESTATION_REQUIRED')
    _session(expected_session)
    directory, target, media = check_paths(directory, destination)
    archive, _, records, lineage, _ = _verified(directory, key, expected_session)
    mapping = _mapping(archive, records)
    return {'status': 'OFFLINE_RESTORE_PLAN_VERIFIED_NO_WRITES', 'session_id': expected_session,
            'source_objects': len(records), **_space(target, records, mapping), 'media': media,
            'lineage': lineage, 'scope': archive.core['scope'], 'restore_executed': False}


def _write_payload(path, archive, item):
    _no_links(path)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
        for block in archive.iter_object_chunks(item['object_id']):
            output.write(block)
        output.flush()
        os.fsync(output.fileno())


def _validate_plaintext(target, archive, records, mapping):
    expected = {item['file'] for item in mapping['objects']} | {'object-map.json'}
    require({p.name for p in target.iterdir()} == expected, 'S3_RESTORE_OUTPUT_SET_MISMATCH')
    assert_private(target, children=True)
    require((target / 'object-map.json').stat().st_size <= MAX_INDEX, 'S3_RESTORE_MAP_TOO_LARGE')
    raw = (target / 'object-map.json').read_bytes()
    require(len(raw) <= MAX_INDEX and _json(raw) == mapping, 'S3_RESTORE_MAP_MISMATCH')
    for item, record in zip(mapping['objects'], records):
        path = target / item['file']
        require(path.is_file() and path.stat().st_size == record['size_bytes'], 'S3_RESTORE_SIZE_MISMATCH')
        checksum = hashlib.sha256()
        with path.open('rb') as stream:
            while True:
                block = stream.read(archive.core['chunk_size'])
                if not block:
                    break
                checksum.update(block)
        require(checksum.hexdigest() == record['sha256'], 'S3_RESTORE_SHA256_MISMATCH')


def _publish_report(target, report):
    # Readback/fsync/ACL checks precede publication. Hard-link creation is atomic
    # and fails if the final filename exists (unlike POSIX rename/replace).
    # Both names present => INCOMPLETE, not a successful completion record.
    pending, complete = target / 'restore-report.pending.json', target / 'restore-report.json'
    exclusive_write(pending, encoded(report))
    with pending.open('r+b') as stream:
        os.fsync(stream.fileno())
    require(_json(pending.read_bytes()) == report, 'S3_RESTORE_REPORT_READBACK')
    assert_private(target, children=True)
    _no_links(complete)
    os.link(pending, complete)
    # Remove only our exclusively-created pending link. If removal fails, retain
    # BOTH links as incomplete evidence. No fallible work after the commit step.
    pending.unlink()


@guarded
def restore_local(directory, key, destination, *, expected_session, confirmed=False,
                  phone_attested=False, independent_media_confirmed=False):
    """Never reads the original key. Retains partial output; no resume/cleanup.

    Physical-media check and all cryptographic/embedded-lineage validation precede
    mkdir. A new report is written LAST; its absence means restore is incomplete.
    """
    require(confirmed is True and phone_attested is True and independent_media_confirmed is True,
            'S3_RESTORE_CONFIRMATIONS_REQUIRED')
    _session(expected_session)
    directory, target, media = check_paths(directory, destination)
    archive, source, records, lineage, manifest_digest = _verified(directory, key, expected_session)
    mapping = _mapping(archive, records)
    require(len(encoded(mapping)) <= MAX_INDEX, 'S3_RESTORE_MAP_TOO_LARGE')
    space = _space(target, records, mapping)
    # Recheck paths/media/parent immediately before claiming a NEW directory.
    check_paths(directory, target)
    target.mkdir(mode=0o700)  # No exist_ok, parents or overwrite.
    private_directory(target)
    session_permissions(target, initialize=True)  # Only our new empty directory.
    for item, mapped in zip(records, mapping['objects']):
        _write_payload(target / mapped['file'], archive, item)
    exclusive_write(target / 'object-map.json', encoded(mapping))
    with (target / 'object-map.json').open('r+b') as stream:
        os.fsync(stream.fileno())
    _validate_plaintext(target, archive, records, mapping)
    require(digest((directory / 'manifest.json').read_bytes()) == manifest_digest,
            'S3_RESTORE_ARCHIVE_CHANGED')
    report = {'schema_version': 1, 'session_id': expected_session,
              'status': ('RESTORED_LIVE_OFFLINE_LOCAL' if archive.core['scope'] == 'live-current-objects'
                         else 'RESTORED_SYNTHETIC_OFFLINE_LOCAL'),
              'source_resource_id': source.resource_id, 'source_objects': len(records),
              'source_bytes': space['source_bytes'], 'sha256_verified_objects': len(records),
              'map_sha256': digest(encoded(mapping)), 'sealed_manifest_sha256': manifest_digest,
              'key_route': 'OPERATOR_ATTESTED_BITWARDEN_PHONE_IN_MEMORY',
              'original_key_file_read': False, 'source_services_used': False,
              'lineage': lineage, 'media': media, 'remote_s3_restore_verified': False}
    _publish_report(target, report)
    return report
