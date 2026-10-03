"""Synthetic multi-context serving tests; no WC2022 constants or network."""
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from application.repository import FootballRepository
from application.services import FootballService
from application.errors import ApiError


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.repo = FootballRepository(self.client)
        self.context = {"competition_id": 7, "season_id": 9}

    def rows(self, columns, rows):
        self.client.query.return_value = SimpleNamespace(column_names=columns, result_rows=rows)

    def test_catalog_projects_only_stored_ids_and_orders_deterministically(self):
        self.rows(["competition_id"], [(7,), (80,)])
        self.assertEqual(self.repo.competitions(), [{"competition_id": 7}, {"competition_id": 80}])
        self.assertIn("SELECT DISTINCT competition_id", self.client.query.call_args.args[0])
        self.assertIn("ORDER BY competition_id", self.client.query.call_args.args[0])
        self.rows(["season_id"], [(9,), (10,)])
        self.assertEqual(self.repo.seasons(7), [{"season_id": 9}, {"season_id": 10}])
        self.assertEqual(self.client.query.call_args.kwargs["parameters"], {"competition_id": 7})
        self.assertEqual(self.client.query.call_args.kwargs["settings"], {"readonly": 1})

    def test_same_match_id_isolated_by_context_for_every_section(self):
        for context in (self.context, {"competition_id": 80, "season_id": 10}):
            self.rows(["competition_id", "season_id", "match_id", "went_to_penalties"],
                      [(context["competition_id"], context["season_id"], 1, 0)])
            self.assertEqual(self.repo.match(1, context)["competition_id"], context["competition_id"])
            for name in ("teams", "players", "shots", "xg_race", "shootout"):
                self.repo.section(name, 1, context=context)
                call = self.client.query.call_args
                self.assertEqual(call.kwargs["parameters"], {**context, "match_id": 1})
                for field in ("competition_id", "season_id", "match_id"):
                    self.assertIn(field + " = {" + field, call.args[0])

    def test_legacy_ambiguous_id_fails_closed(self):
        self.rows(["competition_id", "season_id", "match_id"], [(7, 9, 1), (80, 10, 1)])
        with self.assertRaises(ApiError) as caught:
            self.repo.match(1)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "ambiguous_match"))

    def test_unknown_competition_and_season_are_distinct(self):
        for rows, code in (([], "competition_not_found"), ([(10,)], "season_not_found")):
            self.rows(["season_id"], rows)
            with self.assertRaises(ApiError) as caught:
                self.repo.require_context(self.context)
            self.assertEqual(caught.exception.code, code)

    def test_unknown_match_in_existing_context(self):
        self.client.query.side_effect = [
            SimpleNamespace(column_names=["match_id"], result_rows=[]),
            SimpleNamespace(column_names=["season_id"], result_rows=[(9,)]),
        ]
        with self.assertRaises(ApiError) as caught:
            FootballService(self.repo).match(999, self.context)
        self.assertEqual(caught.exception.code, "match_not_found")

    def test_http_canonical_routes_and_alias_share_service_and_response(self):
        repo = Mock()
        repo.match.return_value = {**self.context, "match_id": 1, "went_to_penalties": False}
        repo.matches.return_value = [repo.match.return_value]
        repo.competitions.return_value = [{"competition_id": 7}]
        repo.seasons.return_value = [{"season_id": 9}]
        repo.section.side_effect = lambda name, *a, **kw: [{"team_id": 1}, {"team_id": 2}] if name == "teams" else []
        @contextmanager
        def opened(): yield repo
        http = Client(HTTP_HOST="localhost")
        prefix = "/api/v1/competitions/7/seasons/9/matches"
        with patch("application.views.open_repository", side_effect=opened):
            self.assertEqual(http.get("/api/v1/competitions").json(), {"competitions": [{"competition_id": 7}]})
            self.assertEqual(http.get("/api/v1/competitions/7/seasons").json(), {"seasons": [{"season_id": 9}]})
            self.assertEqual(http.get(prefix).json(), {"matches": [repo.match.return_value]})
            for suffix in ("", "/teams", "/players", "/shots", "/xg-race", "/shootout", "/analysis"):
                canonical = http.get(prefix + "/1" + suffix)
                self.assertEqual(canonical.status_code, 200)
                self.assertEqual(canonical.json(), http.get("/api/v1/matches/1" + suffix).json())
            for call in repo.section.call_args_list:
                self.assertEqual(call.kwargs["context"], self.context)
            for path in ("/api/v1/competitions/0/seasons", "/api/v1/competitions/7/seasons/no/matches",
                         prefix + "/bad", "/api/v1/competitions/4294967296/seasons"):
                self.assertEqual(http.get(path).status_code, 400)
            repo.seasons.return_value = []
            self.assertEqual(http.get("/api/v1/competitions/999/seasons").json()["error"]["code"], "competition_not_found")
            repo.match.side_effect = ApiError("ambiguous_match", "Use canonical URL", 409)
            self.assertEqual(http.get("/api/v1/matches/1").status_code, 409)
