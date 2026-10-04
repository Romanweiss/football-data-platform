"""Offline current-build selection and cross-table hard/informational references."""

from context_fixtures import in_context

import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from clickhouse_model_fakes import dataset_fixture
from src.analytics import model
from src.analytics.loader import load_record
from src.analytics.specs import SPECS
from src.analytics.validation import ClickHouseBuildConflictError, ClickHouseIntegrityError
from scripts import check_clickhouse_model as cli


class ModelTests(unittest.TestCase):
    def test_anti_join_queries_scoped_to_context_and_current_builds(self):
        self.assertEqual(sum(check.hard for check in model.REFERENCE_CHECKS), 5)
        self.assertEqual(sum(not check.hard for check in model.REFERENCE_CHECKS), 6)
        for check in model.REFERENCE_CHECKS:
            sql = model.reference_sql(check)
            self.assertTrue(sql.startswith("SELECT count()"))
            self.assertIn("LEFT ANTI JOIN", sql)
            self.assertEqual(sql.count("competition_id = %(competition_id)s"), 2)
            self.assertEqual(sql.count("season_id = %(season_id)s"), 2)
            for dataset in (check.child, check.parent):
                self.assertIn(f"%({dataset}_build_id)s", sql)
            self.assertNotIn("SELECT *", sql)
            if check.optional:
                self.assertIn("player_id IS NOT NULL", sql)

    def test_informational_orphans_do_not_fail_and_all_hard_orphans_fail(self):
        builds = {dataset: "a" * 64 for dataset in SPECS}
        client = MagicMock()
        client.query.side_effect = [SimpleNamespace(result_rows=[(0 if check.hard else 9,)]) for check in model.REFERENCE_CHECKS]
        with redirect_stdout(io.StringIO()) as output:
            counts = in_context(model.validate_references)(client, builds)
        self.assertEqual(len(counts), 11)
        self.assertIn("INFO event_core_player_orphan_rows: 9", output.getvalue())
        for failed in range(5):
            client.query.side_effect = [SimpleNamespace(result_rows=[(int(index == failed),)]) for index in range(11)]
            with self.subTest(failed=failed), redirect_stdout(io.StringIO()), self.assertRaises(ClickHouseIntegrityError):
                in_context(model.validate_references)(client, builds)
        client.command.assert_not_called()

    @patch.object(model, "validate_table_schema")
    @patch.object(model, "find_silver_build")
    @patch.object(model, "find_clickhouse_load")
    def test_current_builds_come_from_target_not_latest_silver(self, find_load, find_silver, schema):
        fixtures = {dataset: dataset_fixture(spec)[1] for dataset, spec in SPECS.items()}
        client = MagicMock()
        client.query.side_effect = [SimpleNamespace(result_rows=[(6, 1, build["build_id"])]) for build in fixtures.values()]
        find_silver.side_effect = lambda *a, **k: fixtures[k["dataset"]]
        find_load.side_effect = lambda *a, **k: load_record(fixtures[k["clickhouse_table"]], spec=SPECS[k["clickhouse_table"]])
        self.assertEqual(in_context(model.current_builds)(client, None), {key: value["build_id"] for key, value in fixtures.items()})
        self.assertEqual(schema.call_count, len(SPECS))
        client.command.assert_not_called()
        for count, distinct, error in ((0, 0, ClickHouseIntegrityError), (6, 2, ClickHouseBuildConflictError)):
            client.query.side_effect = None
            client.query.return_value.result_rows = [(count, distinct, "a" * 64)]
            with self.assertRaises(error):
                in_context(model.current_builds)(client, None)

    @patch.object(model, "current_builds")
    @patch.object(model, "validate_references", return_value={})
    def test_changed_model_during_read_fails(self, references, current):
        current.side_effect = [{"teams": "a" * 64}, {"teams": "b" * 64}]
        with self.assertRaises(ClickHouseIntegrityError):
            in_context(model.check_model)(None, None)

    def test_model_cli_errors_redacted(self):
        with patch.object(cli, "create_clickhouse_client", side_effect=RuntimeError("fake secret")):
            with redirect_stderr(io.StringIO()) as output:
                self.assertEqual(cli.main(["--competition-id", "43", "--season-id", "106"]), 1)
        self.assertNotIn("fake secret", output.getvalue())
        self.assertIn("exception=RuntimeError", output.getvalue())


if __name__ == "__main__":
    unittest.main()
