"""Offline Stage 4C mapping, migration, loader state machine and exact-delta tests."""

from context_fixtures import CONTEXT_ARGS, in_context
import copy
import io
import json
import unittest
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from unittest.mock import patch, MagicMock

import test_clickhouse_gold as loader_tests
from src.analytics import gold_job, gold_loader, gold_input
from src.analytics.gold_specs import SPECS, V2_SPECS, serving_spec
from src.analytics.stats_cutover import DELTA_METRICS, validate_deltas, compare_rows, view_bodies, validate_bi
from src.analytics.validation import ClickHouseIntegrityError
from src.gold.stats_snapshot import PINNED_STATS_INPUTS, validate_stats_snapshot
from src.gold import job as build_job
from src.gold.manifest import GoldIntegrityError
from gold_clickhouse_fakes import fixture

ROOT = Path(__file__).resolve().parents[1]
AUDIT = json.loads((ROOT / "docs/stage4b_shot_audit.json").read_text())


def stats_pins():
    return [arg for name, value in PINNED_STATS_INPUTS.items() for arg in ("--silver-build", name + "=" + value)]


def audit_fixture(spec):
    """Recorded affected keys + one unaffected key. All metric deltas stay exact."""
    old, new = [], []
    section = copy.deepcopy(AUDIT[spec.dataset])
    for item in section["differences"]:
        row = {name: 0 for name, _ in spec.columns}
        row.update(competition_id=43, season_id=106)
        row.update({name: item[name] for name in (*spec.identity_columns, "team_name")})
        if "player_id" in spec.identity_columns:
            row["player_name"] = item["player_name"]
        after = dict(row)
        for metric, delta in DELTA_METRICS.items():
            if metric in row:
                row[metric] = 100 + item[delta]
                after[metric] = 100
        for metric, normal in (("shot_count", "normal_shots"), ("shot_xg", "normal_xg"), ("shot_goals", "normal_goals")):
            row[metric], after[metric] = item[metric], item[normal]
        old.append(row)
        new.append(after)
    unchanged = {**old[0], "match_id": 999999}
    old.append(unchanged)
    new.append(dict(unchanged))
    section["rows"] = len(old)
    return old, new, {spec.dataset: section}


class CutoverContractTests(unittest.TestCase):
    def test_closed_registry_and_v1_unchanged(self):
        for name, old in SPECS.items():
            self.assertIs(serving_spec(name, "v1"), old)
            new = serving_spec(name, "v2")
            self.assertEqual(new.target, "football." + name + "_v2")
            self.assertEqual(new.transform_version, name + "_v2")
            self.assertEqual(new.target_columns, old.target_columns)
        for dataset, version in (("unknown", "v2"), ("match_results", "v2"), ("team_match_stats", "some_table")):
            with self.assertRaises(ValueError): serving_spec(dataset, version)

    def test_cli_arbitrary_destination_and_latest_v2_rejected_before_io(self):
        with patch.object(gold_job, "create_postgres_connection") as connect, redirect_stderr(io.StringIO()):
            for extra in (["--table-override", "football.team_match_stats"], ["--table", "random"], ["--transform-version", "v2"]):
                with self.assertRaises(SystemExit): gold_job.main(CONTEXT_ARGS + ["--dataset", "team-match-stats", *extra])
            connect.assert_not_called()
        parsed = gold_job.parse_args(CONTEXT_ARGS + stats_pins() + ["--dataset", "team-match-stats", "--transform-version", "v2", "--build-id", "a" * 64])
        self.assertEqual(parsed.transform_version, "v2")

    def test_exact_pins_are_mandatory_for_build_and_load(self):
        valid = [{"dataset": name, "build_id": value} for name, value in PINNED_STATS_INPUTS.items()]
        validate_stats_snapshot(valid)
        for wrong in (valid[:-1], valid + valid[:1], [{**r, "build_id": "f" * 64} for r in valid]):
            with self.assertRaises(GoldIntegrityError): validate_stats_snapshot(wrong)
        args = ["--dataset", "team-match-stats", "--transform-version", "team_match_stats_v2", "--check-only"]
        for item in valid:
            args += ["--silver-build", item["dataset"] + "=" + "f" * 64]
        with patch.object(build_job, "create_postgres_connection") as connect, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_job.main(CONTEXT_ARGS + args)
        connect.assert_not_called()

    def test_v2_exact_manifest_resolution_and_version_mismatch(self):
        from test_clickhouse_silver_input import ENV
        import os
        spec = V2_SPECS["team_match_stats"]
        client, build, manifest = fixture(spec)
        with patch.dict(os.environ, ENV, clear=True), patch.object(gold_input, "find_gold_build", return_value=build):
            self.assertEqual(in_context(gold_input.resolve_gold_build)(None, build["build_id"], spec=spec), build)
            with self.assertRaises(GoldIntegrityError):
                in_context(gold_input.resolve_gold_build)(None, build["build_id"], spec=SPECS[spec.dataset])
        self.assertEqual(gold_input.verify_gold_manifest(client, build), manifest)
        self.assertEqual(build["transform_version"], "team_match_stats_v2")

    def test_v2_cli_uses_fixed_target_lock_and_rejects_wrong_pins_before_clickhouse(self):
        for alias, name in (("team-match-stats", "team_match_stats"), ("player-match-stats", "player_match_stats")):
            spec = V2_SPECS[name]
            _, build, manifest = fixture(spec)
            manifest["inputs"] = [{"dataset": dataset, "build_id": value, "s3_prefix": f"football/silver/statsbomb/{dataset}/competition_id=43/season_id=106/build_id={value}/"} for dataset, value in PINNED_STATS_INPUTS.items()]
            with ExitStack() as stack:
                for resource in ("create_postgres_connection", "create_s3_client"):
                    stack.enter_context(patch.object(gold_job, resource, return_value=MagicMock()))
                stack.enter_context(patch.object(gold_job, "resolve_gold_build", return_value=build))
                stack.enter_context(patch.object(gold_job, "verify_gold_manifest", return_value=manifest))
                stack.enter_context(patch.object(gold_job, "parquet_url", return_value="https://example.invalid/part-*.parquet"))
                stack.enter_context(patch.object(gold_job, "verify_named_collection"))
                create_ch = stack.enter_context(patch.object(gold_job, "create_clickhouse_client"))
                lock = stack.enter_context(patch.object(gold_job, "clickhouse_load_lock"))
                load = stack.enter_context(patch.object(gold_job, "load_gold"))
                errors = stack.enter_context(redirect_stderr(io.StringIO()))
                args = ["--dataset", alias, "--transform-version", "v2", "--build-id", build["build_id"]]
                self.assertEqual(gold_job.main(CONTEXT_ARGS + stats_pins() + args), 0)
                self.assertIs(load.call_args.kwargs["spec"], spec)
                lock.assert_called_once()
                lock.reset_mock()
                self.assertEqual(gold_job.main(CONTEXT_ARGS + stats_pins() + [*args, "--check-only"]), 0)
                lock.assert_not_called()
                self.assertTrue(load.call_args.kwargs["check_only"])
                create_ch.reset_mock()
                load.reset_mock()
                manifest["inputs"][0]["build_id"] = "f" * 64
                self.assertEqual(gold_job.main(CONTEXT_ARGS + stats_pins() + args), 1)
                create_ch.assert_not_called()
                load.assert_not_called()
                self.assertIn("exception=GoldIntegrityError", errors.getvalue())

    def test_009_schema_and_settings_match_reviewed_v1(self):
        original = (ROOT / "infrastructure/clickhouse/migrations/004_create_gold_match_stats.sql").read_text()
        actual = (ROOT / "infrastructure/clickhouse/migrations/009_create_gold_stats_v2_shadow_tables.sql").read_text()
        actual = "\n".join(line for line in actual.splitlines() if not line.startswith("--")).strip()
        expected = original.replace("football.team_match_stats", "football.team_match_stats_v2").replace("football.player_match_stats", "football.player_match_stats_v2")
        expected = expected.replace("non_replicated_deduplication_window = 1000", "non_replicated_deduplication_window = 1000, index_granularity = 8192")
        self.assertEqual(actual, expected.strip())
        self.assertNotIn("VIEW", actual)

    def test_010_and_011_preserve_every_projection_from_008(self):
        original = (ROOT / "infrastructure/clickhouse/migrations/008_enrich_bi_match_results.sql").read_text()
        bodies = [s.split("\nAS\n", 1)[1].strip() for s in original.split(";") if s.strip()]
        self.assertEqual(view_bodies("v1"), bodies)
        expected = [s.replace("FROM football.team_match_stats AS", "FROM football.team_match_stats_v2 AS")
                    .replace("FROM football.player_match_stats AS", "FROM football.player_match_stats_v2 AS") for s in bodies]
        self.assertEqual(view_bodies("v2"), expected)

    def test_bi_validation_rejects_wrong_source_even_with_equal_counts(self):
        client = MagicMock()
        client.query.return_value.result_rows = [("CREATE VIEW AS SELECT * FROM football.team_match_stats AS t",)]
        with self.assertRaises(ClickHouseIntegrityError): validate_bi(client, version="v2")


class ExactDeltaTests(unittest.TestCase):
    def test_every_recorded_delta_and_unaffected_key(self):
        for spec in V2_SPECS.values():
            old, new, audit = audit_fixture(spec)
            self.assertEqual(validate_deltas(old, new, spec=spec, audit=audit), audit[spec.dataset]["affected_rows"])

    def test_redistributed_deltas_with_unchanged_totals_fail(self):
        for spec in V2_SPECS.values():
            old, new, audit = audit_fixture(spec)
            new[0]["event_count"] += 1
            new[1]["event_count"] -= 1
            with self.assertRaises(ClickHouseIntegrityError): validate_deltas(old, new, spec=spec, audit=audit)

    def test_unknown_affected_missing_duplicate_nonfinite_and_wrong_name_fail(self):
        spec = V2_SPECS["player_match_stats"]
        old, new, audit = audit_fixture(spec)
        for change in ("unexpected", "missing", "duplicate", "nan", "name", "pressure"):
            bad = copy.deepcopy(new)
            if change == "unexpected": bad[-1]["event_count"] += 1
            if change == "missing": bad.pop()
            if change == "duplicate": bad.append(bad[0])
            if change == "nan": bad[0]["shot_xg"] = float("nan")
            if change == "name": bad[0]["player_name"] = "wrong"
            if change == "pressure": bad[0]["under_pressure_events"] += 1
            with self.subTest(change=change), self.assertRaises(ClickHouseIntegrityError):
                validate_deltas(old, bad, spec=spec, audit=audit)

    def test_existing_float_tolerance_is_not_applied_to_counts(self):
        spec = V2_SPECS["team_match_stats"]
        old, new, audit = audit_fixture(spec)
        new[0]["shot_xg"] += 1e-12
        validate_deltas(old, new, spec=spec, audit=audit)
        new[0]["shot_count"] += 1
        with self.assertRaises(ClickHouseIntegrityError): validate_deltas(old, new, spec=spec, audit=audit)


class ShadowLoaderTests(loader_tests.GoldServingLoaderTests):
    """Existing recovery/conflict/lock-independent loader tests against fixed shadows."""
    def case(self, spec):
        return super().case(V2_SPECS[spec.dataset])

    def test_occupied_v1_does_not_participate_and_catalog_records_real_shadow(self):
        for spec in SPECS.values():
            stack, client, store, _, _, run, _ = self.case(spec)
            with stack:
                # Fake only serves selected shadow. Fail if the loader inspects v1.
                query = client.query
                def checked(sql, **options):
                    self.assertNotIn("FROM " + spec.target + " ", sql)
                    return query(sql, **options)
                client.query = checked
                self.assertEqual(run()["output_status"], "LOADED")
                self.assertEqual(store["clickhouse_table"], spec.dataset + "_v2")
                self.assertEqual(client.inserts[0][0].split(" (")[0], "INSERT INTO football." + spec.dataset + "_v2")
                self.assertEqual(run()["catalog"], "ALREADY_REGISTERED")
