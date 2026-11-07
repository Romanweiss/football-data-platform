"""Explicit target gates and fail-closed persistent reads; no live clients."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.historical_connection import persistent_client
from application.historical_repository import HistoricalRepository, create_historical_client
from src.openfootball_etl.serving_contract import AUTHORIZATION, DATASET, MODE, PINNED, validate_bundle

UUID = "12345678-abcd-abcd-abcd-123456789abc"
ENV = {"HISTORICAL_API_ENABLED": "true", "HISTORICAL_SERVING_MODE": MODE,
       "HISTORICAL_PRODUCTION_AUTHORIZATION": AUTHORIZATION, "HISTORICAL_DATASET_ID": DATASET,
       "HISTORICAL_PINNED_BATCH": PINNED.batch_id, "HISTORICAL_EXPECTED_SERVER_UUID": UUID,
       "HISTORICAL_CLICKHOUSE_HOST": "football-clickhouse", "HISTORICAL_CLICKHOUSE_DATABASE": "football",
       "HISTORICAL_CLICKHOUSE_USER": "historical_reader", "HISTORICAL_CLICKHOUSE_PASSWORD": "synthetic-only"}


class ProductionGateTests(unittest.TestCase):
    def test_every_missing_authorization_or_target_pin_rejects_before_sdk(self):
        for key in ENV:
            if key in ("HISTORICAL_API_ENABLED", "HISTORICAL_SERVING_MODE"):
                continue
            for value in ("", "wrong"):
                with self.subTest(key=key, value=value), patch.dict(os.environ, {**ENV, key: value}, clear=True), \
                     patch("application.historical_connection.clickhouse_connect.get_client") as sdk:
                    # A wrong nonempty password/valid username can only be checked by the server.
                    if key in ("HISTORICAL_CLICKHOUSE_USER", "HISTORICAL_CLICKHOUSE_PASSWORD") and value:
                        continue
                    with self.assertRaises(Exception) as error:
                        persistent_client()
                    self.assertEqual(503, error.exception.status)
                    sdk.assert_not_called()

    def test_identity_validation_uses_readonly_and_closes_wrong_target(self):
        for actual_uuid in (UUID, "different-server"):
            client = Mock()
            client.query.side_effect = [SimpleNamespace(column_names=["server_uuid", "database"],
                result_rows=[(actual_uuid, "football")]), SimpleNamespace(column_names=["engine"], result_rows=[("Atomic",)])]
            with patch.dict(os.environ, ENV, clear=True), \
                 patch("application.historical_connection.clickhouse_connect.get_client", return_value=client) as sdk:
                if actual_uuid == UUID:
                    self.assertEqual((client, "football"), create_historical_client())
                    client.close.assert_not_called()
                else:
                    with self.assertRaises(Exception) as error:
                        create_historical_client()
                    self.assertEqual(503, error.exception.status)
                    client.close.assert_called_once()
                self.assertEqual(0, sdk.call_args.kwargs["query_retries"])
                self.assertFalse(sdk.call_args.kwargs["show_clickhouse_errors"])
                self.assertTrue(all(c.kwargs["settings"] == {"readonly": 1} for c in client.query.call_args_list))

    def test_unknown_mode_no_optin_and_wrong_contract_are_rejected(self):
        for env in ({}, {**ENV, "HISTORICAL_API_ENABLED": "false"}, {**ENV, "HISTORICAL_SERVING_MODE": "anything"}):
            with patch.dict(os.environ, env, clear=True), patch("application.historical_connection.clickhouse_connect.get_client") as sdk:
                with self.assertRaises(Exception):
                    create_historical_client()
                sdk.assert_not_called()
        with self.assertRaises(Exception):
            HistoricalRepository(Mock(), "football")
        with self.assertRaises(Exception):
            HistoricalRepository(Mock(), "football", contract=None, mode=MODE)

    def test_partial_or_missing_generation_is_not_ready(self):
        for rows in ([], [(UUID,)]):
            client = Mock()
            client.query.side_effect = [SimpleNamespace(column_names=["uuid"], result_rows=rows),
                                       SimpleNamespace(column_names=[], result_rows=[])]
            with self.assertRaises(Exception) as error:
                HistoricalRepository(client, "football", mode=MODE).load()
            self.assertEqual(503, error.exception.status)

    def test_untrusted_gold_contract_is_rejected(self):
        for data in ({}, {name: [] for name, _, _ in PINNED.datasets}):
            with self.assertRaises(Exception):
                validate_bundle(data)

    def test_sdk_exception_diagnostics_never_include_credentials(self):
        with patch.dict(os.environ, ENV, clear=True), \
             patch("application.historical_connection.clickhouse_connect.get_client", side_effect=ValueError("PRIVATE_SENTINEL")):
            with self.assertRaises(Exception) as error:
                persistent_client()
            self.assertEqual(503, error.exception.status)
            self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))
