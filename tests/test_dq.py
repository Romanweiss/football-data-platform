"""Offline DQ failure injection and existing-validator observer contracts."""
import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.dq.model import Run, Rule
from src.dq.cli import execute, exit_code, main, render
from src.dq.orchestration import DQGateError, validate

C = {'competition_id':7, 'season_id':11}
H = 'a' * 64
RULE = Rule('silver.events.unique_grain', 'structural', 'silver', 'event_core', 'Unique event grain')


class QualityTests(unittest.TestCase):
    def test_status_severity_manual_identity_and_observations(self):
        run = Run(C, 'full')
        run.record(RULE, observed=10, expected=10, build_id=H)
        run.record(Rule('source.optional', 'source_integrity', 'bronze', 'matches', 'Optional evidence', 'WARNING'), passed=False)
        run.record(Rule('golden.not_applicable', 'regression', 'serving', 'bi', 'Optional fixture'), skip=True, reason='not applicable')
        report = run.report()
        self.assertEqual(report['counts'], dict(PASS=1, FAIL=0, WARN=1, SKIP=1))
        self.assertEqual(report['status'], 'WARN')
        self.assertEqual(report['airflow'], {})
        self.assertEqual(exit_code(report), 0)
        with self.assertRaises(ValueError):
            run.record(RULE)

    def test_error_failure_blocks_and_preserves_earlier_results(self):
        run = Run(C, 'full')
        run.record(RULE, passed=False, observed=3, expected=4, build_id=H)
        self.assertEqual(exit_code(run.report()), 1)
        self.assertEqual(run.report()['layers'], {'silver':'FAIL'})

    def test_same_build_multiple_executions_and_contexts(self):
        runs = [Run(C, 'artifact.silver.event_core'), Run(C, 'artifact.silver.event_core'),
                Run({'competition_id':8,'season_id':12}, 'artifact.silver.event_core')]
        for run in runs:
            run.record(RULE, build_id=H)
        self.assertEqual(len({r.execution_id for r in runs}), 3)
        self.assertEqual({r.results[0]['build_id'] for r in runs}, {H})
        self.assertNotEqual(runs[0].results[0]['competition_id'], runs[2].results[0]['competition_id'])

    def test_airflow_link_optional_bounded_and_explicit(self):
        link = {'dag_id':'statsbomb_context_pipeline', 'run_id':'manual__test', 'task_id':'silver.event_core.validate'}
        self.assertEqual(Run(C, 'full', airflow=link).report()['airflow'], link)
        for bad in ({'run_id':'partial'}, {**link,'run_id':'https://secret:password@host'}, {**link,'extra':'token'}):
            with self.assertRaises(ValueError):
                Run(C, 'full', airflow=bad)

    def test_raw_logs_exception_environment_and_payloads_are_not_results(self):
        secret = 'synthetic-S3-SECRET=do-not-store'
        def fail():
            print(secret)
            raise ValueError('postgres://name:' + secret + '@host')
        run = Run(C, 'full')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(run.call(RULE, fail)[0])
            render(run.report(), output_json=True)
        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn('postgres://', json.dumps(run.report()))
        for bad in (secret, {'rows':list(range(100))}, [1], float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                Run(C, 'full').record(RULE, observed=bad)

    def test_runtime_failure_is_distinct_from_analytical_failure(self):
        run = Run(C, 'full')
        def timeout():
            raise TimeoutError('raw secret')
        run.call(RULE, timeout)
        self.assertEqual([(r['category'],r['status']) for r in run.results],
                         [('structural','SKIP'), ('operational','FAIL')])

    def test_json_and_human_output_and_persistence_failure_exit(self):
        run = Run(C, 'full')
        run.record(RULE, passed=False)
        for json_mode in (False, True):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                render(run.report(), output_json=json_mode)
            self.assertIn('silver.events.unique_grain', output.getvalue())
            if json_mode:
                self.assertEqual(json.loads(output.getvalue())['status'], 'FAIL')
        self.assertEqual(exit_code({**run.report(),'persistence_error':'unavailable'}), 2)

    def test_full_run_records_runtime_failure_without_leaking_and_attempts_persistence(self):
        with patch('src.dq.cli.create_postgres_connection', side_effect=RuntimeError('secret')):
            report = execute(C)
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(report['persisted'])
        self.assertEqual(exit_code(report), 2)
        self.assertNotIn('secret', json.dumps(report))

    def test_airflow_uses_same_contract_and_bounded_summary(self):
        run = Run(C, 'references', airflow={'dag_id':'d','run_id':'r','task_id':'t'})
        run.record(RULE, passed=False, build_id=H)
        report = {**run.report(), 'persisted':True}
        with patch('src.dq.orchestration.execute', return_value=report) as call:
            with self.assertRaises(DQGateError) as error:
                validate({'context':C,'airflow':run.airflow}, 'references')
            self.assertEqual(error.exception.summary['dq_failed_rules'], [RULE.rule_id])
            self.assertEqual(call.call_args.kwargs['airflow'], run.airflow)
            self.assertLess(len(json.dumps(error.exception.summary)), 1000)
        self.assertNotIn('results', error.exception.summary)

    def test_airflow_gate_fails_if_persistence_unavailable_even_with_pass(self):
        report = {**Run(C,'api').report(), 'persisted':False, 'persistence_error':'unavailable'}
        with patch('src.dq.orchestration.execute', return_value=report):
            with self.assertRaises(DQGateError):
                validate({'context':C}, 'api')

    def test_gold_existing_tolerance_and_failure_observer(self):
        from src.analytics.gold_model import validate_model_metrics
        from src.analytics.validation import ClickHouseIntegrityError
        client = Mock()
        client.query.return_value.result_rows = [(1.0, 2.0)]
        seen = []
        with patch('src.analytics.gold_model.model_queries', return_value=[('team_shot_xg','SELECT fixture','close')]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ClickHouseIntegrityError):
                validate_model_metrics(client, {}, {}, **C, report=lambda *args:seen.append(args))
        self.assertEqual(seen, [('team_shot_xg',1.0,2.0,False)])
        self.assertEqual(client.query.call_args.kwargs['parameters'], C)

    def test_existing_info_reference_semantics_not_weakened_or_promoted(self):
        from src.analytics.model import REFERENCE_CHECKS, validate_references
        from src.analytics.validation import ClickHouseIntegrityError
        client = Mock()
        client.query.side_effect = [SimpleNamespace(result_rows=[(0 if c.hard else 7,)]) for c in REFERENCE_CHECKS]
        seen = []
        with contextlib.redirect_stdout(io.StringIO()):
            validate_references(client, {}, **C, report=lambda *args:seen.append(args))
        self.assertTrue(any(actual==7 and not hard for _,actual,_,_,hard in seen))
        client.query.side_effect = [SimpleNamespace(result_rows=[(1,)]) for _ in REFERENCE_CHECKS]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ClickHouseIntegrityError):
            validate_references(client, {}, **C)

    def test_bronze_missing_membership_blocks_metadata_and_reports_rule(self):
        from src.dq.bronze import check
        run = Run(C, 'bronze')
        parent = {'s3_bucket':'fixture','object_key':'fixture','sha256':H}
        with patch('scripts.inspect_context_catalog.inspect_catalog', return_value={'parents':[{'sha256':H}],'bronze_max_id':10}), \
             patch('src.common.postgres.find_matches_parent', return_value=parent), \
             patch('src.common.bronze_reader.read_bronze_object', return_value=b'[]'), \
             patch('src.statsbomb.context.matches_context', return_value=[1,2]), \
             patch('src.common.postgres.find_latest_ingestion_objects', return_value=[]), \
             patch('src.common.bronze_reader.verify_bronze_object_metadata') as head:
            check(run, Mock(), Mock())
        self.assertEqual(run.report()['status'], 'FAIL')
        self.assertIn('bronze.match_events_membership', [r['rule_id'] for r in run.results if r['status']=='FAIL'])
        head.assert_not_called()

    def test_golden_is_skipped_for_non_fixture_context_without_network(self):
        from src.dq.api import check, golden_views
        run = Run(C, 'golden')
        with patch('scripts.check_application_api.make_request') as request, \
             patch('scripts.check_clickhouse_match_visuals.main') as main:
            check(run, golden=True)
            golden_views(run)
        self.assertEqual(run.report()['counts']['SKIP'], 2)
        request.assert_not_called()
        main.assert_not_called()

    def test_normalized_cli_uses_validated_explicit_context(self):
        with patch('src.dq.cli.execute', return_value={**Run(C,'full').report(),'persisted':True}) as execute, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--competition-id','7','--season-id','11','--output-json']), 0)
        self.assertEqual(execute.call_args.args, (C,))
        self.assertTrue(json.loads(output.getvalue())['persisted'])

    def test_runtime_gate_calls_dq_no_old_console_parser(self):
        from src.orchestration.runtime import execute as step
        with patch('src.dq.orchestration.validate', return_value={'dq_execution_id':'fixture'}) as quality, \
             patch('src.orchestration.runtime.run_cli') as cli:
            result = step({'context':C,'step':'serving_gold'})
        self.assertEqual(quality.call_args.args[1], 'gold')
        self.assertEqual(result['dq_execution_id'], 'fixture')
        cli.assert_not_called()

    def test_artifact_adapter_keeps_read_only_preflight_and_omits_noop_team_check(self):
        from src.dq.artifacts import check
        run = Run(C, 'artifact.silver.teams')
        with patch('src.analytics.silver_input.resolve_silver_build', return_value={'build_id':H}), \
             patch('src.analytics.silver_input.verify_silver_manifest', return_value={'row_count':2}), \
             patch('src.analytics.silver_input.parquet_url', return_value='fixture'), \
             patch('src.analytics.validation.source_metrics', return_value=(2,2)), \
             patch('src.analytics.validation.validate_metrics'), \
             patch('src.analytics.validation.validate_extra') as extra, \
             patch('src.analytics.loader.load_dataset') as load:
            check(run, Mock(), Mock(), Mock(), layer='silver', dataset='teams', build_id=H)
        self.assertTrue(load.call_args.kwargs['check_only'])
        extra.assert_not_called()
        self.assertNotIn('silver.teams.team_coverage', [r['rule_id'] for r in run.results])
        self.assertTrue(all(r['build_id']==H for r in run.results))

    def test_post_load_failure_records_evidence_without_repair(self):
        from src.dq.serving import gold
        from src.analytics.validation import ClickHouseIntegrityError
        run = Run(C, 'gold')
        client, connection = Mock(), Mock()
        with patch('src.analytics.gold_model.check_model', side_effect=ClickHouseIntegrityError('mismatch')):
            gold(run, connection, client)
        self.assertEqual(run.report()['status'], 'FAIL')
        self.assertEqual(run.results[-1]['rule_id'], 'serving.gold_lineage_metrics')
        client.command.assert_not_called()
        connection.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
