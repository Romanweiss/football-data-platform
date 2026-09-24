"""Every dataset follows one immutable load/validation/recovery contract, offline."""

import io
import os
import re
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from clickhouse_model_fakes import DatasetClient, dataset_fixture
from test_clickhouse_silver_input import ENV, seed_manifest
from src.analytics import loader, silver_input
from src.analytics.job import LoadDiagnostics
from src.analytics.specs import CLI_DATASETS, SPECS, EVENT_IDENTITY, EVENT_ORDER
from src.analytics.validation import ClickHouseBuildConflictError, ClickHouseIntegrityError
from src.silver.manifest import SilverIntegrityError
from scripts import load_clickhouse_silver as cli


class DatasetSpecsTests(unittest.TestCase):
    def test_known_immutable_specs_and_cli(self):
        self.assertEqual(tuple(CLI_DATASETS), ("event-core", "passes", "shots", "teams", "players", "match-squads"))
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                self.assertEqual(spec.clickhouse_table, spec.dataset)
                self.assertEqual(spec.transform_version, spec.dataset + "_v1")
                self.assertEqual(spec.context_columns, ("competition_id", "season_id"))
                with self.assertRaises(FrozenInstanceError):
                    spec.dataset = "other"
        for name in ("event_core", "pass_events", "shot_events"):
            self.assertEqual(SPECS[name].identity_columns, EVENT_IDENTITY)
            self.assertEqual(SPECS[name].order_by, EVENT_ORDER)
        self.assertEqual(SPECS["match_squads"].identity_columns, ("match_id", "team_id", "player_id"))
        self.assertNotIn("team_id", dict(SPECS["players"].columns))

    def test_projection_explicit_safe_precision_and_uuid(self):
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                sql = loader.insert_sql(spec=spec)
                self.assertNotIn("SELECT *", sql)
                self.assertNotIn("Float32", sql)
                self.assertNotIn("secret", sql)
                self.assertNotIn("access_key", sql)
                self.assertIn("silver_build_id", sql)
                self.assertIn("%(build_id)s", sql)
                for name, kind in spec.columns:
                    self.assertIn(f"`{name}`", sql.split("\nSELECT")[0])
                    self.assertIn(f" AS `{name}`", sql)
                    if "Float64" in kind:
                        self.assertIn(f"accurateCast(`{name}`, '{kind}')", sql)
        self.assertIn("toUUID(`key_pass_id`)", loader.insert_sql(spec=SPECS["shot_events"]))
        self.assertEqual(dict(SPECS["players"].columns)["country_name"], "LowCardinality(Nullable(String))")

    def test_migration_003_exact_schemas_and_keys_no_destructive_ddl(self):
        path = Path(__file__).resolve().parents[1] / "infrastructure/clickhouse/migrations/003_create_remaining_silver_tables.sql"
        ddl = path.read_text()
        statements = [s.strip() for s in ddl.split(";") if s.strip()]
        self.assertEqual(len(statements), 5)
        for spec, statement in zip(list(SPECS.values())[1:], statements, strict=True):
            self.assertTrue(statement.startswith(f"CREATE TABLE IF NOT EXISTS {spec.target}\n("))
            body = statement.split("\n(", 1)[1].split("\n)\nENGINE", 1)[0]
            actual = tuple(tuple(line.strip().rstrip(",").split(" ", 1)) for line in body.splitlines() if line.strip())
            expected = (*spec.target_columns[:-1], ("loaded_at", "DateTime64(3, 'UTC') DEFAULT now64(3)"))
            self.assertEqual(actual, expected)
            self.assertIn("ENGINE = MergeTree", statement)
            self.assertIn(f"PARTITION BY ({', '.join(spec.context_columns)})", statement)
            self.assertIn(f"ORDER BY ({', '.join(spec.order_by)})", statement)
            self.assertIn("non_replicated_deduplication_window = 1000", statement)
        self.assertIsNone(re.search(r"\b(DROP|DELETE|TRUNCATE|ALTER|Float32)\b", ddl))

    def test_cli_all_known_datasets_and_invalid_inputs_before_io(self):
        with patch.object(cli, "run_job", return_value=0) as run:
            for option, dataset in CLI_DATASETS.items():
                self.assertEqual(cli.main(["--dataset", option, "--check-only", "--build-id", "a" * 64]), 0)
                run.assert_called_with(dataset=dataset, build_id="a" * 64, check_only=True)
            run.reset_mock()
            for args in ([], ["--dataset", "arbitrary"], ["--dataset", "teams", "--build-id", "secret"],
                         ["--dataset", "teams", "--prefix", "anything"]):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    cli.main(args)
            run.assert_not_called()


class DatasetManifestTests(unittest.TestCase):
    def test_all_manifests_and_latest_exact_resolution(self):
        with patch.dict(os.environ, ENV, clear=True):
            for spec in SPECS.values():
                with self.subTest(dataset=spec.dataset):
                    s3, build, manifest = dataset_fixture(spec)
                    self.assertEqual(silver_input.verify_silver_manifest(s3, build, spec=spec), manifest)
                    self.assertEqual("match_count" in manifest, spec.has_match_count)
                    with patch.object(silver_input, "find_latest_silver_build", return_value=build) as latest:
                        self.assertEqual(silver_input.resolve_silver_build(None, spec=spec), build)
                        latest.assert_called_once_with(None, source="statsbomb", dataset=spec.dataset, competition_id=43, season_id=106)
                    with patch.object(silver_input, "find_silver_build", return_value=build) as exact:
                        self.assertEqual(silver_input.resolve_silver_build(None, build["build_id"], spec=spec), build)
                        exact.assert_called_once_with(None, dataset=spec.dataset, competition_id=43, season_id=106, build_id=build["build_id"])
                    self.assertTrue(all(call[2].endswith("_manifest.json") for call in s3.calls if call[0] == "get"))

    def test_each_manifest_mismatch_fails(self):
        for spec in SPECS.values():
            for field, value in (("row_count", 9), ("file_count", 9), ("build_id", "e" * 64),
                                 ("schema_sha256", "e" * 64), ("input_fingerprint", "e" * 64),
                                 ("dataset", "wrong"), ("transform_version", "wrong")):
                with self.subTest(dataset=spec.dataset, field=field):
                    s3, build, manifest = dataset_fixture(spec)
                    seed_manifest(s3, build, {**manifest, field: value})
                    with self.assertRaises(SilverIntegrityError):
                        silver_input.verify_silver_manifest(s3, build, spec=spec)


class DatasetLoaderTests(unittest.TestCase):
    def setup_case(self, spec):
        client = DatasetClient(spec)
        store = {}
        def register(connection, **record):
            store.update(record)
            return True
        stack = ExitStack()
        self.addCleanup(stack.close)
        find = stack.enter_context(patch.object(loader, "find_clickhouse_load", side_effect=lambda *a, **k: store or None))
        save = stack.enter_context(patch.object(loader, "register_clickhouse_load", side_effect=register))
        stack.enter_context(redirect_stdout(io.StringIO()))
        def run(check_only=False):
            return loader.load_dataset(client, None, client.build, client.manifest, "https://example.invalid/exact/part-*.parquet",
                                       spec=spec, check_only=check_only, diagnostics=LoadDiagnostics())
        return client, store, save, register, run, stack

    def test_first_load_second_load_and_tokens_every_dataset(self):
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                client, store, save, _, run, stack = self.setup_case(spec)
                with stack:
                    self.assertEqual(run()["catalog"], "REGISTERED")
                    self.assertEqual(run(), {"output_status": "UNCHANGED / ALREADY_LOADED", "catalog": "ALREADY_REGISTERED"})
                    self.assertEqual(len(client.inserts), 1)
                    self.assertEqual(client.inserts[0][1]["settings"]["insert_deduplication_token"], client.build["build_id"])
                    self.assertEqual(store["dataset"], spec.dataset)
                    self.assertEqual(store["clickhouse_table"], spec.dataset)
                    save.assert_called_once()

    def test_partial_and_excessive_target_every_dataset(self):
        for spec in SPECS.values():
            for rows in (1, 5, 7):
                client, _, save, _, run, stack = self.setup_case(spec)
                with self.subTest(dataset=spec.dataset, rows=rows), stack:
                    client.target = (rows, *client.source[1:])
                    with self.assertRaises(ClickHouseIntegrityError):
                        run()
                    self.assertEqual(client.inserts, [])
                    save.assert_not_called()

    def test_different_or_mixed_build_conflict_even_check_only(self):
        for spec in SPECS.values():
            for check_only in (True, False):
                for own in (False, True):
                    client, _, save, _, run, stack = self.setup_case(spec)
                    with self.subTest(dataset=spec.dataset, own=own, check_only=check_only), stack:
                        client.other_rows = 1
                        if own:
                            client.target = client.source
                        with self.assertRaises(ClickHouseBuildConflictError):
                            run(check_only)
                        self.assertEqual(client.inserts, [])
                        save.assert_not_called()

    def test_catalog_failure_recovers_without_second_insert_every_dataset(self):
        for spec in SPECS.values():
            client, _, save, register, run, stack = self.setup_case(spec)
            with self.subTest(dataset=spec.dataset), stack:
                save.side_effect = RuntimeError("database failure")
                with self.assertRaises(RuntimeError):
                    run()
                save.side_effect = register
                self.assertEqual(run(), {"output_status": "UNCHANGED / ALREADY_LOADED", "catalog": "REGISTERED"})
                self.assertEqual(len(client.inserts), 1)

    def test_timeout_after_commit_recovery_every_dataset(self):
        for spec in SPECS.values():
            client, _, save, _, run, stack = self.setup_case(spec)
            with self.subTest(dataset=spec.dataset), stack:
                client.fail_after_insert = True
                with self.assertRaises(TimeoutError):
                    run()
                save.assert_not_called()
                client.fail_after_insert = False
                self.assertEqual(run()["output_status"], "UNCHANGED / ALREADY_LOADED")
                self.assertEqual(len(client.inserts), 1)

    def test_check_only_never_mutates_empty_or_complete_every_dataset(self):
        for spec in SPECS.values():
            client, _, save, _, run, stack = self.setup_case(spec)
            with self.subTest(dataset=spec.dataset), stack:
                self.assertFalse(run(True)["already_loaded"])
                client.target = client.source
                self.assertTrue(run(True)["already_loaded"])
                save.assert_not_called()
                self.assertEqual(client.inserts, [])

    def test_schema_source_and_post_insert_mismatches_every_dataset(self):
        for spec in SPECS.values():
            for failure in ("schema", "source", "target"):
                client, _, save, _, run, stack = self.setup_case(spec)
                with self.subTest(dataset=spec.dataset, failure=failure), stack:
                    if failure == "schema":
                        client.bad_schema = True
                    elif failure == "source":
                        client.source = (99, *client.source[1:])
                    else:
                        client.partial_insert = True
                    with self.assertRaises(ClickHouseIntegrityError):
                        run()
                    save.assert_not_called()
                    self.assertEqual(len(client.inserts), int(failure == "target"))

    def test_required_null_domain_and_squad_checks(self):
        for spec in list(SPECS.values())[1:]:
            client, _, save, _, run, stack = self.setup_case(spec)
            with self.subTest(dataset=spec.dataset), stack:
                client.source = (*client.source[:-1], 1)
                with self.assertRaises(ClickHouseIntegrityError):
                    run()
                self.assertEqual(client.inserts, [])
        client, _, save, _, run, stack = self.setup_case(SPECS["match_squads"])
        with stack:
            client.bad_teams = 1
            with self.assertRaises(ClickHouseIntegrityError):
                run()
            self.assertEqual(client.inserts, [])


if __name__ == "__main__":
    unittest.main()
