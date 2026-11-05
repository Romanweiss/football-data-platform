"""Actual Spark phase/failure/replay checks on artificial rows, no source data or network."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from pyspark.sql import SparkSession
from openfootball_etl_fakes import fixture
from src.openfootball_etl.contract import ETLError, GOLD
from src.openfootball_etl.pipeline import bronze, bundle, gold_rows, initialize, inventory, read_json, writer
from src.openfootball_etl.spark_job import run_phase


class OpenFootballSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("synthetic-openfootball")
            .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2")
            .config("spark.sql.session.timeZone", "UTC").getOrCreate())
        cls.spark.sparkContext.setLogLevel("OFF")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_actual_parquet_readback_silver_failure_retry_gold_and_replay(self):
        with tempfile.TemporaryDirectory(prefix="pet3-synthetic-spark-") as temporary:
            store = initialize(Path(temporary) / "owned")
            raw, result = fixture()
            batch = "a" * 64
            source, _ = bronze(store, raw, {"synthetic": True}, result)
            def fail_after_first(index):
                if index == 0:
                    raise ETLError("SYNTHETIC_SPARK_FAILURE")
            with writer(store) as token, patch("src.openfootball_etl.spark_job.proposal", return_value=result):
                with self.assertRaisesRegex(ETLError, "SYNTHETIC_SPARK_FAILURE"):
                    run_phase(self.spark, store, source, batch, "silver", token, fault=fail_after_first)
                self.assertFalse((bundle(store, batch) / "silver").exists())
                self.assertEqual("CREATED", run_phase(self.spark, store, source, batch, "silver", token))
                self.assertEqual("CREATED", run_phase(self.spark, store, source, batch, "gold", token))
                before = inventory(bundle(store, batch))
                self.assertEqual("REUSED", run_phase(self.spark, store, source, batch, "silver", token))
                self.assertEqual("REUSED", run_phase(self.spark, store, source, batch, "gold", token))
                self.assertEqual(before, inventory(bundle(store, batch)))
                data = gold_rows(store, batch)
                self.assertEqual(set(GOLD), set(data))
                self.assertEqual(4, len(data["historical_fixtures"]))
                self.assertEqual(4, len(data["competition_participants"]))
                self.assertEqual(3, len(data["stage_round_coverage"]))
                self.assertEqual(len(result.dq.limitations), len(data["source_quality"]))
                missing = next(r for r in data["historical_fixtures"] if r["result_availability"] == "MISSING")
                self.assertIsNone(missing["source_ft_home"])
                self.assertEqual("unknown", missing["status"])
                self.assertTrue(all(r["kickoff_utc"] is None and r["regulation_home"] is None and
                                    not r["standings_eligible"] for r in data["historical_fixtures"]))
                frame = self.spark.read.parquet(str(bundle(store, batch) / "gold/historical_fixtures/parquet"))
                self.assertEqual("date", frame.schema["match_date"].dataType.simpleString())
                ledger = read_json(bundle(store, batch) / "silver/versions.json")
                self.assertTrue(all(len(s["versions"]) == 1 for s in ledger["streams"]))

    def test_independent_builds_have_identical_logical_content_not_random_filenames(self):
        with tempfile.TemporaryDirectory(prefix="pet3-synthetic-rebuild-") as temporary:
            raw, result = fixture()
            manifests = []
            for name in ("first", "second"):
                store = initialize(Path(temporary) / name)
                source, _ = bronze(store, raw, {"synthetic": True}, result)
                with writer(store) as token, patch("src.openfootball_etl.spark_job.proposal", return_value=result):
                    for phase in ("silver", "gold"):
                        run_phase(self.spark, store, source, "b" * 64, phase, token)
                manifests.append({phase: read_json(bundle(store, "b" * 64) / phase / "_manifest.json")["datasets"]
                                  for phase in ("silver", "gold")})
            self.assertEqual(manifests[0], manifests[1])


if __name__ == "__main__":
    unittest.main()
