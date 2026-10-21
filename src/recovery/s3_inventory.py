"""Executed inside the existing tools runtime. Read-only S3 inventory, never restore."""
import hashlib
import json
import sys

from src.common.s3 import create_s3_client


def check(client, catalog):
    objects, capabilities = {}, {}
    buckets = {row['s3_bucket'] for rows in catalog.values() for row in rows if 's3_bucket' in row}
    for bucket in sorted(buckets):
        status = {}
        for label, operation in (('versioning', client.get_bucket_versioning),
                                 ('object_lock', client.get_object_lock_configuration)):
            try:
                response = operation(Bucket=bucket)
                status[label] = {k: v for k, v in response.items() if k != 'ResponseMetadata'}
            except Exception as exc:
                response = getattr(exc, 'response', {})
                # Only a bounded HTTP status; no raw provider message or exception text.
                status[label] = {'available': False, 'http_status': response.get('ResponseMetadata', {}).get('HTTPStatusCode')}
        capabilities[bucket] = status
    for row in catalog['ingestion_objects']:
        bucket, key = row['s3_bucket'], row['object_key']
        head = client.head_object(Bucket=bucket, Key=key)
        if head['ContentLength'] != row['size_bytes'] or head.get('Metadata', {}).get('sha256') != row['sha256']:
            raise ValueError('BRONZE_METADATA_MISMATCH')
        objects[(bucket, key)] = {'bucket': bucket, 'key': key, 'size': head['ContentLength'],
            'source_sha256': row['sha256'], 'version_id': head.get('VersionId'), 'verification': 'HEAD_METADATA_ONLY'}
    for layer in ('silver', 'gold'):
        for row in catalog[layer + '_builds']:
            bucket, prefix = row['s3_bucket'], row['s3_prefix']
            response = client.get_object(Bucket=bucket, Key=prefix + '_manifest.json')
            with response['Body'] as body:
                raw = body.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != response.get('Metadata', {}).get('sha256'):
                raise ValueError('BUILD_MANIFEST_CHECKSUM')
            manifest = json.loads(raw)
            for field in ('build_id', 'competition_id', 'season_id', 'dataset', 'input_fingerprint', 'schema_sha256', 'row_count', 'file_count'):
                if manifest[field] != row[field]:
                    raise ValueError('BUILD_MANIFEST_IDENTITY')
            if response.get('Metadata', {}).get('build_id') != row['build_id']:
                raise ValueError('BUILD_METADATA_IDENTITY')
            inventory = {}
            for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get('Contents', []):
                    inventory[obj['Key']] = obj
            expected = {prefix + '_SUCCESS', prefix + '_manifest.json'} | {f['object_key'] for f in manifest['files']}
            if set(inventory) - {prefix} != expected or len(manifest['files']) != row['file_count']:
                raise ValueError('BUILD_FILE_SET_MISMATCH')
            for part in manifest['files']:
                obj = inventory[part['object_key']]
                if obj['Size'] != part['size_bytes'] or obj.get('ETag') != part['etag']:
                    raise ValueError('BUILD_PART_METADATA_MISMATCH')
            for key, obj in inventory.items():
                objects[(bucket, key)] = {'bucket': bucket, 'key': key, 'size': obj['Size'],
                    'etag': obj.get('ETag'), 'verification': 'LIST_SIZE_ETAG_ONLY'}
            objects[(bucket, prefix + '_manifest.json')]['sha256'] = hashlib.sha256(raw).hexdigest()
            objects[(bucket, prefix + '_manifest.json')]['verification'] = 'GET_SHA256'
            # Lineage references must resolve to the exact published Silver identities.
            if layer == 'gold':
                published = {r['build_id'] for r in catalog['silver_builds']}
                if any(item['build_id'] not in published for item in manifest['inputs']):
                    raise ValueError('GOLD_LINEAGE_PARENT_MISSING')
    return {'scope': 'REGISTERED_ARTIFACTS_ONLY', 'objects': sorted(objects.values(), key=lambda r: (r['bucket'], r['key'])),
            'capabilities': capabilities, 'remote_restore_tested': False,
            'boundary': 'Inventory is not an independent byte backup; ETag is not assumed to be SHA-256.'}


if __name__ == '__main__':
    try:
        print(json.dumps(check(create_s3_client(), json.load(sys.stdin)), sort_keys=True))
    except Exception:
        print('{"error":"S3_READ_ONLY_VERIFICATION_FAILED"}')
        sys.exit(1)
