"""Offline 015 label contract and exact preservation of historical 013 SQL."""
import copy
import re
import unittest

from match_visuals_fakes import fixture
from src.analytics import match_visuals as model
from src.analytics.validation import ClickHouseIntegrityError


class ShotLabelTests(unittest.TestCase):
    def rows(self):
        rows = fixture()[0]["shot_map"]
        return [{**row, "shot_label": model.expected_shot_label(row)} for row in rows]

    def test_deterministic_unicode_label_and_zero_padded_seconds(self):
        row = {**self.rows()[0], "player_name": "Lionel Andrés Messi Cuccittini", "minute": 22,
               "second": 4, "outcome_name": "Goal", "event_index": 1234}
        self.assertEqual(model.expected_shot_label(row), "Lionel Andrés Messi Cuccittini | 22:04 | Goal | #1234")
        self.assertEqual(model.expected_shot_label({**row, "event_id": "different"}), model.expected_shot_label(row))
        self.assertIn("22:00", model.expected_shot_label({**row, "second": 0}))
        self.assertIn("122:59", model.expected_shot_label({**row, "minute": 122, "second": 59}))

    def test_nullable_fallback_without_mutating_source_values(self):
        row = {**self.rows()[0], "player_name": None, "outcome_name": None, "minute": 0, "second": 0, "event_index": 10}
        original = dict(row)
        self.assertEqual(model.expected_shot_label(row), "Unknown player | 0:00 | Unknown outcome | #10")
        self.assertEqual(row, original)
        # Empty strings are preserved, not silently rewritten into source values.
        self.assertEqual(model.expected_shot_label({**row, "player_name": ""}), " | 0:00 | Unknown outcome | #10")

    def test_same_player_second_outcome_distinguished_by_index(self):
        row = self.rows()[0]
        rows = [{**row, "event_index": i, "event_id": str(i)} for i in (1, 2)]
        for item in rows: item["shot_label"] = model.expected_shot_label(item)
        model.validate_shot_labels(rows)
        self.assertNotEqual(rows[0]["shot_label"], rows[1]["shot_label"])

    def test_uniqueness_scoped_to_full_match_context(self):
        row = self.rows()[0]
        model.validate_shot_labels([row, {**row, "season_id": 107}, {**row, "match_id": 999}])
        with self.assertRaises(ClickHouseIntegrityError): model.validate_shot_labels([row, dict(row)])

    def test_null_blank_wrong_and_colliding_labels_fail(self):
        for value in (None, "", "   ", "wrong label"):
            rows = self.rows()
            rows[0]["shot_label"] = value
            with self.assertRaises(ClickHouseIntegrityError): model.validate_shot_labels(rows)
        rows = self.rows()
        rows[1]["shot_label"] = rows[0]["shot_label"]
        with self.assertRaises(ClickHouseIntegrityError): model.validate_shot_labels(rows)

    def test_migration_only_appends_label_to_exact_013_projection(self):
        old = model.view_selects()["shot_map"]
        enriched = model.shot_map_select()
        stripped = re.sub(r",\n    concat\(ifNull\(s\.player_name,[\s\S]*? AS shot_label\nFROM", "\nFROM", enriched)
        self.assertEqual(stripped, old)
        sql = model.SHOT_MAP_MIGRATION.read_text()
        self.assertEqual(sql.count("CREATE OR REPLACE VIEW"), 1)
        self.assertIn("CREATE OR REPLACE VIEW football.bi_match_shot_map\nSQL SECURITY INVOKER", sql)
        self.assertNotRegex(sql, r"\b(JOIN|GROUP BY|DISTINCT|UNION|DELETE|DROP|TRUNCATE|ALTER)\b")
        self.assertIn("WHERE s.is_shootout = 0", enriched)
        expression = enriched.split(",\n    concat", 1)[1].split(" AS shot_label", 1)[0]
        self.assertNotIn("event_id", expression)

    def test_existing_dq_still_rejects_lost_rows_and_changed_coordinates_xg_period(self):
        data = fixture()
        data[0]["shot_map"] = self.rows()
        for failure in ("missing", "start_x", "statsbomb_xg", "period"):
            views, shots, overview, teams, expected = copy.deepcopy(data)
            if failure == "missing": views["shot_map"].pop()
            else: views["shot_map"][0][failure] = 5 if failure == "period" else 999
            with self.subTest(failure=failure), self.assertRaises(ClickHouseIntegrityError):
                model.validate_visuals(views, shots, overview, teams, expected=expected)


if __name__ == "__main__": unittest.main()
