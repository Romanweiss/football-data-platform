"""Synthetic offline HTTP, source semantics, query and isolation contracts."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from clickhouse_connect.driver.exceptions import OperationalError
from openfootball_etl_fakes import gold
from application.historical import BASE, SEASON_PATH, HistoricalService, fixture
from application.historical_repository import DatasetContract, HistoricalRepository, create_historical_client, open_historical_repository
from src.openfootball_etl.contract import GOLD, row_digest


class FakeClient:
    def __init__(self, data):
        self.data, self.calls = data, []

    def query(self, sql, *, parameters, settings):
        self.calls.append((sql, parameters, settings))
        name = next(n for n in GOLD if "." + n + " WHERE" in sql)
        names = [n for n, _, _ in GOLD[name]]
        return SimpleNamespace(column_names=names, result_rows=[tuple(r[n] for n in names) for r in self.data[name]])


def setup_repository():
    data = gold()
    first = data["historical_fixtures"][0]
    contract = DatasetContract(first["batch_id"], first["source_sha256"], "f" * 64,
                               tuple((n, len(r), row_digest(r)) for n, r in data.items()))
    client = FakeClient(data)
    return HistoricalRepository(client, "pet3_openfootball_api_" + "0" * 12, contract=contract), data, client


class HistoricalApiTests(unittest.TestCase):
    def setUp(self):
        self.repository, self.data, self.client = setup_repository()
        self.http = Client(HTTP_HOST="localhost", raise_request_exception=False)
        @contextmanager
        def opened():
            yield self.repository
        self.open = self.enterContext(patch("application.historical_views.open_historical_repository", side_effect=opened))

    def get(self, section="", query=None):
        return self.http.get(SEASON_PATH + ("/" + section if section else ""), query or {})

    def test_index_and_overview_counts_are_serving_derived_not_real_dataset_constants(self):
        index = self.http.get(BASE).json()["competitions"][0]
        overview = self.get().json()
        self.assertEqual(index, overview)
        self.assertEqual(4, overview["summary"]["fixture_records"])
        self.assertEqual(4, overview["summary"]["participant_records"])
        self.assertEqual(len(self.data["source_quality"]), overview["summary"]["non_fatal_limitations"])
        self.assertEqual("INCOMPLETE", overview["coverage"]["results"])
        self.assertEqual("unsupported", overview["capabilities"]["standings"])
        self.assertEqual("unknown", overview["freshness"]["last_observed_at"]["state"])

    def test_source_only_scores_unknown_and_zero_are_not_confused(self):
        response = self.get("fixtures").json()
        rows = response["fixtures"]
        self.assertEqual(4, len(rows))
        missing = next(r for r in rows if r["result_availability"] == "MISSING")
        self.assertEqual("unknown", missing["status"])
        self.assertEqual({"state": "unknown", "value": None}, missing["source_reported_score"]["ft"])
        self.assertTrue(any(0 in r["source_reported_score"]["ft"]["value"] for r in rows if r["source_reported_score"]["ft"]["value"]))
        ambiguous = next(r for r in rows if r["source_reported_score"]["p"]["value"] == [4, 4])
        self.assertFalse(ambiguous["score_semantics"]["ft_period_verified"])
        for row in rows:
            self.assertEqual({"state": "unsupported", "value": None}, row["canonical_regulation_score"])
            self.assertIsNone(row["kickoff_utc"]["value"])
            self.assertIsInstance(row["status_origin"], str)
            self.assertRegex(row["match_date"], r'^\d{4}-\d{2}-\d{2}$')
            self.assertFalse({"winner_id", "points", "standings", "home_score"} & set(row))
            self.assertEqual("git_commit", row["provenance"]["source_revision"]["kind"])

    def test_stable_pagination_including_past_end(self):
        whole = self.get("fixtures").json()["fixtures"]
        pages = [self.get("fixtures", {"limit": 1, "offset": i}).json() for i in range(4)]
        self.assertEqual(whole, [p["fixtures"][0] for p in pages])
        self.assertEqual([1, 2, 3, None], [p["pagination"]["next_offset"] for p in pages])
        self.assertEqual([], self.get("fixtures", {"offset": 9999}).json()["fixtures"])
        self.assertEqual(4, self.get("fixtures", {"offset": 9999}).json()["pagination"]["total"])
        self.assertEqual(self.get("fixtures").json(), self.get("fixtures").json())

    def test_filters_and_quality_reconcile(self):
        first = self.data["historical_fixtures"][0]
        filters = {"team_id": first["home_id"], "stage_id": first["stage_id"], "round_id": first["round_id"]}
        expected = {r["fixture_id"] for r in self.data["historical_fixtures"] if HistoricalService.matches(r, filters)}
        rows = self.get("fixtures", filters).json()["fixtures"]
        self.assertEqual(expected, {r["id"] for r in rows})
        quality = self.get("quality", filters).json()
        self.assertTrue(all(r["fixture_id"] in expected for r in quality["quality"]))
        self.assertEqual(quality["pagination"]["total"], sum(quality["diagnostic_counts"].values()))
        self.assertEqual(1, self.get("participants", {"team_id": first["home_id"]}).json()["pagination"]["total"])
        self.assertEqual(1, self.get("coverage", {"round_id": first["round_id"]}).json()["pagination"]["total"])
        self.assertEqual(0, self.get("fixtures", {"team_id": "uefa:participant:" + "0" * 64}).json()["pagination"]["total"])

    def test_all_queries_typed_readonly_bounded_and_not_user_sql(self):
        team = self.data["historical_fixtures"][0]["home_id"]
        self.get("fixtures", {"team_id": team})
        self.assertEqual(4, len(self.client.calls))
        for sql, parameters, settings in self.client.calls:
            self.assertEqual({"readonly": 1}, settings)
            self.assertTrue(sql.startswith("SELECT "))
            self.assertIn("{database:Identifier}", sql)
            self.assertIn("{batch_id:String}", sql)
            self.assertIn("LIMIT {row_limit:UInt32}", sql)
            self.assertIn("ORDER BY", sql)
            self.assertNotIn(team, sql)
            self.assertEqual(4097, parameters["row_limit"])
            self.assertNotIn("SELECT *", sql)

    def test_invalid_query_and_injection_rejected_before_connection(self):
        for query in ("?limit=0", "?limit=101", "?limit=-1", "?limit=x", "?offset=-1", "?offset=10001",
                      "?team_id=1%20OR%201=1", "?team_id=", "?round_id=uefa:stage:" + "a" * 64,
                      "?period=1", "?team_id=x&team_id=y", "?limit=1&limit=2"):
            with self.subTest(query=query):
                self.assertEqual(400, self.http.get(SEASON_PATH + "/fixtures" + query).status_code)
        self.open.assert_not_called()

    def test_filter_scope_is_explicit(self):
        for section, key in (("participants", "stage_id"), ("coverage", "team_id"), ("", "limit")):
            self.assertEqual(400, self.get(section, {key: "1"}).status_code)
        self.open.assert_not_called()

    def test_scope_methods_and_existing_health_are_preserved(self):
        for path, status in ((BASE + "/other/2024", 404), (BASE + "/uefa-champions-league/2026", 404),
                             (BASE + "/uefa-champions-league/not-a-year", 400), (SEASON_PATH + "/standings", 404)):
            self.assertEqual(status, self.http.get(path).status_code)
        self.assertEqual(405, self.http.post(SEASON_PATH).status_code)
        self.assertEqual({"status": "ok"}, self.http.get("/api/v1/health").json())
        self.open.assert_not_called()

    def test_missing_or_tampered_serving_data_is_503_not_partial_or_demo(self):
        original = deepcopy(self.data)
        for name in self.data:
            self.data[name] = []
            response = self.get()
            self.assertEqual(503, response.status_code)
            self.assertEqual("historical_not_ready", response.json()["error"]["code"])
            self.data[name] = original[name]
        self.data["historical_fixtures"][0]["regulation_home"] = 99
        self.assertEqual(503, self.get("fixtures").status_code)

    def test_duplicate_drift_and_size_bounds_are_fail_closed(self):
        rows = self.data["historical_fixtures"]
        rows.append(deepcopy(rows[0]))
        self.assertEqual(503, self.get().status_code)
        rows.pop()
        with patch("application.historical_repository.MAX_BUNDLE_BYTES", 1):
            self.assertEqual(503, self.get().status_code)
        with patch("application.historical.MAX_RESPONSE_BYTES", 1):
            self.assertEqual(503, self.get().status_code)

    def test_driver_failure_does_not_expose_sql_or_secret(self):
        with patch.object(self.client, "query", side_effect=OperationalError("SELECT password=PRIVATE_SENTINEL")):
            with self.assertLogs("football_api", level="WARNING") as logs:
                result = self.get()
        self.assertEqual(503, result.status_code)
        self.assertNotIn("PRIVATE_SENTINEL", result.content.decode() + "".join(logs.output))

    def test_serializer_preserves_unknown_and_source_pair_independently(self):
        row = self.data["historical_fixtures"][0]
        item = fixture(row, "f" * 64)
        self.assertEqual([row["source_ft_home"], row["source_ft_away"]] if row["source_ft_home"] is not None else None,
                         item["source_reported_score"]["ft"]["value"])
        self.assertEqual(self.data["historical_fixtures"][0], row)

    def test_partial_generation_changed_between_selects_is_not_exposed(self):
        original = self.client.query
        def changed(sql, **kwargs):
            result = original(sql, **kwargs)
            if len(self.client.calls) == 1:
                self.data["competition_participants"][0]["batch_id"] = "b" * 64
            return result
        with patch.object(self.client, "query", side_effect=changed):
            response = self.get("fixtures")
        self.assertEqual(503, response.status_code)
        self.assertNotIn("fixtures", response.json())

    def test_backend_changes_after_fingerprint_cannot_change_serialized_snapshot(self):
        original = deepcopy(self.data["historical_fixtures"])
        service = HistoricalService(self.repository)
        self.data["historical_fixtures"][0]["source_ft_home"] = 999
        actual = service.response("fixtures", {}, 100, 0)["fixtures"]
        expected = [fixture(row, self.repository.contract.semantic_fingerprint) for row in
                    sorted(original, key=lambda r: (r["match_date"], r["fixture_id"]))]
        # Date values in the source fixture become native JSON strings in the repository.
        from application.serialization import json_value
        self.assertEqual(json_value(expected), actual)
        self.assertEqual(4, len(self.client.calls))

    def test_timeout_is_safe_not_ready(self):
        with patch.object(self.client, "query", side_effect=TimeoutError("PRIVATE_SENTINEL")):
            response = self.get("fixtures")
        self.assertEqual(503, response.status_code)
        self.assertNotIn("PRIVATE_SENTINEL", response.content.decode())


class HistoricalConnectionTests(unittest.TestCase):
    def test_disabled_api_never_uses_production_or_synthetic_fallback(self):
        with patch.dict(os.environ, {"HISTORICAL_API_ENABLED": "false", "CLICKHOUSE_HOST": "football-clickhouse"}), \
             patch("application.historical_repository.clickhouse_connect.get_client") as client:
            response = Client(HTTP_HOST="localhost").get(SEASON_PATH)
        self.assertEqual(503, response.status_code)
        client.assert_not_called()

    def test_production_target_and_missing_configuration_are_denied(self):
        with patch.dict(os.environ, {"HISTORICAL_API_ENABLED": "true", "HISTORICAL_CLICKHOUSE_HOST": "football-clickhouse",
                                    "HISTORICAL_CLICKHOUSE_DATABASE": "football"}), \
             patch("application.historical_repository.clickhouse_connect.get_client") as sdk:
            with self.assertRaises(Exception) as error:
                create_historical_client()
        self.assertEqual(503, error.exception.status)
        sdk.assert_not_called()

    def test_dedicated_factory_and_client_lifecycle(self):
        client = Mock()
        with patch.dict(os.environ, {"HISTORICAL_API_ENABLED": "true", "HISTORICAL_CLICKHOUSE_HOST": "pet3-openfootball-ch-" + "a" * 12,
                "HISTORICAL_CLICKHOUSE_DATABASE": "pet3_openfootball_api_" + "b" * 12,
                "HISTORICAL_CLICKHOUSE_PASSWORD": "synthetic-only"}), \
             patch("application.historical_repository.clickhouse_connect.get_client", return_value=client) as sdk:
            with open_historical_repository():
                pass
        self.assertEqual("historical_reader", sdk.call_args.kwargs["username"])
        self.assertEqual(0, sdk.call_args.kwargs["query_retries"])
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
