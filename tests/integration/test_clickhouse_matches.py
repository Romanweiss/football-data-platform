"""Stage 3E TEMPORARY-only ClickHouse tests; no S3/PG or persistent-table writes."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from integration import test_clickhouse_datasets as silver_tests, test_clickhouse_gold as gold_tests
from src.analytics import loader, matches_model, validation
from src.analytics.specs import MATCHES, SPECS
from src.analytics.gold_specs import SPECS as GOLD_SPECS
from src.common.clickhouse import create_clickhouse_client


class LocalMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()
        cls.client.set_client_setting("session_timeout", 60)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def table(self, spec):
        return silver_tests.LocalDatasetTests.table(self, spec)

    def insert_matches(self, spec, overrides=None):
        overrides = {"match_date": "toDate32('2022-11-21')", "kick_off": "CAST(NULL, 'Nullable(String)')",
                     "stadium_id": "CAST(NULL, 'Nullable(Int64)')", "referee_name": "CAST(NULL, 'Nullable(String)')",
                     **(overrides or {})}
        source = silver_tests.source_sql(spec, overrides).replace("FROM numbers(4)", "FROM numbers(2)")
        self.client.command(loader.insert_sql(spec=spec).replace(validation.S3_SOURCE, source),
            parameters={"build_id": "a" * 64}, settings={**loader.INSERT_SETTINGS, "insert_deduplication_token": "a" * 64})

    def test_actual_date32_conversion_nullable_fields_and_kickoff(self):
        spec = self.table(MATCHES)
        validation.validate_table_schema(self.client, spec=spec)
        self.insert_matches(spec)
        validation.validate_metrics(validation.target_metrics(self.client, "a" * 64, spec=spec),
            {"row_count": 2, "match_count": 2, "competition_id": 43, "season_id": 106}, spec=spec)
        rows = self.client.query(f"SELECT toString(match_date), kick_off, stadium_id, referee_name FROM {spec.target}").result_rows
        self.assertEqual(rows, [("2022-11-21", "", None, None)] * 2)

    def test_source_dq_self_play_negative_scores_null_date(self):
        for overrides in ({"away_team_id": "toInt64(1)"}, {"home_score": "toInt64(-1)"},
                          {"away_score": "toInt64(-1)"}, {"match_date": "CAST(NULL, 'Nullable(Date32)')"}):
            source = silver_tests.source_sql(MATCHES, overrides)
            with patch.object(validation, "S3_SOURCE", source):
                with self.assertRaises(validation.ClickHouseIntegrityError):
                    validation.validate_metrics(validation.source_metrics(self.client, "unused", spec=MATCHES),
                        {"row_count": 4, "match_count": 4, "competition_id": 43, "season_id": 106}, spec=MATCHES)

    def test_no_silent_date_or_integer_narrowing(self):
        for overrides in ({"match_date": "toDate32('1900-01-01')"}, {"home_score": "toInt64(65536)"},
                          {"match_date": "toDate32('2200-01-01')"}, {"match_week": "toInt64(65536)"},
                          {"stadium_id": "toInt64(-1)"}, {"referee_id": "toInt64(4294967296)"},
                          {"competition_stage_id": "toInt64(65536)"}):
            local = self.table(MATCHES)
            with self.assertRaises(Exception):
                self.insert_matches(local, overrides)
            self.assertEqual(self.client.command(f"SELECT count() FROM {local.target}"), 0)

    def tables(self):
        silver = {name: self.table(spec) for name, spec in SPECS.items()}
        gold = {name: gold_tests.LocalGoldTests.table(self, spec) for name, spec in GOLD_SPECS.items()}
        for spec in silver.values():
            if spec.dataset == "matches":
                self.insert_matches(spec)
            else:
                silver_tests.LocalDatasetTests.insert(self, spec)
        for spec in gold.values():
            gold_tests.LocalGoldTests.insert(self, spec)
        return silver, gold

    def check(self, silver, gold):
        with redirect_stdout(io.StringIO()):
            return matches_model.validate_match_references(self.client, {name: "a" * 64 for name in {**silver, **gold}}, specs=silver, gold_specs=gold)

    def test_all_actual_cross_model_joins_pass(self):
        silver, gold = self.tables()
        self.assertEqual(self.check(silver, gold), {name: 0 for name, _ in matches_model.match_queries()})

    def test_each_fact_match_orphan_fails(self):
        silver, gold = self.tables()
        for name in ("event_core", "pass_events", "shot_events", "match_squads", "team_match_stats", "player_match_stats"):
            if name in silver:
                replacement = self.table(SPECS[name])
                silver_tests.LocalDatasetTests.insert(self, replacement, overrides={"match_id": "toInt64(999)"})
                current_silver, current_gold = {**silver, name: replacement}, gold
            else:
                replacement = gold_tests.LocalGoldTests.table(self, GOLD_SPECS[name])
                gold_tests.LocalGoldTests.insert(self, replacement, overrides={"match_id": "toInt64(999)"})
                current_silver, current_gold = silver, {**gold, name: replacement}
            with self.subTest(dataset=name), self.assertRaises(validation.ClickHouseIntegrityError):
                self.check(current_silver, current_gold)

    def test_team_membership_exact_not_just_two_teams_and_missing_gold(self):
        silver, gold = self.tables()
        # Three/four are real teams in the synthetic dimension, but not the match participants.
        replacement = gold_tests.LocalGoldTests.table(self, GOLD_SPECS["team_match_stats"])
        gold_tests.LocalGoldTests.insert(self, replacement, overrides={"team_id": "toInt64(modulo(number, 2) + 3)"})
        with self.assertRaises(validation.ClickHouseIntegrityError):
            self.check(silver, {**gold, "team_match_stats": replacement})
        empty = gold_tests.LocalGoldTests.table(self, GOLD_SPECS["team_match_stats"])
        with self.assertRaises(validation.ClickHouseIntegrityError):
            self.check(silver, {**gold, "team_match_stats": empty})
        for side in ("home", "away"):
            matches = self.table(MATCHES)
            self.insert_matches(matches, {side + "_team_id": "toInt64(999)"})
            with self.assertRaises(validation.ClickHouseIntegrityError):
                self.check({**silver, "matches": matches}, gold)


if __name__ == "__main__":
    unittest.main(verbosity=2)
