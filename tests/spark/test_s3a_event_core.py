"""Stage 2B Spark checks using only local synthetic data, never a cloud endpoint."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from pyspark.sql import SparkSession, functions as F
from silver_fakes import FakeS3, artifact
from scripts import check_s3a
from src.common.spark_s3a import configure_s3a, runtime_versions
from src.silver.manifest import SilverIntegrityError
from src.silver.publish import validate_readback, write_new_silver
from src.silver.statsbomb.events import (
    EVENT_SCHEMA, EventCoreQualityError, read_s3a_events, s3a_match_id,
    transform_event_core, validate_event_core,
)


class S3ASyntheticSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.appName("football-s3a-offline-tests").master("local[2]")
            .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("OFF")
        with patch.dict(os.environ, {
            "S3_ENDPOINT": "https://example.invalid", "S3_REGION": "ru-3",
            "AWS_ACCESS_KEY_ID": "synthetic-access", "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
        }):
            configure_s3a(cls.spark)

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def setUp(self):
        work = PROJECT_ROOT / "data/work"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(prefix="unittest_s3a_", dir=work)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.input = self.directory / "match_id=7" / ("sha256=" + "a" * 64) / "events.json"
        self.input.parent.mkdir(parents=True)
        self.input.write_bytes((PROJECT_ROOT / "tests/fixtures/statsbomb_events.json").read_bytes())

    def frame(self):
        return transform_event_core(read_s3a_events(self.spark, [str(self.input)]), competition_id=43, season_id=106)

    def test_pinned_jvm_versions_and_cloud_classes_load_without_network(self):
        versions = runtime_versions(self.spark)
        self.assertEqual(versions, {
            "Spark version": "4.2.0", "Hadoop version": "3.5.0",
            "S3A filesystem implementation": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        })
        loader = self.spark.sparkContext._jvm.java.lang.Thread.currentThread().getContextClassLoader()
        classes = {
            "org.apache.spark.internal.io.cloud.PathOutputCommitProtocol": "spark-hadoop-cloud_2.13-4.2.0.jar",
            "org.apache.spark.internal.io.cloud.BindingParquetOutputCommitter": "spark-hadoop-cloud_2.13-4.2.0.jar",
            "org.apache.hadoop.fs.s3a.S3AFileSystem": "hadoop-aws-3.5.0.jar",
            "org.apache.hadoop.fs.s3a.commit.S3ACommitterFactory": "hadoop-aws-3.5.0.jar",
            "software.amazon.awssdk.auth.credentials.EnvironmentVariableCredentialsProvider": "bundle-2.35.4.jar",
        }
        for name, expected_jar in classes.items():
            loaded = loader.loadClass(name)
            location = loaded.getProtectionDomain().getCodeSource().getLocation().toString()
            self.assertTrue(location.endswith(expected_jar), location)
            print(f"Installed: {name} -> {expected_jar}")
        print(versions)
        # Build and close an SDK HTTP client without executing any S3 request.
        # This exercises SDK dependency linkage, not just loading class names.
        jvm = self.spark.sparkContext._jvm
        sdk = jvm.software.amazon.awssdk
        client = (
            sdk.services.s3.S3Client.builder()
            .region(sdk.regions.Region.of("ru-3"))
            .credentialsProvider(sdk.auth.credentials.AnonymousCredentialsProvider.create())
            .endpointOverride(jvm.java.net.URI.create("https://example.invalid"))
            .build()
        )
        client.close()

    def test_strict_path_expression_without_udf(self):
        base = "s3a://test-bucket/football/bronze/statsbomb/events"
        digest = "a" * 64
        cases = [
            (f"{base}/match_id=7/sha256={digest}/events.json", 7),
            (f"{base}/match_id=0/sha256={digest}/events.json", None),
            (f"{base}/match_id=07/sha256={digest}/events.json", None),
            (f"{base}/match_id=-7/sha256={digest}/events.json", None),
            (f"{base}/match_id=7/sha256={'A' * 64}/events.json", None),
            (f"{base}/match_id=7/sha256={'a' * 63}/events.json", None),
            (f"{base}/match_id=7/sha256={digest}/lineups.json", None),
            (f"{base}/match_id=7/sha256={digest}/events.json/extra", None),
            (f"{base}/match_id=7/sha256={digest}/events.json?x=y", None),
            (f"{base}/match_id={2**63}/sha256={digest}/events.json", None),
        ]
        df = self.spark.createDataFrame([(i, path) for i, (path, _) in enumerate(cases)], "index int, path string")
        extracted = df.select("index", s3a_match_id(F.col("path")).alias("match_id")).orderBy("index")
        self.assertEqual([row.match_id for row in extracted.collect()], [expected for _, expected in cases])
        self.assertNotIn("PythonUDF", extracted._jdf.queryExecution().executedPlan().toString())

    def test_s3a_reader_uses_schema_and_filename_identity_with_local_fixture(self):
        raw = read_s3a_events(self.spark, [str(self.input)])
        self.assertEqual(raw.drop("match_id").schema, EVENT_SCHEMA)
        flat = self.frame()
        self.assertEqual(flat.first().match_id, 7)
        self.assertEqual(validate_event_core(flat)["row_count"], 3)

    def test_multiple_immutable_paths_do_not_infer_hash_partitions(self):
        other = self.directory / "match_id=8" / ("sha256=" + "b" * 64) / "events.json"
        other.parent.mkdir(parents=True)
        other.write_bytes(self.input.read_bytes())
        raw = read_s3a_events(self.spark, [str(self.input), str(other)])
        self.assertEqual(raw.drop("match_id").schema, EVENT_SCHEMA)
        flat = transform_event_core(raw, competition_id=43, season_id=106)
        counts = validate_event_core(flat)
        self.assertEqual(counts["row_count"], 6)
        self.assertEqual(counts["match_count"], 2)

    def test_bad_input_path_fails_existing_dq(self):
        wrong = self.directory / "events.json"
        wrong.write_bytes(self.input.read_bytes())
        flat = transform_event_core(read_s3a_events(self.spark, [str(wrong)]), competition_id=43, season_id=106)
        with self.assertRaisesRegex(EventCoreQualityError, "null_match_id=3"):
            validate_event_core(flat)

    def test_postwrite_schema_counts_and_parquet_nullability(self):
        frame = self.frame()
        output = self.directory / "competition_id=43/season_id=106/build_id=test"
        frame.repartition(4).write.mode("errorifexists").option("compression", "snappy").parquet(str(output))
        files = [{"object_key": str(path)} for path in output.glob("part-*.parquet")]
        with patch("src.silver.publish.s3a_uri", side_effect=lambda bucket, key: key):
            validate_readback(self.spark, frame, {"row_count": 3, "match_count": 1}, bucket="unused", files=files)
            with self.assertRaisesRegex(SilverIntegrityError, "row_count or match_count"):
                validate_readback(self.spark, frame, {"row_count": 4, "match_count": 1}, bucket="unused", files=files)
            with self.assertRaisesRegex(SilverIntegrityError, "row_count or match_count"):
                validate_readback(self.spark, frame, {"row_count": 3, "match_count": 64}, bucket="unused", files=files)
            with self.assertRaisesRegex(SilverIntegrityError, "schema mismatch"):
                validate_readback(self.spark, frame.withColumn("event_index", F.col("event_index").cast("string")),
                                  {"row_count": 3, "match_count": 1}, bucket="unused", files=files)

    def test_corrupt_parquet_readback_fails_safely(self):
        corrupt = self.directory / "part-corrupt.snappy.parquet"
        corrupt.write_bytes(b"synthetic-private-payload")
        with patch("src.silver.publish.s3a_uri", return_value=str(corrupt)):
            with self.assertRaisesRegex(SilverIntegrityError, "read-back failed") as caught:
                validate_readback(self.spark, self.frame(), {"row_count": 3, "match_count": 1},
                                  bucket="unused", files=[{"object_key": "unused"}])
        self.assertNotIn("private-payload", str(caught.exception))

    def test_silver_writer_uses_new_destination_only_and_four_partitions(self):
        frame = MagicMock()
        write_new_silver(frame, "s3a://test-bucket/immutable/")
        frame.repartition.assert_called_once_with(4)
        writer = frame.repartition.return_value.write
        writer.mode.assert_called_once_with("errorifexists")
        writer.mode.return_value.option.assert_called_once_with("compression", "snappy")
        with self.assertRaises(ValueError):
            write_new_silver(frame, "/app/data/work/not-s3")

    def test_smoke_script_uses_head_then_direct_reader_never_boto_body(self):
        client = FakeS3()
        item = artifact(7)
        client.seed(item["s3_bucket"], item["object_key"], metadata={"sha256": item["sha256"]})
        fake_spark = MagicMock()
        with (
            patch("pyspark.sql.SparkSession") as session,
            patch.object(check_s3a, "configure_s3a"),
            patch.object(check_s3a, "runtime_versions", return_value={}),
            patch.object(check_s3a, "create_postgres_connection"),
            patch.object(check_s3a, "find_latest_ingestion_objects", return_value=[item]),
            patch.object(check_s3a, "create_s3_client", return_value=client),
            patch("src.silver.statsbomb.events.read_s3a_events") as reader,
            redirect_stdout(io.StringIO()),
        ):
            session.builder.appName.return_value.master.return_value.config.return_value.getOrCreate.return_value = fake_spark
            reader.return_value.count.return_value = 3
            self.assertEqual(check_s3a.main(), 0)
            reader.assert_called_once_with(fake_spark, [f"s3a://test-bucket/{item['object_key']}"])
        self.assertEqual([call[0] for call in client.calls], ["head", "close"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
