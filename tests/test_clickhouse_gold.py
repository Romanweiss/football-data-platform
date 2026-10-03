"""Stage 3D offline contracts; no real service IO."""

import copy
import io
import os
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, patch

from gold_clickhouse_fakes import GoldClient, fixture
from gold_fakes import silver_inputs
from test_clickhouse_silver_input import ENV, seed_manifest
from src.analytics import gold_input, gold_job, gold_loader, gold_model
from src.analytics.gold_specs import SPECS, TEAM, PLAYER
from src.analytics.validation import ClickHouseIntegrityError
from src.common import postgres
from src.gold.manifest import GoldIntegrityError
from scripts import check_clickhouse_gold_model as model_cli


class GoldServingSpecTests(unittest.TestCase):
    def test_explicit_casts_frozen_specs_and_lineage(self):
        for spec in SPECS.values():
            with self.subTest(dataset=spec.dataset):
                with self.assertRaises(FrozenInstanceError):
                    spec.dataset = "other"
                sql = gold_loader.insert_sql(spec=spec)
                self.assertIn("gold_build_id", sql)
                for forbidden in ("silver_build_id", "SELECT *", "Float32", "secret", "access_key"):
                    self.assertNotIn(forbidden, sql)
                self.assertIn("s3(selectel_s3, url=%(url)s, format='Parquet')", sql)
                self.assertIn("accurateCast(`shot_xg`, 'Float64')", sql)
                for name, kind in spec.columns:
                    self.assertIn(f"`{name}`", sql.split("\nSELECT")[0])
                    self.assertIn(f" AS `{name}`", sql)
                    if name.endswith("count") or name in ("pass_attempts", "shot_goals", "under_pressure_events", "counterpress_events", "players_with_events"):
                        self.assertEqual(kind, "UInt64")
        self.assertEqual(TEAM.identity_columns, ("match_id", "team_id"))
        self.assertEqual(PLAYER.identity_columns, ("match_id", "team_id", "player_id"))

    def test_migration_exact_types_keys_and_dedup(self):
        sql = (Path(__file__).resolve().parents[1] / "infrastructure/clickhouse/migrations/004_create_gold_match_stats.sql").read_text()
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        self.assertEqual(len(statements), 2)
        for spec, statement in zip(SPECS.values(), statements, strict=True):
            self.assertTrue(statement.startswith(f"CREATE TABLE IF NOT EXISTS {spec.target}\n("))
            body = statement.split("\n(", 1)[1].split("\n)\nENGINE", 1)[0]
            fields = tuple(tuple(line.strip().rstrip(",").split(" ", 1)) for line in body.splitlines() if line.strip())
            self.assertEqual(fields, (*spec.target_columns[:-1], ("loaded_at", "DateTime64(3, 'UTC') DEFAULT now64(3)")))
            self.assertIn("ENGINE = MergeTree", statement)
            self.assertIn(f"ORDER BY ({', '.join(spec.order_by)})", statement)
            self.assertIn("PARTITION BY (competition_id, season_id)", statement)
            self.assertIn("non_replicated_deduplication_window = 1000", statement)
        for forbidden in ("DROP", "TRUNCATE", "DELETE", "ReplacingMergeTree", "Float32"):
            self.assertNotIn(forbidden, sql)


class GoldServingInputTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, ENV, clear=True))

    def test_exact_and_latest_resolution_and_metadata_only_get(self):
        for spec in SPECS.values():
            client, build, manifest = fixture(spec)
            with patch.object(gold_input, "find_latest_gold_build", return_value=build) as latest:
                self.assertEqual(gold_input.resolve_gold_build(None, spec=spec), build)
                latest.assert_called_once_with(None, source="statsbomb", dataset=spec.dataset, competition_id=43, season_id=106)
            with patch.object(gold_input, "find_gold_build", return_value=build) as exact:
                self.assertEqual(gold_input.resolve_gold_build(None, build["build_id"], spec=spec), build)
                exact.assert_called_once_with(None, dataset=spec.dataset, competition_id=43, season_id=106, build_id=build["build_id"])
            self.assertEqual(gold_input.verify_gold_manifest(client, build), manifest)
            self.assertTrue(all(call[2].endswith("_manifest.json") for call in client.calls if call[0] == "get"))
            self.assertFalse(any(call[0] == "put" for call in client.calls))
            self.assertEqual(gold_input.parquet_url(build), f"https://test-bucket.s3.ru-3.storage.selcloud.ru/{build['s3_prefix']}part-*.parquet")

    def test_missing_and_mismatched_catalog_rejected(self):
        _, build, _ = fixture(TEAM)
        for record in (None, {**build, "dataset": PLAYER.dataset}, {**build, "season_id": 99},
                       {**build, "transform_version": "wrong"}, {**build, "s3_prefix": "arbitrary/"},
                       {**build, "s3_bucket": "another"}, {**build, "row_count": 0}, {**build, "schema_sha256": "bad"}):
            with patch.object(gold_input, "find_latest_gold_build", return_value=record), self.assertRaises((GoldIntegrityError, ValueError)):
                gold_input.resolve_gold_build(None, spec=TEAM)
        with patch.object(gold_input, "find_gold_build", return_value=build), self.assertRaises(GoldIntegrityError):
            gold_input.resolve_gold_build(None, "f" * 64, spec=TEAM)

    def test_manifest_fields_inputs_counts_and_identity_checked(self):
        for spec in SPECS.values():
            for field, value in (("layer", "silver"), ("source", "other"), ("dataset", "wrong"),
                                 ("competition_id", 1), ("season_id", 1), ("transform_version", "v2"),
                                 ("input_fingerprint", "a" * 64), ("schema_sha256", "a" * 64),
                                 ("build_id", "a" * 64), ("row_count", 9), ("file_count", 9), ("inputs", []), ("match_count", 0)):
                client, build, manifest = fixture(spec)
                seed_manifest(client, build, {**manifest, field: value})
                with self.subTest(dataset=spec.dataset, field=field), self.assertRaises(GoldIntegrityError):
                    gold_input.verify_gold_manifest(client, build)

    def test_missing_success_manifest_extra_part_and_checksum(self):
        for failure in ("success", "manifest", "part", "checksum"):
            client, build, _ = fixture(TEAM)
            bucket, prefix = build["s3_bucket"], build["s3_prefix"]
            if failure in ("success", "manifest"):
                client.objects.pop((bucket, prefix + ("_SUCCESS" if failure == "success" else "_manifest.json")))
            elif failure == "part":
                client.seed(bucket, prefix + "part-extra.snappy.parquet")
            else:
                client.objects[bucket, prefix + "_manifest.json"]["Metadata"]["sha256"] = "0" * 64
            with self.assertRaises(GoldIntegrityError):
                gold_input.verify_gold_manifest(client, build)


class GoldServingLoaderTests(unittest.TestCase):
    def case(self, spec):
        client = GoldClient(spec)
        store = {}
        def register(connection, **record):
            store.update(record)
            return True
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(gold_loader, "find_clickhouse_gold_load", side_effect=lambda *a, **kw: store or None))
        save = stack.enter_context(patch.object(gold_loader, "register_clickhouse_gold_load", side_effect=register))
        output = io.StringIO()
        stack.enter_context(redirect_stdout(output))
        def run(check_only=False):
            return gold_loader.load_gold(client, None, client.build, client.manifest, "https://example.invalid/gold/part-*.parquet",
                                         spec=spec, check_only=check_only, diagnostics=gold_job.GoldDiagnostics())
        return stack, client, store, save, register, run, output

    def test_first_repeat_and_tokens_for_both_specs(self):
        for spec in SPECS.values():
            stack, client, store, save, _, run, _ = self.case(spec)
            with stack:
                self.assertEqual(run(), {"output_status": "LOADED", "catalog": "REGISTERED"})
                self.assertEqual(run(), {"output_status": "UNCHANGED / ALREADY_LOADED", "catalog": "ALREADY_REGISTERED"})
                self.assertEqual(len(client.inserts), 1)
                self.assertEqual(client.inserts[0][1]["settings"]["insert_deduplication_token"], client.build["build_id"])
                self.assertEqual(store["gold_build_id"], client.build["build_id"])
                self.assertNotIn("silver_build_id", store)
                save.assert_called_once()

    def test_check_only_empty_and_complete_never_writes(self):
        for spec in SPECS.values():
            stack, client, _, save, _, run, output = self.case(spec)
            with stack:
                self.assertFalse(run(True)["already_loaded"])
                client.target = client.source
                self.assertTrue(run(True)["already_loaded"])
                self.assertEqual(client.inserts, [])
                save.assert_not_called()
                for label in ("Dataset:", "Transform version:", "Gold build ID:", "Source rows:", "Expected files:",
                              "Existing target rows:", "Existing build ID:", "Would load:", "CHECK ONLY - nothing loaded"):
                    self.assertIn(label, output.getvalue())

    def test_partial_excess_and_registered_missing_fail(self):
        for spec in SPECS.values():
            for rows in (0, 1, 5):
                stack, client, store, save, _, run, _ = self.case(spec)
                with stack, self.subTest(dataset=spec.dataset, rows=rows):
                    client.target = (rows, *client.source[1:])
                    if rows == 0:
                        store.update(gold_loader.load_record(client.build, spec=spec))
                    with self.assertRaises(ClickHouseIntegrityError):
                        run()
                    save.assert_not_called()
                    self.assertEqual(client.inserts, [])

    def test_different_and_mixed_builds_fail_even_in_check_only(self):
        for spec in SPECS.values():
            for check_only in (True, False):
                for own in (True, False):
                    stack, client, _, save, _, run, _ = self.case(spec)
                    with stack:
                        client.other_rows = 1
                        if own:
                            client.target = client.source
                        with self.assertRaises(gold_loader.GoldBuildConflictError):
                            run(check_only)
                        self.assertEqual(client.inserts, [])
                        save.assert_not_called()

    def test_ambiguous_insert_and_catalog_failure_recover_without_second_insert(self):
        for spec in SPECS.values():
            for stage in ("timeout", "catalog"):
                stack, client, _, save, register, run, _ = self.case(spec)
                with stack:
                    client.fail_after_insert = stage == "timeout"
                    if stage == "catalog":
                        save.side_effect = RuntimeError("synthetic secret")
                    with self.assertRaises((TimeoutError, RuntimeError)):
                        run()
                    client.fail_after_insert = False
                    save.side_effect = register
                    self.assertEqual(run(), {"output_status": "UNCHANGED / ALREADY_LOADED", "catalog": "REGISTERED"})
                    self.assertEqual(len(client.inserts), 1)

    def test_schema_source_and_postload_validation_fail(self):
        for spec in SPECS.values():
            for failure in ("schema", "source", "target", "metric_null", "negative", "nonfinite", "goals"):
                stack, client, _, save, _, run, _ = self.case(spec)
                with stack:
                    if failure == "schema":
                        client.bad_schema = True
                    elif failure == "target":
                        client.partial_insert = True
                    else:
                        values = list(client.source)
                        index = {"source": 0, "metric_null": 7, "negative": 7 + len(spec.required_columns),
                                 "nonfinite": len(values) - 2, "goals": len(values) - 1}[failure]
                        values[index] += 1
                        client.source = tuple(values)
                    with self.assertRaises(ClickHouseIntegrityError):
                        run()
                    save.assert_not_called()
                    self.assertEqual(len(client.inserts), int(failure == "target"))

    def test_team_two_teams_rule_remains_hard(self):
        stack, client, _, save, _, run, _ = self.case(TEAM)
        with stack:
            client.bad_teams = True
            with self.assertRaises(ClickHouseIntegrityError):
                run()
            save.assert_not_called()


class GoldServingSqlTests(unittest.TestCase):
    def test_postgres_helpers_and_migration(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        record = {field: field + "';synthetic-secret" for field in postgres.CLICKHOUSE_GOLD_LOAD_FIELDS}
        cursor.fetchone.return_value = (1,)
        self.assertTrue(postgres.register_clickhouse_gold_load(connection, **record))
        sql, params = cursor.execute.call_args.args
        self.assertIn("ON CONFLICT DO NOTHING RETURNING id", sql)
        self.assertEqual(params, tuple(record.values()))
        self.assertNotIn("synthetic-secret", sql)
        self.assertNotIn("UPDATE", sql)
        cursor.fetchone.return_value = None
        self.assertFalse(postgres.register_clickhouse_gold_load(connection, **record))
        self.assertIsNone(postgres.find_clickhouse_gold_load(connection, clickhouse_database="football", clickhouse_table=TEAM.dataset, gold_build_id="a" * 64))
        expected = {"id": 1, **record, "loaded_at": "time"}
        cursor.fetchone.return_value = tuple(expected[field] for field in postgres.CLICKHOUSE_GOLD_LOAD_COLUMNS)
        self.assertEqual(postgres.find_clickhouse_gold_load(connection, clickhouse_database="football", clickhouse_table=TEAM.dataset, gold_build_id="a" * 64), expected)
        ddl = (Path(__file__).resolve().parents[1] / "infrastructure/postgres/migrations/005_create_clickhouse_gold_loads.sql").read_text()
        self.assertEqual(ddl.count("^[0-9a-f]{64}$"), 3)
        for clause in ("CHECK (row_count > 0)", "UNIQUE (clickhouse_database, clickhouse_table, gold_build_id)",
                       "ON metadata.clickhouse_gold_loads (source, dataset, competition_id, season_id)"):
            self.assertIn(clause, ddl)
        self.assertNotIn("silver_build_id", ddl)


class GoldServingCliTests(unittest.TestCase):
    def test_invalid_cli_rejected_before_io(self):
        with patch.object(gold_job, "create_postgres_connection") as create, redirect_stderr(io.StringIO()):
            for args in ([], ["--dataset", "passes"], ["--dataset", "team-match-stats", "--prefix", "x"],
                         ["--dataset", "team-match-stats", "--build-id", "secret"]):
                with self.assertRaises(SystemExit):
                    gold_job.main(args)
            create.assert_not_called()

    def test_preflight_before_clickhouse_and_safe_failures(self):
        for spec in SPECS.values():
            client, build, manifest = fixture(spec)
            with ExitStack() as stack:
                stack.enter_context(patch.object(gold_job, "create_postgres_connection"))
                stack.enter_context(patch.object(gold_job, "resolve_gold_build", return_value=build))
                stack.enter_context(patch.object(gold_job, "create_s3_client", return_value=client))
                verify = stack.enter_context(patch.object(gold_job, "verify_gold_manifest", return_value=manifest))
                stack.enter_context(patch.object(gold_job, "parquet_url", return_value="https://example.invalid/gold"))
                create_ch = stack.enter_context(patch.object(gold_job, "create_clickhouse_client", return_value=GoldClient(spec)))
                load = stack.enter_context(patch.object(gold_job, "load_gold"))
                lock = stack.enter_context(patch.object(gold_job, "clickhouse_load_lock"))
                output = io.StringIO()
                stack.enter_context(redirect_stderr(output))
                alias = "team-match-stats" if spec == TEAM else "player-match-stats"
                self.assertEqual(gold_job.main(["--dataset", alias, "--check-only"]), 0)
                self.assertTrue(load.call_args.kwargs["check_only"])
                lock.assert_not_called()
                self.assertEqual(gold_job.main(["--dataset", alias, "--build-id", build["build_id"]]), 0)
                lock.assert_called_once()
                create_ch.reset_mock()
                verify.side_effect = GoldIntegrityError("synthetic-secret")
                self.assertEqual(gold_job.main(["--dataset", alias]), 1)
                create_ch.assert_not_called()
                self.assertNotIn("synthetic-secret", output.getvalue())
                self.assertIn("exception=GoldIntegrityError", output.getvalue())

    def test_errors_never_print_raw_credentials(self):
        for kind in (RuntimeError, TimeoutError, GoldIntegrityError, gold_loader.GoldBuildConflictError):
            output = gold_job.GoldDiagnostics().failure(kind("synthetic-access-key synthetic-private-secret"))
            self.assertNotIn("synthetic-access-key", output)
            self.assertNotIn("synthetic-private-secret", output)
        with patch.object(model_cli, "create_clickhouse_client", side_effect=RuntimeError("synthetic-private-secret")), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(model_cli.main(["--competition-id", "43", "--season-id", "106"]), 1)
        self.assertNotIn("synthetic-private-secret", output.getvalue())


class GoldServingModelTests(unittest.TestCase):
    def test_loaded_gold_requires_single_complete_registered_build(self):
        for spec in SPECS.values():
            _, build, _ = fixture(spec)
            client = MagicMock()
            with patch.object(gold_model, "validate_table_schema"), \
                    patch.object(gold_model, "find_gold_build", return_value=build) as catalog, \
                    patch.object(gold_model, "find_clickhouse_gold_load", return_value=gold_loader.load_record(build, spec=spec)) as loads, \
                    patch.object(gold_model, "target_metrics", return_value=GoldClient(spec).source), \
                    patch.object(gold_model, "validate_extra"):
                client.query.return_value.result_rows = [(4, 1, build["build_id"])]
                self.assertEqual(gold_model.current_gold_builds(client, None, specs={spec.dataset: spec}), {spec.dataset: build})
                for count, distinct in ((0, 0), (4, 2), (3, 1)):
                    client.query.return_value.result_rows = [(count, distinct, build["build_id"])]
                    with self.assertRaises(ClickHouseIntegrityError):
                        gold_model.current_gold_builds(client, None, specs={spec.dataset: spec})
                client.query.return_value.result_rows = [(4, 1, build["build_id"])]
                for record in (None, {**build, "transform_version": "wrong"}, {**build, "build_id": "f" * 64}):
                    catalog.return_value = record
                    with self.assertRaises(ClickHouseIntegrityError):
                        gold_model.current_gold_builds(client, None, specs={spec.dataset: spec})
                catalog.return_value = build
                loads.return_value = None
                with self.assertRaises(ClickHouseIntegrityError):
                    gold_model.current_gold_builds(client, None, specs={spec.dataset: spec})

    def test_queries_scope_each_side_to_loaded_context_and_build(self):
        queries = gold_model.model_queries()
        self.assertEqual(len(queries), 12)
        self.assertEqual(sum(rule == "close" for _, _, rule in queries), 1)
        for _, sql, _ in queries:
            self.assertIn("competition_id = %(competition_id)s", sql)
            self.assertIn("season_id = %(season_id)s", sql)
            self.assertIn("gold_build_id", sql)
            self.assertIn("silver_build_id", sql)
            self.assertNotIn("s3(", sql)
        player_queries = [sql for name, sql, _ in queries if name.startswith("player_match_stats_") and "sum(" in sql]
        self.assertTrue(all("player_id IS NOT NULL" in sql for sql in player_queries))

    def test_metrics_float_tolerance_and_each_hard_failure(self):
        queries = gold_model.model_queries()
        good = [(0,) if rule == "zero" else (0.3, 0.30000000000000004) if rule == "close" else (4, 4) for _, _, rule in queries]
        client = MagicMock()
        client.query.side_effect = [MagicMock(result_rows=[row]) for row in good]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(len(gold_model.validate_model_metrics(client, {}, {})), 12)
        for index in range(len(queries)):
            rows = list(good)
            rows[index] = (1,) if queries[index][2] == "zero" else (99, 4)
            client.query.side_effect = [MagicMock(result_rows=[row]) for row in rows]
            with self.subTest(check=queries[index][0]), redirect_stdout(io.StringIO()), self.assertRaises(ClickHouseIntegrityError):
                gold_model.validate_model_metrics(client, {}, {})

    def test_lineage_and_changed_serving_snapshot_fail_without_s3(self):
        _, silver, _ = silver_inputs()
        gold = {spec.dataset: fixture(spec)[1] for spec in SPECS.values()}
        ids = {row["dataset"]: row["build_id"] for row in silver}
        with patch.object(gold_model, "current_gold_builds", return_value=gold) as current, \
                patch.object(gold_model, "current_silver_builds", return_value=ids), \
                patch.object(gold_model, "find_silver_build", side_effect=lambda *a, **kw: next(row for row in silver if row["dataset"] == kw["dataset"])), \
                patch.object(gold_model, "validate_model_metrics", return_value={}) as metrics, redirect_stdout(io.StringIO()):
            self.assertEqual(gold_model.check_model(None, None), {})
            changed = copy.deepcopy(gold)
            changed[TEAM.dataset]["input_fingerprint"] = "f" * 64
            current.return_value = changed
            metrics.reset_mock()
            with self.assertRaises(ClickHouseIntegrityError):
                gold_model.check_model(None, None)
            metrics.assert_not_called()
            current.side_effect = [gold, changed]
            with self.assertRaises(ClickHouseIntegrityError):
                gold_model.check_model(None, None)


if __name__ == "__main__":
    unittest.main()
