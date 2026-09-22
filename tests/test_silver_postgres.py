"""Offline silver_builds SQL contract tests; migration is never applied."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.common.postgres import SILVER_BUILD_COLUMNS, find_silver_build, register_silver_build


class SilverPostgresTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec=["cursor", "transaction"])
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.record = {
            "source": "statsbomb", "dataset": "event_core", "competition_id": 43, "season_id": 106,
            "transform_version": "event_core_v1", "input_fingerprint": "a" * 64,
            "schema_sha256": "b" * 64, "build_id": "c" * 64, "s3_bucket": "test-bucket",
            "s3_prefix": "football/silver/build/", "row_count": 6, "file_count": 4,
        }
        self.identity = {name: self.record[name] for name in ("dataset", "competition_id", "season_id", "build_id")}

    def test_find_returns_all_fields_and_closes_transaction(self):
        expected = {"id": 1, **self.record, "created_at": "synthetic-time"}
        self.cursor.fetchone.return_value = tuple(expected[name] for name in SILVER_BUILD_COLUMNS)
        self.assertEqual(find_silver_build(self.connection, **self.identity), expected)
        query, params = self.cursor.execute.call_args.args
        self.assertIn("FROM metadata.silver_builds", query)
        self.assertEqual(params, tuple(self.identity.values()))
        self.connection.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_missing_build_returns_none(self):
        self.cursor.fetchone.return_value = None
        self.assertIsNone(find_silver_build(self.connection, **self.identity))

    def test_register_is_parameterized_insert_without_update(self):
        self.record["dataset"] = "event_core'; not SQL"
        self.cursor.fetchone.return_value = (1,)
        self.assertTrue(register_silver_build(self.connection, **self.record))
        query, params = self.cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (dataset, competition_id, season_id, build_id) DO NOTHING", query)
        self.assertIn("RETURNING id", query)
        self.assertEqual(params, tuple(self.record.values()))
        self.assertNotIn(self.record["dataset"], query)
        self.assertNotIn("UPDATE", query)

    def test_duplicate_registration_is_false(self):
        self.cursor.fetchone.return_value = None
        self.assertFalse(register_silver_build(self.connection, **self.record))

    def test_commit_failure_propagates(self):
        self.cursor.fetchone.return_value = (1,)
        self.connection.transaction.return_value.__exit__.side_effect = RuntimeError("commit failed")
        with self.assertRaises(RuntimeError):
            register_silver_build(self.connection, **self.record)

    def test_migration_declares_constraints_and_repeat_safe_creation(self):
        path = Path(__file__).resolve().parents[1] / "infrastructure/postgres/migrations/002_create_silver_builds.sql"
        sql = path.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS metadata.silver_builds", sql)
        self.assertIn("UNIQUE (dataset, competition_id, season_id, build_id)", sql)
        self.assertIn("UNIQUE (s3_bucket, s3_prefix)", sql)
        self.assertEqual(sql.count("^[0-9a-f]{64}$"), 3)
        self.assertIn("CHECK (row_count > 0)", sql)
        self.assertIn("CHECK (file_count > 0)", sql)
        self.assertNotIn("DROP", sql)


if __name__ == "__main__":
    unittest.main()
