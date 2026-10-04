"""Stage 2C synthetic Spark tests: local JSON/Parquet only, no cloud calls."""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from context_fixtures import BRONZE_ARGS
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import ArrayType, DoubleType, StructType

from src.silver.statsbomb import event_domains as domain
from src.silver.statsbomb.events import EVENT_SCHEMA, read_s3a_events, transform_event_core
from src.silver.publish import validate_readback
from scripts import publish_silver_event_domains as cli
from silver_fakes import FakeS3, artifact
from src.common.checksum import sha256_bytes
from src.silver import job

COMMON_COLUMNS = [
    "competition_id", "season_id", "match_id", "event_id", "event_index", "period", "timestamp",
    "minute", "second", "team_id", "team_name", "player_id", "player_name", "start_x", "start_y",
]
PASS_COLUMNS = COMMON_COLUMNS + [
    "recipient_id", "recipient_name", "pass_length", "pass_angle", "end_x", "end_y",
    "height_id", "height_name", "body_part_id", "body_part_name", "pass_type_id", "pass_type_name",
    "outcome_id", "outcome_name", "technique_id", "technique_name",
    "cross", "cut_back", "switch", "shot_assist", "goal_assist", "aerial_won", "through_ball",
]
SHOT_COLUMNS = COMMON_COLUMNS + [
    "statsbomb_xg", "end_x", "end_y", "end_z", "key_pass_id", "body_part_id", "body_part_name",
    "shot_type_id", "shot_type_name", "technique_id", "technique_name", "outcome_id", "outcome_name",
    "first_time", "open_goal", "one_on_one", "aerial_won", "deflected",
]


class EventDomainSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.appName("football-domain-offline-tests").master("local[2]")
            .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4")
            .config("spark.sql.ansi.enabled", "true").getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("OFF")
        work = PROJECT_ROOT / "data/work"
        work.mkdir(parents=True, exist_ok=True)
        cls.temp = TemporaryDirectory(prefix="unittest_domains_", dir=work)
        cls.directory = Path(cls.temp.name)
        cls.path = cls.directory / "match_id=7" / ("sha256=" + "a" * 64) / "events.json"
        cls.path.parent.mkdir(parents=True)
        cls.path.write_bytes((PROJECT_ROOT / "tests/fixtures/statsbomb_event_domains.json").read_bytes())
        cls.raw = read_s3a_events(cls.spark, [str(cls.path)], schema=domain.DOMAIN_EVENT_SCHEMA).cache()
        cls.passes = domain.transform_pass_events(cls.raw, competition_id=43, season_id=106).cache()
        cls.shots = domain.transform_shot_events(cls.raw, competition_id=43, season_id=106).cache()

    @classmethod
    def tearDownClass(cls):
        cls.passes.unpersist()
        cls.shots.unpersist()
        cls.raw.unpersist()
        cls.spark.stop()
        cls.temp.cleanup()

    def check_pass(self, frame=None, raw=None, match_ids=None):
        return domain.validate_pass_events(
            self.passes if frame is None else frame, raw=self.raw if raw is None else raw,
            match_ids=[7] if match_ids is None else match_ids,
        )

    def check_shot(self, frame=None, raw=None, match_ids=None):
        return domain.validate_shot_events(
            self.shots if frame is None else frame, raw=self.raw if raw is None else raw,
            match_ids=[7] if match_ids is None else match_ids,
        )

    def test_explicit_nullable_schemas_ignore_unused_nested_data(self):
        self.assertEqual(self.raw.drop("match_id").schema, domain.DOMAIN_EVENT_SCHEMA)
        self.assertEqual(StructType(domain.DOMAIN_EVENT_SCHEMA.fields[:-2]), EVENT_SCHEMA)
        self.assertNotIn("pass", EVENT_SCHEMA.names)
        self.assertNotIn("shot", EVENT_SCHEMA.names)
        self.assertNotIn("tactics", self.raw.columns)
        for schema in (domain.PASS_SCHEMA, domain.SHOT_SCHEMA):
            self.assertTrue(all(field.nullable for field in schema))
            self.assertEqual(schema["end_location"].dataType, ArrayType(DoubleType(), True))
        self.assertNotIn("unused_nested", self.raw.schema["pass"].dataType.names)
        self.assertNotIn("freeze_frame", self.raw.schema["shot"].dataType.names)

    def test_pass_projection_filter_values_and_order(self):
        self.assertEqual(self.passes.columns, PASS_COLUMNS)
        self.assertEqual({r.event_id for r in self.passes.select("event_id").collect()}, {
            "pass-normal", "pass-incomplete", "pass-no-recipient", "pass-goal-assist",
        })
        row = self.passes.filter(F.col("event_id") == "pass-normal").first().asDict()
        expected = {
            "competition_id": 43, "season_id": 106, "match_id": 7, "event_index": 1,
            "period": 1, "timestamp": "00:00:01.250", "minute": 0, "second": 1,
            "team_id": 10, "team_name": "Red FC", "player_id": 100, "player_name": "Pass Player",
            "start_x": 12.5, "start_y": 23.75, "recipient_id": 101, "recipient_name": "Recipient Player",
            "pass_length": 15.25, "pass_angle": -0.5, "end_x": 25.0, "end_y": 30.0,
            "height_id": 1, "height_name": "Ground Pass", "body_part_id": 40, "body_part_name": "Right Foot",
            "pass_type_id": 64, "pass_type_name": "Recovery", "technique_id": 108, "technique_name": "Through Ball",
            "outcome_id": None, "outcome_name": None,
            "cross": True, "cut_back": False, "switch": True, "shot_assist": True,
            "goal_assist": False, "aerial_won": True, "through_ball": True,
        }
        self.assertEqual({name: row[name] for name in expected}, expected)
        failed = self.passes.filter(F.col("event_id") == "pass-incomplete").first()
        self.assertEqual((failed.outcome_id, failed.outcome_name), (9, "Incomplete"))
        self.assertTrue(self.passes.filter(F.col("event_id") == "pass-goal-assist").first().goal_assist)

    def test_pass_optional_nulls_are_preserved_without_defaults(self):
        row = self.passes.filter(F.col("event_id") == "pass-no-recipient").first().asDict()
        for name in ("player_id", "recipient_id", "outcome_id", "body_part_id", "technique_id", "pass_length", *domain.PASS_FLAGS):
            self.assertIsNone(row[name])
        output = io.StringIO()
        with redirect_stdout(output):
            counts = self.check_pass()
        self.assertEqual(counts["row_count"], 4)
        self.assertEqual(counts["expected_row_count"], 4)
        self.assertEqual(counts["input_row_count"], 12)
        self.assertEqual(counts["null_recipient_id"], 2)
        self.assertIn("Informational NULLs pass_events:", output.getvalue())

    def test_shot_projection_filter_values_and_order(self):
        self.assertEqual(self.shots.columns, SHOT_COLUMNS)
        self.assertEqual({r.event_id for r in self.shots.select("event_id").collect()}, {
            "shot-normal", "shot-goal", "shot-null-optionals",
        })
        row = self.shots.filter(F.col("event_id") == "shot-normal").first().asDict()
        expected = {
            "match_id": 7, "event_index": 5, "period": 1, "timestamp": "00:00:05.500",
            "start_x": 100.0, "start_y": 40.0, "statsbomb_xg": 0.12,
            "end_x": 120.0, "end_y": 42.0, "end_z": None, "key_pass_id": "pass-normal",
            "body_part_id": 40, "body_part_name": "Right Foot", "shot_type_id": 87, "shot_type_name": "Open Play",
            "technique_id": 93, "technique_name": "Normal", "outcome_id": 100, "outcome_name": "Saved",
            "first_time": False, "open_goal": False, "one_on_one": True, "aerial_won": False, "deflected": True,
        }
        self.assertEqual({name: row[name] for name in expected}, expected)
        goal = self.shots.filter(F.col("event_id") == "shot-goal").first()
        self.assertEqual((goal.end_z, goal.outcome_name, goal.key_pass_id, goal.statsbomb_xg), (1.25, "Goal", "pass-goal-assist", 0.75))

    def test_shot_optional_nulls_and_informational_counts(self):
        row = self.shots.filter(F.col("event_id") == "shot-null-optionals").first().asDict()
        for name in ("player_id", "key_pass_id", "body_part_id", "technique_id", "end_z", *domain.SHOT_FLAGS):
            self.assertIsNone(row[name])
        output = io.StringIO()
        with redirect_stdout(output):
            counts = self.check_shot()
        self.assertEqual((counts["row_count"], counts["expected_row_count"], counts["input_row_count"]), (3, 3, 12))
        self.assertEqual(counts["null_end_z"], 2)
        self.assertIn("Informational NULLs shot_events:", output.getvalue())

    def test_short_empty_and_null_coordinates_are_safe_in_ansi_mode(self):
        for transform, nested in ((domain.transform_pass_events, "pass"), (domain.transform_shot_events, "shot")):
            for values in (None, [], [8.0]):
                with self.subTest(domain=nested, values=values):
                    array = F.lit(values).cast("array<double>")
                    raw = self.raw.withColumn("location", array).withColumn(nested, F.col(nested).withField("end_location", array))
                    row = transform(raw, competition_id=1, season_id=2).first()
                    self.assertEqual(row.start_x, 8.0 if values else None)
                    self.assertEqual(row.end_x, 8.0 if values else None)
                    self.assertIsNone(row.start_y)
                    self.assertIsNone(row.end_y)
                    if nested == "shot":
                        self.assertIsNone(row.end_z)

    def test_context_parameters_and_no_python_udf(self):
        for transform in (domain.transform_pass_events, domain.transform_shot_events):
            frame = transform(self.raw, competition_id=12, season_id=34)
            self.assertEqual((frame.first().competition_id, frame.first().season_id), (12, 34))
            self.assertNotIn("PythonUDF", frame._jdf.queryExecution().executedPlan().toString())

    def test_pass_required_nulls_fail(self):
        for name in ("match_id", "event_id", "event_index", "team_id"):
            with self.subTest(column=name), self.assertRaises(domain.DomainEventQualityError):
                self.check_pass(self.passes.withColumn(name, F.lit(None).cast(self.passes.schema[name].dataType)))

    def test_shot_required_nulls_fail(self):
        for name in ("match_id", "event_id", "event_index", "team_id", "statsbomb_xg", "outcome_id"):
            with self.subTest(column=name), self.assertRaises(domain.DomainEventQualityError):
                self.check_shot(self.shots.withColumn(name, F.lit(None).cast(self.shots.schema[name].dataType)))

    def test_duplicate_keys_fail_for_both_domains(self):
        for frame, check in ((self.passes, self.check_pass), (self.shots, self.check_shot)):
            # Same count as expected: the duplicate check itself must catch the corruption.
            bad = frame.withColumn("event_id", F.lit("duplicate"))
            with self.assertRaisesRegex(domain.DomainEventQualityError, "duplicate_keys=1"):
                check(bad)

    def test_negative_pass_length_fails(self):
        with self.assertRaisesRegex(domain.DomainEventQualityError, "invalid_domain_values=4"):
            self.check_pass(self.passes.withColumn("pass_length", F.lit(-0.01)))

    def test_xg_out_of_range_or_nan_fails(self):
        for value in (-0.01, 1.01, float("nan")):
            with self.subTest(xg=value), self.assertRaisesRegex(domain.DomainEventQualityError, "invalid_domain_values=3"):
                self.check_shot(self.shots.withColumn("statsbomb_xg", F.lit(value)))

    def test_xg_boundaries_are_valid(self):
        for value in (0.0, 1.0):
            self.assertEqual(self.check_shot(self.shots.withColumn("statsbomb_xg", F.lit(value)))["row_count"], 3)

    def test_lost_rows_fail_expected_count_consistency(self):
        for frame, check in ((self.passes, self.check_pass), (self.shots, self.check_shot)):
            with self.assertRaisesRegex(domain.DomainEventQualityError, "expected_row_count="):
                check(frame.filter(F.col("event_index") != frame.agg(F.min("event_index")).first()[0]))

    def test_empty_domain_fails(self):
        for frame, check in ((self.passes, self.check_pass), (self.shots, self.check_shot)):
            with self.assertRaisesRegex(domain.DomainEventQualityError, "row_count=0"):
                check(frame.limit(0))

    def test_exact_selected_membership_and_missing_match_fail(self):
        for frame, check in ((self.passes, self.check_pass), (self.shots, self.check_shot)):
            with self.assertRaisesRegex(domain.DomainEventQualityError, "unexpected_match_rows="):
                check(frame.withColumn("match_id", F.lit(99)))
            with self.assertRaises(domain.DomainEventQualityError):
                check(match_ids=[7, 8])

    def test_reader_and_build_use_explicit_immutable_paths_for_multiple_matches(self):
        other = self.directory / "match_id=8" / ("sha256=" + "b" * 64) / "events.json"
        other.parent.mkdir(parents=True)
        other.write_bytes(self.path.read_bytes())
        for name, count in (("passes", 8), ("shots", 6)):
            frame, counts = domain.build_domain_frame(
                self.spark, [str(self.path), str(other)], [7, 8], dataset=name, competition_id=43, season_id=106,
            )
            try:
                self.assertEqual((counts["row_count"], counts["match_count"], counts["input_row_count"]), (count, 2, 24))
                self.assertEqual({r.match_id for r in frame.select("match_id").distinct().collect()}, {7, 8})
            finally:
                frame.unpersist()

    def test_domain_parquet_roundtrip_preserves_schema_and_counts(self):
        for name, frame, count in (("passes", self.passes, 4), ("shots", self.shots, 3)):
            output = self.directory / name
            frame.repartition(4).write.mode("errorifexists").option("compression", "snappy").parquet(str(output))
            files = [{"object_key": str(path)} for path in output.glob("part-*.snappy.parquet")]
            self.assertTrue((output / "_SUCCESS").exists())
            # Small synthetic inputs may leave an empty partition without a part file.
            self.assertGreaterEqual(len(files), 1)
            self.assertLessEqual(len(files), 4)
            with patch("src.silver.publish.s3a_uri", side_effect=lambda bucket, key: key):
                validate_readback(self.spark, frame, {"row_count": count, "match_count": 1}, bucket="unused", files=files)

    def test_event_core_contract_and_rows_remain_unchanged_with_extended_reader(self):
        core_raw = read_s3a_events(self.spark, [str(self.path)])
        before = transform_event_core(core_raw, competition_id=43, season_id=106)
        extended = transform_event_core(self.raw, competition_id=43, season_id=106)
        self.assertEqual(core_raw.drop("match_id").schema, EVENT_SCHEMA)
        self.assertEqual(before.schema.json(), extended.schema.json())
        self.assertEqual(before.count(), 12)
        self.assertEqual(before.exceptAll(extended).count(), 0)

    def test_check_only_cli_runs_real_domain_read_transform_dq_and_fingerprints(self):
        client = FakeS3()
        parent = b'[{"match_id": 7, "competition": {"competition_id": 43}, "season": {"season_id": 106}}]'
        client.seed("test-bucket", "parent.json", parent)
        item = artifact(7)
        client.seed("test-bucket", item["object_key"], metadata={"sha256": item["sha256"]})
        for choice, count in (("passes", 4), ("shots", 3)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}),
                patch.object(job, "create_postgres_connection"),
                patch.object(job, "create_s3_client", return_value=client),
                patch.object(job, "find_matches_parent", return_value={
                    "s3_bucket": "test-bucket", "object_key": "parent.json", "sha256": sha256_bytes(parent),
                }),
                patch.object(job, "find_latest_ingestion_objects", return_value=[artifact(99), item]),
                patch.object(job, "event_artifact_s3a_path", return_value=str(self.path)),
                patch.object(job, "create_spark_session", return_value=self.spark),
                patch.object(job, "configure_s3a"),
                patch.object(job, "publish_build") as publisher,
                patch.object(self.spark, "stop"),
                redirect_stdout(stdout), redirect_stderr(stderr),
            ):
                self.assertEqual(cli.main(BRONZE_ARGS + ["--dataset", choice, "--limit", "1", "--check-only"]), 0, stderr.getvalue())
                publisher.assert_not_called()
            for text in ("Input events: 12", f"Domain events: {count}", "Matches processed: 1",
                         "Input fingerprint:", "Schema SHA256:", "Build ID:", "DQ: PASSED", "CHECK ONLY - nothing published"):
                self.assertIn(text, stdout.getvalue())
        self.assertFalse(any(call[0] in ("list", "put") for call in client.calls))

    def test_dq_rejects_accidental_row_loss_in_builder(self):
        for choice, transform_name in (("passes", "transform_pass_events"), ("shots", "transform_shot_events")):
            transform = getattr(domain, transform_name)

            def lossy(raw, **context):
                return transform(raw, **context).limit(1)

            with patch.object(domain, transform_name, side_effect=lossy), self.assertRaises(domain.DomainEventQualityError):
                domain.build_domain_frame(self.spark, [str(self.path)], [7], dataset=choice, competition_id=43, season_id=106)


if __name__ == "__main__":
    unittest.main(verbosity=2)
