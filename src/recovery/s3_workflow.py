"""Shared synthetic/live archive workflow. Cloud restore remains synthetic-only."""
from copy import deepcopy
from dataclasses import asdict
from functools import wraps
import hashlib
import io

from src.recovery.runtime import RecoveryError, digest, encoded, require
from src.recovery.s3_archive import MAX_CHUNK, MAX_OBJECTS, S3ArchiveWriter, _json, verify_archive
from src.recovery.s3_lineage import snapshot_digest, validate_baseline, validate_lineage
from src.recovery.s3_storage import Head, ListEntry, Page, StorageIdentity

READ_CAPABILITIES = {'list', 'head', 'get', 'conditional_get'}
MAX_EVIDENCE = 8 * 1024 * 1024


def guarded(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except RecoveryError:
            raise
        except Exception:
            raise RecoveryError('S3_WORKFLOW_OPERATION_FAILED') from None
    return call


def _identity(identity):
    require(isinstance(identity, StorageIdentity) and identity.mode == 'synthetic', 'S3_SYNTHETIC_ONLY')
    require(all(isinstance(getattr(identity, f), str) and getattr(identity, f)
                for f in ('authority', 'bucket', 'resource_id'))
            and isinstance(identity.aliases, (tuple, list))
            and all(isinstance(a, str) and a for a in identity.aliases), 'S3_STORAGE_IDENTITY')


def _head(head):
    require(isinstance(head, Head) and type(head.size_bytes) is int and head.size_bytes >= 0
            and isinstance(head.last_modified, str) and bool(head.last_modified)
            and isinstance(head.etag, str) and bool(head.etag), 'S3_INVALID_HEAD')
    require(isinstance(head.metadata, dict) and all(isinstance(k, str) and isinstance(v, str)
            for k, v in head.metadata.items()), 'S3_INVALID_STORAGE_METADATA')


@guarded
def inventory(storage, *, allow_live_read=False):
    """Full-root paginated LIST + HEAD. A terminal page is an adapter assertion.

    Cannot prove absence of consistently omitted unknown keys without an external
    trusted inventory; known catalog keys are independently required by lineage.
    allow_live_read enables only enumeration; backup/restore retain their separate
    mandatory synthetic-only identity guards.
    """
    if allow_live_read:
        require(isinstance(storage.identity, StorageIdentity)
                and storage.identity.mode in ('synthetic', 'live-read-only'), 'S3_STORAGE_IDENTITY')
    else:
        _identity(storage.identity)
    require({'list', 'head'} <= storage.capabilities(), 'S3_READ_CAPABILITY_MISSING')
    token, tokens, listed = None, set(), {}
    while True:
        page = storage.list_page(token)
        require(isinstance(page, Page) and type(page.key_count) is int
                and page.key_count == len(page.objects) and type(page.is_truncated) is bool, 'S3_INVALID_LIST_PAGE')
        require((page.is_truncated and isinstance(page.next_token, str) and bool(page.next_token)
                 and bool(page.objects)) or (not page.is_truncated and page.next_token is None), 'S3_INCOMPLETE_PAGINATION')
        for obj in page.objects:
            require(isinstance(obj, ListEntry) and isinstance(obj.key, str) and bool(obj.key)
                    and type(obj.size_bytes) is int and obj.size_bytes >= 0
                    and isinstance(obj.etag, str) and bool(obj.etag)
                    and isinstance(obj.last_modified, str) and bool(obj.last_modified), 'S3_INVALID_LIST_OBJECT')
            require(obj.key not in listed, 'S3_DUPLICATE_LIST_KEY')
            listed[obj.key] = asdict(obj)
            require(len(listed) < MAX_OBJECTS, 'S3_WORKFLOW_OBJECT_LIMIT')  # One encrypted evidence object.
        if not page.is_truncated:
            break
        require(page.next_token not in tokens, 'S3_PAGINATION_CYCLE')
        tokens.add(page.next_token)
        token = page.next_token
    result = {}
    for key, obj in sorted(listed.items()):
        head = deepcopy(storage.head_object(key))
        _head(head)
        require(head.size_bytes == obj['size_bytes'] and head.last_modified == obj['last_modified'], 'S3_LIST_HEAD_STATE_CHANGED')
        result[key] = {'list': obj, 'head': asdict(head)}
    return result


class _Capture:
    def __init__(self, body, capture):
        self.body, self.capture = body, capture
        self.raw = bytearray()

    def read(self, size):
        require(type(size) is int and size > 0, 'S3_UNBOUNDED_READ')
        data = self.body.read(min(size, 65536))
        require(isinstance(data, bytes) and len(data) <= size, 'S3_INVALID_STREAM')
        if self.capture:
            require(len(self.raw) + len(data) <= 1024 * 1024, 'S3_BUILD_MANIFEST_TOO_LARGE')
            self.raw.extend(data)
        return data


def _manifest_keys(snapshot):
    return ({row['s3_prefix'] + '_manifest.json' for layer in ('silver', 'gold')
             for row in snapshot['catalog'][layer + '_builds']}
            | {row['object_key'] for row in snapshot['catalog']['ingestion_objects']
               if row['dataset'] in ('matches', 'world_cup_2022_matches')})


def _evidence_key(session):
    return '__recovery_evidence__/' + session + '/snapshot.json'


@guarded
def backup_synthetic(storage, metadata_source, parent, master_key, *, chunk_size=MAX_CHUNK):
    _identity(storage.identity)
    return _backup(storage, metadata_source, parent, master_key, chunk_size=chunk_size)


def probe_conditionals(storage, initial):
    for layer in ('bronze', 'silver', 'gold'):
        keys = sorted(k for k, v in initial.items() if k.startswith('football/' + layer + '/')
                      and v['head']['size_bytes'] > 0 and (layer == 'bronze' or k.endswith('.parquet')))
        require(bool(keys), 'S3_CONDITIONAL_SAMPLE_MISSING')
        key = keys[0]
        result = storage.conditional_probe(key, expected=Head(**initial[key]['head']))
        require(result['status'] == 'PASS' and result['incorrect_validator'] == 'HTTP_412',
                'S3_CONDITIONAL_GET_NOT_ENFORCED')


@guarded
def backup_live(storage, metadata_source, parent, master_key, *, confirmed=False,
                before_write=None, permission_guard=None, chunk_size=MAX_CHUNK):
    """Explicit operator opt-in; no automatic key generation, resume or cleanup."""
    require(confirmed is True, 'S3_LIVE_BACKUP_CONFIRMATION_REQUIRED')
    from src.recovery.s3_operator import require_live_runtime
    require_live_runtime()
    require(storage.identity.mode == 'live-read-only', 'S3_LIVE_READ_ONLY_SOURCE_REQUIRED')
    require(callable(before_write) and callable(permission_guard), 'S3_LIVE_SAFETY_GATES_REQUIRED')
    return _backup(storage, metadata_source, parent, master_key, chunk_size=chunk_size,
                   live=True, before_write=before_write, permission_guard=permission_guard)


def _backup(storage, metadata_source, parent, master_key, *, chunk_size,
            live=False, before_write=None, permission_guard=None):
    require(READ_CAPABILITIES <= storage.capabilities(), 'S3_READ_CAPABILITY_MISSING')
    origin = deepcopy(storage.identity)
    initial = inventory(storage, allow_live_read=live)
    baseline = deepcopy(metadata_source.snapshot())
    validate_baseline(baseline, origin.bucket, initial)
    baseline_hash = snapshot_digest(baseline)
    manifest_keys = _manifest_keys(baseline)
    require(sum(initial[k]['head']['size_bytes'] for k in manifest_keys) <= MAX_EVIDENCE, 'S3_MANIFEST_CACHE_LIMIT')
    require(all(initial[k]['head']['size_bytes'] <= 1024 * 1024 for k in manifest_keys), 'S3_MANIFEST_CACHE_LIMIT')
    if live:
        before_write(initial, baseline, stage='collect')
        probe_conditionals(storage, initial)
        storage.authorize_full_read(initial, confirmed=True)
    manifests = {}
    scope = 'live-current-objects' if live else 'synthetic-local'
    options = {'scope': scope, 'permission_guard': permission_guard} if live else {}
    with S3ArchiveWriter(parent, master_key, expected_objects=len(initial) + 1, chunk_size=chunk_size, **options) as writer:
        bronze = {r['object_key']: r for r in baseline['catalog']['ingestion_objects']}
        for key, observation in initial.items():
            require(storage.identity == origin, 'S3_SOURCE_IDENTITY_CHANGED')
            expected = Head(**observation['head'])
            with storage.get_object(key, expected=expected) as response:
                require(response.head == expected, 'S3_GET_HEAD_STATE_CHANGED')
                stream = _Capture(response.body, key in manifest_keys)
                writer.add_object(key, stream, size_bytes=expected.size_bytes, metadata=expected.metadata)
                if live and key in bronze:
                    require(writer.objects[-1]['sha256'] == bronze[key]['sha256'], 'S3_BRONZE_BYTES_MISMATCH')
                if key in manifest_keys:
                    manifests[key] = bytes(stream.raw)
        writer.verify_pending()
        final = inventory(storage, allow_live_read=live)
        require(storage.identity == origin and final == initial, 'S3_SOURCE_CHANGED')
        require(snapshot_digest(metadata_source.snapshot()) == baseline_hash, 'S3_METADATA_BASELINE_CHANGED')
        records = {item['key']: item for item in writer.objects}
        lineage = validate_lineage(baseline, origin, initial, records, manifests)
        evidence = {'scope': 'live-current-objects' if live else 'synthetic-workflow', 'source': asdict(origin),
                    'initial_inventory': initial, 'final_inventory': final,
                    'metadata_baseline': baseline, 'metadata_digest': baseline_hash,
                    'source_records_sha256': digest(encoded(writer.objects)), 'lineage': lineage}
        raw = encoded(evidence)
        require(len(raw) <= MAX_EVIDENCE, 'S3_EVIDENCE_TOO_LARGE')
        control_key = _evidence_key(writer.core['session_id'])
        require(control_key not in initial, 'S3_CONTROL_KEY_COLLISION')
        writer.add_object(control_key, io.BytesIO(raw), size_bytes=len(raw),
                          metadata={'recovery_role': 'live-evidence' if live else 'synthetic-evidence'})
        if live:
            before_write(initial, baseline, stage='seal')
        writer.seal()
    return {'directory': str(writer.directory), 'source_objects': len(initial),
            'archive_objects': len(initial) + 1, 'source_bytes': sum(r['head']['size_bytes'] for r in initial.values()),
            'inventory_sha256': digest(encoded(initial)), 'metadata_sha256': baseline_hash,
            'lineage': lineage, 'status': 'SEALED_LIVE_ARCHIVE' if live else 'SEALED_SYNTHETIC_ONLY',
            'independent_storage_verified': False,
            'live_s3_backup_verified': False, 'remote_s3_restore_verified': False}


def _verified_workflow(directory, master_key, *, allow_live=False):
    archive = verify_archive(directory, master_key)
    live = archive.core['scope'] == 'live-current-objects'
    require(not live or allow_live, 'S3_SYNTHETIC_ONLY')
    items = archive.index['objects']
    require(bool(items), 'S3_WORKFLOW_EVIDENCE_REQUIRED')
    control = items[-1]
    require(control['key'] == _evidence_key(archive.core['session_id'])
            and control['metadata'] == {'recovery_role': 'live-evidence' if live else 'synthetic-evidence'}
            and control['size_bytes'] <= MAX_EVIDENCE, 'S3_WORKFLOW_EVIDENCE_REQUIRED')
    evidence = _json(b''.join(archive.iter_object_chunks(control['object_id'])))
    require(set(evidence) == {'scope', 'source', 'initial_inventory', 'final_inventory',
            'metadata_baseline', 'metadata_digest', 'source_records_sha256', 'lineage'}
            and evidence['scope'] == ('live-current-objects' if live else 'synthetic-workflow'), 'S3_WORKFLOW_EVIDENCE_SCHEMA')
    source = StorageIdentity(**evidence['source'])
    if live:
        require(source.mode == 'live-read-only', 'S3_LIVE_READ_ONLY_SOURCE_REQUIRED')
    else:
        _identity(source)
    require(evidence['initial_inventory'] == evidence['final_inventory'], 'S3_SOURCE_CHANGED')
    require(snapshot_digest(evidence['metadata_baseline']) == evidence['metadata_digest'], 'S3_METADATA_BASELINE_CHANGED')
    records = items[:-1]
    require(digest(encoded(records)) == evidence['source_records_sha256'], 'S3_EVIDENCE_RECORD_BINDING')
    manifest_keys = _manifest_keys(evidence['metadata_baseline'])
    manifests = {}
    total = 0
    for item in records:
        observed = evidence['initial_inventory'].get(item['key'])
        require(observed is not None and item['metadata'] == observed['head']['metadata']
                and item['size_bytes'] == observed['head']['size_bytes'], 'S3_EVIDENCE_OBJECT_BINDING')
        if item['key'] in manifest_keys:
            total += item['size_bytes']
            require(item['size_bytes'] <= 1024 * 1024 and total <= MAX_EVIDENCE, 'S3_MANIFEST_CACHE_LIMIT')
            manifests[item['key']] = b''.join(archive.iter_object_chunks(item['object_id']))
    result = validate_lineage(evidence['metadata_baseline'], source, evidence['initial_inventory'],
                              {r['key']: r for r in records}, manifests)
    require(result == evidence['lineage'], 'S3_EVIDENCE_LINEAGE_MISMATCH')
    return archive, source, records, result


@guarded
def verify_backup(directory, master_key):
    """Authenticated, full-byte and lineage verification; never expose the index."""
    archive, _, records, result = _verified_workflow(directory, master_key, allow_live=True)
    return {**archive.summary(), 'status': 'VERIFIED', 'source_objects': len(records), 'lineage': result,
            'independent_storage_verified': False}


def _destination(source, destination):
    require(destination is not None, 'S3_EXPLICIT_DESTINATION_REQUIRED')
    identity = destination.identity
    _identity(identity)
    origin_ids = {source.resource_id, *source.aliases}
    destination_ids = {identity.resource_id, *identity.aliases}
    require(not origin_ids.intersection(destination_ids) and source.bucket != identity.bucket,
            'S3_SOURCE_DESTINATION_ALIAS')
    require(READ_CAPABILITIES | {'put_if_absent'} <= destination.capabilities(), 'S3_DESTINATION_CAPABILITY_MISSING')
    return deepcopy(identity)


@guarded
def restore_synthetic_storage(directory, master_key, *, destination=None, confirmed=False):
    """Restore only source objects; verify provenance/lineage before any writes.

    No delete API, fallback PUT, retries into partial destinations or live adapter.
    """
    require(confirmed is True, 'S3_RESTORE_CONFIRMATION_REQUIRED')
    archive, source, records, lineage = _verified_workflow(directory, master_key)
    target = _destination(source, destination)
    require(not inventory(destination), 'S3_DESTINATION_NOT_EMPTY')
    for item in records:
        require(destination.identity == target, 'S3_DESTINATION_IDENTITY_CHANGED')
        destination.put_if_absent(item['key'], archive.iter_object_chunks(item['object_id']),
                                  size_bytes=item['size_bytes'], metadata=item['metadata'])
    final = inventory(destination)
    require(set(final) == {item['key'] for item in records}, 'S3_RESTORE_KEY_SET')
    for item in records:
        head = Head(**final[item['key']]['head'])
        require(head.size_bytes == item['size_bytes'] and head.metadata == item['metadata'], 'S3_RESTORE_METADATA')
        checksum, length = hashlib.sha256(), 0
        with destination.get_object(item['key'], expected=head) as response:
            require(response.head == head, 'S3_RESTORE_GET_STATE')
            while True:
                block = response.body.read(archive.core['chunk_size'])
                require(isinstance(block, bytes) and len(block) <= archive.core['chunk_size'], 'S3_INVALID_STREAM')
                if not block:
                    break
                length += len(block)
                require(length <= item['size_bytes'], 'S3_RESTORE_SIZE')
                checksum.update(block)
        require(length == item['size_bytes'] and checksum.hexdigest() == item['sha256'], 'S3_RESTORE_SHA256')
    require(destination.identity == target and inventory(destination) == final, 'S3_RESTORE_DESTINATION_CHANGED')
    return {'status': 'RESTORED_SYNTHETIC_ONLY', 'source_objects': len(records), 'lineage': lineage,
            'live_s3_backup_verified': False, 'remote_s3_restore_verified': False}
