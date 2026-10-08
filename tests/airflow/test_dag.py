"""Airflow-image offline parse test. Execute with --network none, no secrets."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/app")


class DagTests(unittest.TestCase):
    def test_project_interpreter_has_all_existing_cli_dependencies(self):
        result = subprocess.run(["/usr/bin/python3", "-c",
                                 "import boto3, psycopg, clickhouse_connect; "
                                 "from importlib.metadata import version; "
                                 "assert version('boto3') == '1.40.21'; "
                                 "assert version('psycopg') == '3.3.6'; "
                                 "assert version('clickhouse-connect') == '0.15.0'"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "Project CLI dependencies unavailable")

    def test_parse_contract_without_network_or_project_environment(self):
        from airflow.dag_processing.dagbag import DagBag
        with patch.dict(os.environ, {"AIRFLOW_HOME": "/tmp/airflow-parse-test", "AIRFLOW__CORE__LOAD_EXAMPLES": "false"}, clear=True):
            with patch("socket.socket.connect", side_effect=AssertionError("DAG parse attempted network IO")):
                bag = DagBag(dag_folder="/opt/airflow/dags", include_examples=False)
        self.assertEqual(bag.import_errors, {})
        self.assertEqual(set(bag.dags), {"statsbomb_context_pipeline",'platform_dq_validation','statsbomb_source_discovery'})
        for name,cron in [('platform_dq_validation','0 5 * * 0'),('statsbomb_source_discovery','0 4 * * 0')]:
            scheduled=bag.dags[name]
            self.assertEqual(scheduled.schedule,cron)
            self.assertFalse(scheduled.catchup)
            self.assertTrue(scheduled.is_paused_upon_creation)
            self.assertEqual(scheduled.max_active_runs,1)
            self.assertEqual(scheduled.max_active_tasks,1)
            self.assertEqual(str(scheduled.timezone),'UTC')
            self.assertEqual(scheduled.start_date.isoformat(),'2026-10-09T00:00:00+00:00')
            self.assertTrue(all(t.retries==0 for t in scheduled.tasks))
        dag = bag.dags["statsbomb_context_pipeline"]
        self.assertIsNone(dag.schedule)
        self.assertEqual(dag.max_active_runs, 1)
        self.assertEqual(dag.max_active_tasks, 2)
        self.assertEqual(set(dag.params), {"competition_id", "season_id"})
        for name in dag.params:
            self.assertFalse(dag.params.get_param(name).has_value)
        self.assertEqual(len(dag.tasks), 60)
        spark_tasks = [t for t in dag.tasks if t.task_id.startswith(("silver.", "gold."))
                       and t.task_id.endswith((".check", ".publish"))]
        self.assertEqual(len(spark_tasks), 20)
        self.assertTrue(all(t.pool == "spark_local" and t.pool_slots == 1 for t in spark_tasks))
        self.assertTrue(all(t.pool != "spark_local" for t in dag.tasks if t not in spark_tasks))
        for params in ({"season_id": 281}, {"competition_id": 9},
                       {"competition_id": "9", "season_id": 281}):
            with self.subTest(params=params), self.assertRaises(Exception):
                # Same required Param schemas used by Airflow before DagRun creation.
                from copy import deepcopy
                candidate = deepcopy(dag.params)
                candidate.update(params)
                candidate.validate()
        for t in dag.tasks:
            self.assertEqual(t.retries, 0)
        self.assertIn("validate_context", dag.get_task("source.preflight").upstream_task_ids)
        self.assertIn("silver.teams.validate", dag.get_task("silver.matches.check").upstream_task_ids)
        for name in ("event_core", "match_squads", "pass_events", "shot_events"):
            self.assertIn(f"silver.{name}.validate", dag.get_task("gold.team_match_stats.check").upstream_task_ids)
        self.assertIn("silver.matches.validate", dag.get_task("gold.match_results.check").upstream_task_ids)
        self.assertIn("gold.match_results.validate", dag.get_task("clickhouse.silver_teams.preflight").upstream_task_ids)
        self.assertIn("clickhouse.silver_teams.preflight", dag.get_task("clickhouse.silver_teams.load").upstream_task_ids)
        self.assertEqual(dag.get_task("silver.event_core.check").pool, "spark_local")
        self.assertEqual(dag.get_task("silver.event_core.publish").pool, "spark_local")
        self.assertEqual(dag.get_task("validation.application_api").upstream_task_ids,
                         {"validate_context", "validation.serving_model", "validation.gold_model", "validation.match_results"})
        # Exercise the real decorated callable's metadata bridge without SDK/DB IO.
        from types import SimpleNamespace
        from unittest.mock import Mock
        callback = dag.get_task('validation.application_api').python_callable
        invoke = Mock(return_value={'dq_status':'PASS'})
        task_context = {'run_id':'manual__dq_fixture', 'ti':SimpleNamespace(
            dag_id=dag.dag_id, task_id='validation.application_api'), 'token':'synthetic-secret'}
        with patch.dict(callback.__globals__, {'get_current_context':lambda:task_context, 'invoke':invoke}):
            callback('application', {'competition_id':9,'season_id':281})
        self.assertEqual(invoke.call_args.args[0]['airflow'],
                         {'dag_id':dag.dag_id,'run_id':'manual__dq_fixture','task_id':'validation.application_api'})
        self.assertNotIn('synthetic-secret', str(invoke.call_args))


if __name__ == "__main__":
    unittest.main()
