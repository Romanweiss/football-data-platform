"""Offline PostgreSQL configuration and catalog registration tests."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import psycopg

from src.common.postgres import (
    IngestionObjectNotFoundError,
    create_postgres_connection,
    find_latest_ingestion_object,
    find_latest_ingestion_objects,
    register_ingestion_object,
)


class PostgresConnectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "POSTGRES_HOST": "football-postgres",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "test-metadata",
            "POSTGRES_USER": "test-user",
            "POSTGRES_PASSWORD": " synthetic password ' ",
        }
        self.enterContext(patch.dict(os.environ, self.settings, clear=True))
        self.connect = self.enterContext(patch("src.common.postgres.psycopg.connect"))

    def test_explicit_environment_connection_and_timeout_preserve_password(self):
        self.assertIs(create_postgres_connection(), self.connect.return_value)
        self.connect.assert_called_once_with(
            host="football-postgres", port=5432, dbname="test-metadata",
            user="test-user", password=self.settings["POSTGRES_PASSWORD"], connect_timeout=10,
        )

    def test_each_required_variable_is_validated_without_exposing_values(self):
        for name in self.settings:
            for value in ("", "   "):
                with self.subTest(name=name, value=value):
                    with patch.dict(os.environ, {name: value}):
                        with self.assertRaisesRegex(ValueError, name) as caught:
                            create_postgres_connection()
                        self.assertNotIn("synthetic password", str(caught.exception))
        self.connect.assert_not_called()

    def test_missing_variables_raise_value_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "POSTGRES_HOST"):
                create_postgres_connection()
        self.connect.assert_not_called()

    def test_invalid_port_is_rejected(self):
        for port in ("invalid", "0", "65536", "-1"):
            with self.subTest(port=port), patch.dict(os.environ, {"POSTGRES_PORT": port}):
                with self.assertRaisesRegex(ValueError, "POSTGRES_PORT"):
                    create_postgres_connection()
        self.connect.assert_not_called()


class RegisterIngestionObjectTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec=["cursor", "transaction"])
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.params = {
            "source": "statsbomb",
            "dataset": "competitions",
            "source_url": "https://example.invalid/data.json",
            "s3_bucket": "test-bucket",
            "object_key": f"football/bronze/sha256={'a' * 64}/data.json",
            "sha256": "a" * 64,
            "size_bytes": 10,
        }

    def test_parameterized_insert_with_conflict_handling(self):
        self.params["dataset"] = "dataset'; not SQL"
        self.cursor.fetchone.return_value = (1,)
        self.assertTrue(register_ingestion_object(self.connection, **self.params))
        query, values = self.cursor.execute.call_args.args
        normalized = " ".join(query.split())
        self.assertIn("INSERT INTO metadata.ingestion_objects", normalized)
        self.assertIn("ON CONFLICT (s3_bucket, object_key) DO NOTHING", normalized)
        self.assertIn("RETURNING id", normalized)
        self.assertEqual(query.count("%s"), 7)
        self.assertEqual(values, tuple(self.params.values()))
        self.assertNotIn(self.params["dataset"], query)
        self.connection.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_repeat_registration_returns_already_registered(self):
        self.cursor.fetchone.side_effect = [(1,), None]
        self.assertTrue(register_ingestion_object(self.connection, **self.params))
        self.assertFalse(register_ingestion_object(self.connection, **self.params))
        self.assertEqual(self.cursor.execute.call_args_list[0], self.cursor.execute.call_args_list[1])
        self.assertEqual(self.connection.transaction.call_count, 2)

    def test_insert_error_exits_transaction_with_error(self):
        error = psycopg.OperationalError("synthetic password")
        self.cursor.execute.side_effect = error
        with self.assertRaises(psycopg.OperationalError):
            register_ingestion_object(self.connection, **self.params)
        transaction_error = self.connection.transaction.return_value.__exit__.call_args.args[1]
        self.assertIs(transaction_error, error)

    def test_commit_failure_does_not_report_registration_success(self):
        self.cursor.fetchone.return_value = (1,)
        self.connection.transaction.return_value.__exit__.side_effect = psycopg.OperationalError(
            "commit failed"
        )
        with self.assertRaises(psycopg.OperationalError):
            register_ingestion_object(self.connection, **self.params)


class FindLatestIngestionObjectTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec=["cursor", "transaction"])
        self.cursor = self.connection.cursor.return_value.__enter__.return_value

    def test_latest_query_is_parameterized_and_returns_catalog_fields(self):
        seen_at = datetime(2026, 9, 22, tzinfo=timezone.utc)
        self.cursor.fetchone.return_value = ("parent-bucket", "registered/key", "a" * 64, 123, seen_at)
        result = find_latest_ingestion_object(
            self.connection, source="statsbomb", dataset="world_cup_2022_matches"
        )
        self.assertEqual(result, {
            "s3_bucket": "parent-bucket", "object_key": "registered/key",
            "sha256": "a" * 64, "size_bytes": 123, "first_seen_at": seen_at,
        })
        query, params = self.cursor.execute.call_args.args
        normalized = " ".join(query.split())
        self.assertIn("WHERE source = %s AND dataset = %s", normalized)
        self.assertIn("ORDER BY first_seen_at DESC, id DESC LIMIT 1", normalized)
        self.assertEqual(params, ("statsbomb", "world_cup_2022_matches"))
        self.assertNotIn("world_cup_2022_matches", query)
        # SELECT must finish its transaction before remote IO/registrations.
        self.connection.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_missing_parent_raises_actionable_error(self):
        self.cursor.fetchone.return_value = None
        with self.assertRaisesRegex(IngestionObjectNotFoundError, "Ingest the parent dataset first"):
            find_latest_ingestion_object(self.connection, source="statsbomb", dataset="world_cup_2022_matches")
        self.connection.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_lookup_sql_error_propagates_and_exits_transaction(self):
        error = psycopg.OperationalError("offline query failure")
        self.cursor.execute.side_effect = error
        with self.assertRaises(psycopg.OperationalError):
            find_latest_ingestion_object(self.connection, source="statsbomb", dataset="matches")
        self.assertIs(self.connection.transaction.return_value.__exit__.call_args.args[1], error)


class FindLatestIngestionObjectsTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(spec=["cursor", "transaction"])
        self.cursor = self.connection.cursor.return_value.__enter__.return_value

    def test_parameterized_distinct_query_and_catalog_mapping(self):
        seen_at = datetime(2026, 9, 22, tzinfo=timezone.utc)
        row = (8, "source-url", "catalog-bucket", "catalog/key", "a" * 64, 123, seen_at)
        self.cursor.fetchall.return_value = [row]
        dataset = "match_events'; not SQL"
        result = find_latest_ingestion_objects(self.connection, source="statsbomb", dataset=dataset)
        self.assertEqual(result, [dict(zip(
            ("id", "source_url", "s3_bucket", "object_key", "sha256", "size_bytes", "first_seen_at"), row,
        ))])
        query, params = self.cursor.execute.call_args.args
        normalized = " ".join(query.split())
        self.assertIn("SELECT DISTINCT ON (source_url)", normalized)
        self.assertIn("FROM metadata.ingestion_objects WHERE source = %s AND dataset = %s", normalized)
        self.assertIn("ORDER BY source_url ASC, first_seen_at DESC, id DESC", normalized)
        self.assertEqual(query.count("%s"), 2)
        self.assertEqual(params, ("statsbomb", dataset))
        self.assertNotIn(dataset, query)
        self.assertNotIn("LIMIT", normalized)
        self.connection.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_empty_dataset_returns_empty_list(self):
        self.cursor.fetchall.return_value = []
        self.assertEqual(find_latest_ingestion_objects(
            self.connection, source="statsbomb", dataset="match_events",
        ), [])

    def test_latest_per_logical_source_with_timestamp_tie_via_mock(self):
        # This mock models DISTINCT ON's ordered first-row contract, not a live DB.
        # Assert the actual SQL separately so changing its tie-breaker fails tests.
        rows = [
            (9, "url-b", "bucket", "b-new", "b" * 64, 10, 2),
            (7, "url-a", "bucket", "a-tie-lower-id", "a" * 64, 10, 3),
            (8, "url-a", "bucket", "a-latest", "c" * 64, 10, 3),
            (99, "url-a", "bucket", "a-older", "d" * 64, 10, 1),
            (6, "url-b", "bucket", "b-old", "e" * 64, 10, 1),
        ]

        def execute(query, params):
            normalized = " ".join(query.split())
            self.assertIn("SELECT DISTINCT ON (source_url)", normalized)
            self.assertIn("ORDER BY source_url ASC, first_seen_at DESC, id DESC", normalized)
            latest = {}
            for row in sorted(rows, key=lambda item: (item[1], -item[6], -item[0])):
                latest.setdefault(row[1], row)
            self.cursor.fetchall.return_value = list(latest.values())

        self.cursor.execute.side_effect = execute
        result = find_latest_ingestion_objects(self.connection, source="statsbomb", dataset="match_events")
        self.assertEqual([row["object_key"] for row in result], ["a-latest", "b-new"])
        self.assertEqual([row["id"] for row in result], [8, 9])

    def test_query_failure_propagates_and_closes_transaction(self):
        error = psycopg.OperationalError("offline failure")
        self.cursor.execute.side_effect = error
        with self.assertRaises(psycopg.OperationalError):
            find_latest_ingestion_objects(self.connection, source="statsbomb", dataset="match_events")
        self.assertIs(self.connection.transaction.return_value.__exit__.call_args.args[1], error)


if __name__ == "__main__":
    unittest.main()
