"""Offline boundary tests: untrusted params, exact pins, safe results and IO gates."""
import json
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.orchestration.commands import (
    GOLD, SILVER, bronze_args, build_command, context, load_command, parse_result,
)
from src.orchestration.runtime import execute, expected_builds, invoke, run_cli

C = {"competition_id": 123, "season_id": 456}
H = "a" * 64
SNAPSHOT = {**C, "parent_sha256": H, "bronze_max_id": 12, "expected_builds": {}}


class OrchestrationTests(unittest.TestCase):
    def test_freeze_does_not_double_count_source_retries(self):
        with patch("src.orchestration.runtime.catalog", return_value={"silver": [], "gold": [], "bronze_max_id": 12}):
            result = execute({"step": "freeze", "context": C,
                              "snapshot": {**SNAPSHOT, "transport_retries": 5}})
        self.assertEqual(result["transport_retries"], 0)
        self.assertEqual(result["bronze_max_id"], 12)

    def test_shared_source_catalog_change_stops_before_ingestion(self):
        source = {**C, "matches_sha256": H, "catalog_sha256": H, "match_count": 1}
        with patch("src.orchestration.runtime.run_cli", return_value=(json.dumps(source), "")) as cli:
            with patch("src.orchestration.runtime.catalog", return_value={"parents": [{"sha256": H}], "shared_catalog_shas": ["b" * 64]}):
                with self.assertRaises(ValueError):
                    execute({"step": "source", "context": C})
            self.assertEqual(cli.call_count, 1)

    def test_bootstrap_preserves_existing_secrets_and_command_has_no_newline(self):
        path = Path(__file__).resolve().parents[1] / "infrastructure/airflow/bootstrap.py"
        spec = importlib.util.spec_from_file_location("airflow_bootstrap_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            module.ROOT = Path(directory) / "secrets"
            module.LOGS = Path(directory) / "logs"
            with patch.object(module.os, "chown"), contextlib.redirect_stdout(io.StringIO()) as output:
                module.bootstrap()
                before = {p.name: p.read_bytes() for p in module.ROOT.iterdir()}
                module.bootstrap()
                self.assertEqual(before, {p.name: p.read_bytes() for p in module.ROOT.iterdir()})
            self.assertNotIn(before["db_password"].decode(), output.getvalue())
            with patch.object(module.sys, "argv", ["bootstrap.py", "connection"]), contextlib.redirect_stdout(io.StringIO()) as connection:
                module.main()
            self.assertNotIn("\n", connection.getvalue())
            self.assertTrue(connection.getvalue().endswith(":5432/airflow"))

    def test_bronze_both_summary_formats_are_parsed(self):
        for prefix in ("", "Objects "):
            output = ("Downloaded: 2\nUploaded: 0\nUnchanged: 2\nRegistered: 0\nAlready registered: 2"
                      if not prefix else "Objects downloaded: 0\nObjects uploaded: 0\nObjects unchanged: 68\nObjects registered: 0\nObjects already registered: 68")
            result = parse_result(output)
            self.assertEqual(result["uploaded"], 0)
            self.assertEqual(result["registered"], 0)
            self.assertEqual(result["reused"], 2 if not prefix else 68)

    def test_strict_context_rejects_missing_bool_string_float_and_range(self):
        for value in (None, True, "9", 9.0, 0, -1, 2**32, "9; command"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                context({"competition_id": value, "season_id": 1})
        with self.assertRaises(ValueError):
            context({})
        self.assertEqual(context(C), C)

    def test_six_silver_jobs_use_frozen_bronze_matches_requires_teams(self):
        for dataset in SILVER:
            upstream = {"teams": {"build_id": "b" * 64}} if dataset == "matches" else {}
            argv = build_command("silver", dataset, SNAPSHOT, upstream, True)
            self.assertIn("--check-only", argv)
            self.assertEqual(argv[argv.index("--parent-sha256") + 1], H)
            self.assertIn("--teams-build-id" if dataset == "matches" else "--bronze-max-id", argv)
            self.assertNotIn("--limit", argv)

    def test_gold_dependencies_exact_no_latest_or_defaults(self):
        for dataset, required in GOLD.items():
            upstream = {name: {**C, "build_id": str(i + 1) * 64} for i, name in enumerate(required)}
            argv = build_command("gold", dataset, SNAPSHOT, upstream, False)
            self.assertEqual(argv.count("--silver-build"), len(required))
            self.assertNotIn("--check-only", argv)
            with self.assertRaises(ValueError):
                build_command("gold", dataset, SNAPSHOT, {}, False)

    def test_load_is_separate_from_preflight_and_keeps_v2_pins(self):
        upstream = {name: {"build_id": H} for name in GOLD["team_match_stats"]}
        check = load_command("gold", "team_match_stats", SNAPSHOT, {"build_id": H}, upstream, True)
        load = load_command("gold", "team_match_stats", SNAPSHOT, {"build_id": H}, upstream, False)
        self.assertEqual(check, load + ["--check-only"])
        self.assertIn("v2", check)
        self.assertEqual(check.count("--silver-build"), 4)

    def test_build_parser_accepts_repeated_equal_rejects_conflict_or_missing(self):
        self.assertEqual(parse_result(f"Build ID: {H}\nBuild ID: {H}", require_build=True)["build_id"], H)
        for output in ("", f"Build ID: {H}\nBuild ID: {'b' * 64}"):
            with self.assertRaises(ValueError):
                parse_result(output, require_build=True)

    def test_raw_secret_text_never_becomes_result(self):
        output = f"S3_SECRET_KEY=synthetic-secret\nBuild ID: {H}\nOutput status: UNCHANGED / ALREADY_BUILT\nCatalog: ALREADY_REGISTERED\nOutput rows: 12"
        result = parse_result(output, require_build=True)
        self.assertNotIn("synthetic-secret", json.dumps(result))
        self.assertEqual(result["row_count"], 12)

    def test_run_cli_uses_argv_no_shell_and_safe_failure(self):
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="synthetic-password exception=IntegrityError", stdout="secret")) as run:
            with self.assertRaises(RuntimeError) as error:
                run_cli(["check_statsbomb_source.py", "--competition-id", "123"])
            self.assertNotIn("synthetic-password", str(error.exception))
            self.assertIn("IntegrityError", str(error.exception))
            self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_invalid_context_fails_before_subprocess_or_catalog(self):
        with patch("src.orchestration.runtime.run_cli") as cli, patch("src.orchestration.runtime.catalog") as catalog:
            with self.assertRaises(ValueError):
                execute({"step": "parent", "context": {"competition_id": 0, "season_id": 1}})
            cli.assert_not_called()
            catalog.assert_not_called()

    def test_source_change_stops_before_ingestion(self):
        with patch("src.orchestration.runtime.run_cli", return_value=(json.dumps({**C, "matches_sha256": H, "catalog_sha256": H, "match_count": 1}), "")) as cli:
            with patch("src.orchestration.runtime.catalog", return_value={"parents": [{"sha256": "b" * 64}], "silver": [], "gold": []}):
                with self.assertRaises(ValueError):
                    execute({"step": "source", "context": C})
            self.assertEqual(cli.call_count, 1)
            self.assertEqual(cli.call_args.args[0][0], "check_statsbomb_source.py")

    def test_ambiguous_catalog_has_no_latest_fallback(self):
        row = {"dataset": "teams", "transform_version": "teams_v1", "build_id": H}
        with self.assertRaises(ValueError):
            expected_builds({"silver": [row, row], "gold": []})

    def test_identity_change_rejected_by_check_before_publish(self):
        snapshot = {**SNAPSHOT, "expected_builds": {"silver/teams": "b" * 64}}
        with patch("src.orchestration.runtime.run_cli", return_value=(f"Build ID: {H}\nCHECK ONLY - nothing published", "")) as cli:
            with self.assertRaises(ValueError):
                execute({"step": "build_check", "context": C, "snapshot": snapshot, "layer": "silver", "dataset": "teams"})
            self.assertIn("--check-only", cli.call_args.args[0])

    def test_boundary_is_required_and_positive(self):
        for boundary in (None, True, 0, "12"):
            with self.assertRaises(ValueError):
                bronze_args({**SNAPSHOT, "bronze_max_id": boundary})

    def test_foreign_upstream_rejected_before_cli(self):
        with patch("src.orchestration.runtime.run_cli") as cli:
            with self.assertRaises(ValueError):
                execute({"step": "build_check", "context": C, "snapshot": SNAPSHOT, "layer": "silver", "dataset": "matches",
                         "upstream": {"teams": {"competition_id": 99, "season_id": 1, "build_id": H}}})
            cli.assert_not_called()
