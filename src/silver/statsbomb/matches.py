"""Source-aligned match dimension from verified small Bronze JSON, never inferred."""

import json

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, IntegerType, LongType, StringType, StructField, StructType

from src.silver.manifest import SilverIntegrityError


def struct(*fields):
    return StructType([StructField(name, kind, True) for name, kind in fields])


NAMED = struct(("id", LongType()), ("name", StringType()))
RAW_SCHEMA = struct(
    ("match_id", LongType()), ("match_date", StringType()), ("kick_off", StringType()),
    ("competition", struct(("competition_id", LongType()))),
    ("season", struct(("season_id", LongType()))),
    ("match_week", IntegerType()), ("competition_stage", NAMED),
    ("home_team", struct(("home_team_id", LongType()), ("home_team_name", StringType()))),
    ("away_team", struct(("away_team_id", LongType()), ("away_team_name", StringType()))),
    ("home_score", IntegerType()), ("away_score", IntegerType()),
    ("stadium", NAMED), ("referee", NAMED),
)
OUTPUT_SCHEMA = struct(
    ("competition_id", LongType()), ("season_id", LongType()), ("match_id", LongType()),
    ("match_date", DateType()), ("kick_off", StringType()), ("match_week", IntegerType()),
    ("competition_stage_id", LongType()), ("competition_stage_name", StringType()),
    ("home_team_id", LongType()), ("home_team_name", StringType()),
    ("away_team_id", LongType()), ("away_team_name", StringType()),
    ("home_score", IntegerType()), ("away_score", IntegerType()),
    ("stadium_id", LongType()), ("stadium_name", StringType()),
    ("referee_id", LongType()), ("referee_name", StringType()),
)
INFORMATIONAL = ("stadium_id", "stadium_name", "referee_id", "referee_name", "kick_off", "match_week")
REQUIRED = tuple(name for name in OUTPUT_SCHEMA.fieldNames() if name not in INFORMATIONAL)


class MatchQualityError(SilverIntegrityError):
    """Messages contain no source text or credentials."""


def read_matches(spark, raw):
    try:
        rows = json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError()
        return spark.createDataFrame(rows, RAW_SCHEMA)
    except Exception:
        raise MatchQualityError("Invalid matches JSON or explicit source schema.") from None


def transform_matches(raw):
    return raw.select(
        F.col("competition.competition_id").alias("competition_id"), F.col("season.season_id").alias("season_id"),
        "match_id", F.col("match_date").try_cast("date").alias("match_date"), "kick_off", "match_week",
        F.col("competition_stage.id").alias("competition_stage_id"), F.col("competition_stage.name").alias("competition_stage_name"),
        F.col("home_team.home_team_id").alias("home_team_id"), F.col("home_team.home_team_name").alias("home_team_name"),
        F.col("away_team.away_team_id").alias("away_team_id"), F.col("away_team.away_team_name").alias("away_team_name"),
        "home_score", "away_score", F.col("stadium.id").alias("stadium_id"), F.col("stadium.name").alias("stadium_name"),
        F.col("referee.id").alias("referee_id"), F.col("referee.name").alias("referee_name"),
    )


def validate_matches(frame, teams, *, competition_id, season_id):
    counts = frame.agg(F.count("*").alias("row_count"), F.countDistinct("match_id").alias("match_count"),
        *[F.count(F.when(F.col(name).isNull(), 1)).alias("null_" + name) for name in OUTPUT_SCHEMA.fieldNames()],
        F.count(F.when((F.col("competition_id") != competition_id) | (F.col("season_id") != season_id)
            | (F.col("home_team_id") == F.col("away_team_id")) | (F.col("home_score") < 0) | (F.col("away_score") < 0), 1)).alias("invalid_rows"),
    ).first().asDict()
    parent = teams.filter((F.col("competition_id") == competition_id) & (F.col("season_id") == season_id)).select("team_id").distinct()
    for side in ("home", "away"):
        keys = frame.select(F.col(side + "_team_id").alias("team_id")).distinct()
        counts[side + "_team_orphans"] = keys.join(parent, "team_id", "left_anti").count()
    print("DQ matches: " + ", ".join(f"{name}={value}" for name, value in counts.items()))
    if (counts["row_count"] <= 0 or counts["row_count"] != counts["match_count"] or counts["invalid_rows"]
            or counts["home_team_orphans"] or counts["away_team_orphans"] or any(counts["null_" + name] for name in REQUIRED)):
        raise MatchQualityError("Matches DQ failed; see aggregate diagnostics.")
    return counts


def build_matches(spark, raw, teams, *, competition_id, season_id):
    frame = transform_matches(read_matches(spark, raw)).cache()
    try:
        if frame.schema != OUTPUT_SCHEMA:
            raise MatchQualityError("Matches output schema mismatch.")
        return frame, validate_matches(frame, teams, competition_id=competition_id, season_id=season_id)
    except Exception:
        frame.unpersist()
        raise
