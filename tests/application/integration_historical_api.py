"""Explicit real-Gold test entrypoint, dedicated internal-network fixture server only."""
import json
import os
from pathlib import Path
import sys
import statistics
import time
import tracemalloc
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from application.historical import BASE, SEASON_PATH
from application.historical_repository import open_historical_repository
from application.repository import FootballRepository
from clickhouse_connect.driver.httpclient import HttpClient

EVIDENCE = {}


class HistoricalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.http = Client(HTTP_HOST="localhost", raise_request_exception=False)

    def get(self, section="", parameters=None):
        response = self.http.get(SEASON_PATH + ("/" + section if section else ""), parameters or {})
        self.assertEqual(200, response.status_code, response.content.decode()[:200])
        self.assertEqual("no-store", response["Cache-Control"])
        return response.json()

    def pages(self, section, filters=None):
        rows, offset = [], 0
        while True:
            response = self.get(section, {**(filters or {}), "offset": offset, "limit": 100})
            rows.extend(response[section])
            offset = response["pagination"]["next_offset"]
            if offset is None:
                self.assertEqual(len(rows), response["pagination"]["total"])
                return rows

    def test_all_routes_counts_and_no_foreign_contexts(self):
        index = self.http.get(BASE)
        self.assertEqual(200, index.status_code)
        overview = self.get()
        self.assertEqual(index.json()["competitions"], [overview])
        self.assertEqual({"fixture_records": 189, "participant_records": 36, "source_stages": 3,
            "coverage_records": 14, "non_fatal_limitations": 394, "source_reported_ft": 188,
            "unknown_results": 1, "ambiguous_components": 2}, overview["summary"])
        self.assertEqual(36, len(self.pages("participants")))
        coverage = self.pages("coverage")
        self.assertEqual(14, len(coverage))
        self.assertEqual(189, sum(r["fixture_count"] for r in coverage))
        quality = self.pages("quality")
        self.assertEqual(394, len(quality))
        self.assertTrue(all(r["severity"] == "NON_FATAL" for r in quality))
        EVIDENCE["summary"] = overview["summary"]
        EVIDENCE["provenance"] = overview["provenance"]

    def test_fixture_semantics_unknown_final_ambiguous_components_and_order(self):
        rows = self.pages("fixtures")
        self.assertEqual(189, len({r["id"] for r in rows}))
        self.assertEqual(rows, sorted(rows, key=lambda r: (r["match_date"], r["id"])))
        unknown = [r for r in rows if r["result_availability"] == "MISSING"]
        self.assertEqual(1, len(unknown))
        self.assertEqual("2025-05-31", unknown[0]["match_date"])
        self.assertEqual("unknown", unknown[0]["status"])
        self.assertIsNone(unknown[0]["source_reported_score"]["ft"]["value"])
        self.assertEqual(2, sum(r["score_semantics"]["quality"] == "AMBIGUOUS_SOURCE_COMPONENTS" for r in rows))
        self.assertTrue(all(r["canonical_regulation_score"] == {"state": "unsupported", "value": None} and
                            r["kickoff_utc"]["value"] is None and not r["score_semantics"]["ft_period_verified"] for r in rows))
        self.assertTrue(all(not ({"winner_id", "points", "standings"} & set(r)) for r in rows))
        EVIDENCE["unknown_fixture_example"] = unknown[0]

    def test_filters_pagination_and_quality_membership(self):
        rows = self.pages("fixtures")
        first = rows[0]
        filters = {"team_id": first["home"]["id"], "stage_id": first["stage"]["id"], "round_id": first["round"]["id"]}
        expected = {r["id"] for r in rows if filters["team_id"] in (r["home"]["id"], r["away"]["id"]) and
                    r["stage"]["id"] == filters["stage_id"] and r["round"]["id"] == filters["round_id"]}
        self.assertEqual(expected, {r["id"] for r in self.pages("fixtures", filters)})
        self.assertTrue(all(r["fixture_id"] in expected for r in self.pages("quality", filters)))
        first_page = self.get("fixtures", {"limit": 10, "offset": 0})
        self.assertEqual(first_page, self.get("fixtures", {"limit": 10, "offset": 0}))
        self.assertEqual([], self.get("fixtures", {"offset": 9999})["fixtures"])

    def test_errors_and_existing_health(self):
        for path, code in ((SEASON_PATH + "/fixtures?team_id=1%20OR%201=1", 400),
                           (SEASON_PATH + "/fixtures?limit=101", 400), (BASE + "/uefa-champions-league/2026", 404),
                           (SEASON_PATH + "/standings", 404)):
            self.assertEqual(code, self.http.get(path).status_code)
        self.assertEqual({"status": "ok"}, self.http.get("/api/v1/health").json())

    def test_absent_dataset_is_not_ready_not_demo(self):
        with patch.dict(os.environ, {"HISTORICAL_CLICKHOUSE_DATABASE": "pet3_openfootball_api_" + "f" * 12}):
            response = self.http.get(SEASON_PATH)
        self.assertEqual(503, response.status_code)
        self.assertEqual("historical_not_ready", response.json()["error"]["code"])
        self.assertNotIn("competitions", response.json())

    def test_reader_profile_really_enforces_readonly(self):
        with open_historical_repository() as repository:
            result = repository.reader.client.query("SELECT value FROM system.settings WHERE name = 'readonly'",
                                                    settings={"readonly": 1})
        self.assertEqual("1", str(result.first_row[0]))

    def test_performance_four_data_selects_not_per_fixture_and_bounded_allocations(self):
        raw_request, data_query = HttpClient._raw_request, FootballRepository._query
        counters = {"http": 0, "data": 0}
        def measured_raw(client, *args, **kwargs):
            counters["http"] += 1  # Never inspect/capture SQL, parameters or auth headers.
            return raw_request(client, *args, **kwargs)
        def measured_data(repository, *args, **kwargs):
            counters["data"] += 1
            return data_query(repository, *args, **kwargs)
        samples = []
        with patch.object(HttpClient, "_raw_request", measured_raw), patch.object(FootballRepository, "_query", measured_data):
            for _ in range(5):
                counters.update(http=0, data=0)
                started = time.perf_counter()
                response = self.http.get(SEASON_PATH + "/fixtures?limit=100")
                elapsed = time.perf_counter() - started
                self.assertEqual(200, response.status_code)
                self.assertEqual(4, counters["data"])
                samples.append({"ms": round(elapsed * 1000, 3), "response_bytes": len(response.content),
                                "data_selects": counters["data"], "sdk_http_requests": counters["http"]})
            counters.update(http=0, data=0)
            self.get("fixtures", {"limit": 1, "offset": 9999})
            self.assertEqual(4, counters["data"])  # Same work for empty pages; no per-row N+1.
        tracemalloc.start()
        try:
            self.get("fixtures", {"limit": 100})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        with open_historical_repository() as repository:
            plan = repository.reader.client.query(
                "EXPLAIN indexes=1 SELECT fixture_id FROM {database:Identifier}.historical_fixtures "
                "WHERE batch_id={batch_id:String} AND source_sha256={source_sha256:String} ORDER BY fixture_id LIMIT 4097",
                parameters={"database": repository.database, "batch_id": repository.contract.batch_id,
                            "source_sha256": repository.contract.source_sha256}, settings={"readonly": 1})
            plan_summary = [str(r[0]).strip() for r in plan.result_rows if
                            any(word in str(r[0]) for word in ("ReadFromMergeTree", "PrimaryKey", "Parts:", "Granules:"))]
        EVIDENCE["performance"] = {"samples": samples, "median_ms": statistics.median(s["ms"] for s in samples),
            "max_ms": max(s["ms"] for s in samples), "traced_peak_bytes_separate_probe": peak,
            "explain_summary": plan_summary,
            "limitations": "local warm process; fresh SDK client per request; no concurrency/RSS guarantee"}


if __name__ == "__main__":
    if os.environ.get("PET3B_INTEGRATION_ENABLED") != "true":
        raise SystemExit("PET3B_EXPLICIT_INTEGRATION_REQUIRED")
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(HistoricalIntegrationTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("HISTORICAL_API_EVIDENCE=" + json.dumps(EVIDENCE, sort_keys=True))
