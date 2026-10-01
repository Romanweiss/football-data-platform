"""Gold synthetic Spark tests, no real S3/PostgreSQL/ClickHouse calls."""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyspark.sql import SparkSession, functions as F
from gold_fixture import silver_frames
from gold_fakes import silver_inputs
from test_clickhouse_silver_input import seed_manifest
from src.gold import inputs, job, publish
from src.gold.build_identity import OUTPUT_PARTITIONS
from src.gold.manifest import GoldIntegrityError
from src.gold.statsbomb.match_stats import COUNT_METRICS, SHOT_GOAL_OUTCOME_ID, build_match_stats, validate_output
from src.silver.manifest import inspect_silver_output


class GoldSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.appName("football-gold-synthetic-tests").master("local[2]")
                     .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2").getOrCreate())
        cls.spark.sparkContext.setLogLevel("OFF")
        cls.frames = {name: frame.cache() for name, frame in silver_frames(cls.spark).items()}
        cls.results = {}
        for dataset in ("team_match_stats", "player_match_stats"):
            cls.results[dataset] = build_match_stats(cls.frames, dataset=dataset, competition_id=43, season_id=106)
        cls.temp = TemporaryDirectory(prefix="football-gold-test-")
        cls.directory = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        for frame in [*cls.frames.values(), *[result[0] for result in cls.results.values()]]:
            frame.unpersist()
        cls.spark.stop()
        cls.temp.cleanup()

    def build(self, frames, dataset):
        with redirect_stdout(io.StringIO()):
            result = build_match_stats(frames, dataset=dataset, competition_id=43, season_id=106)
        self.addCleanup(result[0].unpersist)
        return result

    def test_team_aggregates_zero_fill_and_no_row_multiplication(self):
        frame, counts = self.results["team_match_stats"]
        rows = {(row.match_id, row.team_id): row for row in frame.collect()}
        self.assertEqual((counts["row_count"], counts["match_count"]), (4, 2))
        row = rows[7, 10]
        self.assertEqual((row.event_count, row.pass_attempts, row.shot_count, row.shot_goals,
                          row.under_pressure_events, row.counterpress_events, row.players_with_events), (5, 2, 2, 1, 3, 1, 1))
        self.assertAlmostEqual(row.shot_xg, 0.3)
        self.assertEqual((rows[7, 20].shot_count, rows[7, 20].shot_xg), (0, 0.0))
        for metric in (*COUNT_METRICS, "players_with_events", "shot_xg"):
            self.assertEqual(rows[8, 20][metric], 0)
        self.assertEqual(rows[8, 10].shot_goals, 0)  # No own-goal reinterpretation.
        self.assertEqual(frame.groupBy("match_id").count().filter(F.col("count") != 2).count(), 0)

    def test_player_aggregates_keep_all_squads_and_match_level_names(self):
        frame, counts = self.results["player_match_stats"]
        self.assertEqual(counts["row_count"], self.frames["match_squads"].count())
        rows = {(row.match_id, row.team_id, row.player_id): row for row in frame.collect()}
        scorer = rows[7, 10, 100]
        self.assertEqual((scorer.event_count, scorer.pass_attempts, scorer.shot_count, scorer.shot_goals,
                          scorer.under_pressure_events, scorer.counterpress_events), (4, 2, 2, 1, 2, 1))
        self.assertAlmostEqual(scorer.shot_xg, 0.3)
        self.assertEqual((rows[7, 20, 200].pass_attempts, rows[7, 20, 200].shot_count), (1, 0))
        for metric in (*COUNT_METRICS, "shot_xg"):
            self.assertEqual(rows[7, 10, 101][metric], 0)
        self.assertEqual(scorer.player_name, "Phil Foden")
        self.assertEqual(rows[8, 10, 100].player_name, "Philip Foden")

    def test_null_player_facts_still_count_for_team_not_player(self):
        frames = dict(self.frames)
        for name in ("pass_events", "shot_events"):
            frames[name] = frames[name].unionByName(frames[name].limit(1).withColumn("player_id", F.lit(None).cast("long")))
        team, _ = self.build(frames, "team_match_stats")
        player, _ = self.build(frames, "player_match_stats")
        self.assertEqual(team.agg(F.sum("pass_attempts")).first()[0], 4)
        self.assertEqual(player.exceptAll(self.results["player_match_stats"][0]).count(), 0)

    def test_each_team_or_player_orphan_metric_key_fails(self):
        for dataset in ("team_match_stats", "player_match_stats"):
            for name in ("event_core", "pass_events", "shot_events"):
                frames = dict(self.frames)
                field = "player_id" if dataset == "player_match_stats" else "team_id"
                frames[name] = frames[name].withColumn(field, F.lit(999).cast("long"))
                with self.subTest(dataset=dataset, input=name), self.assertRaises(GoldIntegrityError):
                    self.build(frames, dataset)

    def test_duplicate_base_grain_fails(self):
        frames = dict(self.frames)
        frames["match_squads"] = frames["match_squads"].unionByName(frames["match_squads"].limit(1))
        with self.assertRaises(GoldIntegrityError):
            self.build(frames, "player_match_stats")
        frames["match_squads"] = self.frames["match_squads"].unionByName(
            self.frames["match_squads"].limit(1).withColumn("team_name", F.lit("conflict")))
        with self.assertRaises(GoldIntegrityError):
            self.build(frames, "team_match_stats")

    def test_output_dq_rejects_nulls_negative_nonfinite_and_excess_goals(self):
        for dataset, (frame, _) in self.results.items():
            bad_frames = [frame.limit(0), frame.unionByName(frame.limit(1)),
                          frame.withColumn("team_name", F.lit(None).cast("string")),
                          frame.withColumn("competition_id", F.lit(999)),
                          frame.withColumn("event_count", F.lit(-1)),
                          frame.withColumn("shot_goals", F.col("shot_count") + 1)]
            bad_frames += [frame.withColumn("shot_xg", F.lit(value).cast("double")) for value in (-1.0, float("nan"), float("inf"), None)]
            for index, bad in enumerate(bad_frames):
                with self.subTest(dataset=dataset, index=index), redirect_stdout(io.StringIO()), self.assertRaises(GoldIntegrityError):
                    validate_output(bad, dataset=dataset, competition_id=43, season_id=106)
        team = self.results["team_match_stats"][0].filter(F.col("team_id") == 10)
        with redirect_stdout(io.StringIO()), self.assertRaises(GoldIntegrityError):
            validate_output(team, dataset="team_match_stats", competition_id=43, season_id=106)

    def test_repartition_determinism_and_exact_output_types(self):
        for dataset, (original, _) in self.results.items():
            frames = {name: frame.orderBy(F.col("match_id").desc()).repartition(3) for name, frame in self.frames.items()}
            rebuilt, _ = self.build(frames, dataset)
            self.assertEqual(original.exceptAll(rebuilt).count(), 0)
            self.assertEqual(rebuilt.exceptAll(original).count(), 0)
            self.assertEqual(original.schema.json(), rebuilt.schema.json())
            for metric in COUNT_METRICS:
                self.assertEqual(original.schema[metric].dataType.simpleString(), "bigint")
            self.assertEqual(original.schema["shot_xg"].dataType.simpleString(), "double")
            self.assertNotIn("PythonUDF", original._jdf.queryExecution().executedPlan().toString())
            self.assertNotIn("minutes_played", original.columns)

    def test_goal_value_is_existing_statsbomb_fixture_contract(self):
        records = json.loads((ROOT / "tests/fixtures/statsbomb_event_domains.json").read_text())
        goals = [row["shot"]["outcome"] for row in records if ((row.get("shot") or {}).get("outcome") or {}).get("name") == "Goal"]
        self.assertTrue(goals)
        self.assertTrue(all(outcome["id"] == SHOT_GOAL_OUTCOME_ID for outcome in goals))

    def test_gold_readback_exact_contents_and_writer_settings(self):
        for dataset, (frame, _) in self.results.items():
            path = self.directory / dataset
            # Exercise production writer, mapping only its URI to a local destination.
            class LocalWriter:
                def __init__(self, delegate):
                    self.delegate = delegate
                def mode(self, value):
                    self.delegate = self.delegate.mode(value)
                    self.mode_value = value
                    return self
                def option(self, key, value):
                    self.delegate = self.delegate.option(key, value)
                    return self
                def parquet(self, uri):
                    if self.mode_value != "errorifexists":
                        raise AssertionError("unsafe write mode")
                    self.delegate.parquet(str(path))
            from unittest.mock import MagicMock
            proxy = MagicMock()
            proxy.repartition.side_effect = lambda count: type("Partitioned", (), {"write": LocalWriter(frame.repartition(count).write)})()
            publish.write_new_parquet(proxy, "s3a://test-bucket/gold/", partitions=OUTPUT_PARTITIONS[dataset])
            proxy.repartition.assert_called_once_with(OUTPUT_PARTITIONS[dataset])
            files = [{"object_key": str(item)} for item in path.glob("part-*.snappy.parquet")]
            self.assertEqual(len(files), OUTPUT_PARTITIONS[dataset])
            with patch.object(publish, "s3a_uri", side_effect=lambda bucket, key: key):
                publish.validate_readback(self.spark, frame, bucket="unused", files=files)
                # Same row count/schema but wrong metrics must fail recovery.
                with self.assertRaises(GoldIntegrityError):
                    publish.validate_readback(self.spark, frame.withColumn("event_count", F.col("event_count") + 1), bucket="unused", files=files)

    def test_real_silver_preflight_local_parquet_and_full_check_only_cli(self):
        client, builds, manifests = silver_inputs()
        client.objects.clear()  # Only this test's in-memory fake.
        paths = {}
        io_frames = dict(self.frames)
        for name in ("pass_events", "shot_events"):
            io_frames[name] = self.frames[name].unionByName(self.frames[name].withColumn("match_id", F.lit(8).cast("long")))
        for build in builds:
            name = build["dataset"]
            path = self.directory / ("silver-" + name)
            io_frames[name].repartition(1).write.mode("errorifexists").parquet(str(path))
            client.seed("test-bucket", build["s3_prefix"] + "_SUCCESS", b"{}")
            for part in path.glob("part-*.snappy.parquet"):
                key = build["s3_prefix"] + part.name
                client.seed("test-bucket", key)
                paths[key] = str(part)
            files = inspect_silver_output(client, bucket="test-bucket", prefix=build["s3_prefix"])
            build.update(row_count=io_frames[name].count(), file_count=len(files))
            manifests[name].update(row_count=build["row_count"], file_count=len(files), files=files,
                                   match_count=2)
            seed_manifest(client, build, manifests[name])
        with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True), \
                patch.object(inputs, "find_latest_silver_build", side_effect=lambda *a, **kw: next(b for b in builds if b["dataset"] == kw["dataset"])):
            selected, verified = inputs.resolve_inputs(None, client, competition_id=43, season_id=106, diagnostics=job.Diagnostics())
        # Actual Parquet counts must match the registered build before transformation.
        incorrect = [{**build, "row_count": build["row_count"] + 1} for build in selected]
        with patch.object(inputs, "s3a_uri", side_effect=lambda bucket, key: paths[key]), self.assertRaises(GoldIntegrityError):
            inputs.read_inputs(self.spark, incorrect, verified, diagnostics=job.Diagnostics())
        with patch.object(inputs, "s3a_uri", side_effect=lambda bucket, key: paths[key]):
            frames = inputs.read_inputs(self.spark, selected, verified, diagnostics=job.Diagnostics())
        for frame in frames.values():
            frame.unpersist()
        for option in ("team-match-stats", "player-match-stats"):
            output = io.StringIO()
            with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True), \
                    patch.object(job, "create_postgres_connection"), patch.object(job, "create_s3_client", return_value=client), \
                    patch.object(inputs, "find_latest_silver_build", side_effect=lambda *a, **kw: next(b for b in builds if b["dataset"] == kw["dataset"])), \
                    patch.object(job, "create_spark_session", return_value=self.spark), patch.object(job, "configure_s3a"), \
                    patch.object(self.spark, "stop"), patch.object(inputs, "s3a_uri", side_effect=lambda bucket, key: paths[key]), \
                    patch.object(job, "publish_build") as writer, redirect_stdout(output):
                self.assertEqual(job.main(["--dataset", option, "--check-only"]), 0)
                writer.assert_not_called()
            self.assertIn("CHECK ONLY - nothing published", output.getvalue())
        self.assertFalse(any(call[0] == "put" for call in client.calls))
        self.assertTrue(all(call[2].endswith("_manifest.json") for call in client.calls if call[0] == "get"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
