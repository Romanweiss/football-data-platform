"""Opt-in synthetic ClickHouse tests: TEMPORARY tables only, no S3/PostgreSQL IO."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from clickhouse_model_fakes import dataset_fixture
from src.analytics import loader, model, validation
from src.analytics.specs import SPECS
from src.common.clickhouse import create_clickhouse_client


def source_sql(spec, overrides=None):
    values = {
        "competition_id": "toInt64(43)", "season_id": "toInt64(106)",
        "match_id": "toInt64(7 + intDiv(number, 2))",
        "team_id": "toInt64(number + 1)" if spec.dataset == "teams" else "toInt64(modulo(number, 2) + 1)",
        "player_id": "toInt64(number + 100)",
        "event_id": "concat('00000000-0000-0000-0000-00000000000', toString(number + 1))",
        "key_pass_id": "if(number = 0, CAST(NULL, 'Nullable(String)'), '00000000-0000-0000-0000-000000000001')",
        "statsbomb_xg": "toFloat64(0.1)",
    }
    for name, kind in spec.columns:
        if name in values:
            continue
        raw_kind = "String" if "String" in kind else "Float64" if "Float" in kind else "Bool" if "Bool" in kind else "Int64"
        value = "'synthetic'" if raw_kind == "String" else "0.1" if raw_kind == "Float64" else "1"
        expression = f"CAST({value}, '{raw_kind}')"
        if "Nullable" in kind:
            expression = f"if(number = 0, CAST(NULL, 'Nullable({raw_kind})'), {expression})"
        values[name] = expression
    values.update(overrides or {})
    return "(SELECT " + ", ".join(f"{values[name]} AS `{name}`" for name, _ in spec.columns) + " FROM numbers(4))"


class LocalDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()
        cls.client.set_client_setting("session_timeout", 60)
        print(f"Local ClickHouse version: {cls.client.server_version}")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def table(self, spec):
        migrations = ROOT / "infrastructure/clickhouse/migrations"
        if spec.dataset == "event_core":
            ddl = (migrations / "001_create_event_core.sql").read_text()
            for column in ("location_x", "location_y", "duration"):
                ddl = ddl.replace(f"{column} Nullable(Float32)", f"{column} Nullable(Float64)")
        else:
            # Read the migration as a fixture; never execute it against football.
            statements = (migrations / "003_create_remaining_silver_tables.sql").read_text().split(";")
            ddl = next(s for s in statements if f"CREATE TABLE IF NOT EXISTS {spec.target}\n" in s)
        local = replace(spec, clickhouse_database="", clickhouse_table="stage3b_test_" + uuid4().hex)
        ddl = ddl.replace(f"CREATE TABLE IF NOT EXISTS {spec.target}", f"CREATE TEMPORARY TABLE {local.target}")
        self.assertNotIn("football.", ddl)
        self.client.command(ddl)
        return local

    def insert(self, spec, build_id="a" * 64, overrides=None):
        sql = loader.insert_sql(spec=spec).replace(validation.S3_SOURCE, source_sql(spec, overrides))
        self.assertNotIn("s3(", sql)
        self.client.command(sql, parameters={"build_id": build_id},
                            settings={**loader.INSERT_SETTINGS, "insert_deduplication_token": build_id})

    def test_all_schemas_casts_precision_nulls_and_identities(self):
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                local = self.table(spec)
                validation.validate_table_schema(self.client, spec=local)
                self.insert(local)
                manifest = {"row_count": 4, "match_count": 2, "competition_id": 43, "season_id": 106}
                validation.validate_metrics(validation.target_metrics(self.client, "a" * 64, spec=local), manifest, spec=local)
                validation.validate_extra(self.client, local.target, {}, spec=local)
                for name, kind in local.columns:
                    if "Float64" in kind:
                        values = self.client.query(f"SELECT `{name}` FROM {local.target}").result_rows
                        self.assertTrue(any(row[0] == 0.1 for row in values))
                        self.assertTrue(all(row[0] is None or row[0] == 0.1 for row in values))
                if spec.dataset == "shot_events":
                    values = self.client.query(f"SELECT key_pass_id FROM {local.target} ORDER BY event_index, event_id").result_rows
                    self.assertIsNone(values[0][0])
                    self.assertEqual(values[1][0], UUID("00000000-0000-0000-0000-000000000001"))
                if spec.dataset == "players":
                    self.assertEqual(self.client.query(f"SELECT country_name FROM {local.target} ORDER BY player_id").result_rows[0], (None,))

    def test_every_dataset_dedup_token_and_conflict_scope(self):
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                local = self.table(spec)
                build = {"build_id": "a" * 64, "competition_id": 43, "season_id": 106}
                self.assertEqual(validation.inspect_context(self.client, build, spec=local), 0)
                self.insert(local)
                self.insert(local)
                self.assertEqual(validation.inspect_context(self.client, build, spec=local), 4)
                with self.assertRaises(validation.ClickHouseBuildConflictError):
                    validation.inspect_context(self.client, {**build, "build_id": "b" * 64}, spec=local)
                # A different context does not conflict with the requested context.
                self.assertEqual(validation.inspect_context(self.client, {**build, "season_id": 999}, spec=local), 0)

    def test_nullable_uuid_rejects_invalid_nonnull_text(self):
        local = self.table(SPECS["shot_events"])
        with self.assertRaises(Exception):
            self.insert(local, overrides={"key_pass_id": "'invalid-uuid'"})
        self.assertEqual(self.client.command(f"SELECT count() FROM {local.target}"), 0)

    def test_source_hard_checks_for_xg_nulls_and_two_teams(self):
        spec = SPECS["shot_events"]
        manifest = {"row_count": 4, "match_count": 2, "competition_id": 43, "season_id": 106}
        for value in ("-0.1", "1.1", "nan", "inf"):
            with self.subTest(value=value), patch.object(validation, "S3_SOURCE", source_sql(spec, {"statsbomb_xg": f"toFloat64('{value}')"})):
                metrics = validation.source_metrics(self.client, "unused", spec=spec)
                with self.assertRaises(validation.ClickHouseIntegrityError):
                    validation.validate_metrics(metrics, manifest, spec=spec)
        spec = SPECS["match_squads"]
        with self.assertRaises(validation.ClickHouseIntegrityError):
            validation.validate_extra(self.client, source_sql(spec, {"team_id": "toInt64(1)"}), {}, spec=spec)

    def test_model_anti_joins_and_ten_analytical_queries(self):
        specs = {name: self.table(spec) for name, spec in SPECS.items()}
        builds = {name: "a" * 64 for name in specs}
        for spec in specs.values():
            self.insert(spec)
        with redirect_stdout(io.StringIO()):
            counts = model.validate_references(self.client, builds, specs=specs)
        self.assertTrue(all(count == 0 for count in counts.values()))
        sql = (ROOT / "scripts/clickhouse_model_smoke_queries.sql").read_text()
        for name, spec in specs.items():
            sql = sql.replace("football." + name, spec.target)
        self.assertNotIn("football.", sql)
        queries = [q for q in sql.split(";") if q.strip()]
        self.assertEqual(len(queries), 10)
        for query in queries:
            self.assertTrue(self.client.query(query, parameters={"competition_id": 43, "season_id": 106}).result_rows)

    def test_actual_orphan_checks_hard_vs_informational(self):
        specs = {name: self.table(spec) for name, spec in SPECS.items()}
        builds = {name: "a" * 64 for name in specs}
        for name, spec in specs.items():
            # Event player/team orphans are informational; event keys remain linked.
            overrides = {"team_id": "toInt64(999)", "player_id": "toInt64(999)"} if name in ("event_core", "pass_events", "shot_events") else None
            self.insert(spec, overrides=overrides)
        with redirect_stdout(io.StringIO()):
            counts = model.validate_references(self.client, builds, specs=specs)
        self.assertTrue(all(counts[check.name] == 4 for check in model.REFERENCE_CHECKS if not check.hard))
        # Point the parent dimension at a new empty temporary table, not production.
        specs["teams"] = self.table(SPECS["teams"])
        with redirect_stdout(io.StringIO()), self.assertRaises(validation.ClickHouseIntegrityError):
            model.validate_references(self.client, builds, specs=specs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
