"""Explicit pass/shot inputs, built-in Spark projections and domain DQ."""

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.types import ArrayType, BooleanType, DoubleType, StringType, StructField, StructType

from src.silver.statsbomb.events import EVENT_SCHEMA, NAMED_ENTITY_SCHEMA, read_s3a_events

PASS_FLAGS = ("cross", "cut_back", "switch", "shot_assist", "goal_assist", "aerial_won", "through_ball")
SHOT_FLAGS = ("first_time", "open_goal", "one_on_one", "aerial_won", "deflected")

PASS_SCHEMA = StructType([
    StructField("recipient", NAMED_ENTITY_SCHEMA, True),
    StructField("length", DoubleType(), True),
    StructField("angle", DoubleType(), True),
    StructField("height", NAMED_ENTITY_SCHEMA, True),
    StructField("end_location", ArrayType(DoubleType(), True), True),
    StructField("body_part", NAMED_ENTITY_SCHEMA, True),
    StructField("type", NAMED_ENTITY_SCHEMA, True),
    StructField("outcome", NAMED_ENTITY_SCHEMA, True),
    StructField("technique", NAMED_ENTITY_SCHEMA, True),
    *[StructField(name, BooleanType(), True) for name in PASS_FLAGS],
])

SHOT_SCHEMA = StructType([
    StructField("statsbomb_xg", DoubleType(), True),
    StructField("end_location", ArrayType(DoubleType(), True), True),
    StructField("key_pass_id", StringType(), True),
    StructField("body_part", NAMED_ENTITY_SCHEMA, True),
    StructField("type", NAMED_ENTITY_SCHEMA, True),
    StructField("technique", NAMED_ENTITY_SCHEMA, True),
    StructField("outcome", NAMED_ENTITY_SCHEMA, True),
    *[StructField(name, BooleanType(), True) for name in SHOT_FLAGS],
])

# Do not mutate EVENT_SCHEMA: event_core's input/output contracts remain unchanged.
DOMAIN_EVENT_SCHEMA = StructType([
    *EVENT_SCHEMA.fields,
    StructField("pass", PASS_SCHEMA, True),
    StructField("shot", SHOT_SCHEMA, True),
])


class DomainEventQualityError(ValueError):
    """Domain DQ failed before any publication; messages contain aggregate counts only."""


def domain_condition(domain: str):
    return (F.col("type.name") == {"pass": "Pass", "shot": "Shot"}[domain]) & F.col(domain).isNotNull()


def _common_columns(competition_id: int, season_id: int):
    return [
        F.lit(competition_id).cast("long").alias("competition_id"),
        F.lit(season_id).cast("long").alias("season_id"),
        F.col("match_id"), F.col("id").alias("event_id"), F.col("index").alias("event_index"),
        F.col("period"), F.col("timestamp"), F.col("minute"), F.col("second"),
        F.col("team.id").alias("team_id"), F.col("team.name").alias("team_name"),
        F.col("player.id").alias("player_id"), F.col("player.name").alias("player_name"),
        F.get("location", 0).alias("start_x"), F.get("location", 1).alias("start_y"),
    ]


def _named_columns(path: str, prefix: str):
    return [F.col(f"{path}.{field}").alias(f"{prefix}_{field}") for field in ("id", "name")]


def transform_pass_events(df: DataFrame, *, competition_id: int, season_id: int) -> DataFrame:
    return df.filter(domain_condition("pass")).select(
        *_common_columns(competition_id, season_id),
        *_named_columns("pass.recipient", "recipient"),
        F.col("pass.length").alias("pass_length"), F.col("pass.angle").alias("pass_angle"),
        F.get("pass.end_location", 0).alias("end_x"), F.get("pass.end_location", 1).alias("end_y"),
        *_named_columns("pass.height", "height"),
        *_named_columns("pass.body_part", "body_part"),
        *_named_columns("pass.type", "pass_type"),
        *_named_columns("pass.outcome", "outcome"),
        *_named_columns("pass.technique", "technique"),
        *[F.col(f"pass.{name}").alias(name) for name in PASS_FLAGS],
    )


def transform_shot_events(df: DataFrame, *, competition_id: int, season_id: int) -> DataFrame:
    return df.filter(domain_condition("shot")).select(
        *_common_columns(competition_id, season_id),
        F.col("shot.statsbomb_xg").alias("statsbomb_xg"),
        F.get("shot.end_location", 0).alias("end_x"), F.get("shot.end_location", 1).alias("end_y"),
        F.get("shot.end_location", 2).alias("end_z"), F.col("shot.key_pass_id").alias("key_pass_id"),
        *_named_columns("shot.body_part", "body_part"),
        *_named_columns("shot.type", "shot_type"),
        *_named_columns("shot.technique", "technique"),
        *_named_columns("shot.outcome", "outcome"),
        *[F.col(f"shot.{name}").alias(name) for name in SHOT_FLAGS],
    )


def _validate_domain(
    df: DataFrame, *, raw: DataFrame, match_ids: list[int], domain: str,
    required: tuple[str, ...], informational: tuple[str, ...], invalid_value,
) -> dict[str, int]:
    if not match_ids or any(type(value) is not int or value <= 0 for value in match_ids) or len(set(match_ids)) != len(match_ids):
        raise DomainEventQualityError("DQ requires distinct positive selected match ids.")
    input_counts = raw.agg(
        F.count("*").alias("input_row_count"),
        F.count(F.when(domain_condition(domain), 1)).alias("expected_row_count"),
    ).first().asDict()
    counts = df.agg(
        F.count("*").alias("row_count"),
        F.countDistinct("match_id").alias("match_count"),
        *[F.count(F.when(F.col(name).isNull(), 1)).alias(f"null_{name}") for name in (*required, *informational)],
        F.count(F.when(~F.col("match_id").isin(match_ids), 1)).alias("unexpected_match_rows"),
        F.count(F.when(invalid_value, 1)).alias("invalid_domain_values"),
    ).first().asDict()
    counts.update(input_counts)
    counts["duplicate_keys"] = df.groupBy("match_id", "event_id").count().filter(F.col("count") > 1).count()
    summary = ", ".join(f"{name}={value}" for name, value in counts.items() if name not in {f"null_{key}" for key in informational})
    print(f"DQ {domain}_events: {summary}")
    print(f"Informational NULLs {domain}_events: " + ", ".join(f"{name}={counts[f'null_{name}']}" for name in informational))
    if (
        counts["row_count"] == 0 or counts["row_count"] != counts["expected_row_count"]
        or counts["match_count"] != len(match_ids) or counts["unexpected_match_rows"]
        or any(counts[f"null_{name}"] for name in required)
        or counts["duplicate_keys"] or counts["invalid_domain_values"]
    ):
        raise DomainEventQualityError(f"{domain}_events DQ failed: {summary}")
    return counts


def validate_pass_events(df: DataFrame, *, raw: DataFrame, match_ids: list[int]) -> dict[str, int]:
    return _validate_domain(
        df, raw=raw, match_ids=match_ids, domain="pass",
        required=("match_id", "event_id", "event_index", "team_id"),
        informational=("player_id", "recipient_id", "outcome_id", "body_part_id", "technique_id"),
        invalid_value=F.col("pass_length") < 0,
    )


def validate_shot_events(df: DataFrame, *, raw: DataFrame, match_ids: list[int]) -> dict[str, int]:
    return _validate_domain(
        df, raw=raw, match_ids=match_ids, domain="shot",
        required=("match_id", "event_id", "event_index", "team_id", "statsbomb_xg", "outcome_id"),
        informational=("player_id", "key_pass_id", "body_part_id", "technique_id", "end_z"),
        invalid_value=(F.col("statsbomb_xg") < 0) | (F.col("statsbomb_xg") > 1) | F.isnan("statsbomb_xg"),
    )


def build_domain_frame(spark, paths: list[str], match_ids: list[int], *, dataset: str, competition_id: int, season_id: int):
    transform, validate = {
        "passes": (transform_pass_events, validate_pass_events),
        "shots": (transform_shot_events, validate_shot_events),
    }[dataset]
    raw = read_s3a_events(spark, paths, schema=DOMAIN_EVENT_SCHEMA).cache()
    frame = None
    try:
        frame = transform(raw, competition_id=competition_id, season_id=season_id).cache()
        counts = validate(frame, raw=raw, match_ids=match_ids)
        return frame, counts
    except Exception:
        if frame is not None:
            frame.unpersist()
        raise
    finally:
        raw.unpersist()
