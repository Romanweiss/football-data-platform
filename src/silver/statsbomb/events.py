"""Explicit StatsBomb event core schema, built-in transformations and DQ."""

from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, functions as F
from pyspark.sql.types import (
    ArrayType, BooleanType, DoubleType, IntegerType, LongType,
    StringType, StructField, StructType,
)

NAMED_ENTITY_SCHEMA = StructType([
    StructField("id", LongType(), True),
    StructField("name", StringType(), True),
])

EVENT_SCHEMA = StructType([
    StructField("id", StringType(), True),
    StructField("index", IntegerType(), True),
    StructField("period", IntegerType(), True),
    # StatsBomb timestamp is period-relative, not an absolute datetime.
    StructField("timestamp", StringType(), True),
    StructField("minute", IntegerType(), True),
    StructField("second", IntegerType(), True),
    StructField("type", NAMED_ENTITY_SCHEMA, True),
    StructField("possession", IntegerType(), True),
    StructField("possession_team", NAMED_ENTITY_SCHEMA, True),
    StructField("play_pattern", NAMED_ENTITY_SCHEMA, True),
    StructField("team", NAMED_ENTITY_SCHEMA, True),
    StructField("player", NAMED_ENTITY_SCHEMA, True),
    StructField("position", NAMED_ENTITY_SCHEMA, True),
    StructField("location", ArrayType(DoubleType(), True), True),
    StructField("duration", DoubleType(), True),
    StructField("under_pressure", BooleanType(), True),
    StructField("counterpress", BooleanType(), True),
])

OUTPUT_PARTITIONS = 4
REQUIRED_COLUMNS = ("match_id", "event_id", "event_index", "type_id", "team_id")


class EventCoreQualityError(ValueError):
    """Event core data quality failed; the preview must not be published."""


def read_staged_events(spark: SparkSession, paths: list[Path]) -> DataFrame:
    """Read only this run's selected files, never a directory-wide wildcard."""
    raw = (
        spark.read.schema(EVENT_SCHEMA)
        .option("multiLine", "true")
        .option("mode", "FAILFAST")
        .json([str(path) for path in paths])
    )
    filename_id = F.regexp_extract(
        F.input_file_name(), r"/match_id=([1-9][0-9]*)\.json$", 1,
    )
    # Invalid names/overflow become NULL even with Spark ANSI mode enabled.
    return raw.withColumn("match_id", filename_id.try_cast("long"))


def transform_event_core(
    df: DataFrame, *, competition_id: int, season_id: int
) -> DataFrame:
    """Flatten event core without dropping rows or replacing nullable values."""
    return df.select(
        F.lit(competition_id).cast("long").alias("competition_id"),
        F.lit(season_id).cast("long").alias("season_id"),
        "match_id",
        F.col("id").alias("event_id"),
        F.col("index").alias("event_index"),
        "period", "timestamp", "minute", "second",
        F.col("type.id").alias("type_id"),
        F.col("type.name").alias("type_name"),
        "possession",
        F.col("possession_team.id").alias("possession_team_id"),
        F.col("possession_team.name").alias("possession_team_name"),
        F.col("play_pattern.id").alias("play_pattern_id"),
        F.col("play_pattern.name").alias("play_pattern_name"),
        F.col("team.id").alias("team_id"),
        F.col("team.name").alias("team_name"),
        F.col("player.id").alias("player_id"),
        F.col("player.name").alias("player_name"),
        F.col("position.id").alias("position_id"),
        F.col("position.name").alias("position_name"),
        # get() is zero-based and returns NULL for null/short arrays.
        F.get("location", 0).alias("location_x"),
        F.get("location", 1).alias("location_y"),
        "duration", "under_pressure", "counterpress",
    )


def validate_event_core(df: DataFrame) -> dict[str, int]:
    """Return small aggregate counts or raise before any Parquet write."""
    counts = df.agg(
        F.count("*").alias("row_count"),
        F.countDistinct("match_id").alias("match_count"),
        *[
            F.count(F.when(F.col(name).isNull(), 1)).alias(f"null_{name}")
            for name in REQUIRED_COLUMNS
        ],
    ).first().asDict()
    counts["duplicate_keys"] = (
        df.groupBy("match_id", "event_id").count().filter(F.col("count") > 1).count()
    )
    summary = ", ".join(f"{name}={value}" for name, value in counts.items())
    print(f"DQ: {summary}")
    if (
        counts["row_count"] == 0
        or any(counts[f"null_{name}"] for name in REQUIRED_COLUMNS)
        or counts["duplicate_keys"]
    ):
        raise EventCoreQualityError(f"Event core DQ failed: {summary}")
    return counts


def write_event_core(df: DataFrame, output_dir: Path) -> None:
    """Write a disposable local preview; callers must validate DQ first."""
    (
        df.repartition(OUTPUT_PARTITIONS).write.mode("overwrite")
        .option("compression", "snappy").parquet(str(output_dir))
    )
