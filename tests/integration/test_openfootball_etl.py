"""Opt-in writes to labelled networkless PET-3 container only; synthetic data."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from openfootball_etl_fakes import gold
from src.openfootball_etl.clickhouse import IsolatedClickHouse
from src.openfootball_etl.contract import ETLError


@unittest.skipUnless(os.environ.get("PET3_SYNTHETIC_CLICKHOUSE_CONTAINER"), "Explicit isolated container required")
class OpenFootballClickHouseTests(unittest.TestCase):
    def setUp(self):
        self.client = IsolatedClickHouse(os.environ["PET3_SYNTHETIC_CLICKHOUSE_CONTAINER"],
                                        "pet3_openfootball_test_" + uuid.uuid4().hex)
        self.data = gold()

    def test_load_and_replay_with_typed_nulls(self):
        self.assertEqual("CREATED", self.client.publish(self.data)[0])
        self.assertEqual("REUSED", self.client.publish(self.data)[0])
        rows = self.client.read("historical_fixtures")
        missing = next(r for r in rows if r["result_availability"] == "MISSING")
        self.assertIsNone(missing["source_ft_home"])
        self.assertIsNone(missing["kickoff_utc"])
        self.assertIsNone(missing["winner_id"])

    def test_partial_insert_failure_is_not_visible_then_retry_succeeds(self):
        def fail():
            raise ETLError("SYNTHETIC_CLICKHOUSE_LOAD_FAILURE")
        with self.assertRaisesRegex(ETLError, "SYNTHETIC_CLICKHOUSE_LOAD_FAILURE"):
            self.client.publish(self.data, fault=fail)
        self.assertEqual(0, int(self.client.query("SELECT count() AS n FROM " + self.client.database + ".records")[0]["n"]))
        for name in self.data:
            self.assertEqual(0, int(self.client.query("SELECT count() AS n FROM " + self.client.database + "." + name)[0]["n"]))
        self.assertEqual("CREATED", self.client.publish(self.data)[0])
        self.assertEqual("REUSED", self.client.publish(self.data)[0])

    def test_conflicting_replay_is_refused_without_mutating_published_data(self):
        self.client.publish(self.data)
        conflict = deepcopy(self.data)
        conflict["historical_fixtures"][0]["source_ft_home"] = 99
        with self.assertRaisesRegex(ETLError, "CLICKHOUSE_CONTENT"):
            self.client.publish(conflict)
        self.client.matches(self.data)


if __name__ == "__main__":
    if "--require-isolated" in sys.argv:
        sys.argv.remove("--require-isolated")
        if not os.environ.get("PET3_SYNTHETIC_CLICKHOUSE_CONTAINER"):
            raise SystemExit("PET3_CI_ISOLATED_CONTAINER_REQUIRED")
    unittest.main()
