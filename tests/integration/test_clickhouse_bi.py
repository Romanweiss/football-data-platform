"""SELECT-only BI tests: synthetic CTEs, no CREATE/INSERT, S3 or migration apply."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from bi_view_fixtures import CHECKS, statements, synthetic_ctes
from src.common.clickhouse import create_clickhouse_client


class BiClickHouseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def query(self, suffix, **options):
        ctes, substitute = synthetic_ctes(**options)
        sql = ctes + substitute(suffix)
        self.assertNotIn("football.", sql)
        return self.client.query(sql, parameters={"competition_id": 43, "season_id": 106}, settings={"readonly": 1}).result_rows

    def test_all_seven_validation_queries_pass(self):
        for sql in statements(CHECKS):
            with self.subTest(query=sql[:60]):
                self.query(sql)

    def test_official_score_opponents_signed_difference_and_results(self):
        rows = self.query("SELECT match_id, team_id, is_home, opponent_team_id, goals_for, goals_against, goal_difference, match_result FROM test_team_view ORDER BY match_id, team_id")
        self.assertEqual(rows, [(1, 10, 1, 20, 2, 1, 1, "W"), (1, 20, 0, 10, 1, 2, -1, "L"),
                                (2, 10, 1, 20, 0, 0, 0, "D"), (2, 20, 0, 10, 0, 0, 0, "D"),
                                (3, 10, 1, 20, 1, 3, -2, "L"), (3, 20, 0, 10, 3, 1, 2, "W")])
        self.assertEqual(self.query("SELECT uniqExact(player_id), count() FROM test_player_view"), [(2, 6)])
        self.assertEqual(self.query("SELECT min(shot_xg), max(shot_xg) FROM test_team_view"), [(0.1, 0.1)])

    def test_duplicate_join_and_player_grain_are_detected(self):
        checks = statements(CHECKS)
        for index, options in ((0, {"duplicate_matches": True}), (1, {"duplicate_matches": True}),
                               (2, {"duplicate_matches": True}), (3, {"duplicate_players": True})):
            with self.subTest(index=index), self.assertRaises(Exception):
                self.query(checks[index], **options)

    def test_invalid_team_and_incorrect_official_score_fail(self):
        checks = statements(CHECKS)
        for index, options in ((4, {"invalid_team": True}), (6, {"invalid_team": True}), (5, {"bad_score": True})):
            with self.subTest(index=index), self.assertRaises(Exception):
                self.query(checks[index], **options)


if __name__ == "__main__":
    unittest.main(verbosity=2)
