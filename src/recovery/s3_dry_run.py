"""Bounded read-only live audit. Does not create an archive, key or destination."""
from collections import Counter
from pathlib import PurePosixPath

from src.recovery.runtime import digest, encoded, require
from src.recovery.s3_lineage import validate_baseline, validate_metadata_lineage
from src.recovery.s3_storage import Head
from src.recovery.s3_workflow import _manifest_keys, guarded, inventory


@guarded
def audit_source(storage, snapshot):
    """Full LIST/HEAD twice, small lineage JSON, three one-byte payload probes.

    Snapshot acquisition/final database fence are the caller's responsibility.
    Even success is NOT a byte backup or an atomic database/object-store snapshot.
    """
    origin = storage.identity
    initial = inventory(storage, allow_live_read=True)
    validate_baseline(snapshot, origin.bucket, initial)
    documents = {}
    selected = sorted(_manifest_keys(snapshot))
    for key in selected:
        expected = Head(**initial[key]['head'])
        storage.budget.reserve(expected.size_bytes)
    require(sum(initial[k]['head']['size_bytes'] for k in selected) <= storage.budget.max_total_bytes,
            'S3_DRY_RUN_BYTE_LIMIT')
    for key in selected:
        expected = Head(**initial[key]['head'])
        data = bytearray()
        with storage.get_object(key, expected=expected) as result:
            while block := result.body.read(65536):
                data.extend(block)
        require(len(data) == expected.size_bytes, 'S3_DOCUMENT_SIZE')
        documents[key] = bytes(data)
    lineage = validate_metadata_lineage(snapshot, origin, initial, documents)
    probes = {}
    for layer in ('bronze', 'silver', 'gold'):
        candidates = sorted(k for k, v in initial.items() if k.startswith('football/' + layer + '/')
                            and v['head']['size_bytes'] > 0 and k not in documents
                            and (layer == 'bronze' or k.endswith('.parquet')))
        require(bool(candidates), 'S3_DRY_RUN_SAMPLE_MISSING')
        key = candidates[0]
        probes[layer] = storage.conditional_probe(key, expected=Head(**initial[key]['head']))
        probes[layer]['list_head_etag_different'] = initial[key]['list']['etag'] != initial[key]['head']['etag']
    optional = storage.optional_capabilities()
    owner = storage.owner_reference()
    final = inventory(storage, allow_live_read=True)
    require(storage.identity == origin and final == initial, 'S3_SOURCE_CHANGED')
    layers, formats = {}, Counter()
    for key, value in initial.items():
        layer = key.split('/')[1] if key.startswith('football/') and len(key.split('/')) > 2 else 'other'
        stats = layers.setdefault(layer, {'objects': 0, 'bytes': 0})
        stats['objects'] += 1
        stats['bytes'] += value['head']['size_bytes']
        formats['directory_marker' if key.endswith('/') else PurePosixPath(key).suffix or 'no_extension'] += 1
    contexts = []
    for row in snapshot['catalog']['silver_builds']:
        if row['dataset'] == 'matches':
            contexts.append({f: row[f] for f in ('competition_id', 'season_id', 'row_count')})
    return {'status': 'PASS_READ_ONLY_DRY_RUN', 'source': storage.describe_identity(),
            'objects': len(initial), 'bytes': sum(v['head']['size_bytes'] for v in initial.values()),
            'layers': layers, 'formats': dict(formats), 'lineage': lineage, 'contexts': contexts,
            'metadata_index_compatibility': 'PASS_SCHEMA_2_STRING_MAP',
            'list_head_etag_mismatches': sum(v['list']['etag'] != v['head']['etag'] for v in initial.values()),
            'get_bytes': storage.budget.consumed_bytes, 'fully_downloaded_documents': len(documents),
            'conditional_probes': probes, 'optional_capabilities': optional,
            'owner_observation': owner,
            'inventory_fence': 'PASS', 'inventory_sha256': digest(encoded(initial)), 'calls': dict(storage.calls),
            'live_s3_backup_verified': False, 'remote_s3_restore_verified': False,
            'live_backup_enabled': False, 'live_restore_enabled': False}
