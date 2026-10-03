"""Generic CLI context parsing and forwarding, no network."""
import argparse
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch
from src.analytics.context import add_context_arguments, context_from_args
from scripts import check_clickhouse_model as model, check_clickhouse_gold_model as gold


class ContextArgumentTests(unittest.TestCase):
    def test_explicit_context_and_invalid_ids(self):
        parser = argparse.ArgumentParser()
        add_context_arguments(parser)
        self.assertEqual(context_from_args(parser.parse_args(["--competition-id", "7", "--season-id", "9"])),
                         {"competition_id": 7, "season_id": 9})
        from src.analytics.context import context_id
        for value in ("0", "-1", "1 OR 1=1", "4294967296"):
            with self.assertRaises(argparse.ArgumentTypeError):
                context_id(value)

    def test_cli_forwards_non_wc_context_without_cloud_calls(self):
        for module in (model, gold):
            with patch.object(module, "create_clickhouse_client", return_value=Mock()), \
                 patch.object(module, "create_postgres_connection", return_value=Mock()), \
                 patch.object(module, "check_model") as check, redirect_stdout(StringIO()):
                self.assertEqual(module.main(["--competition-id", "7", "--season-id", "9"]), 0)
                self.assertEqual(check.call_args.kwargs, {"competition_id": 7, "season_id": 9})
