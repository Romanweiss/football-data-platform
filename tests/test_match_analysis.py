"""Offline contracts and adversarial validation tests for additive Match Analysis."""

import copy
import io
import re
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

from match_analysis_fakes import fixture
from src.analytics import match_analysis as model
from src.analytics.validation import ClickHouseIntegrityError
from scripts import check_clickhouse_match_analysis as cli


class MatchAnalysisTests(unittest.TestCase):
    def validate(self, views, sources, expected):
        return model.validate_rows(views, sources, expected=expected)

    def test_all_periods_zero_activity_and_nullable_players_preserved(self):
        views, sources, expected = fixture()
        summary = self.validate(views, sources, expected)
        self.assertEqual(summary["normal_shots"], 4)
        self.assertEqual(summary["extra_time_shots"], 2)
        self.assertEqual(summary["shootout_shots"], 1)
        self.assertEqual(summary["rows"]["player_stats"], 4)

    def test_label_deterministic_ascii_hyphen_no_score(self):
        views, sources, expected = fixture()
        row = sources["results"][0]
        self.assertEqual(model.match_label(row), "2022-12-01 | Home - Away")
        self.assertEqual(model.match_label({**row, "display_score": "9-9"}), model.match_label(row))
        for name in views:
            for label in (None, "", "2022-12-01 | Home – Away", "wrong"):
                bad = copy.deepcopy(views)
                bad[name][0]["match_label"] = label
                with self.subTest(view=name, label=label), self.assertRaises(ClickHouseIntegrityError):
                    self.validate(bad, sources, expected)

    def test_incorrect_flags_for_every_period_fail(self):
        views, sources, expected = fixture()
        for index in range(5):
            for flag in ("is_extra_time", "is_shootout"):
                bad = copy.deepcopy(views)
                bad["shots"][index][flag] = 1 - bad["shots"][index][flag]
                with self.subTest(period=index + 1, flag=flag), self.assertRaises(ClickHouseIntegrityError):
                    self.validate(bad, sources, expected)

    def test_duplicate_missing_and_orphan_grains_fail(self):
        views, sources, expected = fixture()
        for name in views:
            for mutation in ("duplicate", "missing", "orphan_match", "context"):
                bad = copy.deepcopy(views)
                if mutation == "duplicate": bad[name].append(copy.deepcopy(bad[name][0]))
                if mutation == "missing": bad[name].pop()
                if mutation == "orphan_match": bad[name][0]["match_id"] = 999
                if mutation == "context": bad[name][0]["season_id"] = 999
                with self.subTest(view=name, mutation=mutation), self.assertRaises(ClickHouseIntegrityError):
                    self.validate(bad, sources, expected)

    def test_orphan_team_rejected_even_if_source_also_has_it(self):
        for name in ("team_stats", "player_stats", "shots"):
            views, sources, expected = fixture()
            views[name][0]["team_id"] = sources[name][0]["team_id"] = 999
            with self.assertRaises(ClickHouseIntegrityError): self.validate(views, sources, expected)

    def test_metrics_coordinates_and_nulls_are_exactly_preserved(self):
        views, sources, expected = fixture()
        for name, field, value in (("team_stats", "shot_count", 1), ("player_stats", "event_count", 1),
                                   ("shots", "statsbomb_xg", 0.10000000000001), ("shots", "start_x", 99),
                                   ("shots", "player_id", 0), ("shots", "player_name", ""),
                                   ("shots", "end_z", 0), ("shots", "key_pass_id", "wrong")):
            bad = copy.deepcopy(views)
            bad[name][0][field] = value
            with self.subTest(field=field), self.assertRaises(ClickHouseIntegrityError):
                self.validate(bad, sources, expected)

    def test_preserved_totals_do_not_hide_per_row_changes(self):
        views, sources, expected = fixture()
        views["shots"][0]["statsbomb_xg"] += 0.05
        views["shots"][1]["statsbomb_xg"] -= 0.05
        with self.assertRaises(ClickHouseIntegrityError): self.validate(views, sources, expected)

    def test_counts_xg_tolerance_nonfinite_and_shootout_set(self):
        views, sources, expected = fixture()
        self.validate(views, sources, {**expected, "normal_xg": 0.4 + 1e-12})
        for key, value in (("normal_xg", 0.41), ("shootout_xg", 0.2), ("raw_xg", float("nan")),
                           ("normal_shots", 3), ("shootout_shots", 2), ("extra_time_shots", 0),
                           ("shootout_matches", {1})):
            with self.subTest(key=key), self.assertRaises(ClickHouseIntegrityError):
                self.validate(views, sources, {**expected, key: value})
        for value in (float("inf"), float("nan"), -0.1, 1.1):
            views, sources, expected = fixture()
            views["shots"][0]["statsbomb_xg"] = sources["shots"][0]["statsbomb_xg"] = value
            with self.assertRaises(ClickHouseIntegrityError): self.validate(views, sources, expected)

    def test_authoritative_results_and_shootout_goal_id_not_name(self):
        views, sources, expected = fixture()
        self.validate(views, sources, expected)  # Deliberately misleading outcome_name.
        views["shots"][-1]["outcome_id"] = sources["shots"][-1]["outcome_id"] = 98
        with self.assertRaises(ClickHouseIntegrityError): self.validate(views, sources, expected)
        views, sources, expected = fixture()
        views["shots"][0]["display_score"] = "wrong"
        with self.assertRaises(ClickHouseIntegrityError): self.validate(views, sources, expected)

    def test_sql_additive_full_key_joins_no_v1_or_metric_recomputation(self):
        sql = model.MIGRATION.read_text()
        bodies = model.view_selects()
        self.assertEqual(sql.count("CREATE VIEW IF NOT EXISTS football.bi_match_"), 4)
        self.assertNotRegex(sql, r"\b(REPLACE|DROP|DELETE|TRUNCATE|ALTER|MATERIALIZED|DEFINER)\b")
        self.assertNotRegex(sql, r"football\.(team_match_stats|player_match_stats)\b")
        self.assertNotIn("SELECT *", sql)
        self.assertNotRegex(sql, r"\b(GROUP BY|WHERE|DISTINCT|LIMIT)\b")
        self.assertIn("FROM football.match_results AS r", bodies["overview"])
        for name, a, b in (("overview", "r", "m"), ("team_stats", "t", "o"),
                           ("player_stats", "p", "o"), ("shots", "s", "o")):
            for key in model.MATCH_KEY:
                self.assertIn(f"{a}.{key} = {b}.{key}", bodies[name])
        for name in ("team_stats", "player_stats"):
            self.assertIn("FROM football.bi_" + name.replace("_stats", "_match_stats"), bodies[name])
            self.assertIn("o.match_label AS match_label", bodies[name])
        self.assertIn("s.period = 5 AS is_shootout", bodies["shots"])
        self.assertIn("s.period IN (3, 4) AS is_extra_time", bodies["shots"])
        for field, _ in model.SHOTS.columns:
            self.assertIn(f"s.{field} AS {field}", bodies["shots"])
        self.assertNotIn("event_core", bodies["shots"])  # Timing/context already present.
        self.assertEqual(sql.count("concat(toString(r.match_date), ' | ', r.home_team_name, ' - ', r.away_team_name)"), 1)

    def test_event_identity_includes_full_context_not_just_uuid(self):
        keys = model.GRAINS["shots"]
        rows = [dict(competition_id=43, season_id=106, match_id=i, event_id="same") for i in (1, 2)]
        self.assertEqual(len(model.rows_by_key(rows, keys)), 2)
        bad = copy.deepcopy(rows)
        bad[1]["match_id"] = 3
        with self.assertRaises(ClickHouseIntegrityError): model.equal_projection(rows, bad, keys, keys)

    def test_candidate_is_select_only_and_read_queries_are_bounded(self):
        for relation in model.candidate_relations().values():
            self.assertTrue(relation.startswith("(SELECT"))
            self.assertNotRegex(relation, r"\b(CREATE|INSERT|ALTER|DELETE|DROP|TRUNCATE)\b")
            self.assertNotIn("football.bi_match_overview", relation)
        client = MagicMock()
        client.query.return_value = MagicMock(result_rows=[], column_names=[], column_types=[])
        model.read_relation(client, "football.shot_events")
        self.assertEqual(client.query.call_args.kwargs["settings"], {"readonly": 1})
        self.assertIn("LIMIT 10001", client.query.call_args.args[0])
        client.query.return_value.result_rows = [()] * 10001
        with self.assertRaises(ClickHouseIntegrityError): model.read_relation(client, "football.shot_events")

    def test_cli_fails_closed_and_hides_raw_exception(self):
        with patch.object(cli, "check_cutover", return_value=1), patch.object(cli, "create_clickhouse_client") as connect:
            self.assertEqual(cli.main([]), 1)
            connect.assert_not_called()
        with patch.object(cli, "check_cutover", return_value=0), \
                patch.object(cli, "create_clickhouse_client", side_effect=RuntimeError("synthetic-secret-value")), \
                redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(["--candidate"]), 1)
        self.assertNotIn("synthetic-secret-value", errors.getvalue())
        self.assertIn("stage=candidate SELECT; exception=RuntimeError", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
