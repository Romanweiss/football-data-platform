"""Offline PostgreSQL configuration and catalog registration tests."""

import os
import unittest
from unittest.mock import MagicMock, patch

import psycopg

from src.common.postgres import create_postgres_connection, register_ingestion_object


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


if __name__ == "__main__":
    unittest.main()
