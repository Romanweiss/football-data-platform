"""Opt-in local ClickHouse tests. Temporary session tables only; no S3 or PostgreSQL.

Run directly, not via offline discovery. The production migration is NEVER applied:
its DDL is redirected to a uniquely named TEMPORARY MergeTree table, automatically
expired by ClickHouse with the HTTP session. No DROP/TRUNCATE/DELETE is executed.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.analytics import event_core as loader
from src.common.clickhouse import create_clickhouse_client

ROOT = Path(__file__).resolve().parents[2]


class LocalClickHouseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()
        cls.client.set_client_setting("session_timeout", 60)
        print(f"Local ClickHouse version: {cls.client.server_version}")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        self.table = "stage3a_test_" + uuid4().hex
        ddl = (ROOT / "infrastructure/clickhouse/migrations/001_create_event_core.sql").read_text()
        ddl = ddl.replace("CREATE TABLE IF NOT EXISTS football.event_core", "CREATE TEMPORARY TABLE " + self.table)
        # Construct the post-002 synthetic schema without applying any migration.
        for name in ("location_x", "location_y", "duration"):
            ddl = ddl.replace(f"{name} Nullable(Float32)", f"{name} Nullable(Float64)")
        self.assertNotIn("football.event_core", ddl)
        self.client.command(ddl)
        self.build_id = "a" * 64

    def source(self, overrides=None):
        values = {
            "competition_id": "toInt64(43)", "season_id": "toInt64(106)",
            "match_id": "toInt64(7 + number)",
            "event_id": "concat('00000000-0000-0000-0000-00000000000', toString(number + 1))",
            "timestamp": "'00:00:01.000'", "type_name": "'Pass'", "team_name": "'Synthetic FC'",
        }
        for name, kind in loader.EVENT_COLUMNS:
            if name not in values:
                if kind.startswith("Nullable"):
                    raw_type = "String" if "String" in kind else "Float64" if "Float" in kind else "Int64"
                    value = "'synthetic'" if raw_type == "String" else "1"
                    values[name] = f"if(number = 0, CAST(NULL, 'Nullable({raw_type})'), CAST({value}, 'Nullable({raw_type})'))"
                else:
                    values[name] = "toInt32(1)"
        values.update(overrides or {})
        return "(SELECT " + ", ".join(f"{values[name]} AS `{name}`" for name, _ in loader.EVENT_COLUMNS) + " FROM numbers(2))"

    def insert(self, *, overrides=None, token=None):
        with patch.object(loader, "TARGET", self.table):
            sql = loader.insert_sql().replace(loader.S3_SOURCE, self.source(overrides))
        self.assertNotIn("s3(", sql)
        self.client.command(sql, parameters={"build_id": self.build_id}, settings={
            **loader.INSERT_SETTINGS, "insert_deduplication_token": token or self.build_id,
        })

    def test_schema_engine_keys_and_default(self):
        # system.tables lists temporary tables with an empty database name.
        with patch.multiple(loader, TARGET=self.table, DATABASE="", TABLE=self.table):
            loader.validate_table_schema(self.client)

    def test_explicit_casts_nulls_and_postload_metrics(self):
        self.insert()
        with patch.object(loader, "TARGET", self.table):
            metrics = loader.target_metrics(self.client, self.build_id)
        loader.validate_metrics(metrics, {"row_count": 2, "match_count": 2, "competition_id": 43, "season_id": 106})
        rows = self.client.query(
            f"SELECT player_id, player_name, location_x, under_pressure, counterpress, silver_build_id, loaded_at "
            f"FROM {self.table} ORDER BY match_id"
        ).result_rows
        self.assertEqual(rows[0][:5], (None, None, None, None, None))
        self.assertEqual(rows[1][:5], (1, "synthetic", 1.0, True, True))
        self.assertEqual(rows[0][5], self.build_id.encode())
        self.assertIsNotNone(rows[0][6])

    def test_same_dedup_token_does_not_insert_twice(self):
        self.insert()
        self.insert()
        self.assertEqual(self.client.command(f"SELECT count() FROM {self.table}"), 2)

    def test_smoke_sql_and_build_scoping(self):
        self.insert()
        self.build_id = "b" * 64
        self.insert()
        self.assertEqual(self.client.command(f"SELECT count() FROM {self.table}"), 4)
        sql = (ROOT / "scripts/clickhouse_smoke_queries.sql").read_text().replace("football.event_core", self.table)
        queries = [query for query in sql.split(";") if query.strip()]
        self.assertEqual(len(queries), 5)
        results = [self.client.query(query, parameters={"build_id": self.build_id}).result_rows for query in queries]
        self.assertEqual(results[0], [(2,)])
        self.assertEqual(len(results[-1]), 1)

    def test_required_null_and_integer_overflow_rejected(self):
        for overrides in ({"team_id": "CAST(NULL, 'Nullable(Int64)')"}, {"period": "toInt32(256)"},
                          {"team_id": "toInt64(-1)"}, {"event_id": "'not-a-uuid'"}):
            with self.subTest(overrides=overrides), self.assertRaises(Exception):
                self.insert(overrides=overrides, token=uuid4().hex)
        self.assertEqual(self.client.command(f"SELECT count() FROM {self.table}"), 0)

    def test_s3_named_collection_query_syntax_without_execution(self):
        # EXPLAIN AST only parses SQL. It does not resolve a collection or do IO.
        query = f"EXPLAIN AST SELECT {loader.METRICS} FROM {loader.S3_SOURCE}"
        result = self.client.command(query, parameters={"url": "https://example.invalid/exact/part-*.parquet"})
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
