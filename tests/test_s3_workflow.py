"""Synthetic S3/metadata/serving fixtures and failure injection; no external IO."""
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.gold import build_identity as gold
from src.silver import build_identity as silver
from src.recovery import s3_archive
from src.recovery.runtime import RecoveryError, digest, encoded
from src.recovery.s3_lineage import CATALOG_TABLES, snapshot_digest
from src.recovery.s3_storage import (
    ListEntry, Page, StaticMetadata, StorageIdentity, SyntheticObject, SyntheticStorage,
)
from src.recovery.s3_workflow import backup_synthetic, inventory, restore_synthetic_storage


def fixture(*, full=False, contexts=((43, 106),), storage_type=SyntheticStorage):
    """Real manifest/build-ID contracts, fake JSON/Parquet bytes and tiny row counts.

    Full two-context fixture has 22 builds (14 Silver + 8 Gold), not 315 objects.
    There are no real football payloads or database connections in these fixtures.
    """
    objects, catalog, serving = {}, {name: [] for name in CATALOG_TABLES}, {}
    bucket = 'fixture-source'

    def bronze(dataset, suffix, raw):
        key = 'football/bronze/statsbomb/' + dataset + '/sha256=' + digest(raw) + '/source.json'
        row = {'source': 'statsbomb', 'dataset': dataset, 'source_url': 'https://raw.githubusercontent.com/hudl/open-data/master/data/' + suffix,
               's3_bucket': bucket, 'object_key': key, 'sha256': digest(raw), 'size_bytes': len(raw)}
        objects[key] = SyntheticObject(raw, {'sha256': digest(raw), 'ContentType': 'application/json'})
        catalog['ingestion_objects'].append(row)
        return row

    def build(layer, dataset, context, version, inputs):
        contract = silver if layer == 'silver' else gold
        kind = 'matches' if dataset == 'matches' else 'lineups' if dataset in silver.LINEUP_DATASETS else 'events'
        fingerprint = silver.input_fingerprint(inputs, artifact_kind=kind) if layer == 'silver' else gold.input_fingerprint(inputs)
        spec = contract.build_specification(dataset=dataset, competition_id=context[0], season_id=context[1],
                    transform_version=version, input_fingerprint=fingerprint, schema_sha256=digest(('synthetic-schema:' + dataset).encode()))
        build_id = contract.calculate_build_id(spec)
        prefix = (silver.silver_prefix if layer == 'silver' else gold.gold_prefix)(spec, build_id)
        part = prefix + 'part-00000.snappy.parquet'
        objects[part] = SyntheticObject(('synthetic-not-parquet:' + build_id).encode(), {'ContentType': 'application/octet-stream'})
        file = {'object_key': part, 'size_bytes': len(objects[part].payload), 'etag': 'list:' + digest(objects[part].payload)}
        manifest = {**spec, 'build_id': build_id, 'row_count': 1, 'file_count': 1,
                    'inputs': silver.canonical_inputs(inputs, artifact_kind=kind) if layer == 'silver' else gold.canonical_inputs(inputs),
                    'files': [file], 'match_count': 1}
        raw = encoded(manifest)
        objects[prefix + '_manifest.json'] = SyntheticObject(raw, {'sha256': digest(raw), 'build_id': build_id})
        objects[prefix + '_SUCCESS'] = SyntheticObject(b'synthetic-success')
        objects[prefix] = SyntheticObject(b'')
        row = {k: v for k, v in spec.items() if k != 'layer'}
        row.update(build_id=build_id, s3_bucket=bucket, s3_prefix=prefix, row_count=1, file_count=1)
        catalog[layer + '_builds'].append(row)
        target = dataset + ('_v2' if layer == 'gold' and version.endswith('_v2') else '')
        receipt = {k: row[k] for k in ('source', 'dataset', 'competition_id', 'season_id',
                   'input_fingerprint', 'schema_sha256', 's3_bucket', 's3_prefix', 'row_count')}
        receipt.update({layer + '_build_id': build_id, 'clickhouse_database': 'football', 'clickhouse_table': target})
        catalog['clickhouse_' + ('gold_' if layer == 'gold' else '') + 'loads'].append(receipt)
        group = {'competition_id': context[0], 'season_id': context[1], 'build_id': build_id, 'rows': 1}
        serving.setdefault(target, {'duplicate_keys': 0, 'groups': []})['groups'].append(group)
        return row

    for context in contexts:
        match_id = context[1]
        event = bronze('match_events', f'events/{match_id}.json', encoded({'synthetic': 'event', 'match_id': match_id}))
        lineup = bronze('match_lineups', f'lineups/{match_id}.json', encoded({'synthetic': 'lineup', 'match_id': match_id}))
        matches = bronze('matches', f'matches/{context[0]}/{context[1]}.json', encoded([
            {'match_id': match_id, 'competition': {'competition_id': context[0]}, 'season': {'season_id': context[1]}}]))
        event['match_id'] = lineup['match_id'] = match_id  # Canonical Silver inputs; catalog may carry additional DTO fields.
        selected = {}
        names = silver.SILVER_DATASETS if full else ('event_core', 'shot_events', 'matches')
        for name in names:
            inputs = [matches] if name == 'matches' else [lineup] if name in silver.LINEUP_DATASETS else [event]
            selected[name] = build('silver', name, context, name + '_v1', inputs)
        versions = [('match_results', 'match_results_v1')]
        if full:
            versions += [(name, name + '_v2') for name in ('team_match_stats', 'player_match_stats')]
            if context == (43, 106):
                versions += [(name, name + '_v1') for name in ('team_match_stats', 'player_match_stats')]
        for name, version in versions:
            build('gold', name, context, version, [selected[n] for n in gold.required_inputs(name)])
    # Non-catalog objects must be backed up too, including keys with no SHA metadata.
    objects['football/bronze/_tests/sample.json'] = SyntheticObject(b'{"synthetic":true}')
    objects['football/bronze/statsbomb/legacy.json'] = SyntheticObject(b'legacy')
    objects['unregistered/бинарный'] = SyntheticObject(bytes(range(16)), {'note': 'fixture'})
    store = storage_type(bucket, objects=objects, page_size=3)
    return store, StaticMetadata({'catalog': catalog, 'serving': serving})


class S3WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = os.urandom(32)
        for name in ('socket.socket', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def backup(self, store=None, metadata=None):
        if store is None:
            store, metadata = fixture()
        return backup_synthetic(store, metadata, self.root, self.key, chunk_size=4096)

    def assert_unsealed(self, store, metadata, code=None):
        with self.assertRaisesRegex(RecoveryError, code or 'S3_|MISMATCH|MISSING|LOADED_|SERVING_'):
            self.backup(store, metadata)
        self.assertFalse(any(self.root.glob('*/manifest.json')))

    def test_success_pagination_etag_mismatch_metadata_and_binary_empty_restore(self):
        store, metadata = fixture()
        before = deepcopy(store.objects)
        result = self.backup(store, metadata)
        self.assertEqual(result['source_objects'], len(store.objects))
        self.assertEqual(result['archive_objects'], len(store.objects) + 1)
        self.assertEqual(result['lineage']['published_builds'], 4)
        self.assertEqual(result['lineage']['classification_counts']['legacy'], 1)
        self.assertEqual(result['lineage']['classification_counts']['test'], 1)
        self.assertEqual(result['lineage']['classification_counts']['unregistered'], 1)
        self.assertGreater(store.calls['list'], 2)
        target = SyntheticStorage('fixture-restored')
        restored = restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertEqual(restored['status'], 'RESTORED_SYNTHETIC_ONLY')
        self.assertEqual(set(target.objects), set(before))
        for key, obj in before.items():
            self.assertEqual(target.objects[key].payload, obj.payload)
            self.assertEqual(target.objects[key].metadata, obj.metadata)
        self.assertEqual(store.objects, before)
        self.assertFalse(restored['remote_s3_restore_verified'])

    def test_22_build_baseline_and_another_context_count_are_not_hardcoded(self):
        store, metadata = fixture(full=True, contexts=((43, 106), (9, 281)))
        result = self.backup(store, metadata)
        self.assertEqual(result['lineage']['published_builds'], 22)
        self.assertEqual(result['lineage']['loaded_builds'], 22)
        self.assertNotEqual(result['source_objects'], 315)

    def test_metadata_snapshot_row_order_is_not_a_change(self):
        store, metadata = fixture()
        baseline = metadata.snapshot()
        changed = deepcopy(baseline)
        for rows in changed['catalog'].values():
            rows.reverse()
        self.assertEqual(snapshot_digest(baseline), snapshot_digest(changed))
        with patch.object(metadata, 'snapshot', side_effect=[baseline, changed]):
            self.backup(store, metadata)

    def test_empty_storage_and_catalog(self):
        empty = {'catalog': {name: [] for name in CATALOG_TABLES}, 'serving': {}}
        result = self.backup(SyntheticStorage(), StaticMetadata(empty))
        self.assertEqual(result['source_objects'], 0)
        target = SyntheticStorage('empty-destination')
        self.assertEqual(restore_synthetic_storage(result['directory'], self.key, destination=target,
                         confirmed=True)['source_objects'], 0)

    def test_duplicate_keys_between_pages(self):
        class Duplicate(SyntheticStorage):
            def list_page(self, token=None):
                page = super().list_page(None)
                return replace(page, next_token='again')
        store, metadata = fixture(storage_type=Duplicate)
        self.assert_unsealed(store, metadata, 'DUPLICATE_LIST_KEY')

    def test_pagination_faults(self):
        variants = [Page((), 0, True, 'next'), Page((), 0, False, 'unused'),
                    Page((), 3, False, None), Page((), 0, True, None)]
        for page in variants:
            store, metadata = fixture()
            with self.subTest(page=page), patch.object(store, 'list_page', return_value=page):
                self.assert_unsealed(store, metadata, 'PAGE|PAGINATION')

    def test_pagination_cycle(self):
        class Cycle(SyntheticStorage):
            def list_page(self, token=None):
                key = 'a' if token is None else 'b'
                return Page((ListEntry(key, 0, 'date', 'etag'),), 1, True, 'same-token')
        store, metadata = fixture(storage_type=Cycle)
        self.assert_unsealed(store, metadata, 'PAGINATION_CYCLE')

    def test_consistently_partial_list_missing_catalog_object_is_detected(self):
        class Partial(SyntheticStorage):
            def list_page(self, token=None):
                return Page((), 0, False, None)
        store, metadata = fixture(storage_type=Partial)
        self.assert_unsealed(store, metadata, 'REGISTERED_OBJECT_MISSING')

    def test_head_failure_access_denied_and_missing_capability(self):
        store, metadata = fixture()
        with patch.object(store, 'head_object', side_effect=OSError('synthetic-private-error')):
            self.assert_unsealed(store, metadata, 'WORKFLOW_OPERATION_FAILED')
        store._capabilities = frozenset(('list', 'head'))
        self.assert_unsealed(store, metadata, 'READ_CAPABILITY_MISSING')
        store, metadata = fixture()
        with patch.object(store, 'get_object', side_effect=RecoveryError('S3_STORAGE_ACCESS_DENIED')):
            self.assert_unsealed(store, metadata, 'ACCESS_DENIED')

    def test_source_changes_during_collection(self):
        for change in ('add', 'delete', 'bytes', 'metadata', 'last_modified', 'list_etag', 'head_etag'):
            store, metadata = fixture()
            original = store.get_object
            called = False
            def mutate(key, *, expected):
                nonlocal called
                response = original(key, expected=expected)
                if not called:
                    called = True
                    if change == 'add':
                        store.objects['new-key'] = SyntheticObject(b'new')
                    elif change == 'delete':
                        del store.objects[key]
                    elif change == 'bytes':
                        store.objects[key].payload += b'changed'
                    elif change == 'metadata':
                        store.objects[key].metadata['new'] = 'value'
                    elif change == 'last_modified':
                        store.objects[key].last_modified = 'changed-date'
                    elif change == 'list_etag':
                        store.objects[key].list_etag = 'changed-list'
                    else:
                        store.objects[key].head_etag = 'changed-head'
                return response
            with self.subTest(change=change), patch.object(store, 'get_object', side_effect=mutate):
                self.assert_unsealed(store, metadata, 'SOURCE_CHANGED|PRECONDITION|MISSING|STATE_CHANGED')

    def test_truncated_get_and_get_header_change(self):
        for truncated in (True, False):
            store, metadata = fixture()
            original = store.get_object
            def broken(key, *, expected):
                result = original(key, expected=expected)
                if truncated and expected.size_bytes:
                    result.body = io.BytesIO(store.objects[key].payload[:-1])
                elif not truncated:
                    result.head = replace(expected, etag='changed')
                return result
            with self.subTest(truncated=truncated), patch.object(store, 'get_object', side_effect=broken):
                self.assert_unsealed(store, metadata, 'TRUNCATED|GET_HEAD_STATE')

    def test_missing_required_object(self):
        store, metadata = fixture()
        key = metadata.value['catalog']['silver_builds'][0]['s3_prefix'] + '_SUCCESS'
        del store.objects[key]
        self.assert_unsealed(store, metadata, 'REGISTERED_OBJECT_MISSING')

    def test_source_change_between_head_and_get(self):
        store, metadata = fixture()
        original = store.get_object
        def changed(key, *, expected):
            store.objects[key].metadata['mutated'] = 'yes'
            return original(key, expected=expected)
        with patch.object(store, 'get_object', side_effect=changed):
            self.assert_unsealed(store, metadata, 'PRECONDITION_FAILED')

    def test_metadata_baseline_change(self):
        store, metadata = fixture()
        before = metadata.snapshot()
        after = deepcopy(before)
        after['catalog']['silver_builds'][0]['row_count'] += 1
        with patch.object(metadata, 'snapshot', side_effect=[before, after]):
            self.assert_unsealed(store, metadata, 'METADATA_BASELINE_CHANGED')

    def test_pagination_exception_is_safe_and_unsealed(self):
        store, metadata = fixture()
        with patch.object(store, 'list_page', side_effect=OSError('private-provider-message')):
            with self.assertRaises(RecoveryError) as caught:
                self.backup(store, metadata)
        self.assertNotIn('private-provider-message', str(caught.exception))
        self.assertFalse(any(self.root.glob('*/manifest.json')))

    def test_source_identity_change_is_refused(self):
        store, metadata = fixture()
        original = store.get_object
        def change(key, *, expected):
            result = original(key, expected=expected)
            store.identity = replace(store.identity, resource_id='different-source')
            return result
        with patch.object(store, 'get_object', side_effect=change):
            self.assert_unsealed(store, metadata, 'SOURCE_IDENTITY_CHANGED')

    def test_bronze_actual_bytes_sha_mismatch(self):
        store, metadata = fixture()
        key = metadata.value['catalog']['ingestion_objects'][0]['object_key']
        store.objects[key].payload = b'wrong-but-stable-source-bytes'
        self.assert_unsealed(store, metadata, 'BRONZE_BYTES_MISMATCH')

    def test_lineage_manifest_context_parent_and_serving_mismatches(self):
        for change in ('manifest_context', 'manifest_parent', 'load_build', 'serving_count', 'duplicate_keys', 'schema', 'part_etag'):
            store, metadata = fixture()
            catalog = metadata.value['catalog']
            if change.startswith('manifest_'):
                key = catalog['silver_builds'][0]['s3_prefix'] + '_manifest.json'
                m = json.loads(store.objects[key].payload)
                if change == 'manifest_context':
                    m['season_id'] += 1
                else:
                    m['inputs'][0]['sha256'] = '0' * 64
                raw = encoded(m)
                store.objects[key].payload = raw
                store.objects[key].metadata['sha256'] = digest(raw)
            elif change == 'load_build':
                catalog['clickhouse_loads'][0]['silver_build_id'] = '0' * 64
            elif change == 'serving_count':
                next(iter(metadata.value['serving'].values()))['groups'][0]['rows'] += 1
            elif change == 'duplicate_keys':
                next(iter(metadata.value['serving'].values()))['duplicate_keys'] = 1
            elif change == 'schema':
                catalog['silver_builds'][0]['schema_sha256'] = '0' * 64
            else:
                part = next(k for k in store.objects if k.endswith('.parquet'))
                store.objects[part].list_etag = 'changed-etag'
            with self.subTest(change=change):
                self.assert_unsealed(store, metadata)

    def test_gold_parent_context_mismatch(self):
        store, metadata = fixture()
        row = metadata.value['catalog']['gold_builds'][0]
        row['season_id'] += 1
        self.assert_unsealed(store, metadata, 'CATALOG_IDENTITY')

    def test_duplicate_receipt_and_catalog_rows_rejected(self):
        for table in ('ingestion_objects', 'silver_builds', 'clickhouse_loads'):
            store, metadata = fixture()
            metadata.value['catalog'][table].append(deepcopy(metadata.value['catalog'][table][0]))
            with self.subTest(table=table):
                self.assert_unsealed(store, metadata, 'DUPLICATE')

    def test_write_error_and_readback_corruption_abort(self):
        for write_error in (True, False):
            store, metadata = fixture()
            if write_error:
                with patch.object(s3_archive, '_write', side_effect=OSError('synthetic-private-error')):
                    self.assert_unsealed(store, metadata)
            else:
                original = s3_archive.S3ArchiveWriter.verify_pending
                def corrupt(writer):
                    next(writer.directory.glob('object-*.enc')).write_bytes(b'corrupt')
                    return original(writer)
                with patch.object(s3_archive.S3ArchiveWriter, 'verify_pending', corrupt):
                    self.assert_unsealed(store, metadata, 'ARTIFACT_SIZE')

    def test_destination_requires_confirmation_explicit_target_and_conditional_put(self):
        result = self.backup()
        destination = SyntheticStorage('restored')
        with self.assertRaisesRegex(RecoveryError, 'CONFIRMATION'):
            restore_synthetic_storage(result['directory'], self.key, destination=destination)
        with self.assertRaisesRegex(RecoveryError, 'EXPLICIT_DESTINATION'):
            restore_synthetic_storage(result['directory'], self.key, confirmed=True)
        destination._capabilities = frozenset(('list', 'head', 'get', 'conditional_get'))
        with self.assertRaisesRegex(RecoveryError, 'DESTINATION_CAPABILITY'):
            restore_synthetic_storage(result['directory'], self.key, destination=destination, confirmed=True)
        self.assertEqual(destination.calls['put_if_absent'], 0)

    def test_source_bucket_and_alias_destinations_refused(self):
        store, metadata = fixture()
        result = self.backup(store, metadata)
        identities = [store.identity, replace(store.identity, bucket='endpoint-alias'),
                      StorageIdentity('other', 'fixture-source', 'different-id'),
                      StorageIdentity('other', 'other-bucket', 'new', aliases=(store.identity.resource_id,))]
        for identity in identities:
            target = SyntheticStorage(identity=identity)
            with self.subTest(identity=identity), self.assertRaisesRegex(RecoveryError, 'SOURCE_DESTINATION_ALIAS'):
                restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
            self.assertFalse(target.objects)

    def test_nonempty_destination_and_repeated_restore_never_overwrite(self):
        result = self.backup()
        target = SyntheticStorage('restored', objects={'keep': SyntheticObject(b'keep')})
        with self.assertRaisesRegex(RecoveryError, 'DESTINATION_NOT_EMPTY'):
            restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertEqual(target.objects['keep'].payload, b'keep')
        target = SyntheticStorage('restored')
        restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        before = deepcopy(target.objects)
        with self.assertRaisesRegex(RecoveryError, 'DESTINATION_NOT_EMPTY'):
            restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertEqual(target.objects, before)

    def test_collision_after_empty_preflight_is_atomic_and_leaves_foreign_bytes(self):
        result = self.backup()
        class RacingDestination(SyntheticStorage):
            def put_if_absent(self, key, chunks, **kwargs):
                self.objects[key] = SyntheticObject(b'foreign')
                return super().put_if_absent(key, chunks, **kwargs)
        target = RacingDestination('restored')
        with self.assertRaisesRegex(RecoveryError, 'DESTINATION_COLLISION'):
            restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertTrue(all(o.payload == b'foreign' for o in target.objects.values()))

    def test_restore_allows_new_provider_etags_and_preserves_original_manifests(self):
        store, metadata = fixture()
        result = self.backup(store, metadata)
        class DifferentETags(SyntheticStorage):
            def put_if_absent(self, key, chunks, **kwargs):
                super().put_if_absent(key, chunks, **kwargs)
                self.objects[key].list_etag = 'destination-list:' + digest(self.objects[key].payload)
                self.objects[key].head_etag = 'destination-head:' + digest(self.objects[key].payload)
        target = DifferentETags('restored')
        restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        for key in store.objects:
            self.assertEqual(target.objects[key].payload, store.objects[key].payload)
        first = next(iter(store.objects))
        self.assertNotEqual(store.head_object(first).etag, target.head_object(first).etag)

    def test_destination_extra_object_detected_without_cleanup(self):
        result = self.backup()
        class Extra(SyntheticStorage):
            def put_if_absent(self, key, chunks, **kwargs):
                super().put_if_absent(key, chunks, **kwargs)
                self.objects['foreign-key'] = SyntheticObject(b'keep')
        target = Extra('restored')
        with self.assertRaisesRegex(RecoveryError, 'RESTORE_KEY_SET'):
            restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertEqual(target.objects['foreign-key'].payload, b'keep')

    def test_destination_identity_change_stops_further_writes(self):
        result = self.backup()
        class Redirect(SyntheticStorage):
            def put_if_absent(self, key, chunks, **kwargs):
                super().put_if_absent(key, chunks, **kwargs)
                self.identity = replace(self.identity, resource_id='changed-destination')
        target = Redirect('restored')
        with self.assertRaisesRegex(RecoveryError, 'DESTINATION_IDENTITY_CHANGED'):
            restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertEqual(target.calls['put_if_absent'], 1)

    def test_restore_detects_wrong_bytes_and_metadata(self):
        result = self.backup()
        for mutate_metadata in (True, False):
            class CorruptDestination(SyntheticStorage):
                def put_if_absent(self, key, chunks, **kwargs):
                    super().put_if_absent(key, chunks, **kwargs)
                    if mutate_metadata:
                        self.objects[key].metadata['wrong'] = 'value'
                    elif self.objects[key].payload:
                        raw = self.objects[key].payload
                        self.objects[key].payload = bytes([raw[0] ^ 1]) + raw[1:]
            target = CorruptDestination('restored')
            with self.subTest(metadata=mutate_metadata), self.assertRaisesRegex(RecoveryError, 'RESTORE_METADATA|RESTORE_SHA256'):
                restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
            self.assertTrue(target.objects)  # No automatic cleanup of failed targets.

    def test_corrupt_archive_blocks_destination_writes(self):
        result = self.backup()
        next(Path(result['directory']).glob('object-*.enc')).write_bytes(b'broken')
        target = SyntheticStorage('restored')
        with self.assertRaises(RecoveryError):
            restore_synthetic_storage(result['directory'], self.key, destination=target, confirmed=True)
        self.assertFalse(target.objects)
        self.assertEqual(target.calls['put_if_absent'], 0)

    def test_archive_without_workflow_evidence_is_not_restore_authority(self):
        with s3_archive.S3ArchiveWriter(self.root, self.key, expected_objects=0) as writer:
            writer.seal()
        target = SyntheticStorage('restored')
        with self.assertRaisesRegex(RecoveryError, 'WORKFLOW_EVIDENCE'):
            restore_synthetic_storage(writer.directory, self.key, destination=target, confirmed=True)
        self.assertFalse(target.objects)

    def test_live_mode_is_refused(self):
        store, metadata = fixture()
        store.identity = replace(store.identity, mode='live')
        self.assert_unsealed(store, metadata, 'SYNTHETIC_ONLY')


if __name__ == '__main__':
    unittest.main()
