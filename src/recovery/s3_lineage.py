"""Pure snapshot/lineage validators. No database, storage or network connections."""
from collections import Counter
from copy import deepcopy
import re

from src.gold import build_identity as gold
from src.silver import build_identity as silver
from src.recovery.runtime import digest, encoded, reconcile, require
from src.recovery.s3_archive import _json
from src.statsbomb.context import matches_context, validate_parent_url

CATALOG_TABLES = ('ingestion_objects', 'silver_builds', 'gold_builds',
                  'clickhouse_loads', 'clickhouse_gold_loads')


def snapshot_digest(snapshot):
    canonical = deepcopy(snapshot)
    for rows in canonical['catalog'].values():
        rows.sort(key=encoded)
    for table in canonical['serving'].values():
        table['groups'].sort(key=encoded)
    return digest(encoded(canonical))


def _unique(rows, fields, code):
    keys = [tuple(row[f] for f in fields) for row in rows]
    require(len(keys) == len(set(keys)), code)


def validate_baseline(snapshot, bucket, inventory):
    """Require known objects even if a provider supplies a consistently partial LIST."""
    require(set(snapshot) == {'catalog', 'serving'}, 'S3_METADATA_SNAPSHOT_SCHEMA')
    catalog = snapshot['catalog']
    require(set(catalog) == set(CATALOG_TABLES), 'S3_CATALOG_SCHEMA')
    for rows in catalog.values():
        require(isinstance(rows, list), 'S3_CATALOG_SCHEMA')
        require(all(r['s3_bucket'] == bucket for r in rows), 'S3_CATALOG_BUCKET')
    _unique(catalog['ingestion_objects'], ('s3_bucket', 'object_key'), 'S3_DUPLICATE_BRONZE_RECORD')
    for row in catalog['ingestion_objects']:
        silver.require_sha256(row['sha256'])
        require(type(row['size_bytes']) is int and row['size_bytes'] >= 0, 'S3_CATALOG_SIZE')
        require(row['object_key'] in inventory, 'S3_REGISTERED_OBJECT_MISSING')
    for layer in ('silver', 'gold'):
        rows = catalog[layer + '_builds']
        _unique(rows, ('dataset', 'competition_id', 'season_id', 'build_id'), 'S3_DUPLICATE_BUILD')
        _unique(rows, ('s3_bucket', 's3_prefix'), 'S3_DUPLICATE_BUILD_LOCATION')
        for row in rows:
            require(row['source'] == 'statsbomb' and all(type(row[f]) is int and row[f] > 0
                    for f in ('competition_id', 'season_id', 'row_count', 'file_count')), 'S3_BUILD_CONTEXT_OR_COUNTS')
            for field in ('build_id', 'schema_sha256', 'input_fingerprint'):
                silver.require_sha256(row[field])
            for suffix in ('_manifest.json', '_SUCCESS'):
                require(row['s3_prefix'] + suffix in inventory, 'S3_REGISTERED_OBJECT_MISSING')
        loads = catalog['clickhouse_' + ('gold_' if layer == 'gold' else '') + 'loads']
        _unique(loads, ('clickhouse_database', 'clickhouse_table', layer + '_build_id'), 'S3_DUPLICATE_LOAD_RECEIPT')
        for row in loads:
            require(row['clickhouse_database'] == 'football', 'S3_LOAD_DATABASE')


def validate_lineage(snapshot, identity, inventory, records, manifest_bytes):
    """Check byte hashes, exact build file sets and lineage against detached DTOs.

    LIST ETag is compared only to the source manifest's LIST ETag. Restore byte
    verification uses SHA-256, without requiring a destination to reproduce ETags.
    """
    return _lineage(snapshot, identity, inventory, records, manifest_bytes, set(records))


def validate_metadata_lineage(snapshot, identity, inventory, manifest_bytes):
    """Read-only audit: never substitute catalog/ETag claims for measured byte SHA.

    Only the explicitly downloaded small documents have byte-level verification.
    Full archive validation above still requires every source object's byte hash.
    """
    require(set(manifest_bytes) <= set(inventory), 'S3_UNEXPECTED_DOCUMENT')
    records = {k: {'size_bytes': v['head']['size_bytes']} for k, v in inventory.items()}
    for key, raw in manifest_bytes.items():
        require(len(raw) == records[key]['size_bytes'], 'S3_DOCUMENT_SIZE')
        records[key]['sha256'] = digest(raw)
    result = _lineage(snapshot, identity, inventory, records, manifest_bytes, set(manifest_bytes))
    return {**result, 'verification': 'METADATA_AND_SMALL_DOCUMENTS_ONLY',
            'byte_sha256_verified_objects': len(manifest_bytes),
            'byte_sha256_unverified_objects': len(inventory) - len(manifest_bytes)}


def _lineage(snapshot, identity, inventory, records, manifest_bytes, verified):
    validate_baseline(snapshot, identity.bucket, inventory)
    catalog = snapshot['catalog']
    bronze = {r['object_key']: r for r in catalog['ingestion_objects']}
    require(set(records) == set(inventory), 'S3_ARCHIVE_SOURCE_KEY_SET')
    registered = set(bronze)
    for key, row in bronze.items():
        require(records[key]['size_bytes'] == row['size_bytes']
                and (key not in verified or records[key]['sha256'] == row['sha256']), 'S3_BRONZE_BYTES_MISMATCH')
        require(inventory[key]['head']['metadata'].get('sha256') == row['sha256'], 'S3_BRONZE_METADATA_SHA')
        require('sha256=' + row['sha256'] in key.split('/'), 'S3_BRONZE_VERSIONED_KEY')
    parents = {(r['dataset'], r['competition_id'], r['season_id'], r['build_id']): r for r in catalog['silver_builds']}
    manifests, memberships = {}, {}
    for layer in ('silver', 'gold'):
        contract = silver if layer == 'silver' else gold
        for row in catalog[layer + '_builds']:
            prefix = row['s3_prefix']
            key = prefix + '_manifest.json'
            require(key in manifest_bytes, 'S3_MANIFEST_MISSING')
            raw = manifest_bytes[key]
            manifest = _json(raw)
            meta = inventory[key]['head']['metadata']
            require(meta.get('sha256') == digest(raw) == records[key]['sha256']
                    and meta.get('build_id') == row['build_id'], 'S3_MANIFEST_METADATA')
            for f in (*silver.SPEC_FIELDS, 'build_id', 'row_count', 'file_count'):
                require(manifest[f] == (layer if f == 'layer' else row[f]), 'S3_MANIFEST_CATALOG_IDENTITY')
            require(contract.calculate_build_id(manifest) == row['build_id'], 'S3_DETERMINISTIC_BUILD_ID')
            location = silver.silver_prefix if layer == 'silver' else gold.gold_prefix
            require(location(manifest, row['build_id']) == prefix, 'S3_BUILD_PREFIX')
            files = manifest['files']
            require(isinstance(files, list) and len(files) == row['file_count'], 'S3_MANIFEST_FILE_COUNT')
            keys = [f['object_key'] for f in files]
            require(len(keys) == len(set(keys)), 'S3_DUPLICATE_MANIFEST_FILE')
            expected = set(keys) | {key, prefix + '_SUCCESS'}
            actual = {k for k in inventory if k.startswith(prefix)}
            require(actual - {prefix} == expected, 'S3_BUILD_EXACT_FILE_SET')
            if prefix in actual:
                require(inventory[prefix]['list']['size_bytes'] == 0, 'S3_DIRECTORY_MARKER_SIZE')
            for part in files:
                require(part['object_key'].startswith(prefix)
                        and re.fullmatch(r'part-[^/]+\.snappy\.parquet', part['object_key'][len(prefix):])
                        is not None and type(part['size_bytes']) is int and part['size_bytes'] > 0,
                        'S3_INVALID_PARQUET_PART')
                observed = inventory[part['object_key']]['list']
                require(observed['size_bytes'] == part['size_bytes']
                        and observed['etag'] == part['etag'], 'S3_MANIFEST_PART_METADATA')
            registered.update(actual)
            context = row['competition_id'], row['season_id']
            inputs = manifest['inputs']
            if layer == 'silver':
                kind = 'matches' if row['dataset'] == 'matches' else 'lineups' if row['dataset'] in silver.LINEUP_DATASETS else 'events'
                require(silver.input_fingerprint(inputs, artifact_kind=kind) == row['input_fingerprint'], 'S3_SILVER_INPUT_FINGERPRINT')
                for source in inputs:
                    parent = bronze.get(source['object_key'])
                    require(parent is not None, 'S3_BRONZE_PARENT_MISSING')
                    for field in ('s3_bucket', 'source_url', 'sha256'):
                        require(source[field] == parent[field], 'S3_BRONZE_PARENT_IDENTITY')
                if kind == 'matches':
                    validate_parent_url(inputs[0], competition_id=context[0], season_id=context[1])
                    raw_parent = manifest_bytes[inputs[0]['object_key']]
                    ids = set(matches_context(raw_parent, competition_id=context[0], season_id=context[1]))
                    require(len(ids) == row['row_count'] == manifest['match_count'], 'S3_MATCHES_PARENT_COUNT')
                else:
                    ids = {i['match_id'] for i in inputs}
                memberships[(row['dataset'], *context, row['build_id'])] = ids
            else:
                require(gold.input_fingerprint(inputs) == row['input_fingerprint'], 'S3_GOLD_INPUT_FINGERPRINT')
                require(tuple(i['dataset'] for i in inputs) == gold.required_inputs(row['dataset']), 'S3_GOLD_INPUT_DATASETS')
                for source in inputs:
                    parent = parents.get((source['dataset'], *context, source['build_id']))
                    require(parent is not None, 'S3_SILVER_PARENT_MISSING')
                    for field in gold.INPUT_FIELDS:
                        require(source[field] == parent[field], 'S3_SILVER_PARENT_IDENTITY')
                selected = [memberships[(i['dataset'], *context, i['build_id'])] for i in inputs]
                require(all(ids == selected[0] for ids in selected), 'S3_CONTEXT_MATCH_MEMBERSHIP')
            manifests[(layer, row['dataset'], *context, row['build_id'])] = manifest
    result = reconcile(catalog, snapshot['serving'])
    # The shared reconciler checks receipt fields/counts. Bind table names to builds too.
    for layer in ('silver', 'gold'):
        builds = {r['build_id']: r for r in catalog[layer + '_builds']}
        for load in catalog['clickhouse_' + ('gold_' if layer == 'gold' else '') + 'loads']:
            row = builds[load[layer + '_build_id']]
            target = row['dataset'] + ('_v2' if layer == 'gold' and row['transform_version'].endswith('_v2') else '')
            require(load['clickhouse_table'] == target and load['source'] == row['source'], 'S3_LOAD_TARGET_IDENTITY')
    classes = {}
    for key in inventory:
        classes[key] = ('registered' if key in registered else 'test' if key.startswith('football/bronze/_tests/')
                        else 'legacy' if key.startswith('football/bronze/statsbomb/') and '/sha256=' not in key
                        and key.endswith('.json') else 'unregistered')
    return {**result, 'manifests': len(manifests), 'classification_counts': dict(Counter(classes.values()))}
