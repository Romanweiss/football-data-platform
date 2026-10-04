"""Opt-in Stage 3D SQL tests: session TEMPORARY tables, no S3 or catalog IO."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from context_fixtures import in_context
from integration import test_clickhouse_datasets as silver_tests
from src.analytics import gold_loader, gold_model, validation
from src.analytics.gold_specs import SPECS, TEAM
from src.common.clickhouse import create_clickhouse_client


def source_sql(spec, overrides=None):
    values = {
        "competition_id": "toInt64(43)", "season_id": "toInt64(106)",
        "match_id": "toInt64(7 + intDiv(number, 2))",
        "team_id": "toInt64(modulo(number, 2) + 1)",
        "player_id": "toInt64(number + 100)",
        "team_name": "'synthetic team'", "player_name": "'synthetic player'",
        "shot_xg": "toFloat64(0.1)", "shot_goals": "toInt64(0)",
    }
    values.update(overrides or {})
    return "(SELECT " + ", ".join(f"{values.get(name, 'toInt64(1)')} AS `{name}`" for name, _ in spec.columns) + " FROM numbers(4))"


class LocalGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()
        cls.client.set_client_setting("session_timeout", 60)
        print(f"Local ClickHouse version: {cls.client.server_version}")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def table(self, spec):
        statements = (ROOT / "infrastructure/clickhouse/migrations/004_create_gold_match_stats.sql").read_text().split(";")
        ddl = next(s for s in statements if f"CREATE TABLE IF NOT EXISTS {spec.target}\n" in s)
        local = replace(spec, clickhouse_database="", table_override="stage3d_test_" + uuid4().hex)
        ddl = ddl.replace(f"CREATE TABLE IF NOT EXISTS {spec.target}", f"CREATE TEMPORARY TABLE {local.target}")
        self.assertNotIn("football.", ddl)
        self.client.command(ddl)
        return local

    def insert(self, spec, overrides=None):
        sql = gold_loader.insert_sql(spec=spec).replace(validation.S3_SOURCE, source_sql(spec, overrides))
        self.assertNotIn("s3(", sql)
        self.client.command(sql, parameters={"build_id": "a" * 64},
                            settings={**gold_loader.INSERT_SETTINGS, "insert_deduplication_token": "a" * 64})

    def test_schema_casts_float64_and_target_dq(self):
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                local = self.table(spec)
                validation.validate_table_schema(self.client, spec=local)
                self.insert(local)
                gold_loader.validate_gold_metrics(gold_loader.target_metrics(self.client, "a" * 64, spec=local),
                    {"row_count": 4, "match_count": 2, "competition_id": 43, "season_id": 106}, spec=local)
                validation.validate_extra(self.client, local.target, {}, spec=local)
                self.assertEqual(self.client.query(f"SELECT DISTINCT shot_xg, toTypeName(shot_xg) FROM {local.target}").result_rows,
                                 [(0.1, "Float64")])

    def test_same_token_deduplicates_and_other_build_conflicts(self):
        for spec in SPECS.values():
            local = self.table(spec)
            build = {"build_id": "a" * 64, "competition_id": 43, "season_id": 106}
            self.assertEqual(gold_loader.inspect_context(self.client, build, spec=local), 0)
            self.insert(local)
            self.insert(local)
            self.assertEqual(gold_loader.inspect_context(self.client, build, spec=local), 4)
            with self.assertRaises(gold_loader.GoldBuildConflictError):
                gold_loader.inspect_context(self.client, {**build, "build_id": "b" * 64}, spec=local)

    def test_accurate_cast_rejects_negative_overflow_and_null(self):
        for spec in SPECS.values():
            for overrides in ({"event_count": "toInt64(-1)"}, {"team_id": "toInt64(4294967296)"},
                              {"event_count": "CAST(NULL, 'Nullable(Int64)')"}):
                with self.subTest(dataset=spec.dataset, overrides=overrides):
                    local = self.table(spec)
                    with self.assertRaises(Exception):
                        self.insert(local, overrides)
                    self.assertEqual(self.client.command(f"SELECT count() FROM {local.target}"), 0)

    def test_source_nonfinite_negative_null_and_goals_dq(self):
        expected = {"row_count": 4, "match_count": 2, "competition_id": 43, "season_id": 106}
        for spec in SPECS.values():
            for overrides in ({"shot_xg": "toFloat64('nan')"}, {"shot_xg": "toFloat64('inf')"},
                              {"shot_xg": "toFloat64(-0.1)"}, {"shot_goals": "toInt64(2)"},
                              {"event_count": "CAST(NULL, 'Nullable(Int64)')"}, {"event_count": "toInt64(-1)"}):
                with self.subTest(dataset=spec.dataset, overrides=overrides), patch.object(validation, "S3_SOURCE", source_sql(spec, overrides)):
                    metrics = validation.source_metrics(self.client, "unused", spec=spec)
                    with self.assertRaises(validation.ClickHouseIntegrityError):
                        gold_loader.validate_gold_metrics(metrics, expected, spec=spec)
        with self.assertRaises(validation.ClickHouseIntegrityError):
            validation.validate_extra(self.client, source_sql(TEAM, {"team_id": "toInt64(1)"}), {}, spec=TEAM)

    def model_tables(self):
        gold = {name: self.table(spec) for name, spec in SPECS.items()}
        silver = {name: silver_tests.LocalDatasetTests.table(self, spec) for name, spec in gold_model.INPUT_SPECS.items()}
        for spec in gold.values():
            self.insert(spec)
        for spec in silver.values():
            silver_tests.LocalDatasetTests.insert(self, spec)
        return gold, silver

    def test_model_queries_and_smoke_queries(self):
        gold, silver = self.model_tables()
        with redirect_stdout(io.StringIO()):
            result = in_context(gold_model.validate_model_metrics)(self.client, {name: "a" * 64 for name in gold},
                {name: "a" * 64 for name in silver}, gold_specs=gold, silver_specs=silver)
        self.assertEqual(len(result), 12)
        sql = (ROOT / "scripts/clickhouse_gold_smoke_queries.sql").read_text()
        matches = silver_tests.LocalDatasetTests.table(self, silver_tests.SPECS["matches"])
        silver_tests.LocalDatasetTests.insert(self, matches)
        for name, spec in {**gold, **silver, "matches": matches}.items():
            sql = sql.replace("football." + name, spec.target)
        self.assertNotIn("football.", sql)
        queries = [q for q in sql.split(";") if q.strip()]
        self.assertEqual(len(queries), 9)
        for query in queries:
            self.client.query(query, parameters={"competition_id": 43, "season_id": 106})

    def test_model_rejects_orphan_keys_and_metric_mismatch(self):
        gold, silver = self.model_tables()
        for overrides in ({"team_id": "toInt64(999)"}, {"event_count": "toInt64(2)"}):
            replacement = self.table(TEAM)
            self.insert(replacement, overrides)
            with redirect_stdout(io.StringIO()), self.assertRaises(validation.ClickHouseIntegrityError):
                in_context(gold_model.validate_model_metrics)(self.client, {name: "a" * 64 for name in gold},
                    {name: "a" * 64 for name in silver}, gold_specs={**gold, TEAM.dataset: replacement}, silver_specs=silver)


if __name__ == "__main__":
    unittest.main(verbosity=2)
