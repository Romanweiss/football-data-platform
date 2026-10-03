"""Offline tests: no server, network, ClickHouse, PostgreSQL or S3 required."""
import os
import unittest
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from clickhouse_connect.driver.exceptions import OperationalError
from application.errors import ApiError, ServingIntegrityError
from application.repository import FootballRepository, PROJECTIONS, open_repository
from application.serialization import json_value, serialize_row
from application.services import FootballService


class SerializationTests(unittest.TestCase):
    def test_native_types_nulls_dates_and_uuid(self):
        row = {"match_id": 2**63, "shot_xg": 2.758305926, "is_home": 1,
               "is_goal": False, "went_to_penalties": 0, "player_name": None,
               "match_date": date(2022, 12, 18), "event_id": UUID(int=1)}
        result = serialize_row(row)
        self.assertIs(type(result["match_id"]), int)
        self.assertIs(type(result["shot_xg"]), float)
        self.assertIs(result["is_home"], True)
        self.assertIs(result["went_to_penalties"], False)
        self.assertIsNone(result["player_name"])
        self.assertEqual(result["match_date"], "2022-12-18")
        self.assertEqual(result["event_id"], str(UUID(int=1)))
        self.assertIs(type(row["is_home"]), int)

    def test_no_nonfinite_or_silent_stringification(self):
        for value in (float("nan"), float("inf"), object()):
            with self.assertRaises((ValueError, TypeError)): json_value(value)
        with self.assertRaises(ValueError): serialize_row({"is_home": 2})


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.query.return_value = SimpleNamespace(column_names=["team_id"], result_rows=[(779,)])
        self.repo = FootballRepository(self.client)

    def test_only_parameterized_readonly_allowlisted_queries(self):
        self.repo.matches({"competition_id": 7, "season_id": 9})
        self.repo.match(123, {"competition_id": 7, "season_id": 9})
        for name in PROJECTIONS: self.repo.section(name, 123, context={"competition_id": 7, "season_id": 9})
        self.repo.section("players", 123, 779, context={"competition_id": 7, "season_id": 9})
        for call in self.client.query.call_args_list:
            sql = call.args[0]
            self.assertTrue(sql.startswith("SELECT "))
            self.assertNotIn("123", sql)
            self.assertNotIn("779", sql)
            self.assertNotIn("SELECT *", sql)
            self.assertEqual(call.kwargs["settings"]["readonly"], 1)
            self.assertEqual(call.kwargs["parameters"]["competition_id"], 7)
            self.assertEqual(call.kwargs["parameters"]["season_id"], 9)
            for forbidden in ("gold_build_id", "loaded_at", "INSERT", "ALTER", "CREATE", "DROP", "JOIN", "SUM("):
                self.assertNotIn(forbidden, sql)
        self.assertIn("team_id = {team_id:UInt32}", self.client.query.call_args.args[0])

    def test_ordering_and_view_sources(self):
        for name, (table, fields, order) in PROJECTIONS.items():
            self.repo.section(name, 123, context={"competition_id": 7, "season_id": 9})
            sql = self.client.query.call_args.args[0]
            self.assertIn("FROM " + table, sql)
            self.assertIn("ORDER BY " + order, sql)

    def test_driver_failure_is_safe_503(self):
        self.client.query.side_effect = OperationalError("password=SECRET SELECT internal")
        with self.assertRaises(ApiError) as caught: self.repo.matches({"competition_id": 7, "season_id": 9})
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn("SECRET", str(caught.exception))

    def test_duplicate_match_and_result_overflow_fail_closed(self):
        self.client.query.return_value.result_rows = [(1,), (1,)]
        with self.assertRaises(ServingIntegrityError): self.repo.match(1, {"competition_id": 7, "season_id": 9})
        self.client.query.return_value.result_rows = [(1,)] * 10001
        with self.assertRaises(ServingIntegrityError): self.repo.matches({"competition_id": 7, "season_id": 9})

    def test_client_lifecycle_and_failed_creation(self):
        with patch("application.repository.create_clickhouse_client", return_value=self.client) as create:
            with open_repository() as repo:
                repo.matches({"competition_id": 7, "season_id": 9})
                repo.matches({"competition_id": 7, "season_id": 9})
            create.assert_called_once()
            self.client.close.assert_called_once()
        with patch("application.repository.create_clickhouse_client", side_effect=ValueError("secret")):
            with self.assertRaises(ApiError):
                with open_repository(): pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.repo.match.return_value = {"competition_id": 7, "season_id": 9, "match_id": 1, "went_to_penalties": True}
        self.repo.section.side_effect = lambda name, *args, **kwargs: [{"id": 1}, {"id": 2}] if name == "teams" else [{"shootout_order": 1}] if name == "shootout" else []
        self.service = FootballService(self.repo)

    def test_composite_exactly_six_data_queries(self):
        result = self.service.analysis(1)
        self.assertEqual(set(result), {"match", "teams", "players", "shots", "xg_race", "shootout"})
        self.repo.match.assert_called_once_with(1)
        self.assertEqual(self.repo.section.call_count, 5)
        self.assertEqual(result["shootout"], {"match_id": 1, "went_to_penalties": True, "attempts": [{"shootout_order": 1}]})

    def test_no_shootout_and_missing_match(self):
        self.repo.match.return_value["went_to_penalties"] = False
        self.repo.section.side_effect = lambda *args, **kwargs: []
        self.assertEqual(self.service.section("shootout", 1), {"match_id": 1, "went_to_penalties": False, "attempts": []})
        self.repo.match.return_value = None
        with self.assertRaises(ApiError) as caught: self.service.analysis(99)
        self.assertEqual(caught.exception.code, "match_not_found")
        self.assertEqual(caught.exception.status, 404)

    def test_shootout_coverage_must_agree_with_overview(self):
        self.repo.section.side_effect = lambda *args, **kwargs: []
        with self.assertRaises(ServingIntegrityError): self.service.section("shootout", 1)

    def test_non_two_teams_is_not_silently_accepted(self):
        self.repo.section.side_effect = None
        self.repo.section.return_value = []
        with self.assertRaises(ServingIntegrityError): self.service.section("teams", 1)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.http = Client(HTTP_HOST="localhost", raise_request_exception=False)
        self.repo = Mock()
        self.repo.match.return_value = {"competition_id": 7, "season_id": 9, "match_id": 1, "went_to_penalties": False}
        self.repo.section.side_effect = lambda name, *args, **kwargs: [{"team_id": 1}, {"team_id": 2}] if name == "teams" else []
        self.repo.matches.return_value = [self.repo.match.return_value]

        @contextmanager
        def opened(): yield self.repo
        self.open = patch("application.views.open_repository", side_effect=opened).start()
        self.addCleanup(patch.stopall)

    def test_health_independent_of_clickhouse_and_no_admin(self):
        self.assertEqual(self.http.get("/api/v1/health").json(), {"status": "ok"})
        self.open.assert_not_called()
        result = self.http.get("/admin/")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()["error"]["code"], "not_found")

    def test_invalid_parameters_rejected_before_connection(self):
        paths = ["/matches/abc", "/matches/-1", "/matches/0", "/matches/18446744073709551616",
                 "/matches/1/players?team_id=1%20OR%201=1", "/matches/1/players?team_id=",
                 "/matches/1/players?team_id=4294967296", "/matches/1/players?team_id=1&team_id=2",
                 "/matches/1/teams?team_id=1", "/matches/1?unknown=1"]
        for path in paths:
            with self.subTest(path=path):
                result = self.http.get("/api/v1" + path)
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()["error"]["code"], "invalid_request")
        self.open.assert_not_called()

    def test_team_filter_and_zero_activity_are_preserved(self):
        row = {"team_id": 779, "player_id": 1, "event_count": 0, "shot_xg": 0.0, "player_name": None}
        self.repo.section.side_effect = None
        self.repo.section.return_value = [row]
        result = self.http.get("/api/v1/matches/1/players?team_id=779")
        self.assertEqual(result.json()["players"], [row])
        self.repo.section.assert_called_once_with("players", 1, 779, context={"competition_id": 7, "season_id": 9})

    def test_detail_lists_composite_and_shootout(self):
        self.assertEqual(self.http.get("/api/v1/matches/1").json(), self.repo.match.return_value)
        self.assertEqual(len(self.http.get("/api/v1/competitions/43/seasons/106/matches").json()["matches"]), 1)
        self.assertEqual(self.http.get("/api/v1/matches/1/shootout").json(), {"match_id": 1, "went_to_penalties": False, "attempts": []})
        result = self.http.get("/api/v1/matches/1/analysis").json()
        self.assertEqual(set(result), {"match", "teams", "players", "shots", "xg_race", "shootout"})

    def test_errors_and_logs_never_include_raw_exception(self):
        for exc, status, code in ((RuntimeError("password=SECRET SELECT internal"), 500, "server_error"),
                                  (ApiError("clickhouse_unavailable", "ClickHouse is unavailable", 503), 503, "clickhouse_unavailable")):
            self.repo.match.side_effect = exc
            with self.assertLogs("football_api", level="WARNING") as logs:
                result = self.http.get("/api/v1/matches/1")
            self.assertEqual(result.status_code, status)
            self.assertEqual(result.json()["error"]["code"], code)
            self.assertNotIn("SECRET", result.content.decode() + str(logs.output))
            self.assertNotIn("SELECT", result.content.decode() + str(logs.output))

    def test_unknown_match_all_child_endpoints_are_404(self):
        self.repo.match.return_value = None
        for suffix in ("", "/teams", "/players", "/shots", "/xg-race", "/shootout", "/analysis"):
            result = self.http.get("/api/v1/matches/999" + suffix)
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.json()["error"]["code"], "match_not_found")
        self.repo.section.assert_not_called()

    def test_post_unknown_context_and_bad_host(self):
        result = self.http.post("/api/v1/matches/1")
        self.assertEqual(result.status_code, 405)
        self.assertEqual(result.headers["Allow"], "GET")
        self.assertEqual(self.http.get("/api/v1/health", HTTP_HOST="attacker.invalid").status_code, 400)
        self.open.assert_not_called()

    def test_excessive_query_fields_use_json_400(self):
        query = "&".join(f"p{i}=1" for i in range(1001))
        result = self.http.get("/api/v1/health?" + query)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.json()["error"]["code"], "invalid_request")
        self.open.assert_not_called()


if __name__ == "__main__": unittest.main()
