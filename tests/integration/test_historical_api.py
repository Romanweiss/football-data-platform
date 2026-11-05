"""CI database-backed HTTP regression on artificial Gold only. Never production."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from ci.databases import guard
from src.common.clickhouse import create_clickhouse_client
from src.openfootball_etl.contract import GOLD, row_digest
from src.openfootball_etl.clickhouse import TYPES
from openfootball_etl_fakes import gold
from application.historical import BASE, SEASON_PATH
from application.historical_repository import DatasetContract, HistoricalRepository


class HistoricalDatabaseTests(unittest.TestCase):
    def setUp(self):
        guard("clickhouse")  # Exact existing ephemeral CI host/database/user/flag.
        self.client = create_clickhouse_client()
        self.addCleanup(self.client.close)
        self.database = "pet3_openfootball_api_" + uuid.uuid4().hex[:12]
        self.data = gold()
        first = self.data["historical_fixtures"][0]
        contract = DatasetContract(first["batch_id"], first["source_sha256"], "f" * 64,
                                  tuple((n, len(r), row_digest(r)) for n, r in self.data.items()))
        self.client.command("CREATE DATABASE " + self.database)
        for name, fields in GOLD.items():
            columns = ",".join(n + " " + ("Nullable(" + TYPES[t] + ")" if null else TYPES[t]) for n, t, null in fields)
            self.client.command("CREATE TABLE " + self.database + ".raw_" + name + " (" + columns + ") ENGINE=Memory")
            self.client.command("CREATE VIEW " + self.database + "." + name + " AS SELECT " +
                                ",".join(n for n, _, _ in fields) + " FROM " + self.database + ".raw_" + name)
            self.insert(name, self.data[name])
        self.repository = HistoricalRepository(self.client, self.database, contract=contract)
        @contextmanager
        def opened():
            yield self.repository
        self.patcher = patch("application.historical_views.open_historical_repository", side_effect=opened)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.http = Client(HTTP_HOST="localhost", raise_request_exception=False)

    def insert(self, name, rows):
        names = [n for n, _, _ in GOLD[name]]
        self.client.insert(self.database + ".raw_" + name,
                           [tuple(row[n] for n in names) for row in rows], column_names=names)

    def test_six_routes_use_native_clickhouse_results_not_fake_transport(self):
        for path in (BASE, SEASON_PATH, *[SEASON_PATH + "/" + n for n in ("fixtures", "participants", "coverage", "quality")]):
            self.assertEqual(200, self.http.get(path).status_code, path)
        response = self.http.get(SEASON_PATH + "/fixtures?limit=2").json()
        self.assertEqual(4, response["pagination"]["total"])
        self.assertEqual(2, response["pagination"]["next_offset"])
        rows = self.http.get(SEASON_PATH + "/fixtures?limit=100").json()["fixtures"]
        self.assertEqual(4, len({r["id"] for r in rows}))
        unknown = next(r for r in rows if r["result_availability"] == "MISSING")
        self.assertIsNone(unknown["source_reported_score"]["ft"]["value"])
        self.assertTrue(all(r["canonical_regulation_score"]["value"] is None for r in rows))

    def test_partial_and_foreign_batch_rows_fail_closed_until_exact_content_restored(self):
        name = "source_quality"
        table = self.database + ".raw_" + name
        original = self.data[name]
        self.client.command("TRUNCATE TABLE " + table)  # Only this test's fresh synthetic Memory table.
        self.insert(name, original[:1])
        self.assertEqual(503, self.http.get(SEASON_PATH).status_code)
        self.client.command("TRUNCATE TABLE " + table)
        foreign = deepcopy(original)
        for row in foreign:
            row["batch_id"] = "b" * 64
        self.insert(name, foreign)
        self.assertEqual(503, self.http.get(SEASON_PATH).status_code)
        self.client.command("TRUNCATE TABLE " + table)
        self.insert(name, original)
        self.assertEqual(200, self.http.get(SEASON_PATH).status_code)

    def test_invalid_filters_do_not_change_source_and_valid_filters_reconcile(self):
        before = self.repository.load()
        response = self.http.get(SEASON_PATH + "/fixtures?team_id=1%20OR%201=1")
        self.assertEqual(400, response.status_code)
        team = before["historical_fixtures"][0]["home_id"]
        page = self.http.get(SEASON_PATH + "/fixtures", {"team_id": team}).json()
        self.assertTrue(all(team in (r["home"]["id"], r["away"]["id"]) for r in page["fixtures"]))
        self.assertEqual(before, self.repository.load())


if __name__ == "__main__":
    guard("clickhouse")  # No skips and no credential search on absent/wrong configuration.
    unittest.main()
