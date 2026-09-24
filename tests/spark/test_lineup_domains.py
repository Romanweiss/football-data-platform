"""Stage 2D synthetic Spark tests; exact local fixture paths and mocked cloud IO."""

import io
import json
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

from pyspark.sql import SparkSession, functions as F
from scripts import publish_silver_lineup_domains as cli
from silver_fakes import FakeS3
from test_lineup_inputs import lineup_artifact
from src.common.checksum import sha256_bytes
from src.silver import job, publish
from src.silver.diagnostics import PublishDiagnostics
from src.silver.statsbomb import lineups as domain

SQUAD_COLUMNS = ["competition_id", "season_id", "match_id", "team_id", "team_name", "player_id", "player_name",
                 "player_nickname", "jersey_number", "country_id", "country_name"]
TEAM_COLUMNS = ["competition_id", "season_id", "team_id", "team_name"]
PLAYER_COLUMNS = ["competition_id", "season_id", "player_id", "player_name", "player_nickname", "country_id", "country_name"]


class LineupSparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.appName("football-lineup-offline-tests").master("local[2]")
                     .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4")
                     .config("spark.sql.ansi.enabled", "true").getOrCreate())
        cls.spark.sparkContext.setLogLevel("OFF")
        work = PROJECT_ROOT / "data/work"
        work.mkdir(parents=True, exist_ok=True)
        cls.temp = TemporaryDirectory(prefix="unittest_lineups_", dir=work)
        cls.directory = Path(cls.temp.name)
        cls.paths = []
        for match_id in (7, 8):
            path = cls.directory / "lineups" / f"match_id={match_id}" / ("sha256=" + "a" * 64) / "lineups.json"
            path.parent.mkdir(parents=True)
            path.write_bytes((PROJECT_ROOT / f"tests/fixtures/statsbomb_lineups_match_{match_id}.json").read_bytes())
            cls.paths.append(str(path))
        cls.raw = domain.read_s3a_lineups(cls.spark, cls.paths).cache()
        cls.context = {"competition_id": 43, "season_id": 106}
        cls.squads = domain.transform_match_squads(cls.raw, **cls.context).cache()
        cls.teams = domain.transform_teams(cls.squads, **cls.context).cache()
        cls.players = domain.transform_players(cls.squads, **cls.context).cache()

    @classmethod
    def tearDownClass(cls):
        for frame in (cls.players, cls.teams, cls.squads, cls.raw):
            frame.unpersist()
        cls.spark.stop()
        cls.temp.cleanup()

    def check_squads(self, frame=None, raw=None, ids=None):
        return domain.validate_match_squads(self.squads if frame is None else frame,
                                           raw=self.raw if raw is None else raw, match_ids=[7, 8] if ids is None else ids)

    def test_reader_exact_schema_match_ids_and_ignored_fields(self):
        self.assertEqual(self.raw.drop("match_id").schema, domain.LINEUP_SCHEMA)
        self.assertEqual(self.raw.count(), 4)
        self.assertEqual({r.match_id for r in self.raw.select("match_id").distinct().collect()}, {7, 8})
        self.assertNotIn("unused_team_field", self.raw.columns)
        self.assertNotIn("positions", domain.LINEUP_PLAYER_SCHEMA.names)
        self.assertNotIn("cards", domain.LINEUP_PLAYER_SCHEMA.names)

    def test_path_regex_rejects_invalid_ids_hashes_and_suffixes(self):
        base = "s3a://test-bucket/football/bronze/statsbomb/lineups"
        good = f"{base}/match_id=7/sha256={'a' * 64}/lineups.json"
        cases = [(good, 7), (good.replace("match_id=7", "match_id=0"), None),
                 (good.replace("match_id=7", "match_id=07"), None), (good.replace("match_id=7", "match_id=-1"), None),
                 (good.replace("match_id=7", f"match_id={2**63}"), None),
                 (good.replace("a" * 64, "A" * 64), None), (good.replace("a" * 64, "a" * 63), None),
                 (good.replace("lineups.json", "events.json"), None), (good + "?token=x", None),
                 (good.replace("/lineups/", "/events/"), None)]
        frame = self.spark.createDataFrame([(i, path) for i, (path, _) in enumerate(cases)], "index int, path string")
        found = frame.select("index", domain.lineup_match_id(F.col("path")).alias("match_id")).orderBy("index").collect()
        self.assertEqual([row.match_id for row in found], [value for _, value in cases])

    def test_squad_projection_explode_and_nullable_values(self):
        self.assertEqual(self.squads.columns, SQUAD_COLUMNS)
        self.assertEqual(self.squads.count(), 8)
        row = self.squads.filter((F.col("match_id") == 7) & (F.col("player_id") == 100)).first()
        self.assertEqual((row.team_id, row.team_name, row.player_name, row.jersey_number, row.country_id), (10, "Red FC", "Alex", 7, 1000))
        self.assertIsNone(row.player_nickname)
        optional = self.squads.filter(F.col("player_id") == 201).first()
        self.assertIsNone(optional.country_id)
        self.assertIsNone(optional.country_name)
        self.assertIsNone(self.squads.filter(F.col("player_id") == 200).first().jersey_number)
        self.assertFalse({"starter", "captain", "substitute", "position"} & set(self.squads.columns))
        self.assertNotIn("PythonUDF", self.squads._jdf.queryExecution().executedPlan().toString())

    def test_context_is_parameterized(self):
        squads = domain.transform_match_squads(self.raw, competition_id=12, season_id=34)
        for frame in (squads, domain.transform_teams(squads, competition_id=12, season_id=34),
                      domain.transform_players(squads, competition_id=12, season_id=34)):
            row = frame.first()
            self.assertEqual((row.competition_id, row.season_id), (12, 34))

    def test_squad_dq_counts_and_references_pass(self):
        counts = self.check_squads()
        self.assertEqual((counts["row_count"], counts["match_count"], counts["raw_lineup_team_rows"], counts["raw_lineup_player_rows"]), (8, 2, 4, 8))
        self.assertEqual(domain.validate_teams(self.teams)["row_count"], 3)
        self.assertEqual(domain.validate_players(self.players)["row_count"], 6)
        self.assertEqual(domain.validate_references(self.squads, self.teams, self.players), {"missing_team_references": 0, "missing_player_references": 0})

    def test_required_squad_nulls_fail(self):
        for name in ("match_id", "team_id", "team_name", "player_id", "player_name"):
            with self.subTest(column=name), self.assertRaises(domain.LineupQualityError):
                self.check_squads(self.squads.withColumn(name, F.lit(None).cast(self.squads.schema[name].dataType)))

    def test_duplicate_squad_key_fails(self):
        with self.assertRaises(domain.LineupQualityError):
            self.check_squads(self.squads.withColumn("player_id", F.lit(1)))

    def test_unexpected_and_missing_match_fail(self):
        with self.assertRaises(domain.LineupQualityError):
            self.check_squads(self.squads.withColumn("match_id", F.lit(99)))
        with self.assertRaises(domain.LineupQualityError):
            self.check_squads(ids=[7, 8, 9])

    def test_match_with_one_or_three_teams_fails(self):
        one = self.squads.withColumn("team_id", F.lit(10))
        three = self.squads.withColumn("team_id", F.when(F.col("player_id") == 100, 99).otherwise(F.col("team_id")))
        for frame in (one, three):
            with self.assertRaises(domain.LineupQualityError):
                self.check_squads(frame)

    def test_empty_or_null_team_lineup_fails_even_when_two_other_teams_exist(self):
        for value in ([], None):
            empty = self.raw.limit(1).withColumn("team_id", F.lit(99)).withColumn("lineup", F.lit(value).cast(domain.LINEUP_SCHEMA["lineup"].dataType))
            raw = self.raw.unionByName(empty)
            with self.assertRaises(domain.LineupQualityError):
                self.check_squads(domain.transform_match_squads(raw, **self.context), raw=raw)

    def test_invalid_path_causes_dq_failure(self):
        invalid = self.directory / "lineups.json"
        invalid.write_bytes(Path(self.paths[0]).read_bytes())
        raw = domain.read_s3a_lineups(self.spark, [str(invalid)])
        with self.assertRaises(domain.LineupQualityError):
            self.check_squads(domain.transform_match_squads(raw, **self.context), raw=raw, ids=[7])

    def test_teams_dedup_and_stable_output(self):
        self.assertEqual(self.teams.columns, TEAM_COLUMNS)
        expected = [(43, 106, 10, "Red FC"), (43, 106, 20, "Blue FC"), (43, 106, 30, "Green FC")]
        self.assertEqual([tuple(row) for row in self.teams.orderBy("team_id").collect()], expected)
        shuffled = domain.transform_teams(self.squads.repartition(3), **self.context)
        self.assertEqual(self.teams.exceptAll(shuffled).count(), 0)

    def test_team_identity_conflict_fails_before_dedup(self):
        bad = self.squads.withColumn("team_name", F.when(F.col("match_id") == 8, "conflict").otherwise(F.col("team_name")))
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(domain.LineupQualityError, "Conflicting team_id"):
            domain.transform_teams(bad, **self.context)
        self.assertIn("identity=team_id attribute=team_name conflicting_ids=1", output.getvalue())
        self.assertIn('sample: team_id=10 values=["Red FC", "conflict"]', output.getvalue())

    def test_players_dedup_nullable_enrichment_and_membership_separation(self):
        self.assertEqual(self.players.columns, PLAYER_COLUMNS)
        self.assertEqual(self.players.count(), 6)
        self.assertEqual(self.players.select("player_id").distinct().count(), 6)
        alex = self.players.filter(F.col("player_id") == 100).first()
        self.assertEqual(alex.player_nickname, "Alex")
        self.assertEqual(self.squads.filter(F.col("player_id") == 100).select("team_id").distinct().count(), 2)
        self.assertNotIn("team_id", self.players.columns)
        self.assertEqual(self.players.filter(F.col("player_id") == 101).first().country_id, 3000)
        self.assertIsNone(self.players.filter(F.col("player_id") == 201).first().country_id)
        shuffled = domain.transform_players(self.squads.repartition(3), **self.context)
        self.assertEqual(self.players.exceptAll(shuffled).count(), 0)
        # Preserve the exact pre-canonicalization schema, including nullability/order.
        attributes = ("player_name", "player_nickname", "country_id", "country_name")
        previous_schema = self.squads.groupBy("player_id").agg(*[F.min(name).alias(name) for name in attributes]).select(
            F.lit(43).cast("long").alias("competition_id"), F.lit(106).cast("long").alias("season_id"),
            "player_id", *attributes,
        ).schema
        self.assertEqual(self.players.schema, previous_schema)

    def test_player_representatives_frequency_length_and_lexical_order(self):
        cases = {
            4354: [("Phil Foden", None), ("Philip Foden", None)],
            2: [("Phil Foden", "Short")] * 2 + [("Philip Foden", "LongNickname")],
            3: [("Zeta", "Zulu"), ("Beta", "Able")],
            4: [("Name", None), ("Name", "Nick")],
            5: [("Name", "X"), ("Name", "Long")],
            6: [("Name", None)] * 2,
            7: [("Name", "N")] * 2 + [("Name", "Muchlonger")],
        }
        rows = [(identity, name, nickname, None, None)
                for identity, values in cases.items() for name, nickname in values]
        frame = self.spark.createDataFrame(rows,
            "player_id long, player_name string, player_nickname string, country_id long, country_name string")
        output = io.StringIO()
        with redirect_stdout(output):
            players = domain.transform_players(frame, **self.context)
        expected = {4354: ("Philip Foden", None), 2: ("Phil Foden", "Short"),
                    3: ("Beta", "Able"), 4: ("Name", "Nick"), 5: ("Name", "Long"),
                    6: ("Name", None), 7: ("Name", "N")}
        self.assertEqual({row.player_id: (row.player_name, row.player_nickname) for row in players.collect()}, expected)
        self.assertIn("player_name_variant_ids=3", output.getvalue())
        self.assertIn("player_nickname_variant_ids=4", output.getvalue())
        self.assertIn("country_pair_variant_ids=0", output.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(domain.validate_players(players)["row_count"], len(cases))
        shuffled = domain.transform_players(frame.orderBy(F.col("player_id").desc()).repartition(3), **self.context)
        self.assertEqual(players.exceptAll(shuffled).count(), 0)
        self.assertEqual(players.schema, self.players.schema)
        self.assertNotIn("PythonUDF", players._jdf.queryExecution().executedPlan().toString())

    def test_country_pairs_never_mix_fields_and_conflicts_are_informational(self):
        cases = {
            1: [(22, "Belgium")] * 2,
            2: [(None, None), (154, "Morocco")],
            131037: [(22, "Belgium"), (154, "Morocco")],
            4: [(None, None)],
            5: [(22, None), (None, "Belgium")],
            6: [(22, "Zulu"), (154, "Able")],  # Independent minima would invent (22, Able).
            7: [(22, "Belgium"), (22, "Other")],
            8: [(22, "Belgium"), (154, "Belgium")],
            9: [(22, None), (None, "Other"), (154, "Morocco")],
        }
        frame = self.spark.createDataFrame(
            [(identity, "Name", None, country_id, country_name)
             for identity, pairs in cases.items() for country_id, country_name in pairs],
            "player_id long, player_name string, player_nickname string, country_id long, country_name string",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            players = domain.transform_players(frame, **self.context)
        found = {row.player_id: (row.country_id, row.country_name) for row in players.collect()}
        expected = {identity: (None, None) for identity in cases}
        expected.update({1: (22, "Belgium"), 2: (154, "Morocco"), 9: (154, "Morocco")})
        self.assertEqual(found, expected)
        self.assertIn("country_pair_variant_ids=4", output.getvalue())
        for identity, pair in found.items():
            self.assertTrue(pair == (None, None) or pair in cases[identity])
        shuffled = domain.transform_players(frame.repartition(3), **self.context)
        self.assertEqual(players.exceptAll(shuffled).count(), 0)
        self.assertEqual(domain.validate_players(players)["row_count"], len(cases))

    def test_source_player_variations_preserved_in_squads_and_full_build_passes(self):
        # Alter synthetic source metadata across matches, never the stored fixtures.
        raw = self.raw.withColumn("lineup", F.transform("lineup", lambda player:
            player.withField("player_name", F.when(player.player_id == 100,
                F.when(F.col("match_id") == 7, "Phil Foden").otherwise("Philip Foden")).otherwise(player.player_name))
            .withField("country", F.when(player.player_id == 100, F.struct(
                F.when(F.col("match_id") == 7, F.lit(22)).otherwise(F.lit(154)).cast("long").alias("id"),
                F.when(F.col("match_id") == 7, "Belgium").otherwise("Morocco").alias("name"),
            )).otherwise(player.country))))
        squads = domain.transform_match_squads(raw, **self.context)
        before = squads.orderBy("match_id", "team_id", "player_id").collect()
        for dataset in ("teams", "players", "match_squads"):
            with patch.object(domain, "read_s3a_lineups", return_value=raw), redirect_stdout(io.StringIO()):
                frame, counts = domain.build_lineup_frame(self.spark, self.paths, [7, 8], dataset=dataset, **self.context)
            try:
                self.assertEqual(counts["input_match_count"], 2)
                if dataset == "players":
                    player = frame.filter(F.col("player_id") == 100).first()
                    self.assertEqual((player.player_name, player.country_id, player.country_name), ("Philip Foden", None, None))
                if dataset == "match_squads":
                    self.assertEqual(frame.orderBy("match_id", "team_id", "player_id").collect(), before)
                    values = frame.filter(F.col("player_id") == 100).orderBy("match_id").collect()
                    self.assertEqual([(row.player_name, row.country_id, row.country_name) for row in values],
                                     [("Phil Foden", 22, "Belgium"), ("Philip Foden", 154, "Morocco")])
            finally:
                frame.unpersist()

    def test_all_null_player_names_remain_a_hard_failure(self):
        players = domain.transform_players(self.squads.withColumn("player_name", F.lit(None).cast("string")), **self.context)
        self.assertEqual(players.count(), self.players.count())
        with self.assertRaises(domain.LineupQualityError):
            domain.validate_players(players)

    def test_null_plus_known_player_name_is_consistent_during_dedup(self):
        raw = self.squads.withColumn("player_name", F.when(F.col("match_id") == 7, F.lit(None)).otherwise(F.col("player_name")))
        players = domain.transform_players(raw, **self.context)
        self.assertEqual(players.filter(F.col("player_id") == 100).first().player_name, "Alex")

    def test_team_identity_diagnostics_collect_only_ten_sorted_groups(self):
        rows = [(identity, name) for identity in range(15, 0, -1)
                for name in ("Name B", None, "Name A", "Name B")]
        frame = self.spark.createDataFrame(rows, "team_id long, team_name string").repartition(3)
        output = io.StringIO()
        collected = []
        original_collect = type(frame).collect
        def bounded_collect(dataframe):
            result = original_collect(dataframe)
            self.assertEqual(dataframe.columns, ["team_id", "values"])
            self.assertLessEqual(len(result), 10)
            collected.append(result)
            return result
        with patch.object(type(frame), "collect", bounded_collect), redirect_stdout(output):
            with self.assertRaisesRegex(domain.LineupQualityError, "identity attributes: 15") as caught:
                domain.transform_teams(frame, **self.context)
        self.assertEqual(len(collected), 1)
        for sample in collected:
            self.assertEqual([row.team_id for row in sample], list(range(1, 11)))
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 11)
        self.assertEqual(lines[0], "Identity consistency conflict: identity=team_id attribute=team_name conflicting_ids=15")
        for line in lines[1:11]:
            self.assertEqual(json.loads(line.split("values=", 1)[1]), ["Name A", "Name B"])
        diagnostic = PublishDiagnostics().failure(caught.exception)
        self.assertIn('detail="Conflicting team_id identity attributes: 15."', diagnostic)
        self.assertIn("category=integrity", diagnostic)

    def test_null_plus_one_known_team_name_has_no_conflict_diagnostics(self):
        frame = self.spark.createDataFrame(
            [(1, None), (1, "Known"), (1, "Known"), (2, None)],
            "team_id long, team_name string",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            domain.transform_teams(frame, **self.context)
        self.assertEqual(output.getvalue(), "")

    def test_dimension_required_nulls_duplicates_and_empty_output_fail(self):
        for frame, validate, names in ((self.teams, domain.validate_teams, ("team_id", "team_name")),
                                       (self.players, domain.validate_players, ("player_id", "player_name"))):
            for name in names:
                with self.subTest(column=name), self.assertRaises(domain.LineupQualityError):
                    validate(frame.withColumn(name, F.lit(None).cast(frame.schema[name].dataType)))
            with self.assertRaises(domain.LineupQualityError):
                validate(frame.unionByName(frame))
            with self.assertRaises(domain.LineupQualityError):
                validate(frame.limit(0))

    def test_orphan_team_and_player_fail_referential_dq(self):
        with self.assertRaises(domain.LineupQualityError):
            domain.validate_references(self.squads, self.teams.filter(F.col("team_id") != 10), self.players)
        with self.assertRaises(domain.LineupQualityError):
            domain.validate_references(self.squads, self.teams, self.players.filter(F.col("player_id") != 100))

    def test_parquet_readback_supports_dimensions_and_bridge_and_partition_counts(self):
        for name, frame, partitions in (("teams", self.teams, 1), ("players", self.players, 2), ("match_squads", self.squads, 2)):
            output = self.directory / name
            frame.repartition(partitions).write.mode("errorifexists").option("compression", "snappy").parquet(str(output))
            files = [{"object_key": str(path)} for path in output.glob("part-*.snappy.parquet")]
            self.assertEqual(len(files), partitions)
            counts = {"row_count": frame.count()}
            if name == "match_squads":
                counts["match_count"] = 2
            with patch.object(publish, "s3a_uri", side_effect=lambda bucket, key: key):
                publish.validate_readback(self.spark, frame, counts, bucket="unused", files=files)
                with self.assertRaises(publish.SilverIntegrityError):
                    publish.validate_readback(self.spark, frame, {**counts, "row_count": 999}, bucket="unused", files=files)

    def test_check_only_cli_all_datasets_uses_real_spark_and_no_publication(self):
        parent = b'[{"match_id": 7}, {"match_id": 8}]'
        client = FakeS3()
        client.seed("test-bucket", "parent.json", parent)
        inputs = [lineup_artifact(8), lineup_artifact(99), lineup_artifact(7)]
        for item in inputs:
            client.seed("test-bucket", item["object_key"], metadata={"sha256": item["sha256"]})
        for choice, output_count in (("teams", 3), ("players", 6), ("match-squads", 8)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}),
                patch.object(job, "create_postgres_connection"),
                patch.object(job, "create_s3_client", return_value=client),
                patch.object(job, "find_latest_ingestion_object", return_value={"s3_bucket": "test-bucket", "object_key": "parent.json", "sha256": sha256_bytes(parent)}),
                patch.object(job, "find_latest_ingestion_objects", return_value=inputs),
                patch.object(job, "lineup_artifact_s3a_path", side_effect=lambda item: self.paths[item["match_id"] - 7]),
                patch.object(job, "create_spark_session", return_value=self.spark),
                patch.object(job, "configure_s3a"), patch.object(self.spark, "stop"),
                patch.object(job, "publish_build") as publisher,
                redirect_stdout(stdout), redirect_stderr(stderr),
            ):
                self.assertEqual(cli.main(["--dataset", choice, "--limit", "2", "--check-only"]), 0, stderr.getvalue())
                publisher.assert_not_called()
            for message in ("Raw lineup team rows: 4", "Raw lineup player rows: 8", "Matches processed: 2",
                            f"Output rows: {output_count}", "DQ: PASSED", "Build ID:", "CHECK ONLY - nothing published"):
                self.assertIn(message, stdout.getvalue())
        self.assertFalse(any(call[0] in ("put", "list") for call in client.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
