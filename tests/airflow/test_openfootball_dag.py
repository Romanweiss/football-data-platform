"""Parse the opt-in blueprint outside production dags/, no scheduler/DB/network."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/app")
from src.openfootball_etl.contract import STEPS


class OpenFootballDagTests(unittest.TestCase):
    def test_manual_linear_graph_outside_production_discovery(self):
        from airflow.dag_processing.dagbag import DagBag
        path = Path("/app/src/orchestration/openfootball_historical_dag.py")
        self.assertFalse(path.is_relative_to(Path("/opt/airflow/dags")))
        with patch("socket.socket.connect", side_effect=AssertionError("No parse-time network")):
            bag = DagBag(dag_folder=str(path), include_examples=False)
        self.assertEqual({}, bag.import_errors)
        self.assertEqual({"openfootball_historical_isolated"}, set(bag.dags))
        dag = bag.dags["openfootball_historical_isolated"]
        self.assertIsNone(dag.schedule)
        self.assertTrue(dag.is_paused_upon_creation)
        self.assertEqual(set(STEPS), set(dag.task_ids))
        self.assertEqual(1, dag.max_active_runs)
        self.assertEqual(1, dag.max_active_tasks)
        self.assertEqual({"source", "receipt", "store", "container", "database"}, set(dag.params))
        self.assertTrue(all(not dag.params.get_param(name).has_value for name in dag.params))
        for index, step in enumerate(STEPS):
            task = dag.get_task(step)
            self.assertEqual(set() if index == 0 else {STEPS[index - 1]}, task.upstream_task_ids)
            self.assertEqual(0, task.retries)


if __name__ == "__main__":
    unittest.main()
