"""Offline identity, manifests, SQL, Silver preflight, recovery and CLI contracts."""

from context_fixtures import CONTEXT_ARGS

import copy
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from gold_fakes import seed_output, silver_inputs, specification
from test_clickhouse_silver_input import seed_manifest
from src.common import postgres
from src.gold import build_identity as identity, inputs, job, manifest, publish
from src.gold.manifest import GoldIntegrityError
from src.silver.manifest import SilverIntegrityError


class GoldIdentityTests(unittest.TestCase):
    def setUp(self):
        _, self.builds, _ = silver_inputs()
        self.spec = specification(self.builds)

    def test_canonical_inputs_order_and_whitelist(self):
        original = identity.input_fingerprint(self.builds)
        self.assertEqual(original, identity.input_fingerprint(list(reversed(self.builds))))
        changed = [{**row, "created_at": "later", "id": 999, "secret": "not-lineage"} for row in self.builds]
        self.assertEqual(original, identity.input_fingerprint(changed))
        self.assertNotIn("secret", identity.canonical_json(identity.canonical_inputs(changed)).decode())
        self.assertEqual(tuple(row["dataset"] for row in identity.canonical_inputs(changed)), identity.REQUIRED_INPUTS)

    def test_every_upstream_identity_field_changes_fingerprint(self):
        for index in range(len(self.builds)):
            for name, value in (("build_id", "e" * 64), ("schema_sha256", "f" * 64),
                                ("transform_version", "new_v2"), ("s3_bucket", "other-bucket"),
                                ("s3_prefix", "football/silver/other/")):
                changed = copy.deepcopy(self.builds)
                changed[index][name] = value
                with self.subTest(index=index, field=name):
                    self.assertNotEqual(identity.input_fingerprint(self.builds), identity.input_fingerprint(changed))

    def test_build_identity_changes_only_for_specification(self):
        original = identity.calculate_build_id(self.spec)
        self.assertEqual(original, identity.calculate_build_id({**self.spec, "created_at": "ignored", "id": 9}))
        for field, value in (("transform_version", "team_match_stats_v2"), ("schema_sha256", "d" * 64),
                             ("input_fingerprint", "e" * 64), ("dataset", "player_match_stats")):
            self.assertNotEqual(original, identity.calculate_build_id({**self.spec, field: value}))
        self.assertEqual(identity.gold_prefix(self.spec, original),
                         f"football/gold/statsbomb/team_match_stats/competition_id=43/season_id=106/build_id={original}/")

    def test_invalid_empty_duplicate_inputs_rejected(self):
        for builds in ([], [self.builds[0], self.builds[0]], [{**self.builds[0], "build_id": "invalid"}]):
            with self.assertRaises(ValueError):
                identity.canonical_inputs(builds)


class GoldInputTests(unittest.TestCase):
    def setUp(self):
        self.client, self.builds, self.manifests = silver_inputs()
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.lookup = self.enterContext(patch.object(inputs, "find_latest_silver_build", side_effect=lambda *a, **kw:
            next((row for row in self.builds if row["dataset"] == kw["dataset"]), None)))

    def resolve(self):
        return inputs.resolve_inputs(None, self.client, competition_id=43, season_id=106, diagnostics=job.Diagnostics())

    def test_resolves_exact_four_builds_and_gets_metadata_only(self):
        self.assertEqual(self.resolve(), (self.builds, self.manifests))
        self.assertEqual(self.lookup.call_count, 4)
        self.assertTrue(all(call[2].endswith("_manifest.json") for call in self.client.calls if call[0] == "get"))
        self.assertFalse(any(call[0] == "put" for call in self.client.calls))

    def test_missing_catalog_and_wrong_context_fail(self):
        self.lookup.side_effect = None
        for build in (None, {**self.builds[0], "season_id": 99}):
            self.lookup.return_value = build
            with self.assertRaises(GoldIntegrityError):
                self.resolve()

    def test_missing_manifest_success_wrong_inventory_and_checksum(self):
        initial = copy.deepcopy(self.client.objects)
        build = self.builds[0]
        bucket, prefix = build["s3_bucket"], build["s3_prefix"]
        for failure in ("manifest", "success", "extra", "checksum"):
            self.client.objects = copy.deepcopy(initial)
            if failure in ("manifest", "success"):
                self.client.objects.pop((bucket, prefix + ("_manifest.json" if failure == "manifest" else "_SUCCESS")))
            elif failure == "extra":
                self.client.seed(bucket, prefix + "part-extra.snappy.parquet")
            else:
                self.client.objects[bucket, prefix + "_manifest.json"]["Metadata"]["sha256"] = "0" * 64
            with self.subTest(failure=failure), self.assertRaises((GoldIntegrityError, SilverIntegrityError)):
                self.resolve()

    def test_manifest_fields_and_lineage_mismatch(self):
        build = self.builds[0]
        for field, value in (("row_count", 999), ("schema_sha256", "f" * 64), ("layer", "gold"),
                             ("file_count", 8), ("match_count", 8)):
            seed_manifest(self.client, build, {**self.manifests[build["dataset"]], field: value})
            with self.subTest(field=field), self.assertRaises(GoldIntegrityError):
                self.resolve()


class GoldPostgresTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.record = {field: field + "';secret" for field in postgres.GOLD_BUILD_FIELDS}

    def test_parameterized_register_and_duplicate(self):
        self.cursor.fetchone.return_value = (1,)
        self.assertTrue(postgres.register_gold_build(self.connection, **self.record))
        sql, params = self.cursor.execute.call_args.args
        self.assertIn("ON CONFLICT DO NOTHING RETURNING id", sql)
        self.assertEqual(params, tuple(self.record.values()))
        self.assertNotIn("secret", sql)
        self.assertNotIn("UPDATE", sql)
        self.cursor.fetchone.return_value = None
        self.assertFalse(postgres.register_gold_build(self.connection, **self.record))

    def test_exact_latest_lookup_and_commit_failure(self):
        expected = {"id": 1, **self.record, "created_at": "time"}
        self.cursor.fetchone.return_value = tuple(expected[name] for name in postgres.GOLD_BUILD_COLUMNS)
        self.assertEqual(postgres.find_gold_build(self.connection, dataset="x", competition_id=43, season_id=106, build_id="a" * 64), expected)
        self.assertEqual(postgres.find_latest_gold_build(self.connection, source="statsbomb", dataset="x", competition_id=43, season_id=106), expected)
        self.assertIn("ORDER BY created_at DESC, id DESC LIMIT 1", self.cursor.execute.call_args.args[0])
        self.cursor.fetchone.return_value = None
        self.assertIsNone(postgres.find_gold_build(self.connection, dataset="x", competition_id=43, season_id=106, build_id="a" * 64))
        self.connection.transaction.return_value.__exit__.side_effect = RuntimeError("commit failed")
        with self.assertRaises(RuntimeError):
            postgres.register_gold_build(self.connection, **self.record)

    def test_migration_constraints(self):
        sql = (Path(__file__).resolve().parents[1] / "infrastructure/postgres/migrations/004_create_gold_builds.sql").read_text()
        for clause in ("CREATE TABLE IF NOT EXISTS metadata.gold_builds", "GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
                       "row_count BIGINT NOT NULL", "file_count BIGINT NOT NULL", "CHECK (row_count > 0)", "CHECK (file_count > 0)",
                       "UNIQUE (dataset, competition_id, season_id, build_id)", "UNIQUE (s3_bucket, s3_prefix)",
                       "(source, dataset, competition_id, season_id)"):
            self.assertIn(clause, sql)
        self.assertEqual(sql.count("^[0-9a-f]{64}$"), 3)
        self.assertNotIn("silver_builds", sql)
        self.assertNotIn("DROP", sql)


class GoldPublishTests(unittest.TestCase):
    def setUp(self):
        self.client, self.builds, _ = silver_inputs()
        self.spec = specification(self.builds)
        self.prefix = identity.gold_prefix(self.spec, identity.calculate_build_id(self.spec))
        self.record = None
        self.find = self.enterContext(patch.object(publish, "find_gold_build", side_effect=lambda *a, **kw: self.record))
        self.save = self.enterContext(patch.object(publish, "register_gold_build", side_effect=self.register))
        self.write = self.enterContext(patch.object(publish, "write_new_parquet", side_effect=lambda frame, uri, partitions:
            seed_output(self.client, "test-bucket", self.prefix, partitions)))
        self.readback = self.enterContext(patch.object(publish, "validate_readback"))
        self.params = dict(spark=MagicMock(), frame=MagicMock(), counts={"row_count": 4, "match_count": 2},
                           inputs=self.builds, specification=self.spec, bucket="test-bucket", client=self.client,
                           connection=MagicMock(), diagnostics=job.Diagnostics())

    def register(self, connection, **record):
        self.readback.assert_called()
        self.assertIn(("test-bucket", self.prefix + "_manifest.json"), self.client.objects)
        self.record = record
        return True

    def run_build(self):
        return publish.publish_build(**self.params)

    def test_first_second_and_exact_manifest_lineage(self):
        self.assertEqual(self.run_build()["output_status"], "CREATED")
        before = copy.deepcopy(self.client.objects)
        result = self.run_build()
        self.assertEqual((result["output_status"], result["catalog"]), ("UNCHANGED / ALREADY_BUILT", "ALREADY_REGISTERED"))
        self.assertEqual(before, self.client.objects)
        self.assertEqual(self.write.call_count, 1)
        self.assertEqual(self.save.call_count, 1)
        self.assertEqual(self.write.call_args.kwargs["partitions"], 1)
        actual = manifest.read_manifest(self.client, bucket="test-bucket", prefix=self.prefix, build_id=result["build_id"])
        self.assertEqual(actual["inputs"], identity.canonical_inputs(self.builds))
        self.assertEqual((actual["row_count"], actual["file_count"], actual["layer"]), (4, 1, "gold"))

    def test_catalog_failure_recovers_without_rewrite(self):
        self.save.side_effect = RuntimeError("database failure")
        with self.assertRaises(RuntimeError):
            self.run_build()
        self.save.side_effect = self.register
        self.assertEqual(self.run_build()["catalog"], "REGISTERED")
        self.assertEqual(self.write.call_count, 1)

    def test_manifest_failure_and_complete_unregistered_recovery(self):
        with patch.object(publish, "ensure_manifest", side_effect=RuntimeError("failure")), self.assertRaises(RuntimeError):
            self.run_build()
        self.save.assert_not_called()
        self.assertEqual(self.run_build()["output_status"], "UNCHANGED / ALREADY_BUILT")
        self.assertEqual(self.write.call_count, 1)

    def test_partial_and_registered_missing_outputs_are_never_rewritten(self):
        self.client.seed("test-bucket", self.prefix + "part-partial.snappy.parquet")
        before = copy.deepcopy(self.client.objects)
        with self.assertRaises(GoldIntegrityError):
            self.run_build()
        self.assertEqual(before, self.client.objects)
        self.write.assert_not_called()
        self.client.objects.pop(("test-bucket", self.prefix + "part-partial.snappy.parquet"))
        self.record = {"id": 1}
        with self.assertRaises(GoldIntegrityError):
            self.run_build()
        self.write.assert_not_called()

    def test_corrupt_readback_never_registers_or_writes_manifest(self):
        self.readback.side_effect = GoldIntegrityError("bad values")
        with self.assertRaises(GoldIntegrityError):
            self.run_build()
        self.save.assert_not_called()
        self.assertNotIn(("test-bucket", self.prefix + "_manifest.json"), self.client.objects)

    def test_manifest_and_catalog_mismatches_fail(self):
        self.run_build()
        original = copy.deepcopy(self.client.objects)
        key = ("test-bucket", self.prefix + "_manifest.json")
        self.client.objects.pop(key)
        with self.assertRaises(GoldIntegrityError):
            self.run_build()
        self.client.objects = original
        self.record["row_count"] += 1
        with self.assertRaises(GoldIntegrityError):
            self.run_build()
        self.record["row_count"] -= 1
        self.client.seed("test-bucket", self.prefix + "part-00000.snappy.parquet", b"changed")
        with self.assertRaises(GoldIntegrityError):
            self.run_build()
        self.assertEqual(self.write.call_count, 1)

    def test_manifest_contract_mismatches_and_invalid_counts(self):
        seed_output(self.client, "test-bucket", self.prefix)
        files = manifest.inspect_output(self.client, bucket="test-bucket", prefix=self.prefix)
        expected = manifest.make_manifest(self.spec, self.builds, self.params["counts"], files)
        for field, value in (("build_id", "f" * 64), ("row_count", 999), ("file_count", 9), ("inputs", [])):
            with self.subTest(field=field), self.assertRaises(GoldIntegrityError):
                manifest.validate_manifest({**expected, field: value}, expected)
        for counts in ({"row_count": 0, "match_count": 2}, {"row_count": 4, "match_count": 0}):
            with self.assertRaises(GoldIntegrityError):
                manifest.make_manifest(self.spec, self.builds, counts, files)
        with self.assertRaises(GoldIntegrityError):
            manifest.make_manifest({**self.spec, "input_fingerprint": "f" * 64}, self.builds, self.params["counts"], files)


class GoldCliTests(unittest.TestCase):
    def setUp(self):
        self.client, self.builds, self.manifests = silver_inputs()
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.stdout))
        self.enterContext(redirect_stderr(self.stderr))
        self.enterContext(patch.object(job, "create_postgres_connection"))
        self.enterContext(patch.object(job, "create_s3_client", return_value=self.client))
        self.resolve = self.enterContext(patch.object(job, "resolve_inputs", return_value=(self.builds, self.manifests)))
        self.spark = self.enterContext(patch.object(job, "create_spark_session"))
        self.enterContext(patch.object(job, "configure_s3a"))
        self.read = self.enterContext(patch.object(job, "read_inputs", return_value={name: MagicMock() for name in identity.REQUIRED_INPUTS}))
        self.pins = [arg for build in self.builds for arg in ("--silver-build", build["dataset"] + "=" + build["build_id"])]
        self.frame = MagicMock()
        self.frame.schema.json.return_value = '{"fields":[]}'
        self.build = self.enterContext(patch.object(job, "build_frame", return_value=(self.frame, {"row_count": 4, "match_count": 2})))
        self.publish = self.enterContext(patch.object(job, "publish_build", return_value=dict(output_status="CREATED", catalog="REGISTERED", output_uri="s3a://test/output", file_count=1)))

    def test_check_only_both_datasets_never_publishes(self):
        for dataset in ("team-match-stats", "player-match-stats"):
            self.assertEqual(job.main(CONTEXT_ARGS + self.pins + ["--dataset", dataset, "--check-only"]), 0)
        self.publish.assert_not_called()
        self.assertNotIn("put", [call[0] for call in self.client.calls])
        for label in ("Selected Silver inputs", "Input fingerprint", "Schema SHA256", "Build ID", "Matches: 2", "CHECK ONLY - nothing published"):
            self.assertIn(label, self.stdout.getvalue())

    def test_no_limits_build_id_or_unknown_datasets(self):
        for args in ([], ["--dataset", "unknown"], ["--dataset", "team-match-stats", "--limit", "1"],
                     ["--dataset", "team-match-stats", "--build-id", "a" * 64]):
            with self.assertRaises(SystemExit):
                job.main(CONTEXT_ARGS + args)
        self.resolve.assert_not_called()

    def test_failure_is_safe_and_stops_publication(self):
        self.build.side_effect = GoldIntegrityError("synthetic-access-secret synthetic-private-secret")
        self.assertEqual(job.main(CONTEXT_ARGS + self.pins + ["--dataset", "team-match-stats", "--check-only"]), 1)
        self.assertIn("exception=GoldIntegrityError category=integrity", self.stderr.getvalue())
        self.assertIn('stage="Gold transformation/DQ"', self.stderr.getvalue())
        self.assertNotIn("secret", self.stderr.getvalue())
        self.publish.assert_not_called()
        self.spark.return_value.stop.assert_called_once()

    def test_full_run_uses_gold_publisher(self):
        self.assertEqual(job.main(CONTEXT_ARGS + self.pins + ["--dataset", "player-match-stats"]), 0)
        self.assertEqual(self.publish.call_args.kwargs["specification"]["transform_version"], "player_match_stats_v1")
        self.assertIn("CREATED", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
