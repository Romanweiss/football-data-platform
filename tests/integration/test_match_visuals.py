"""SELECT-only 013/014/015 verification: live sources and synthetic edge cases."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.analytics import match_visuals as model
from src.common.clickhouse import create_clickhouse_client


class MatchVisualReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.client = create_clickhouse_client()

    @classmethod
    def tearDownClass(cls): cls.client.close()

    def test_all_candidate_rows_schemas_and_windows_against_independent_oracle(self):
        result = model.check_visuals(self.client, candidate=True)
        self.assertEqual((result["xg_race"], result["shot_map"], result["shootout"]), (1453, 1453, 41))

    def test_final_actual_team_xg_and_eight_attempts_four_two(self):
        bodies = model.view_selects()
        _, race = model.read_relation(self.client, "(" + bodies["xg_race"] + ")")
        final = sorted((r for r in race if r["match_id"] == 3869685), key=lambda r: r["event_order"])[-1]
        self.assertAlmostEqual(final["home_cumulative_xg"], 2.758305926, places=9)
        self.assertAlmostEqual(final["away_cumulative_xg"], 2.272617949, places=9)
        _, shootout = model.read_relation(self.client, "(" + bodies["shootout"] + ")")
        final = sorted((r for r in shootout if r["match_id"] == 3869685), key=lambda r: r["shootout_order"])
        self.assertEqual(len(final), 8)
        self.assertEqual((final[-1]["home_shootout_goals_after"], final[-1]["away_shootout_goals_after"]), (4, 2))

    def test_long_form_candidate_from_installed_wide_race(self):
        result = model.check_race_series(self.client, candidate=True)
        self.assertEqual(result, {"xg_race_series": 2906, "team_final_states": 128})
        _, rows = model.read_relation(self.client, "(" + model.series_select() + ")")
        final = [r for r in rows if r["match_id"] == 3869685]
        last_order = max(r["event_order"] for r in final)
        last = {r["team_name"]: r["cumulative_xg"] for r in final if r["event_order"] == last_order}
        self.assertEqual(set(last), {"Argentina", "France"})
        self.assertAlmostEqual(last["Argentina"], 2.758305926, places=9)
        self.assertAlmostEqual(last["France"], 2.2726179490000002, places=9)

    def test_015_preserves_all_original_columns_and_unique_labels(self):
        original_schema, original = model.read_relation(self.client, "(" + model.view_selects()["shot_map"] + ")")
        enriched_schema, enriched = model.read_relation(self.client, "(" + model.shot_map_select() + ")")
        self.assertEqual(enriched_schema, (*original_schema, ("shot_label", "String")))
        model.equal_projection(enriched, original, model.SHOT_KEY, dict(original_schema))
        model.validate_shot_labels(enriched)
        self.assertEqual(len(enriched), 1453)
        self.assertEqual(len({(*model.key_of(r), r["shot_label"]) for r in enriched}), 1453)

    def test_015_sql_nullable_fallback_and_padding(self):
        expression = "concat" + model.shot_map_select().split(",\n    concat", 1)[1].split(" AS shot_label", 1)[0]
        source = "SELECT CAST(NULL AS Nullable(String)) AS player_name, CAST(NULL AS Nullable(String)) AS outcome_name, toUInt16(22) AS minute, toUInt8(4) AS second, toUInt32(1234) AS event_index"
        result = self.client.query("SELECT " + expression + " AS shot_label FROM (" + source + ") AS s", settings={"readonly": 1})
        self.assertEqual(result.result_rows, [("Unknown player | 22:04 | Unknown outcome | #1234",)])

    def test_real_sql_same_second_tie_uses_index_and_rows_not_range(self):
        rows = []
        # Deliberately emit reverse order with identical clocks and one shooting team.
        for index, xg in ((20, 0.2), (10, 0.1)):
            rows.append(f"SELECT * REPLACE (toUInt32({index}) AS event_index, toUInt8(1) AS period, "
                        f"toUInt16(12) AS minute, toUInt8(30) AS second, toFloat64({xg}) AS statsbomb_xg) "
                        "FROM (SELECT * FROM football.bi_match_shots WHERE competition_id=43 AND season_id=106 "
                        "AND match_id=3869685 AND team_id=779 AND is_shootout=0 LIMIT 1)")
        body = model.view_selects()["xg_race"].replace("football.bi_match_shots AS s", "(" + " UNION ALL ".join(rows) + ") AS s")
        result = self.client.query("SELECT event_index,team_cumulative_xg,event_order FROM (" + body + ") ORDER BY event_order",
                                   settings={"readonly": 1}).result_rows
        self.assertEqual([r[0] for r in result], [10, 20])
        self.assertAlmostEqual(result[0][1], 0.1)
        self.assertAlmostEqual(result[1][1], 0.3)
        self.assertEqual([r[2] for r in result], [1, 2])


if __name__ == "__main__": unittest.main(verbosity=2)
