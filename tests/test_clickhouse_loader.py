"""Offline state machine, SQL contracts and safe CLI diagnostics."""

from context_fixtures import in_context

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_clickhouse_silver_input import fixture
from src.analytics import event_core as loader
from src.analytics import job
from scripts.load_clickhouse_event_core import main


class FakeClickHouse:
    def __init__(self):
        self.metrics = (0, 0, 0, 0, 0, 0, 0)
        self.source = (6, 2, 6, 43, 43, 106, 106)
        self.inserts = []
        self.queries = []
        self.timeout_after_commit = False

    def query(self, sql, **options):
        self.queries.append((sql, options))
        if sql.startswith("DESCRIBE"):
            rows = [(name, kind, "DEFAULT" if name == "loaded_at" else "", "now64(3)" if name == "loaded_at" else "")
                    for name, kind in loader.TARGET_COLUMNS]
        elif "system.tables" in sql:
            rows = [("MergeTree", "PARTITION BY (competition_id, season_id) "
                     "ORDER BY (competition_id, season_id, match_id, period, event_index, event_id) "
                     "SETTINGS non_replicated_deduplication_window = 1000")]
        elif "system.named_collections" in sql:
            rows = [(1,)]
        elif "FROM s3(" in sql:
            rows = [self.source]
        elif "uniqExact(silver_build_id)" in sql:
            rows = [(self.metrics[0], int(self.metrics[0] > 0), 0, options["parameters"]["build_id"])]
        else:
            rows = [self.metrics]
        return SimpleNamespace(result_rows=rows)

    def command(self, sql, **options):
        self.inserts.append((sql, options))
        self.metrics = self.source
        if self.timeout_after_commit:
            raise TimeoutError("sensitive server error with credentials")


class ClickHouseLoaderTests(unittest.TestCase):
    def setUp(self):
        _, self.build, self.manifest = fixture()
        self.client = FakeClickHouse()
        self.catalog = None
        self.find = patch("src.analytics.loader.find_clickhouse_load", side_effect=lambda *a, **k: self.catalog)
        self.register = patch("src.analytics.loader.register_clickhouse_load", side_effect=self.save)
        self.find_mock = self.find.start()
        self.register_mock = self.register.start()
        self.addCleanup(self.find.stop)
        self.addCleanup(self.register.stop)
        self.output = io.StringIO()
        redirect = redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def save(self, connection, **record):
        self.catalog = record
        return True

    def run_load(self, check_only=False):
        return loader.load_event_core(self.client, None, self.build, self.manifest,
                                      "https://test-bucket.s3.ru-3.storage.selcloud.ru/exact/part-*.parquet",
                                      check_only=check_only, diagnostics=job.LoadDiagnostics())

    def test_first_and_identical_second_load(self):
        self.assertEqual(self.run_load(), {"output_status": "LOADED", "catalog": "REGISTERED"})
        self.assertEqual(self.run_load(), {"output_status": "UNCHANGED / ALREADY_LOADED", "catalog": "ALREADY_REGISTERED"})
        self.assertEqual(len(self.client.inserts), 1)
        self.register_mock.assert_called_once()
        sql, options = self.client.inserts[0]
        self.assertEqual(options["settings"]["insert_deduplication_token"], self.build["build_id"])
        self.assertEqual(options["parameters"]["build_id"], self.build["build_id"])
        self.assertNotIn("SELECT *", sql)
        self.assertIn("ORDER BY ALL", sql)
        self.assertNotIn("FINAL", sql)
        for name, _ in loader.EVENT_COLUMNS:
            self.assertIn(f"AS `{name}`", sql)
        self.assertIn("toUUID(`event_id`)", sql)
        self.assertIn("accurateCast(`player_id`, 'Nullable(UInt32)')", sql)
        self.assertNotIn("access_key", sql)
        self.assertNotIn("secret", sql)

    def test_complete_unregistered_target_skips_insert_and_registers(self):
        self.client.metrics = self.client.source
        self.assertEqual(self.run_load()["catalog"], "REGISTERED")
        self.assertEqual(self.client.inserts, [])

    def test_partial_excess_rows_fail_without_mutations(self):
        for count in (1, 5, 7):
            self.client.metrics = (count, 2, count, 43, 43, 106, 106)
            with self.subTest(count=count), self.assertRaises(loader.ClickHouseIntegrityError):
                self.run_load()
        self.assertEqual(self.client.inserts, [])
        self.register_mock.assert_not_called()

    def test_registered_missing_target_never_reloads(self):
        self.catalog = loader.load_record(self.build)
        with self.assertRaises(loader.ClickHouseIntegrityError):
            self.run_load()
        self.assertEqual(self.client.inserts, [])

    def test_database_failure_then_recovery_without_second_insert(self):
        self.register_mock.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(RuntimeError):
            self.run_load()
        self.assertEqual(len(self.client.inserts), 1)
        self.register_mock.side_effect = self.save
        self.assertEqual(self.run_load(), {"output_status": "UNCHANGED / ALREADY_LOADED", "catalog": "REGISTERED"})
        self.assertEqual(len(self.client.inserts), 1)

    def test_ambiguous_insert_commit_then_recovery_without_second_insert(self):
        self.client.timeout_after_commit = True
        with self.assertRaises(TimeoutError):
            self.run_load()
        self.register_mock.assert_not_called()
        self.client.timeout_after_commit = False
        self.assertEqual(self.run_load()["output_status"], "UNCHANGED / ALREADY_LOADED")
        self.assertEqual(len(self.client.inserts), 1)

    def test_check_only_empty_and_complete_never_mutates(self):
        self.assertFalse(self.run_load(True)["already_loaded"])
        self.client.metrics = self.client.source
        self.assertTrue(self.run_load(True)["already_loaded"])
        self.register_mock.assert_not_called()
        self.assertEqual(self.client.inserts, [])
        for text in ("Would load: yes", "Would load: no", "CHECK ONLY - nothing loaded"):
            self.assertIn(text, self.output.getvalue())

    def test_source_and_target_dq_failures(self):
        for position in range(7):
            metrics = list(self.client.source)
            metrics[position] += 1
            with self.subTest(position=position), self.assertRaises(loader.ClickHouseIntegrityError):
                loader.validate_metrics(tuple(metrics), self.manifest)
        self.client.metrics = (6, 2, 5, 43, 43, 106, 106)
        with self.assertRaises(loader.ClickHouseIntegrityError):
            self.run_load()
        self.register_mock.assert_not_called()
        self.assertEqual(self.client.inserts, [])

    def test_post_insert_validation_before_registration(self):
        def partial_insert(*args, **kwargs):
            self.client.metrics = (3, 1, 3, 43, 43, 106, 106)
        self.client.command = partial_insert
        with self.assertRaises(loader.ClickHouseIntegrityError):
            self.run_load()
        self.register_mock.assert_not_called()

    def test_catalog_conflict_fails(self):
        self.catalog = {**loader.load_record(self.build), "row_count": 999}
        with self.assertRaises(loader.ClickHouseIntegrityError):
            self.run_load()
        self.assertEqual(self.client.inserts, [])

    def test_duplicate_registration_validates_conflicting_row(self):
        self.client.metrics = self.client.source
        def duplicate(connection, **record):
            self.catalog = record
            return False
        self.register_mock.side_effect = duplicate
        self.assertEqual(self.run_load()["catalog"], "ALREADY_REGISTERED")
        self.assertEqual(self.client.inserts, [])

    def test_check_only_partial_target_fails_without_registration(self):
        self.client.metrics = (1, 1, 1, 43, 43, 106, 106)
        with self.assertRaises(loader.ClickHouseIntegrityError):
            self.run_load(True)
        self.assertEqual(self.client.inserts, [])
        self.register_mock.assert_not_called()

    def test_source_mismatch_fails_before_insert(self):
        self.client.source = (5, 2, 5, 43, 43, 106, 106)
        with self.assertRaises(loader.ClickHouseIntegrityError):
            self.run_load()
        self.assertEqual(self.client.inserts, [])
        self.register_mock.assert_not_called()

    def test_table_engine_sorting_and_dedup_mismatches(self):
        schema = self.client.query("DESCRIBE").result_rows
        engine, ddl = self.client.query("system.tables").result_rows[0]
        for values in (("ReplacingMergeTree", ddl), (engine, ddl.replace("1000", "0")),
                       (engine, ddl.replace("ORDER BY (competition_id, season_id, match_id, period, event_index, event_id)", "ORDER BY event_id"))):
            bad = MagicMock()
            bad.query.side_effect = [SimpleNamespace(result_rows=schema), SimpleNamespace(result_rows=[values])]
            with self.subTest(values=values), self.assertRaises(loader.ClickHouseIntegrityError):
                loader.validate_table_schema(bad)

    def test_schema_mismatch_and_named_collection_absent(self):
        bad = MagicMock()
        bad.query.return_value.result_rows = [("wrong", "String")]
        with self.assertRaises(loader.ClickHouseIntegrityError):
            loader.validate_table_schema(bad)
        bad.query.return_value.result_rows = [(0,)]
        with self.assertRaises(loader.ClickHouseIntegrityError):
            loader.verify_named_collection(bad)
        loader.verify_named_collection(self.client)
        self.assertNotIn("collection,", self.client.queries[-1][0])

    def test_migration_schema_matches_python_contract(self):
        migrations = Path(__file__).resolve().parents[1] / "infrastructure/clickhouse/migrations"
        ddl = (migrations / "001_create_event_core.sql").read_text()
        widening = (migrations / "002_event_core_float64_metrics.sql").read_text()
        metrics = ("location_x", "location_y", "duration")
        self.assertEqual(widening.strip(), "ALTER TABLE football.event_core\n" + ",\n".join(
            f"MODIFY COLUMN {name} Nullable(Float64)" for name in metrics
        ) + ";")
        for name, kind in loader.TARGET_COLUMNS:
            if name in metrics:
                self.assertIn(f"{name} Nullable(Float32)", ddl)  # Applied migration 001 stays unchanged.
                self.assertIn(f"MODIFY COLUMN {name} {kind}", widening)
            else:
                self.assertIn(f"{name} {kind}", ddl)
        self.assertIn("ENGINE = MergeTree", ddl)
        self.assertNotIn("ReplacingMergeTree", ddl)
        self.assertIn("non_replicated_deduplication_window = 1000", ddl)

    def test_metrics_schema_requires_nullable_float64(self):
        for name in ("location_x", "location_y", "duration"):
            with self.subTest(name=name):
                self.assertEqual(dict(loader.EVENT_COLUMNS)[name], "Nullable(Float64)")
                self.assertEqual(dict(loader.TARGET_COLUMNS)[name], "Nullable(Float64)")
        loader.validate_table_schema(self.client)

    def test_metrics_float32_schema_rejected(self):
        schema = self.client.query("DESCRIBE").result_rows
        for name in ("location_x", "location_y", "duration"):
            bad = MagicMock()
            bad.query.return_value.result_rows = [
                (row[0], "Nullable(Float32)", *row[2:]) if row[0] == name else row
                for row in schema
            ]
            with self.subTest(name=name), self.assertRaises(loader.ClickHouseIntegrityError):
                loader.validate_table_schema(bad)

    def test_metrics_insert_keeps_accurate_cast_to_float64(self):
        sql = loader.insert_sql()
        for name in ("location_x", "location_y", "duration"):
            with self.subTest(name=name):
                self.assertIn(f"accurateCast(`{name}`, 'Nullable(Float64)') AS `{name}`", sql)
        self.assertNotIn("Float32", sql)


class ClickHouseJobTests(unittest.TestCase):
    @patch.object(job, "run_job")
    def test_invalid_cli_rejected_before_io(self, run):
        with redirect_stderr(io.StringIO()):
            for argv in (["--build-id", "not-hex"], ["--build-id", "A" * 64], ["--prefix", "s3://anything"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    main(argv)
        run.assert_not_called()

    def test_all_job_failures_safe_without_raw_text(self):
        secret = "FAKE-SECRET-ACCESS-KEY-and-password"
        with patch.object(job, "create_postgres_connection", side_effect=TimeoutError(secret)):
            output = io.StringIO()
            with redirect_stderr(output):
                self.assertEqual(in_context(job.run_job)(), 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("exception=TimeoutError", output.getvalue())
        self.assertIn("stage=configuration", output.getvalue())
        diagnostics = job.LoadDiagnostics("ClickHouse INSERT", "insert_select")
        self.assertNotIn(secret, diagnostics.failure(TimeoutError(secret)))
        self.assertIn("category=integrity", diagnostics.failure(loader.ClickHouseIntegrityError(secret)))

    @patch.object(job, "clickhouse_load_lock")
    @patch.object(job, "load_dataset")
    @patch.object(job, "verify_named_collection")
    @patch.object(job, "create_clickhouse_client")
    @patch.object(job, "verify_silver_manifest")
    @patch.object(job, "parquet_url", return_value="https://test.invalid/part-*.parquet")
    @patch.object(job, "create_s3_client")
    @patch.object(job, "resolve_silver_build")
    @patch.object(job, "create_postgres_connection")
    def test_smoke_and_check_only_paths(self, pg, resolve, s3, url, verify, ch, named, load, lock):
        _, build, manifest = fixture()
        resolve.return_value, verify.return_value = build, manifest
        ch.return_value.server_version = "25.8.23.13"
        ch.return_value.query.return_value.result_rows = [(6, 2, 6, 43, 43, 106, 106)]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(in_context(job.run_job)(smoke=True), 0)
        self.assertIn("CLICKHOUSE S3 CHECK PASSED", output.getvalue())
        load.assert_not_called()
        lock.assert_not_called()
        ch.return_value.command.assert_not_called()
        self.assertEqual(in_context(job.run_job)(check_only=True), 0)
        self.assertTrue(load.call_args.kwargs["check_only"])
        lock.assert_not_called()
        self.assertEqual(in_context(job.run_job)(), 0)
        lock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
