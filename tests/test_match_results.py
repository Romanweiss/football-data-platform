"""Stage 4B offline identity, manifest, input, loader and CLI contracts."""
import copy
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from dataclasses import replace
from unittest.mock import MagicMock, patch

from gold_fakes import silver_inputs, specification
from gold_clickhouse_fakes import fixture
import test_clickhouse_gold as loader_tests
import test_gold as gold_tests
from src.gold import inputs, job, manifest
from src.gold.build_identity import RESULT_INPUTS, calculate_build_id, input_fingerprint
from src.gold.build_identity import gold_prefix
from src.analytics import gold_input, gold_job, gold_loader
from src.analytics import gold_model
from src.analytics.gold_specs import RESULTS, SPECS

ROOT = Path(__file__).resolve().parents[1]


class MatchResultsOfflineTests(unittest.TestCase):
    def test_exact_three_inputs_in_manifest_identity_and_determinism(self):
        _, builds, _ = silver_inputs(RESULT_INPUTS)
        original = specification(builds,'match_results')
        self.assertEqual(calculate_build_id(original),calculate_build_id(specification(list(reversed(builds)),'match_results')))
        for index in range(3):
            changed = copy.deepcopy(builds)
            changed[index]['build_id']='f'*64
            self.assertNotEqual(input_fingerprint(builds),input_fingerprint(changed))
        _, build, actual = fixture(RESULTS)
        self.assertEqual(tuple(item['dataset'] for item in actual['inputs']),RESULT_INPUTS)
        self.assertEqual(build['transform_version'],'match_results_v1')
        self.assertIn('/match_results/competition_id=43/season_id=106/build_id=',build['s3_prefix'])
        with self.assertRaises(manifest.GoldIntegrityError):
            manifest.make_manifest(original,builds[:-1],{'row_count':4,'match_count':4},actual['files'])

    def test_pinned_inputs_handle_matches_parent_lineage_and_never_use_latest(self):
        client,builds,manifests = silver_inputs(RESULT_INPUTS)
        ids = {b['dataset']:b['build_id'] for b in builds}
        with patch.dict(os.environ,{'S3_BUCKET':'test-bucket'},clear=True), \
                patch.object(inputs,'find_silver_build',side_effect=lambda *a,**kw:next(b for b in builds if b['dataset']==kw['dataset'])) as exact, \
                patch.object(inputs,'find_latest_silver_build') as latest:
            self.assertEqual(inputs.resolve_inputs(None,client,competition_id=43,season_id=106,diagnostics=job.Diagnostics(),required=RESULT_INPUTS,build_ids=ids),(builds,manifests))
            self.assertEqual(exact.call_count,3)
            latest.assert_not_called()
            for bad in ({}, {'matches':'f'*64}):
                with self.assertRaises(manifest.GoldIntegrityError):
                    inputs.resolve_inputs(None,client,competition_id=43,season_id=106,diagnostics=job.Diagnostics(),required=RESULT_INPUTS,build_ids=bad)
        self.assertFalse(any(call[0]=='put' for call in client.calls))

    def test_pinned_build_mismatch_is_rejected(self):
        client,builds,_ = silver_inputs(RESULT_INPUTS)
        ids={b['dataset']:b['build_id'] for b in builds}
        with patch.object(inputs,'find_silver_build',return_value={**builds[0],'build_id':'f'*64}):
            with self.assertRaises(manifest.GoldIntegrityError):
                inputs.resolve_inputs(None,client,competition_id=43,season_id=106,diagnostics=job.Diagnostics(),required=RESULT_INPUTS,build_ids=ids)

    def test_sql_migration_and_safe_cast_contract(self):
        sql=(ROOT/'infrastructure/clickhouse/migrations/007_create_match_results.sql').read_text()
        body=sql.split('\n(\n')[1].split('\n)')[0]
        columns=tuple(tuple(line.strip().rstrip(',').split(' ',1)) for line in body.splitlines())
        self.assertEqual(columns,(*RESULTS.target_columns[:-1],('loaded_at',"DateTime64(3, 'UTC') DEFAULT now64(3)")))
        self.assertIn('ORDER BY (competition_id, season_id, match_date, match_id)',sql)
        self.assertNotIn('winner_team_id',RESULTS.required_columns)
        insert=gold_loader.insert_sql(spec=RESULTS)
        self.assertIn("accurateCast(`match_date`, 'Date')",insert)
        self.assertIn("accurateCast(`winner_team_id`, 'Nullable(UInt32)')",insert)
        self.assertNotIn('DELETE',insert)
        self.assertIn('home_shootout_goals=away_shootout_goals',' '.join(RESULTS.invalid_predicates))

    def test_new_cli_requires_exact_builds_before_connections(self):
        with patch.object(job,'create_postgres_connection') as connect,redirect_stderr(io.StringIO()):
            for args in (['--dataset','match-results'],['--dataset','team-match-stats','--transform-version','team_match_stats_v2']):
                with self.assertRaises(SystemExit): job.main(args)
            connect.assert_not_called()
        self.assertEqual(gold_job.parse_args(['--dataset','match-results']).dataset,'match-results')
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            gold_job.parse_args(['--dataset','match-results','--transform-version','v2'])

    def test_v2_identity_changes_and_model_checks_keep_extra_time(self):
        _,builds,_=silver_inputs()
        v1=specification(builds)
        v2={**v1,'transform_version':'team_match_stats_v2'}
        self.assertNotEqual(calculate_build_id(v1),calculate_build_id(v2))
        specs={name:replace(spec,version='v2') for name,spec in SPECS.items()}
        sql=' '.join(query for _,query,_ in gold_model.model_queries(gold_specs=specs))
        self.assertIn('AND period != 5',sql)
        self.assertNotIn('period IN (1, 2)',sql)
        mixed={**SPECS,'team_match_stats':specs['team_match_stats']}
        with self.assertRaises(gold_loader.ClickHouseIntegrityError): gold_model.model_queries(gold_specs=mixed)

    def test_results_check_only_never_publishes_and_version_is_exact(self):
        client,builds,manifests=silver_inputs(RESULT_INPUTS)
        args=['--dataset','match-results','--check-only']
        for build in builds: args+=['--silver-build',build['dataset']+'='+build['build_id']]
        frame=MagicMock()
        frame.schema.json.return_value='{}'
        with patch.dict(os.environ,{'S3_BUCKET':'test-bucket'},clear=True), \
                patch.object(job,'create_postgres_connection'),patch.object(job,'create_s3_client',return_value=client), \
                patch.object(job,'resolve_inputs',return_value=(builds,manifests)) as resolve, \
                patch.object(job,'create_spark_session'),patch.object(job,'configure_s3a'),patch.object(job,'read_inputs',return_value={}), \
                patch.object(job,'build_frame',return_value=(frame,{'row_count':4,'match_count':4})), \
                patch.object(job,'publish_build') as publish,redirect_stdout(io.StringIO()) as output:
            self.assertEqual(job.main(args),0)
            publish.assert_not_called()
            self.assertEqual(resolve.call_args.kwargs['required'],RESULT_INPUTS)
            self.assertIn('Transform version: match_results_v1',output.getvalue())

    def test_result_manifest_verified_without_parquet_get(self):
        client,build,manifest_=fixture(RESULTS)
        self.assertEqual(gold_input.verify_gold_manifest(client,build),manifest_)
        self.assertTrue(all(call[2].endswith('_manifest.json') for call in client.calls if call[0]=='get'))

    def test_bi_migration_uses_authoritative_results_not_shot_derivation(self):
        sql=(ROOT/'infrastructure/clickhouse/migrations/008_enrich_bi_match_results.sql').read_text()
        self.assertEqual(sql.count('CREATE OR REPLACE VIEW'),2)
        self.assertEqual(sql.count('SQL SECURITY INVOKER'),2)
        self.assertEqual(sql.count('INNER JOIN football.match_results AS r'),2)
        self.assertEqual(sql.count('r.display_score AS display_score'),2)
        self.assertNotIn('shot_events',sql)
        self.assertNotIn('period = 5',sql)

    def test_recorded_live_audit_is_complete_and_consistent(self):
        audit=json.loads((ROOT/'docs/stage4b_shot_audit.json').read_text())
        self.assertEqual(len(audit['shootout_matches']),5)
        self.assertTrue(all(row['has_extra_time'] for row in audit['shootout_matches']))
        for name,affected in (('team_match_stats',10),('player_match_stats',53)):
            dataset=audit[name]
            self.assertEqual(dataset['affected_rows'],affected)
            self.assertEqual(len(dataset['differences']),affected)
            self.assertEqual(sum(r['delta_shots'] for r in dataset['differences']),41)
            self.assertEqual(dataset['totals']['delta_goals'],26)
            self.assertAlmostEqual(dataset['totals']['delta_xg'],32.1235)


class MatchResultsLoaderTests(unittest.TestCase):
    def case(self):
        return loader_tests.GoldServingLoaderTests.case(self,RESULTS)

    def test_first_repeat_and_timeout_recovery(self):
        stack,client,_,save,_,run,_=self.case()
        with stack:
            self.assertEqual(run()['output_status'],'LOADED')
            self.assertEqual(run()['output_status'],'UNCHANGED / ALREADY_LOADED')
            self.assertEqual(len(client.inserts),1)
            save.assert_called_once()
        stack,client,_,_,_,run,_=self.case()
        with stack:
            client.fail_after_insert=True
            with self.assertRaises(TimeoutError): run()
            client.fail_after_insert=False
            self.assertEqual(run()['output_status'],'UNCHANGED / ALREADY_LOADED')
            self.assertEqual(len(client.inserts),1)

    def test_partial_conflicting_and_check_only_never_insert(self):
        for failure in ('partial','conflict','none'):
            stack,client,_,save,_,run,_=self.case()
            with stack:
                if failure=='partial': client.target=(1,*client.source[1:])
                if failure=='conflict': client.other_rows=4
                if failure=='none': self.assertFalse(run(True)['already_loaded'])
                else:
                    with self.assertRaises(gold_loader.ClickHouseIntegrityError): run(True)
                save.assert_not_called()
                self.assertEqual(client.inserts,[])


class MatchResultsPublicationTests(gold_tests.GoldPublishTests):
    """Run the existing immutable publication/recovery cases with three-input results."""
    def setUp(self):
        super().setUp()
        self.client,self.builds,_=silver_inputs(RESULT_INPUTS)
        self.spec=specification(self.builds,'match_results')
        self.prefix=gold_prefix(self.spec,calculate_build_id(self.spec))
        self.params.update(client=self.client,inputs=self.builds,specification=self.spec,
                           counts={'row_count':4,'match_count':4})
