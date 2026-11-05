"""Actual bounded adapter -> Spark Silver/Gold, explicit schemas, Parquet/readback."""
from datetime import datetime
from pathlib import Path
import uuid

from src.openfootball_etl.contract import (
    GOLD, SILVER, SPARK_VERSION, check, proposal, row_digest, rows_from_proposal,
)
from src.openfootball_etl.pipeline import bundle, inventory, read_json, safe_path, seal, verify_phase, write_new


def schema(fields):
    from pyspark.sql import types as T
    kinds = {"string": T.StringType, "int": T.IntegerType, "bool": T.BooleanType,
             "date": T.DateType, "timestamp": T.TimestampType}
    return T.StructType([T.StructField(n, kinds[t](), null) for n, t, null in fields])


def frames(spark, result, batch):
    data = rows_from_proposal(result, batch)
    return {name: spark.createDataFrame(rows, schema(SILVER[name])) for name, rows in data.items()}


def gold_frames(silver):
    from pyspark.sql import functions as F
    f = silver["fixtures"]
    names = silver["participants"].select("participant_id", "participant_name")
    fixtures = f.join(names.select(F.col("participant_id").alias("home_id"), F.col("participant_name").alias("home_name")), "home_id")
    fixtures = fixtures.join(names.select(F.col("participant_id").alias("away_id"), F.col("participant_name").alias("away_name")), "away_id")
    stage = silver["stages"].select("stage_id", "stage_name", "stage_kind")
    rounds = silver["rounds"].select("round_id", "round_name")
    fixtures = fixtures.join(stage, "stage_id").join(rounds, "round_id")
    from src.openfootball_etl.contract import PROVENANCE
    group = ["stage_id", "round_id", "stage_name", "round_name", "stage_kind", *[n for n, _, _ in PROVENANCE]]
    coverage = fixtures.groupBy(*group).agg(F.count("*").cast("int").alias("fixture_count"),
        F.sum(F.when(F.col("result_availability") == "REPORTED", 1).otherwise(0)).cast("int").alias("reported_result_count"),
        F.sum(F.when(F.col("result_availability") == "MISSING", 1).otherwise(0)).cast("int").alias("unknown_result_count"),
        F.sum(F.when(F.col("score_quality") == "AMBIGUOUS_SOURCE_COMPONENTS", 1).otherwise(0)).cast("int").alias("ambiguous_component_count"),
        F.min("match_date").alias("date_min"), F.max("match_date").alias("date_max"))
    return {"historical_fixtures": fixtures, "competition_participants": silver["participants"],
            "stage_round_coverage": coverage, "source_quality": silver["quality"]}


def checked_rows(frame, fields, expected_count=None):
    check(frame.columns == [n for n, _, _ in fields], "SPARK_COLUMNS")
    check(frame.schema.simpleString() == schema(fields).simpleString(), "SPARK_TYPES")
    rows = [r.asDict() for r in frame.collect()]
    check(expected_count is None or len(rows) == expected_count, "SPARK_ROW_COUNT")
    check(rows and all(all(r[n] is not None for n, _, nullable in fields if not nullable) for r in rows), "SPARK_REQUIRED")
    if "fixture_id" in frame.columns and "code" not in frame.columns:
        check(len({r["fixture_id"] for r in rows}) == len(rows), "SPARK_DUPLICATES")
        check(all(r["regulation_home"] is None and r["winner_id"] is None and not r["standings_eligible"]
                  and r["points_home"] is None for r in rows), "SCORE_SAFETY")
    return rows


def run_phase(spark, store, bronze_path, batch, phase, token, *, fault=None):
    store = safe_path(store)
    check((store / "_writer.lock").read_text() == token, "COORDINATOR_LOCK_REQUIRED")
    check(spark.version == SPARK_VERSION, "SPARK_VERSION")
    target = bundle(store, batch) / phase
    specifications = SILVER if phase == "silver" else GOLD
    if target.exists():
        manifest = verify_phase(target)
        check(manifest["batch_id"] == batch and manifest["phase"] == phase and
              manifest["spark_version"] == SPARK_VERSION and set(manifest["datasets"]) == set(specifications),
              "PHASE_IDENTITY")
        for name, fields in specifications.items():
            rows = checked_rows(spark.read.parquet(str(target / name / "parquet")), fields,
                                manifest["datasets"][name]["rows"])
            check(row_digest(rows) == manifest["datasets"][name]["logical_sha256"], "REPLAY_CONTENT")
        return "REUSED"
    verify_phase(bronze_path)
    bronze_meta = read_json(bronze_path / "_manifest.json")
    result = proposal((bronze_path / "uefa.cl.json").read_bytes(), read_json(bronze_path / "acquisition.json"),
                      datetime.fromisoformat(bronze_meta["observed_at"]))
    if phase == "gold":
        verify_phase(bundle(store, batch) / "silver")
    source_frames = frames(spark, result, batch) if phase == "silver" else {
        name: spark.read.parquet(str(bundle(store, batch) / "silver" / name / "parquet")) for name in SILVER}
    outputs = source_frames if phase == "silver" else gold_frames(source_frames)
    expected = {"fixtures": len(result.fixtures), "participants": len(result.participants), "stages": len(result.stages),
        "rounds": len(result.rounds), "quality": len(result.dq.limitations), "historical_fixtures": len(result.fixtures),
        "competition_participants": len(result.participants), "stage_round_coverage": len(result.rounds),
        "source_quality": len(result.dq.limitations)}
    attempt = store / "attempts" / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    datasets = {}
    for index, (name, fields) in enumerate(specifications.items()):
        frame = outputs[name].select(*[n for n, _, _ in fields]).coalesce(1).cache()
        try:
            rows = checked_rows(frame, fields, expected[name])
            path = attempt / name / "parquet"
            frame.write.mode("errorifexists").parquet(str(path))
            readback = checked_rows(spark.read.parquet(str(path)), fields, len(rows))
            check(row_digest(rows) == row_digest(readback), "PARQUET_READBACK")
            if phase == "gold":
                frame.write.mode("errorifexists").option("ignoreNullFields", "false").json(str(attempt / name / "json"))
            datasets[name] = {"rows": len(rows), "logical_sha256": row_digest(rows), "schema": fields}
        finally:
            frame.unpersist()
        if fault is not None:
            fault(index)
    if phase == "silver":
        write_new(attempt / "registry.json", result.registry_after_state)
        write_new(attempt / "versions.json", result.ledger_after_state)
    manifest = {"batch_id": batch, "phase": phase, "spark_version": spark.version,
        "semantic_fingerprint": result.semantic_digest, "source_sha256": result.manifest.content_sha256,
        "datasets": datasets, "files": inventory(attempt)}
    seal(attempt, target, manifest)
    return "CREATED"


def main(argv=None):
    import argparse
    from pyspark.sql import SparkSession
    parser = argparse.ArgumentParser()
    for name in ("store", "bronze", "batch", "phase", "token"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    check(args.phase in ("silver", "gold"), "PHASE")
    spark = (SparkSession.builder.master("local[2]").appName("isolated-openfootball-etl")
        .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    spark.sparkContext.setLogLevel("OFF")
    try:
        status = run_phase(spark, Path(args.store), Path(args.bronze), args.batch, args.phase, args.token)
        print("OPENFOOTBALL_PHASE=" + status)
    finally:
        spark.stop()
