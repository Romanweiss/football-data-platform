"""Offline SQL contracts for Stage 3A; no migrations are applied."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.common.postgres import (
    CLICKHOUSE_LOAD_COLUMNS, CLICKHOUSE_LOAD_FIELDS, SILVER_BUILD_COLUMNS,
    clickhouse_load_lock, find_clickhouse_load, find_latest_silver_build, register_clickhouse_load,
)


class ClickHousePostgresTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value

    def test_latest_silver_deterministic_tie_break_all_fields(self):
        values = tuple(range(len(SILVER_BUILD_COLUMNS)))
        self.cursor.fetchone.return_value = values
        result = find_latest_silver_build(self.connection, source="statsbomb", dataset="event_core", competition_id=43, season_id=106)
        self.assertEqual(result, dict(zip(SILVER_BUILD_COLUMNS, values)))
        query, parameters = self.cursor.execute.call_args.args
        self.assertIn("ORDER BY created_at DESC, id DESC LIMIT 1", query)
        self.assertEqual(parameters, ("statsbomb", "event_core", 43, 106))
        self.connection.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_missing_latest(self):
        self.cursor.fetchone.return_value = None
        self.assertIsNone(find_latest_silver_build(self.connection, source="statsbomb", dataset="event_core", competition_id=43, season_id=106))

    def test_find_load_parameterized_and_missing(self):
        values = tuple(range(len(CLICKHOUSE_LOAD_COLUMNS)))
        self.cursor.fetchone.return_value = values
        options = {"clickhouse_database": "football", "clickhouse_table": "event_core", "silver_build_id": "b" * 64}
        self.assertEqual(find_clickhouse_load(self.connection, **options), dict(zip(CLICKHOUSE_LOAD_COLUMNS, values)))
        query, parameters = self.cursor.execute.call_args.args
        self.assertEqual(parameters, tuple(options.values()))
        self.assertNotIn("b" * 64, query)
        self.cursor.fetchone.return_value = None
        self.assertIsNone(find_clickhouse_load(self.connection, **options))

    def test_register_duplicate_and_commit_failure(self):
        record = dict(zip(CLICKHOUSE_LOAD_FIELDS, range(len(CLICKHOUSE_LOAD_FIELDS))))
        self.cursor.fetchone.return_value = (1,)
        self.assertTrue(register_clickhouse_load(self.connection, **record))
        query, parameters = self.cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (clickhouse_database, clickhouse_table, silver_build_id) DO NOTHING RETURNING id", query)
        self.assertNotIn("UPDATE", query)
        self.assertEqual(parameters, tuple(record.values()))
        self.cursor.fetchone.return_value = None
        self.assertFalse(register_clickhouse_load(self.connection, **record))
        self.connection.transaction.return_value.__exit__.side_effect = RuntimeError("commit failure")
        with self.assertRaises(RuntimeError):
            register_clickhouse_load(self.connection, **record)

    def test_writer_lock_release_even_on_failure(self):
        self.cursor.fetchone.return_value = (True,)
        with self.assertRaises(ValueError):
            with clickhouse_load_lock(self.connection):
                raise ValueError("test")
        queries = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertEqual(queries, ["SELECT pg_try_advisory_lock(%s)", "SELECT pg_advisory_unlock(%s)"])

    def test_writer_lock_contention_fails_without_unlocking_other_writer(self):
        self.cursor.fetchone.return_value = (False,)
        with self.assertRaises(RuntimeError):
            with clickhouse_load_lock(self.connection):
                self.fail("lock should not be acquired")
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_migration_constraints(self):
        sql = (Path(__file__).resolve().parents[1] / "infrastructure/postgres/migrations/003_create_clickhouse_loads.sql").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS metadata.clickhouse_loads", sql)
        self.assertIn("UNIQUE (clickhouse_database, clickhouse_table, silver_build_id)", sql)
        self.assertEqual(sql.count("^[0-9a-f]{64}$"), 3)
        self.assertIn("CHECK (row_count > 0)", sql)
        self.assertNotIn("DROP", sql)


if __name__ == "__main__":
    unittest.main()
