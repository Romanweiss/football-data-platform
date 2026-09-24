"""Aggregate each Silver fact separately, then join to the match_squads grain."""

from functools import reduce

from pyspark.sql import functions as F

from src.gold.manifest import GoldIntegrityError

SHOT_GOAL_OUTCOME_ID = 97  # Existing tests/fixtures/statsbomb_event_domains.json: 97 / Goal.
COUNT_METRICS = ("event_count", "pass_attempts", "shot_count", "shot_goals", "under_pressure_events", "counterpress_events")


def _sum_true(name):
    return F.sum(F.when(F.col(name) == F.lit(True), F.lit(1)).otherwise(F.lit(0))).cast("long")


def validate_output(frame, *, dataset, competition_id, season_id):
    player = dataset == "player_match_stats"
    keys = ["match_id", "team_id", *(["player_id"] if player else [])]
    required = ["competition_id", "season_id", *keys, "team_name", *(["player_name"] if player else [])]
    metrics = (*COUNT_METRICS, *(() if player else ("players_with_events",)))
    invalid = [F.col(name).isNull() for name in required]
    invalid += [F.col(name).isNull() | (F.col(name) < 0) for name in metrics]
    invalid += [F.col("shot_xg").isNull() | F.isnan("shot_xg") | (F.col("shot_xg") < 0)
                | (F.col("shot_xg") == float("inf")),
                F.col("shot_goals") > F.col("shot_count"),
                F.col("competition_id") != competition_id, F.col("season_id") != season_id]
    counts = frame.agg(F.count("*").alias("row_count"), F.countDistinct("match_id").alias("match_count"),
                       F.count(F.when(reduce(lambda a, b: a | b, invalid), 1)).alias("invalid_rows")).first().asDict()
    counts["duplicate_keys"] = frame.groupBy(*keys).count().filter(F.col("count") > 1).count()
    if not player:
        counts["matches_without_two_teams"] = frame.groupBy("match_id").count().filter(F.col("count") != 2).count()
    print("Gold DQ: " + ", ".join(f"{name}={value}" for name, value in counts.items()))
    if counts["row_count"] <= 0 or any(value for name, value in counts.items() if name not in ("row_count", "match_count")):
        raise GoldIntegrityError("Gold grain/context/metric DQ failed.")
    return counts


def build_match_stats(frames, *, dataset, competition_id, season_id):
    if dataset not in ("team_match_stats", "player_match_stats"):
        raise ValueError("Unsupported Gold dataset.")
    player = dataset == "player_match_stats"
    keys = ["match_id", "team_id", *(["player_id"] if player else [])]
    base_columns = ["competition_id", "season_id", "match_id", "team_id", "team_name",
                    *(["player_id", "player_name"] if player else [])]
    base = frames["match_squads"].select(*base_columns)
    if not player:
        base = base.distinct()
    # Duplicate names/identities must not multiply joined aggregates.
    if base.groupBy(*keys).count().filter(F.col("count") > 1).count():
        raise GoldIntegrityError("Duplicate squad base grain.")
    facts = {name: (frames[name].filter(F.col("player_id").isNotNull()) if player else frames[name])
             for name in ("event_core", "pass_events", "shot_events")}
    events = facts["event_core"].groupBy(*keys).agg(
        F.count("*").alias("event_count"), _sum_true("under_pressure").alias("under_pressure_events"),
        _sum_true("counterpress").alias("counterpress_events"),
        *([] if player else [F.countDistinct("player_id").alias("players_with_events")]),
    )
    passes = facts["pass_events"].groupBy(*keys).agg(F.count("*").alias("pass_attempts"))
    # Canonical summation order avoids partition-dependent Float64 reduction order.
    # Built-in array aggregate, not a Python UDF or collection to the driver.
    shots = facts["shot_events"].groupBy(*keys).agg(
        F.count("*").alias("shot_count"),
        F.aggregate(F.sort_array(F.collect_list("statsbomb_xg")), F.lit(0.0), lambda total, x: total + x).alias("shot_xg"),
        F.sum(F.when(F.col("outcome_id") == SHOT_GOAL_OUTCOME_ID, 1).otherwise(0)).cast("long").alias("shot_goals"),
    )
    loss_counts = {}
    result = base
    for name, aggregate in (("event_core", events), ("pass_events", passes), ("shot_events", shots)):
        loss_counts[name + "_orphan_keys"] = aggregate.select(*keys).join(base.select(*keys), keys, "left_anti").count()
        result = result.join(aggregate, keys, "left")
    print("Gold metric coverage: " + ", ".join(f"{name}={value}" for name, value in loss_counts.items()))
    if any(loss_counts.values()):
        raise GoldIntegrityError("Metric keys missing from match_squads; refusing silent metric loss.")
    # Reject invalid source xG rather than letting collect_list silently ignore NULLs.
    if facts["shot_events"].filter(F.col("statsbomb_xg").isNull() | F.isnan("statsbomb_xg")
            | (F.col("statsbomb_xg") < 0) | (F.col("statsbomb_xg") > 1)).limit(1).count():
        raise GoldIntegrityError("Invalid Silver shot xG.")
    metrics = (*COUNT_METRICS, *(() if player else ("players_with_events",)))
    for metric in metrics:
        result = result.withColumn(metric, F.coalesce(F.col(metric), F.lit(0)).cast("long"))
    result = result.withColumn("shot_xg", F.coalesce(F.col("shot_xg"), F.lit(0.0)).cast("double"))
    ordered = [*base_columns, "event_count", "pass_attempts", "shot_count", "shot_xg", "shot_goals",
               "under_pressure_events", "counterpress_events", *([] if player else ["players_with_events"])]
    result = result.select(*ordered).cache()
    try:
        counts = validate_output(result, dataset=dataset, competition_id=competition_id, season_id=season_id)
        if counts["row_count"] != base.count():
            raise GoldIntegrityError("Gold joins changed the base grain row count.")
        counts.update(loss_counts)
        return result, counts
    except Exception:
        result.unpersist()
        raise
