"""Stage 3E synthetic Spark tests. No external S3 or PostgreSQL calls."""

import io
import json
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from context_fixtures import in_context
from pyspark.sql import SparkSession, functions as F
from matches_fakes import RAW, parent
from silver_fakes import FakeS3
from src.silver import matches_job as job
from src.silver.statsbomb.matches import OUTPUT_SCHEMA, REQUIRED, MatchQualityError, build_matches, read_matches, transform_matches, validate_matches
from src.silver.build_identity import build_specification, input_fingerprint, calculate_build_id
from src.common.checksum import sha256_bytes
from src.silver.manifest import SilverIntegrityError


class MatchesSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.appName("football-matches-offline-tests").master("local[2]")
                     .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2").getOrCreate())
        cls.spark.sparkContext.setLogLevel("OFF")
        cls.teams = cls.spark.createDataFrame([(43, 106, value, "synthetic") for value in (10, 20, 30)],
            "competition_id long, season_id long, team_id long, team_name string")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def frame(self, raw=RAW):
        return transform_matches(read_matches(self.spark, raw))

    def test_explicit_schema_nested_values_date_and_optional_nulls(self):
        frame, counts = in_context(build_matches)(self.spark, RAW, self.teams)
        self.addCleanup(frame.unpersist)
        self.assertEqual(frame.schema, OUTPUT_SCHEMA)
        self.assertEqual((counts["row_count"], counts["match_count"]), (2, 2))
        a, b = frame.orderBy("match_id").collect()
        self.assertEqual((a.match_date, a.kick_off, a.competition_stage_name, a.home_team_id, a.away_team_id, a.home_score, a.away_score),
                         (date(2022, 11, 21), "13:00:00.000", "Group Stage", 10, 20, 2, 0))
        self.assertEqual((a.stadium_id, a.stadium_name, a.referee_id, a.referee_name), (100, "Test Stadium", 200, "Test Referee"))
        self.assertEqual((b.match_date, b.competition_stage_name, b.away_team_id), (date(2022, 12, 3), "Round of 16", 30))
        for field in ("stadium_id", "stadium_name", "referee_id", "referee_name", "kick_off", "match_week"):
            self.assertIsNone(b[field])
            self.assertEqual(counts["null_" + field], 1)

    def test_empty_duplicate_self_play_negative_and_context_fail(self):
        base = self.frame()
        frames = [base.limit(0), base.unionByName(base), base.withColumn("away_team_id", F.col("home_team_id")),
                  base.withColumn("home_score", F.lit(-1)), base.withColumn("away_score", F.lit(-1)),
                  base.withColumn("competition_id", F.lit(99)), base.withColumn("season_id", F.lit(99))]
        for frame in frames:
            with redirect_stdout(io.StringIO()), self.assertRaises(MatchQualityError):
                in_context(validate_matches)(frame, self.teams)

    def test_every_required_null_fails(self):
        for name in REQUIRED:
            with self.subTest(field=name), redirect_stdout(io.StringIO()), self.assertRaises(MatchQualityError):
                in_context(validate_matches)(self.frame().withColumn(name, F.lit(None).cast(OUTPUT_SCHEMA[name].dataType)), self.teams)

    def test_home_and_away_orphans_and_wrong_team_context_fail(self):
        for teams in (self.teams.filter("team_id != 10"), self.teams.filter("team_id != 30"),
                      self.teams.withColumn("competition_id", F.lit(99)), self.teams.withColumn("season_id", F.lit(99))):
            with redirect_stdout(io.StringIO()), self.assertRaises(MatchQualityError):
                in_context(validate_matches)(self.frame(), teams)

    def test_bad_dates_and_malformed_source_fail_safely(self):
        rows = json.loads(RAW)
        rows[0]["match_date"] = "2022-02-30"
        with redirect_stdout(io.StringIO()), self.assertRaises(MatchQualityError):
            in_context(validate_matches)(self.frame(json.dumps(rows).encode()), self.teams)
        for raw in (b"secret", b"{}", b"[null]", b'[{"match_id":true}]'):
            with self.assertRaises(MatchQualityError) as error:
                read_matches(self.spark, raw)
            self.assertNotIn("secret", str(error.exception))

    def test_determinism_and_one_partition_parquet_roundtrip(self):
        from src.silver.publish import write_new_silver
        raw = json.dumps(list(reversed(json.loads(RAW)))).encode()
        self.assertEqual(self.frame().orderBy("match_id").collect(), self.frame(raw).orderBy("match_id").collect())
        spec = build_specification(dataset="matches", transform_version="matches_v1", competition_id=43, season_id=106,
            input_fingerprint=input_fingerprint([parent()], artifact_kind="matches"), schema_sha256=sha256_bytes(self.frame().schema.json().encode()))
        self.assertEqual(calculate_build_id(spec), calculate_build_id(dict(reversed(list(spec.items())))))
        with TemporaryDirectory(prefix="football-matches-test-") as directory:
            path = str(Path(directory) / "out")
            self.frame().repartition(1).write.mode("errorifexists").option("compression", "snappy").parquet(path)
            self.assertEqual(len(list(Path(path).glob("part-*.snappy.parquet"))), 1)
            restored = self.spark.read.parquet(path)
            self.assertEqual(restored.schema, OUTPUT_SCHEMA)
            self.assertEqual(restored.orderBy("match_id").collect(), self.frame().orderBy("match_id").collect())
        mocked = MagicMock()
        write_new_silver(mocked, "s3a://test-bucket/new-prefix/", partitions=1)
        mocked.repartition.assert_called_once_with(1)
        mocked.repartition.return_value.write.mode.assert_called_once_with("errorifexists")

    def test_exact_teams_readback_schema_counts_and_context(self):
        with TemporaryDirectory(prefix="football-teams-ref-") as directory:
            path = str(Path(directory) / "teams")
            self.teams.repartition(1).write.parquet(path)
            files = [{"object_key": str(item)} for item in Path(path).glob("*.parquet")]
            with patch.object(job, "s3a_uri", side_effect=lambda bucket, key: key):
                frame = job.read_teams(self.spark, {"competition_id": 43, "season_id": 106, "s3_bucket": "test-bucket", "row_count": 3}, {"files": files})
                frame.unpersist()
                with self.assertRaises(SilverIntegrityError):
                    job.read_teams(self.spark, {"competition_id": 43, "season_id": 106, "s3_bucket": "test-bucket", "row_count": 4}, {"files": files})

    def test_full_check_only_and_publish_orchestration_safe_errors(self):
        s3 = FakeS3()
        item = parent()
        s3.seed(item["s3_bucket"], item["object_key"], RAW, {"sha256": item["sha256"]})
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}))
            stack.enter_context(patch.object(job, "create_postgres_connection"))
            stack.enter_context(patch.object(job, "create_s3_client", return_value=s3))
            stack.enter_context(patch.object(job, "find_matches_parent", return_value=item))
            stack.enter_context(patch.object(job, "resolve_silver_build", return_value={"build_id": "a" * 64}))
            stack.enter_context(patch.object(job, "verify_silver_manifest", return_value={}))
            stack.enter_context(patch.object(job, "create_spark_session", return_value=self.spark))
            stack.enter_context(patch.object(self.spark, "stop"))
            stack.enter_context(patch.object(job, "configure_s3a"))
            stack.enter_context(patch.object(job, "read_teams", return_value=self.teams))
            publish = stack.enter_context(patch.object(job, "publish_build", return_value={"output_status": "CREATED", "catalog": "REGISTERED", "output_uri": "synthetic"}))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            errors = stack.enter_context(redirect_stderr(io.StringIO()))
            self.assertEqual(in_context(job.run_job)(parent_sha256=item["sha256"], teams_build_id="a" * 64, check_only=True), 0, errors.getvalue())
            publish.assert_not_called()
            self.assertIn("CHECK ONLY - nothing published", output.getvalue())
            self.assertFalse(any(call[0] == "put" for call in s3.calls))
            self.assertEqual(in_context(job.run_job)(parent_sha256=item["sha256"], teams_build_id="a" * 64, ), 0, errors.getvalue())
            self.assertEqual(publish.call_args.kwargs["specification"]["dataset"], "matches")
            with patch.object(job, "read_bronze_object", side_effect=RuntimeError("synthetic-private-secret")):
                self.assertEqual(in_context(job.run_job)(parent_sha256=item["sha256"], teams_build_id="a" * 64, check_only=True), 1)
            self.assertNotIn("synthetic-private-secret", errors.getvalue())
            self.assertIn("parent GET/integrity", errors.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
