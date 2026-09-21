"""Synthetic local Spark tests; run this file with spark-submit, not ingestion.

No __init__.py here: ordinary `unittest discover -s tests` deliberately leaves
this Spark-only suite out of the Python tools container.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from botocore.response import StreamingBody

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import ArrayType, DoubleType, LongType, StringType

from scripts import build_silver_event_core as job
from src.common.checksum import sha256_bytes
from src.silver.statsbomb.events import (
    EVENT_SCHEMA, EventCoreQualityError, read_staged_events,
    transform_event_core, validate_event_core, write_event_core,
)
from src.statsbomb.events import EventArtifactError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "tests/fixtures/statsbomb_events.json"
EXPECTED_COLUMNS = [
    "competition_id", "season_id", "match_id", "event_id", "event_index",
    "period", "timestamp", "minute", "second", "type_id", "type_name", "possession",
    "possession_team_id", "possession_team_name", "play_pattern_id", "play_pattern_name",
    "team_id", "team_name", "player_id", "player_name", "position_id", "position_name",
    "location_x", "location_y", "duration", "under_pressure", "counterpress",
]


class EventCoreSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.appName("football-event-core-offline-tests")
            .master("local[2]").config("spark.ui.enabled", "false")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.sql.ansi.enabled", "true")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("OFF")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def setUp(self):
        work = PROJECT_ROOT / "data/work"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(prefix="unittest_spark_", dir=work)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "match_id=11.json"
        self.path.write_bytes(FIXTURE.read_bytes())

    def read(self, paths=None):
        return read_staged_events(self.spark, paths or [self.path])

    def transform(self, raw=None):
        return transform_event_core(
            self.read() if raw is None else raw, competition_id=43, season_id=106,
        )

    def test_explicit_schema_ignores_extra_fields(self):
        raw = self.read()
        self.assertEqual(raw.drop("match_id").schema, EVENT_SCHEMA)
        self.assertEqual(raw.schema["location"].dataType, ArrayType(DoubleType(), True))
        self.assertEqual(raw.schema["timestamp"].dataType, StringType())
        self.assertEqual(raw.schema["match_id"].dataType, LongType())
        self.assertNotIn("pass", raw.columns)
        self.assertNotIn("tactics", raw.columns)
        self.assertEqual(raw.count(), 3)

    def test_expected_columns_nested_flatten_and_coordinates(self):
        flat = self.transform()
        self.assertEqual(flat.columns, EXPECTED_COLUMNS)
        event = flat.filter(F.col("event_id") == "synthetic-event-1").first().asDict()
        self.assertEqual(event, dict(zip(EXPECTED_COLUMNS, [
            43, 106, 11, "synthetic-event-1", 1, 1, "00:00:01.250", 0, 1,
            30, "Pass", 1, 10, "Red FC", 1, "Regular Play", 10, "Red FC",
            100, "Test Player", 6, "Left Back", 12.5, 23.75, 0.5, True, False,
        ])))

    def test_nullable_fields_are_preserved(self):
        event = self.transform().filter(F.col("event_index") == 2).first().asDict()
        for name in (
            "player_id", "player_name", "position_id", "position_name", "location_x", "location_y",
            "duration", "under_pressure", "counterpress", "possession_team_id", "play_pattern_id",
        ):
            self.assertIsNone(event[name], name)

    def test_short_and_empty_arrays_are_null_safe_in_ansi_mode(self):
        event = self.transform().filter(F.col("event_index") == 3).first()
        self.assertEqual(event.location_x, 42.0)
        self.assertIsNone(event.location_y)
        raw = self.read().withColumn("location", F.array().cast("array<double>"))
        event = self.transform(raw).first()
        self.assertIsNone(event.location_x)
        self.assertIsNone(event.location_y)

    def test_filename_identity_multiple_files_and_stale_files_ignored(self):
        other = self.directory / "match_id=22.json"
        other.write_bytes(FIXTURE.read_bytes())
        # A stale invalid file is not one of the selected paths.
        (self.directory / "match_id=99.json").write_bytes(b"not valid JSON")
        flat = self.transform(self.read([self.path, other]))
        counts = validate_event_core(flat)
        self.assertEqual(counts["row_count"], 6)
        self.assertEqual(counts["match_count"], 2)
        self.assertEqual(counts["duplicate_keys"], 0)  # Same event_id in different matches is allowed.
        ids = {row.match_id for row in flat.select("match_id").distinct().collect()}
        self.assertEqual(ids, {11, 22})
        plan = flat._jdf.queryExecution().executedPlan().toString()
        self.assertNotIn("PythonUDF", plan)
        self.assertNotIn("BatchEvalPython", plan)

    def test_transformation_uses_explicit_context_parameters(self):
        row = transform_event_core(self.read(), competition_id=7, season_id=8).first()
        self.assertEqual((row.competition_id, row.season_id), (7, 8))

    def test_successful_quality_counts(self):
        counts = validate_event_core(self.transform())
        self.assertEqual(counts["row_count"], 3)
        self.assertEqual(counts["match_count"], 1)
        self.assertTrue(all(value == 0 for name, value in counts.items() if name.startswith("null_")))

    def test_duplicate_pair_fails_quality(self):
        flat = self.transform()
        with self.assertRaisesRegex(EventCoreQualityError, "duplicate_keys=1"):
            validate_event_core(flat.unionByName(flat.filter(F.col("event_index") == 1)))

    def test_each_required_null_fails_quality_including_event_id(self):
        flat = self.transform()
        for name in ("match_id", "event_id", "event_index", "type_id", "team_id"):
            with self.subTest(column=name), self.assertRaisesRegex(EventCoreQualityError, f"null_{name}=3"):
                validate_event_core(flat.withColumn(name, F.lit(None).cast(flat.schema[name].dataType)))

    def test_empty_dataset_fails_quality(self):
        with self.assertRaisesRegex(EventCoreQualityError, "row_count=0"):
            validate_event_core(self.transform().limit(0))

    def test_invalid_filename_produces_null_and_fails_quality(self):
        wrong = self.directory / "events.json"
        wrong.write_bytes(FIXTURE.read_bytes())
        with self.assertRaisesRegex(EventCoreQualityError, "null_match_id=3"):
            validate_event_core(self.transform(self.read([wrong])))

    def test_local_snappy_parquet_roundtrip_and_overwrite(self):
        flat = self.transform()
        validate_event_core(flat)
        output = self.directory / "event_core"
        write_event_core(flat, output)
        restored = self.spark.read.parquet(str(output))
        self.assertEqual(restored.columns, EXPECTED_COLUMNS)
        self.assertEqual(restored.count(), 3)
        self.assertEqual(restored.exceptAll(flat).count(), 0)
        self.assertEqual(flat.exceptAll(restored).count(), 0)
        self.assertTrue(list(output.glob("*.snappy.parquet")))
        self.assertTrue((output / "_SUCCESS").exists())
        self.assertFalse(list(output.glob("match_id=*")))
        self.assertEqual(flat.repartition(4).rdd.getNumPartitions(), 4)
        write_event_core(flat.filter(F.col("event_index") == 1), output)
        self.assertEqual(self.spark.read.parquet(str(output)).count(), 1)

    def test_job_dq_failure_never_calls_writer(self):
        fake_spark = MagicMock()
        raw = self.read().withColumn("id", F.lit(None).cast("string"))
        with (
            patch("pyspark.sql.SparkSession") as session,
            patch("src.silver.statsbomb.events.read_staged_events", return_value=raw),
            patch("src.silver.statsbomb.events.write_event_core") as writer,
        ):
            session.builder.appName.return_value.master.return_value.config.return_value.config.return_value.getOrCreate.return_value = fake_spark
            with self.assertRaisesRegex(EventArtifactError, "null_event_id=3"):
                job.build_local_preview([self.path])
        writer.assert_not_called()
        fake_spark.stop.assert_called_once()

    def test_job_rejects_selected_match_with_no_events(self):
        fake_spark = MagicMock()
        raw = self.read()
        with (
            patch("pyspark.sql.SparkSession") as session,
            patch("src.silver.statsbomb.events.read_staged_events", return_value=raw),
            patch("src.silver.statsbomb.events.write_event_core") as writer,
        ):
            session.builder.appName.return_value.master.return_value.config.return_value.config.return_value.getOrCreate.return_value = fake_spark
            with self.assertRaisesRegex(EventArtifactError, "matches_with_events=1, selected_artifacts=2"):
                job.build_local_preview([self.path, self.directory / "match_id=22.json"])
        writer.assert_not_called()

    def test_writer_repartitions_four_and_uses_snappy_overwrite(self):
        df = MagicMock()
        writer = df.repartition.return_value.write
        write_event_core(df, self.directory / "event_core")
        df.repartition.assert_called_once_with(4)
        writer.mode.assert_called_once_with("overwrite")
        writer.mode.return_value.option.assert_called_once_with("compression", "snappy")
        writer.mode.return_value.option.return_value.parquet.assert_called_once_with(str(self.directory / "event_core"))


class SilverJobSyntheticIntegrationTests(unittest.TestCase):
    def test_full_job_with_fake_catalog_and_in_memory_s3(self):
        """Real staging, checksum, Spark DQ/write and CLI; only external IO is mocked."""
        raw = FIXTURE.read_bytes()
        artifacts = [
            {
                "source_url": f"https://raw.githubusercontent.com/hudl/open-data/master/data/events/{n}.json",
                "s3_bucket": "offline-bucket", "object_key": f"offline/{n}.json",
                "sha256": sha256_bytes(raw), "size_bytes": len(raw),
            }
            for n in (11, 22, 33)
        ]
        client = MagicMock(spec=["get_object", "close"])
        client.get_object.side_effect = lambda **kwargs: {"Body": StreamingBody(io.BytesIO(raw), len(raw))}
        work = PROJECT_ROOT / "data/work"
        work.mkdir(parents=True, exist_ok=True)
        stdout = io.StringIO()
        with TemporaryDirectory(prefix="unittest_spark_job_", dir=work) as temporary:
            directory = Path(temporary)
            output = directory / "silver/event_core"
            with (
                patch.object(job, "create_postgres_connection"),
                patch.object(job, "find_latest_ingestion_objects", return_value=artifacts),
                patch.object(job, "create_s3_client", return_value=client),
                patch.object(job, "STAGING_DIR", directory / "bronze_events"),
                patch.object(job, "OUTPUT_DIR", output),
                redirect_stdout(stdout),
            ):
                self.assertEqual(job.main(["--limit", "2"]), 0)
            self.assertTrue((output / "_SUCCESS").exists())
            self.assertTrue(list(output.glob("*.snappy.parquet")))
            self.assertEqual((directory / "bronze_events/match_id=11.json").read_bytes(), raw)
            self.assertEqual((directory / "bronze_events/match_id=22.json").read_bytes(), raw)
            self.assertFalse((directory / "bronze_events/match_id=33.json").exists())
        self.assertEqual(client.get_object.call_count, 2)
        client.close.assert_called_once()
        for message in (
            "Silver event_core build complete", "Bronze artifacts selected: 2", "Matches processed: 2",
            "Events read: 6", "Events written: 6", "Output partitions: 4", "Spark version: 4.2.0",
        ):
            self.assertIn(message, stdout.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
