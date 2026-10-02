"""Offline Stage 4E contracts and deliberately corrupted visual results."""
import copy
import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from match_visuals_fakes import fixture
from src.analytics import match_visuals as model
from src.analytics.validation import ClickHouseIntegrityError
from scripts import check_clickhouse_match_visuals as cli


class MatchVisualTests(unittest.TestCase):
    def check(self, data):
        views, shots, overview, teams, expected = data
        return model.validate_visuals(views, shots, overview, teams, expected=expected)

    def test_tied_second_order_both_teams_extra_time_and_cumulative(self):
        data = fixture()
        self.assertEqual(self.check(data)["extra_time_shots"], 2)
        race = data[0]["xg_race"]
        self.assertEqual([r["event_index"] for r in race[:2]], [10, 20])
        self.assertEqual([r["home_cumulative_xg"] for r in race[:2]], [0, 0.1])
        self.assertEqual([r["away_cumulative_xg"] for r in race[:2]], [0.1, 0.1])

    def test_every_running_value_not_only_final_is_checked(self):
        for name in ("team_cumulative_xg", "home_cumulative_xg", "away_cumulative_xg", "event_order", "event_time_seconds"):
            data = fixture()
            data[0]["xg_race"][0][name] += 1
            with self.subTest(field=name), self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_final_xg_reconciles_and_float_tolerance_is_bounded(self):
        data = fixture()
        data[3][0]["shot_xg"] += 1e-12
        self.check(data)
        data[3][0]["shot_xg"] += 0.1
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_team_without_shots_is_not_synthesized(self):
        data = fixture()
        views, shots, overview, teams, expected = data
        remove = next(r for r in shots if r["match_id"] == 1 and r["team_id"] == 10)
        shots.remove(remove)
        for name in ("xg_race", "shot_map"):
            views[name][:] = [r for r in views[name] if r["event_id"] != remove["event_id"]]
        next(r for r in teams if r["match_id"] == 1 and r["team_id"] == 10)["shot_xg"] = 0
        expected.update(normal=3, normal_xg=0.3)
        self.check(data)

    def test_penalty_order_attempts_and_every_running_score(self):
        data = fixture()
        self.assertEqual([r["shootout_order"] for r in data[0]["shootout"]], [1, 2, 3, 4])
        self.assertEqual([r["team_attempt_number"] for r in data[0]["shootout"]], [1, 1, 2, 2])
        self.assertEqual([(r["home_shootout_goals_after"], r["away_shootout_goals_after"]) for r in data[0]["shootout"]], [(0, 1), (1, 1), (1, 1), (2, 1)])
        for field in ("shootout_order", "team_attempt_number", "home_shootout_goals_after", "away_shootout_goals_after"):
            bad = fixture()
            bad[0]["shootout"][1][field] += 1
            with self.subTest(field=field), self.assertRaises(ClickHouseIntegrityError): self.check(bad)

    def test_authoritative_final_score_and_home_away_ids(self):
        for mutation in ("score", "context"):
            data = fixture()
            if mutation == "score": data[2][-1]["away_shootout_goals"] += 1
            else: data[0]["shootout"][0]["home_team_id"] = 999
            with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_goal_ids_not_names_and_outcomes_preserved(self):
        data = fixture()
        self.check(data)  # Fixture names deliberately contradict goal semantics.
        for name in ("shot_map", "shootout"):
            bad = fixture()
            bad[0][name][0]["is_goal"] = not bad[0][name][0]["is_goal"]
            with self.assertRaises(ClickHouseIntegrityError): self.check(bad)
        data[0]["shootout"][0]["outcome_name"] = "wrong"
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_period_exclusion_extra_time_and_exact_source_keys(self):
        for name in model.VIEWS:
            for mutation in ("missing", "duplicate", "context", "xg", "player_null"):
                data = fixture()
                rows = data[0][name]
                if mutation == "missing": rows.pop()
                if mutation == "duplicate": rows.append(copy.deepcopy(rows[0]))
                if mutation == "context": rows[0]["season_id"] = 999
                if mutation == "xg": rows[0]["statsbomb_xg"] += 1e-12
                if mutation == "player_null": rows[0]["player_id"] = 0
                with self.subTest(view=name, mutation=mutation), self.assertRaises(ClickHouseIntegrityError): self.check(data)
        data = fixture()
        data[0]["shot_map"][0]["period"] = 5
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_coordinate_nulls_preserved_and_bounds_not_goal_height(self):
        model.validate_coordinates({"start_x": None, "start_y": None, "end_x": 120, "end_y": 80, "end_z": 7.6})
        for field in model.COORDINATES:
            for value in (-0.1, model.COORDINATE_MAX[field] + 0.1, float("nan"), float("inf")):
                row = dict.fromkeys(model.COORDINATES)
                row[field] = value
                with self.assertRaises(ClickHouseIntegrityError): model.validate_coordinates(row)
        data = fixture()
        data[0]["shot_map"][0]["end_z"] = 0
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_duplicate_event_index_cannot_have_ambiguous_window_order(self):
        data = fixture()
        data[1][0]["event_index"] = data[1][1]["event_index"]
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_full_context_keys_isolate_repeated_match_and_event_ids(self):
        rows = [dict(competition_id=43, season_id=season, match_id=1, event_id="same", event_index=1) for season in (106, 107)]
        self.assertEqual(len(model.rows_by_key(rows, model.SHOT_KEY)), 2)
        self.assertEqual(len(model.rows_by_key(rows, (*model.MATCH_KEY, "event_index"))), 2)

    def test_sql_additive_filters_full_keys_and_rows_windows(self):
        sql = model.MIGRATION.read_text()
        bodies = model.view_selects()
        self.assertEqual(sql.count("SQL SECURITY INVOKER"), 3)
        self.assertNotRegex(sql, r"\b(REPLACE|DELETE|DROP|TRUNCATE|ALTER|MATERIALIZED|DEFINER)\b")
        self.assertNotRegex(sql, r"football\.(team_match_stats|player_match_stats)\b")
        self.assertNotIn("UNION", sql)
        self.assertNotIn("SELECT *", sql)
        for name in model.VIEWS:
            self.assertIn("FROM football.bi_match_shots AS s", bodies[name])
            self.assertIn("WHERE s.is_shootout = " + ("1" if name == "shootout" else "0"), bodies[name])
        for name in ("xg_race", "shootout"):
            for key in model.MATCH_KEY:
                self.assertIn(f"s.{key} = o.{key}", bodies[name])
            self.assertIn("ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW", bodies[name])
            self.assertIn("PARTITION BY s.competition_id, s.season_id, s.match_id", bodies[name])
        self.assertEqual(bodies["xg_race"].count("ORDER BY s.period, s.minute, s.second, s.event_index"), 3)
        self.assertIn("ORDER BY s.event_index", bodies["shootout"])
        for field in model.COORDINATES:
            self.assertIn(f"s.{field} AS {field}", bodies["shot_map"])

    def test_cli_runs_regressions_first_and_never_prints_raw_exception(self):
        with patch.object(cli, "check_stage4d", return_value=1), patch.object(cli, "create_clickhouse_client") as connect:
            self.assertEqual(cli.main([]), 1)
            connect.assert_not_called()
        with patch.object(cli, "check_stage4d", return_value=0), \
                patch.object(cli, "create_clickhouse_client", side_effect=RuntimeError("synthetic-secret")), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(cli.main(["--candidate"]), 1)
        self.assertNotIn("synthetic-secret", output.getvalue())
        self.assertIn("exception=RuntimeError", output.getvalue())


if __name__ == "__main__": unittest.main()
