"""Fake SDK/metadata transports. No network, provider credentials or cloud writes."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.recovery.runtime import RecoveryError, digest
from src.recovery.s3_dry_run import audit_source
from src.recovery.s3_lineage import validate_lineage, validate_metadata_lineage
from src.recovery.s3_metadata import DockerMetadataSource
from src.recovery.s3_readonly import ReadBudget, S3ReadOnly, canonical_identity
from src.recovery.s3_workflow import _destination, backup_synthetic, inventory
from tests.test_s3_workflow import fixture


class ProviderError(Exception):
    def __init__(self, status):
        super().__init__('sensitive-provider-message-do-not-log')
        self.response = {'ResponseMetadata': {'HTTPStatusCode': status}}


class FakeSDK:
    def __init__(self, storage):
        self.storage = storage
        self.meta = SimpleNamespace(endpoint_url='https://s3.example.invalid/',
                                    config=SimpleNamespace(s3={'addressing_style': 'virtual'}, signature_version='s3v4'))
        self.streams, self.gets = [], []
        self.ignore_conditions = False

    def list_objects_v2(self, *, Bucket, MaxKeys, ContinuationToken=None, FetchOwner=False):
        page = self.storage.list_page(ContinuationToken)
        result = {'ResponseMetadata': {'HTTPStatusCode': 200}, 'KeyCount': page.key_count,
                  'IsTruncated': page.is_truncated,
                  'Contents': [{'Key': o.key, 'Size': o.size_bytes, 'ETag': o.etag,
                                'LastModified': datetime.fromisoformat(o.last_modified.replace('Z', '+00:00'))}
                               for o in page.objects]}
        if page.next_token is not None:
            result['NextContinuationToken'] = page.next_token
        return result

    def head_object(self, *, Bucket, Key):
        head = self.storage.head_object(Key)
        return {'ResponseMetadata': {'HTTPStatusCode': 200}, 'ContentLength': head.size_bytes,
                'ETag': head.etag, 'LastModified': datetime.fromisoformat(head.last_modified.replace('Z', '+00:00')),
                'Metadata': deepcopy(head.metadata), 'ContentType': 'application/octet-stream'}

    def get_object(self, *, Bucket, Key, IfMatch, Range=None):
        response = self.head_object(Bucket=Bucket, Key=Key)
        self.gets.append({'Key': Key, 'IfMatch': IfMatch, 'Range': Range})
        if IfMatch != response['ETag'] and not self.ignore_conditions:
            raise ProviderError(412)
        raw = self.storage.objects[Key].payload
        if Range is not None:
            response['ResponseMetadata']['HTTPStatusCode'] = 206
            response['ContentRange'] = f'bytes 0-0/{len(raw)}'
            raw = raw[:1]
        response['ContentLength'] = len(raw)
        response['Body'] = io.BytesIO(raw)
        self.streams.append(response['Body'])
        return response

    def get_bucket_versioning(self, **kwargs):
        raise ProviderError(403)

    get_object_lock_configuration = get_bucket_versioning
    list_object_versions = get_bucket_versioning


class S3ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.store, self.metadata = fixture()
        self.client = FakeSDK(self.store)
        self.adapter = S3ReadOnly(self.client, self.store.identity.bucket)
        for name in ('socket.socket', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def object(self):
        key = next(k for k in self.store.objects if '/match_events/' in k)
        return key, self.adapter.head_object(key)

    def test_pagination_and_list_head_etags_remain_distinct(self):
        result = inventory(self.adapter, allow_live_read=True)
        self.assertEqual(len(result), len(self.store.objects))
        self.assertGreater(self.adapter.calls['list'], 1)
        self.assertTrue(all(v['list']['etag'] != v['head']['etag'] for v in result.values()))

    def test_stream_head_validator_metadata_and_close(self):
        key, head = self.object()
        with self.adapter.get_object(key, expected=head) as result:
            raw = bytearray()
            while block := result.body.read(3):
                raw.extend(block)
        self.assertEqual(raw, self.store.objects[key].payload)
        self.assertEqual(self.client.gets[0]['IfMatch'], head.etag)
        self.assertTrue(self.client.streams[0].closed)
        self.assertEqual(self.adapter.budget.consumed_bytes, len(raw))

    def test_partial_consumption_closes_stream(self):
        key, head = self.object()
        with self.adapter.get_object(key, expected=head) as result:
            result.body.read(1)
        self.assertTrue(self.client.streams[0].closed)

    def test_truncated_stream_is_failure_and_closed(self):
        key, head = self.object()
        original = self.client.get_object
        def truncated(**kwargs):
            result = original(**kwargs)
            result['Body'].close()
            result['Body'] = io.BytesIO(b'x')
            return result
        with patch.object(self.client, 'get_object', side_effect=truncated):
            with self.adapter.get_object(key, expected=head) as result:
                result.body.read(65536)
                with self.assertRaisesRegex(RecoveryError, 'S3_STREAM_TRUNCATED'):
                    result.body.read(65536)
                self.assertTrue(result.body.closed)

    def test_stream_exception_is_sanitized(self):
        key, head = self.object()
        with self.adapter.get_object(key, expected=head) as result:
            with patch.object(result.body.raw, 'read', side_effect=RuntimeError('sensitive-provider-message')):
                with self.assertRaisesRegex(RecoveryError, '^S3_STREAM_READ_FAILED$'):
                    result.body.read(1)
            self.assertTrue(result.body.closed)

    def test_correct_and_wrong_conditional_validators(self):
        key, head = self.object()
        self.assertEqual(self.adapter.conditional_probe(key, expected=head)['incorrect_validator'], 'HTTP_412')
        self.assertEqual(self.adapter.budget.consumed_bytes, 1)
        self.assertTrue(all(s.closed for s in self.client.streams))

    def test_ignored_conditions_block_backup(self):
        key, head = self.object()
        self.client.ignore_conditions = True
        with self.assertRaisesRegex(RecoveryError, 'S3_CONDITIONAL_GET_NOT_ENFORCED'):
            self.adapter.conditional_probe(key, expected=head)
        self.assertTrue(all(s.closed for s in self.client.streams))

    def test_precondition_mismatch_412(self):
        key, head = self.object()
        with self.assertRaisesRegex(RecoveryError, '^S3_READ_HTTP_412$'):
            self.adapter.get_object(key, expected=replace(head, etag='wrong'))

    def test_denied_missing_and_provider_errors_never_leak(self):
        for status in (403, 404, 412, 500):
            with self.subTest(status=status), patch.object(self.client, 'head_object', side_effect=ProviderError(status)):
                with self.assertRaises(RecoveryError) as error:
                    self.adapter.head_object('not-logged')
                self.assertNotIn('sensitive', str(error.exception))
                self.assertEqual(str(error.exception), 'S3_READ_HTTP_' + (str(status) if status != 500 else 'FAILED'))

    def test_malformed_list_responses(self):
        cases = [{}, {'ResponseMetadata': {'HTTPStatusCode': 200}, 'Contents': None},
                 {'ResponseMetadata': {'HTTPStatusCode': 200}, 'KeyCount': True, 'IsTruncated': False},
                 {'ResponseMetadata': {'HTTPStatusCode': 200}, 'KeyCount': 0, 'IsTruncated': True}]
        for response in cases:
            with self.subTest(response=response), patch.object(self.client, 'list_objects_v2', return_value=response):
                with self.assertRaises(RecoveryError):
                    self.adapter.list_page()

    def test_pagination_cycle_rejected(self):
        original = self.client.list_objects_v2
        def cycle(**kwargs):
            result = original(Bucket=kwargs['Bucket'], MaxKeys=1000)
            result['NextContinuationToken'] = 'same'
            return result
        with patch.object(self.client, 'list_objects_v2', side_effect=cycle):
            with self.assertRaisesRegex(RecoveryError, 'S3_DUPLICATE_LIST_KEY|S3_PAGINATION_CYCLE'):
                inventory(self.adapter, allow_live_read=True)

    def test_full_get_size_limit_prevents_request(self):
        key, head = self.object()
        self.adapter.budget.max_object_bytes = 1
        with self.assertRaisesRegex(RecoveryError, 'S3_DRY_RUN_BYTE_LIMIT'):
            self.adapter.get_object(key, expected=head)
        self.assertEqual(self.client.gets, [])

    def test_total_budget_and_unbounded_reads(self):
        key, head = self.object()
        self.adapter.budget.max_total_bytes = 1
        with self.adapter.sample_object(key, expected=head) as result:
            result.body.read(1)
        with self.assertRaisesRegex(RecoveryError, 'S3_DRY_RUN_BYTE_LIMIT'):
            self.adapter.sample_object(key, expected=head)
        self.adapter.budget.max_total_bytes = 10000
        with self.adapter.get_object(key, expected=head) as result:
            with self.assertRaisesRegex(RecoveryError, 'S3_UNBOUNDED_READ'):
                result.body.read(-1)

    def test_metadata_string_normalization_and_reserved_collision(self):
        key, _ = self.object()
        original = self.client.head_object
        def headers(**kwargs):
            result = original(**kwargs)
            result.update(Expires=datetime(2026, 1, 1, tzinfo=timezone.utc), BucketKeyEnabled=True)
            return result
        with patch.object(self.client, 'head_object', side_effect=headers):
            head = self.adapter.head_object(key)
        self.assertEqual(head.metadata['s3:Expires'], '2026-01-01T00:00:00Z')
        self.assertEqual(head.metadata['s3:BucketKeyEnabled'], 'True')
        self.store.objects[key].metadata['s3:ContentType'] = 'collision'
        with self.assertRaisesRegex(RecoveryError, 'S3_INVALID_USER_METADATA'):
            self.adapter.head_object(key)

    def test_invalid_metadata_not_silently_stringified(self):
        key, _ = self.object()
        self.store.objects[key].metadata['not-a-string'] = 12
        with self.assertRaisesRegex(RecoveryError, 'S3_INVALID_USER_METADATA'):
            self.adapter.head_object(key)

    def test_identity_normalizes_aliases_and_disallows_credential_urls(self):
        one = canonical_identity('https://S3.EXAMPLE.invalid:443/', 'fixture-source')
        two = canonical_identity('https://s3.example.invalid', 'fixture-source')
        self.assertEqual(one, two)
        self.assertIn('https://fixture-source.s3.example.invalid', one.aliases)
        self.assertIn('https://s3.example.invalid/fixture-source', one.aliases)
        for endpoint in ('http://s3.example.invalid', 'https://user:secret@s3.example.invalid',
                         'https://s3.example.invalid/?secret=x', 'https://s3.example.invalid/bucket'):
            with self.subTest(endpoint=endpoint), self.assertRaises(RecoveryError):
                canonical_identity(endpoint, 'fixture-source')

    def test_source_has_no_write_capabilities_or_methods(self):
        self.assertFalse({'put_if_absent', 'put_object', 'delete_object', 'create_bucket'} & set(dir(self.adapter)))
        self.assertNotIn('put_if_absent', self.adapter.capabilities())
        with self.assertRaisesRegex(RecoveryError, 'S3_SYNTHETIC_ONLY'):
            backup_synthetic(self.adapter, self.metadata, 'never-created', b'')
        with self.assertRaisesRegex(RecoveryError, 'S3_SYNTHETIC_ONLY'):
            inventory(self.adapter)
        with self.assertRaisesRegex(RecoveryError, 'S3_SYNTHETIC_ONLY'):
            _destination(self.store.identity, self.adapter)
        self.assertFalse(self.adapter.describe_identity()['live_restore_enabled'])

    def test_403_optional_capabilities_are_unknown_not_disabled(self):
        for result in self.adapter.optional_capabilities().values():
            self.assertEqual(result, {'access': 'HTTP_403', 'state': 'UNKNOWN'})

    def test_dry_run_checks_lineage_without_claiming_byte_backup(self):
        report = audit_source(self.adapter, self.metadata.snapshot())
        self.assertEqual(report['lineage']['published_builds'], 4)
        self.assertEqual(report['lineage']['byte_sha256_verified_objects'], 5)
        self.assertGreater(report['lineage']['byte_sha256_unverified_objects'], 0)
        self.assertFalse(report['live_s3_backup_verified'])
        self.assertFalse(report['live_backup_enabled'])
        self.assertTrue(all(s.closed for s in self.client.streams))
        self.assertTrue(all(g['Range'] == 'bytes=0-0' or g['Key'].endswith(('_manifest.json', 'source.json'))
                            for g in self.client.gets))

    def test_metadata_and_full_lineage_modes_do_not_confuse_hash_claims(self):
        observed = inventory(self.store)
        snapshot = self.metadata.snapshot()
        keys = {r['s3_prefix'] + '_manifest.json' for layer in ('silver', 'gold') for r in snapshot['catalog'][layer + '_builds']}
        keys |= {r['object_key'] for r in snapshot['catalog']['ingestion_objects'] if r['dataset'] == 'matches'}
        documents = {k: self.store.objects[k].payload for k in keys}
        self.assertEqual(validate_metadata_lineage(snapshot, self.store.identity, observed, documents)['verification'],
                         'METADATA_AND_SMALL_DOCUMENTS_ONLY')
        records = {k: {'size_bytes': len(o.payload), 'sha256': digest(o.payload)} for k, o in self.store.objects.items()}
        bronze_key = next(k for k in records if '/match_events/' in k)
        records[bronze_key]['sha256'] = '0' * 64
        with self.assertRaisesRegex(RecoveryError, 'S3_BRONZE_BYTES_MISMATCH'):
            validate_lineage(snapshot, self.store.identity, observed, records, documents)

    def test_dry_run_source_drift_refused(self):
        original = self.adapter.optional_capabilities
        def changed():
            self.store.objects.pop(next(iter(self.store.objects)))
            return original()
        with patch.object(self.adapter, 'optional_capabilities', side_effect=changed):
            with self.assertRaisesRegex(RecoveryError, 'S3_SOURCE_CHANGED'):
                audit_source(self.adapter, self.metadata.snapshot())

    def test_small_parent_document_hash_mismatch_refused(self):
        observed = inventory(self.store)
        snapshot = self.metadata.snapshot()
        keys = {r['s3_prefix'] + '_manifest.json' for layer in ('silver', 'gold') for r in snapshot['catalog'][layer + '_builds']}
        keys |= {r['object_key'] for r in snapshot['catalog']['ingestion_objects'] if r['dataset'] == 'matches'}
        documents = {k: self.store.objects[k].payload for k in keys}
        parent = next(k for k in keys if k.startswith('football/bronze/') and '/matches/' in k)
        documents[parent] = b' ' + documents[parent][1:]
        with self.assertRaisesRegex(RecoveryError, 'S3_BRONZE_BYTES_MISMATCH'):
            validate_metadata_lineage(snapshot, self.store.identity, observed, documents)

    def test_invalid_limits_and_configuration(self):
        with self.assertRaisesRegex(RecoveryError, 'S3_INVALID_DRY_RUN_BUDGET'):
            S3ReadOnly(self.client, 'fixture-source', budget=ReadBudget(max_total_bytes=100000000))
        self.client.meta.config.s3['addressing_style'] = 'path'
        with self.assertRaisesRegex(RecoveryError, 'S3_CLIENT_CONFIG'):
            S3ReadOnly(self.client, 'fixture-source')

    def test_owner_not_exposed_or_denied_remains_unknown(self):
        self.assertEqual(self.adapter.owner_reference()['state'], 'NOT_EXPOSED')
        self.assertIsNone(self.adapter.describe_identity()['account_project_reference'])
        with patch.object(self.client, 'list_objects_v2', side_effect=ProviderError(403)):
            self.assertEqual(self.adapter.owner_reference(), {'access': 'HTTP_403', 'state': 'UNKNOWN'})

    def test_owner_reference_is_fingerprint_not_raw_identity_or_restore_permission(self):
        response = {'ResponseMetadata': {'HTTPStatusCode': 200}, 'Contents': [{'Owner': {'ID': 'fixture-owner'}}]}
        with patch.object(self.client, 'list_objects_v2', return_value=response):
            self.assertEqual(self.adapter.owner_reference()['state'], 'CANONICAL_OWNER_FINGERPRINT')
        identity = self.adapter.describe_identity()
        self.assertNotIn('fixture-owner', identity['account_project_reference'])
        self.assertFalse(identity['live_restore_enabled'])

    def test_get_changed_metadata_and_ignored_range_close_streams(self):
        key, head = self.object()
        original = self.client.get_object
        def changed(**kwargs):
            response = original(**kwargs)
            response['Metadata']['unexpected'] = 'change'
            return response
        with patch.object(self.client, 'get_object', side_effect=changed):
            with self.assertRaisesRegex(RecoveryError, 'S3_GET_HEAD_STATE_CHANGED'):
                self.adapter.get_object(key, expected=head)
        self.assertTrue(self.client.streams[-1].closed)
        def range_ignored(**kwargs):
            response = original(**kwargs)
            response['ResponseMetadata']['HTTPStatusCode'] = 200
            return response
        with patch.object(self.client, 'get_object', side_effect=range_ignored):
            with self.assertRaisesRegex(RecoveryError, 'S3_INVALID_HTTP_RESPONSE'):
                self.adapter.sample_object(key, expected=head)
        self.assertTrue(self.client.streams[-1].closed)

    def test_empty_object_and_timezone_normalization(self):
        key = next(k for k, v in self.store.objects.items() if not v.payload)
        head = self.adapter.head_object(key)
        with self.adapter.get_object(key, expected=head) as result:
            self.assertEqual(result.body.read(1), b'')
        self.assertEqual(self.adapter.budget.consumed_bytes, 0)
        self.assertTrue(self.client.streams[-1].closed)
        original = self.client.head_object
        def offset_date(**kwargs):
            result = original(**kwargs)
            result['LastModified'] = datetime.fromisoformat('2026-01-01T03:00:00+03:00')
            return result
        with patch.object(self.client, 'head_object', side_effect=offset_date):
            self.assertEqual(self.adapter.head_object(key).last_modified, '2026-01-01T00:00:00Z')

    def test_dry_run_refuses_ignored_conditions(self):
        self.client.ignore_conditions = True
        with self.assertRaisesRegex(RecoveryError, 'S3_CONDITIONAL_GET_NOT_ENFORCED'):
            audit_source(self.adapter, self.metadata.snapshot())


class MetadataAdapterTests(unittest.TestCase):
    def test_snapshot_reuses_exported_read_only_transaction_and_aggregate_selects(self):
        calls = []
        @contextmanager
        def snapshot(container):
            calls.append(('begin_read_only', container))
            yield 'A-B-C'
            calls.append(('rollback', container))
        def registry(container, snapshot_id):
            calls.append(('registry', container, snapshot_id))
            return {'detached': []}
        def query(container, sql):
            calls.append(('ch', sql))
            self.assertTrue(sql.startswith(('SELECT ', 'DESCRIBE TABLE ')))
            self.assertNotIn('SELECT *', sql)
            if 'system.tables' in sql:
                return [{'name': 'event_core', 'engine': 'MergeTree', 'sorting_key': 'competition_id, season_id, match_id, event_id'}]
            if sql.startswith('DESCRIBE'):
                return [{'name': 'silver_build_id'}]
            if ' AS build_id' in sql:
                return [{'competition_id': 43, 'season_id': 106, 'build_id': 'safe-id', 'rows': 64}]
            return [{'n': 0}]
        io = SimpleNamespace(pg_snapshot=snapshot, registry=registry, ch_json=query)
        result = DockerMetadataSource('pg', 'ch', transport=io).snapshot()
        self.assertEqual(result['serving']['event_core']['duplicate_keys'], 0)
        self.assertEqual(calls[0], ('begin_read_only', 'pg'))
        self.assertEqual(calls[1], ('registry', 'pg', 'A-B-C'))
        self.assertEqual(calls[-1], ('rollback', 'pg'))

    def test_metadata_transport_failure_is_sanitized(self):
        io = SimpleNamespace(pg_snapshot=lambda _: (_ for _ in ()).throw(RuntimeError('password-do-not-print')))
        with self.assertRaisesRegex(RecoveryError, '^S3_WORKFLOW_OPERATION_FAILED$'):
            DockerMetadataSource('pg', 'ch', transport=io).snapshot()
