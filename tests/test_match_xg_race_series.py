"""Offline checks for the exact two-state projection of the existing wide race."""
import copy
import unittest

from match_visuals_fakes import fixture
from src.analytics import match_visuals as model
from src.analytics.validation import ClickHouseIntegrityError


def series_fixture():
    views, _, _, teams, _ = fixture()
    race = views["xg_race"]
    series = []
    for row in race:
        for side, flag in (("home", 1), ("away", 0)):
            series.append({**{f: row[f] for f in model.SERIES_EVENT_FIELDS},
                           "team_id": row[side + "_team_id"], "team_name": row[side + "_team_name"],
                           "is_home": flag, "cumulative_xg": row[side + "_cumulative_xg"]})
    for team in teams:
        team["team_name"] = "Home" if team["team_id"] == 10 else "Away"
    return series, race, teams


class XgRaceSeriesTests(unittest.TestCase):
    def check(self, data):
        return model.validate_race_series(*data, expected_rows=2 * len(data[1]))

    def test_both_teams_at_every_event_with_opponent_plateaus(self):
        series, race, teams = series_fixture()
        self.assertEqual(self.check((series, race, teams))["xg_race_series"], 8)
        self.assertEqual((series[0]["team_id"], series[1]["team_id"]), (10, 20))
        self.assertEqual(race[0]["team_id"], 20)  # The away team shot; home state still emitted.
        self.assertEqual((series[0]["cumulative_xg"], series[1]["cumulative_xg"]), (0, 0.1))

    def test_missing_duplicate_or_wrong_side_fails(self):
        for mutation in ("missing", "duplicate", "flag", "shooter"):
            data = series_fixture()
            if mutation == "missing": data[0].pop()
            if mutation == "duplicate": data[0][-1] = copy.deepcopy(data[0][0])
            if mutation == "flag": data[0][0]["is_home"] = 0
            if mutation == "shooter": data[0][0]["team_id"] = data[1][0]["team_id"]
            with self.subTest(mutation=mutation), self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_exact_projection_all_fields_including_float(self):
        for field in model.SERIES_FIELDS:
            data = series_fixture()
            value = data[0][0][field]
            data[0][0][field] = value + 1e-12 if field == "cumulative_xg" else value + 1 if isinstance(value, int) else "wrong"
            with self.subTest(field=field), self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_final_reconciliation_tolerance_missing_team_and_duplicate_order(self):
        data = series_fixture()
        data[2][0]["shot_xg"] += 1e-12
        self.check(data)
        data[2][0]["shot_xg"] += 0.1
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)
        data = series_fixture()
        data[2].pop()
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)
        data = series_fixture()
        data[1][1]["event_order"] = data[1][0]["event_order"]
        with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_full_context_separates_identical_event_ids(self):
        series, race, teams = series_fixture()
        copies = copy.deepcopy((series, race, teams))
        for rows in copies:
            for row in rows: row["season_id"] = 107
        self.check((series + copies[0], race + copies[1], teams + copies[2]))

    def test_zero_state_for_team_without_shots_is_preserved(self):
        series, race, teams = series_fixture()
        # Every event belongs to away, but home state remains present and zero.
        for row in race:
            row.update(team_id=20, home_cumulative_xg=0.0)
        for row in series:
            if row["is_home"]: row["cumulative_xg"] = 0.0
        for team in teams:
            if team["team_id"] == 10: team["shot_xg"] = 0.0
        self.check((series, race, teams))

    def test_nonfinite_and_non_normal_source_rejected(self):
        for mutation in ("nan", "period"):
            data = series_fixture()
            if mutation == "nan": data[1][0]["home_cumulative_xg"] = float("nan")
            else: data[1][0]["period"] = 5
            with self.assertRaises(ClickHouseIntegrityError): self.check(data)

    def test_migration_only_projects_home_away_without_windows(self):
        sql = model.SERIES_MIGRATION.read_text()
        self.assertIn("CREATE VIEW IF NOT EXISTS football.bi_match_xg_race_series\nSQL SECURITY INVOKER", sql)
        self.assertEqual(sql.count("FROM football.bi_match_xg_race"), 2)
        self.assertEqual(sql.count("UNION ALL"), 1)
        self.assertNotRegex(sql, r"\b(REPLACE|ALTER|DROP|DELETE|TRUNCATE|OVER|GROUP BY|JOIN)\b")
        for side in ("home", "away"):
            self.assertIn(side + "_team_id AS team_id", sql)
            self.assertIn(side + "_team_name AS team_name", sql)
            self.assertIn(side + "_cumulative_xg AS cumulative_xg", sql)
        self.assertNotIn("team_cumulative_xg", sql)
        self.assertTrue(model.series_select().startswith("SELECT"))


if __name__ == "__main__": unittest.main()
