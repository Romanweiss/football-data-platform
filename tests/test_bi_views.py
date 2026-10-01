"""Offline BI projection, join and read-only validation contracts."""

import re
import unittest
from bi_view_fixtures import CHECKS, MIGRATION, statements, view_selects


class BiViewTests(unittest.TestCase):
    def test_two_invoker_views_no_ddl_on_source_tables(self):
        ddl = statements(MIGRATION)
        self.assertEqual(len(ddl), 2)
        for name, sql in zip(("team", "player"), ddl):
            self.assertTrue(sql.startswith(f"CREATE VIEW IF NOT EXISTS football.bi_{name}_match_stats\nSQL SECURITY INVOKER"))
            self.assertIsNone(re.search(r"\b(DELETE|DROP|TRUNCATE|ALTER|MATERIALIZED|DEFINER)\b", sql))
            self.assertNotIn("SELECT *", sql)

    def test_grain_preserving_three_key_joins_and_required_fields(self):
        for alias, sql in zip(("t", "p"), view_selects()):
            for key in ("competition_id", "season_id", "match_id"):
                self.assertIn(f"{alias}.{key} = m.{key}", sql)
            for field in ("match_date", "kick_off", "competition_stage_id", "competition_stage_name",
                          "home_team_id", "home_team_name", "away_team_id", "away_team_name", "home_score", "away_score",
                          "team_id", "team_name", "is_home", "opponent_team_id", "opponent_team_name",
                          "event_count", "pass_attempts", "shot_count", "shot_xg", "shot_goals", "under_pressure_events", "counterpress_events"):
                self.assertIn(" AS " + field, sql)
            self.assertNotIn("GROUP BY", sql)
            self.assertNotIn("per90", sql)
        team, player = view_selects()
        self.assertIn("toInt32(goals_for) - toInt32(goals_against)", team)
        self.assertIn("if(is_home, m.home_score, m.away_score) AS goals_for", team)
        self.assertIn("if(is_home, m.away_score, m.home_score) AS goals_against", team)
        self.assertIn("'W', goals_for < goals_against, 'L', 'D') AS match_result", team)
        self.assertIn(" AS player_id", player)
        self.assertIn(" AS player_name", player)

    def test_validation_is_read_only_scoped_and_fails_closed(self):
        checks = statements(CHECKS)
        self.assertEqual(len(checks), 7)
        for sql in checks:
            self.assertIn("throwIf(", sql)
            self.assertIn("{competition_id:UInt32}", sql)
            self.assertIn("{season_id:UInt32}", sql)
            self.assertIsNone(re.search(r"\b(INSERT|CREATE|ALTER|DELETE|DROP|TRUNCATE)\b", sql))


if __name__ == "__main__":
    unittest.main()
