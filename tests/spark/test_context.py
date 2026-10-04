"""Two synthetic contexts reuse IDs without changing Silver/Gold semantics. No cloud IO."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pyspark.sql import SparkSession, functions as F
from src.silver.statsbomb import events, event_domains, lineups, matches
from src.gold.statsbomb.match_stats import build_match_stats
from src.gold.statsbomb.match_results import build_match_results

spec = importlib.util.spec_from_file_location("spark_results_fixtures", Path(__file__).with_name("test_match_results.py"))
fixtures_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures_module)


class ContextSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("context-synthetic")
                     .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2").getOrCreate())
        cls.spark.sparkContext.setLogLevel("OFF")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def assert_context(self, frame, context):
        self.assertEqual([r.asDict() for r in frame.select("competition_id", "season_id").distinct().collect()], [context])
        self.assertGreater(frame.count(), 0)

    def test_all_silver_projections_keep_explicit_context(self):
        raw_events = self.spark.read.schema(event_domains.DOMAIN_EVENT_SCHEMA).option("multiLine", True).json(
            str(ROOT / "tests/fixtures/statsbomb_event_domains.json")).withColumn("match_id", F.lit(7).cast("long"))
        raw_lineups = self.spark.read.schema(lineups.LINEUP_SCHEMA).option("multiLine", True).json(
            [str(ROOT / f"tests/fixtures/statsbomb_lineups_match_{match_id}.json") for match_id in (7, 8)]
        ).withColumn("match_id", F.lit(7).cast("long"))
        source = json.loads((ROOT / "tests/fixtures/statsbomb_matches.json").read_text())
        for context in ({"competition_id": 7, "season_id": 9}, {"competition_id": 80, "season_id": 10}):
            squads = lineups.transform_match_squads(raw_lineups, **context)
            for frame in (events.transform_event_core(raw_events, **context),
                          event_domains.transform_pass_events(raw_events, **context),
                          event_domains.transform_shot_events(raw_events, **context), squads,
                          lineups.transform_teams(squads, **context), lineups.transform_players(squads, **context)):
                self.assert_context(frame, context)
            for row in source:
                row["competition"]["competition_id"] = context["competition_id"]
                row["season"]["season_id"] = context["season_id"]
            frame, _ = matches.build_matches(self.spark, json.dumps(source).encode(),
                                             lineups.transform_teams(squads, **context), **context)
            self.addCleanup(frame.unpersist)
            self.assert_context(frame, context)

    def test_gold_results_and_v2_metrics_identical_across_contexts(self):
        original = fixtures_module.fixtures(self.spark)
        baseline = {}
        for context in ({"competition_id": 7, "season_id": 9}, {"competition_id": 80, "season_id": 10}):
            frames = {name: frame.withColumn("competition_id", F.lit(context["competition_id"]).cast("long"))
                      .withColumn("season_id", F.lit(context["season_id"]).cast("long")) for name, frame in original.items()}
            for dataset in ("team_match_stats", "player_match_stats", "match_results"):
                if dataset == "match_results":
                    result, _ = build_match_results(frames, **context)
                else:
                    result, _ = build_match_stats(frames, dataset=dataset, transform_version=dataset + "_v2", **context)
                try:
                    self.assert_context(result, context)
                    values = sorted(result.drop("competition_id", "season_id").toJSON().collect())
                    if dataset in baseline:
                        self.assertEqual(values, baseline[dataset])
                    baseline[dataset] = values
                finally:
                    result.unpersist()


if __name__ == "__main__":
    unittest.main(verbosity=2)
