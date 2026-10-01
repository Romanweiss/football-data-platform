"""match_results_v1: official match score and independently counted shootout score."""

from functools import reduce
from pyspark.sql import functions as F
from src.gold.manifest import GoldIntegrityError
from src.gold.statsbomb.periods import MATCH_KEY, join_domain, validate_events

SOURCE_COLUMNS = (*MATCH_KEY, "match_date", "kick_off", "competition_stage_id", "competition_stage_name",
                  "home_team_id", "home_team_name", "away_team_id", "away_team_name", "home_score", "away_score")
SHOOTOUT_COLUMNS = ("home_shootout_attempts", "away_shootout_attempts", "home_shootout_goals", "away_shootout_goals")
OUTPUT_COLUMNS = (*SOURCE_COLUMNS, "went_to_extra_time", "went_to_penalties", *SHOOTOUT_COLUMNS,
                  "winner_team_id", "winner_team_name", "result_method", "display_score")


def winner_home():
    return F.when(F.col("went_to_penalties"), F.col("home_shootout_goals") > F.col("away_shootout_goals")) \
        .otherwise(F.col("home_score") > F.col("away_score"))


def winner_away():
    return F.when(F.col("went_to_penalties"), F.col("away_shootout_goals") > F.col("home_shootout_goals")) \
        .otherwise(F.col("away_score") > F.col("home_score"))


def method():
    return (F.when(F.col("went_to_penalties"), "PENALTIES")
            .when(F.col("winner_team_id").isNull(), "DRAW")
            .when(F.col("went_to_extra_time"), "EXTRA_TIME").otherwise("REGULATION"))


def display():
    # ASCII hyphen is deliberate and stable across SQL/UI/export clients.
    score = F.concat_ws("-", F.col("home_score"), F.col("away_score"))
    return F.when(F.col("went_to_penalties"), F.concat(score, F.lit(" ("),
        F.concat_ws("-", F.col("home_shootout_goals"), F.col("away_shootout_goals")), F.lit(" pens)"))).otherwise(score)


def validate_output(frame, matches, *, competition_id, season_id):
    invalid = [F.col(name).isNull() for name in OUTPUT_COLUMNS if name not in ("winner_team_id", "winner_team_name")]
    invalid += [(F.col("competition_id") != competition_id), (F.col("season_id") != season_id),
                F.col("home_team_id") == F.col("away_team_id")]
    invalid += [F.col(name) < 0 for name in ("home_score", "away_score", *SHOOTOUT_COLUMNS)]
    invalid += [F.col(side + "_shootout_goals") > F.col(side + "_shootout_attempts") for side in ("home", "away")]
    invalid += [F.col("went_to_penalties") & ((F.col("home_shootout_goals") == F.col("away_shootout_goals"))
                | F.col("winner_team_id").isNull() | (F.col("home_shootout_attempts") <= 0)
                | (F.col("away_shootout_attempts") <= 0) | (F.col("home_score") != F.col("away_score")))]
    invalid += [(~F.col("went_to_penalties")) & (F.col(name) != 0) for name in SHOOTOUT_COLUMNS]
    expected_id = F.when(winner_home(), F.col("home_team_id")).when(winner_away(), F.col("away_team_id"))
    expected_name = F.when(winner_home(), F.col("home_team_name")).when(winner_away(), F.col("away_team_name"))
    invalid += [~F.col("winner_team_id").eqNullSafe(expected_id), ~F.col("winner_team_name").eqNullSafe(expected_name),
                ~F.col("result_method").eqNullSafe(method()), ~F.col("display_score").eqNullSafe(display())]
    counts = frame.agg(F.count("*").alias("row_count"), F.countDistinct("match_id").alias("match_count"),
        F.count(F.when(reduce(lambda a, b: a | b, invalid), 1)).alias("invalid_rows"),
        *[F.count(F.when(F.col("result_method") == value, 1)).alias("result_" + value.lower())
          for value in ("REGULATION", "EXTRA_TIME", "PENALTIES", "DRAW")],
        F.count(F.when(F.col("went_to_penalties") & ~F.col("went_to_extra_time"), 1)).alias("penalties_without_extra_time")).first().asDict()
    # Source columns (including official scores and Date) must survive byte-for-value.
    changed = (frame.select(*SOURCE_COLUMNS).exceptAll(matches.select(*SOURCE_COLUMNS)).limit(1).count()
               or matches.select(*SOURCE_COLUMNS).exceptAll(frame.select(*SOURCE_COLUMNS)).limit(1).count())
    print("Match results DQ: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if not counts["row_count"] or counts["row_count"] != counts["match_count"] or counts["invalid_rows"] or changed:
        raise GoldIntegrityError("Match results grain, source coverage, score or winner DQ failed.")
    # Extra time is evidence, not inferred from penalties; this count is informational.
    return counts


def build_match_results(frames, *, competition_id, season_id):
    matches, events = frames["matches"], frames["event_core"]
    validate_events(events)
    if matches.groupBy(*MATCH_KEY).count().filter("count > 1").limit(1).count():
        raise GoldIntegrityError("Duplicate Silver matches.")
    match_keys = matches.select(*MATCH_KEY)
    if (events.join(match_keys, MATCH_KEY, "left_anti").limit(1).count()
            or match_keys.join(events.select(*MATCH_KEY), MATCH_KEY, "left_anti").limit(1).count()):
        raise GoldIntegrityError("Events/matches coverage mismatch.")
    joined = events.join(matches.select(*MATCH_KEY, "home_team_id", "away_team_id"), MATCH_KEY)
    if joined.filter((F.col("team_id") != F.col("home_team_id")) & (F.col("team_id") != F.col("away_team_id"))).limit(1).count():
        raise GoldIntegrityError("Event team is outside the match.")
    shots = join_domain(events, frames["shot_events"], type_id=16)
    if shots.filter(F.col("outcome_id").isNull() | ((F.col("outcome_name") == "Goal") != (F.col("outcome_id") == 97))).limit(1).count():
        raise GoldIntegrityError("Shot outcome disagrees with the Silver Goal=97 contract.")
    shootout = shots.filter("core_period = 5").groupBy(*MATCH_KEY, "team_id").agg(
        F.count("*").alias("attempts"), F.sum(F.when(F.col("outcome_id") == 97, 1).otherwise(0)).alias("goals"))
    extra = events.groupBy(*MATCH_KEY).agg(F.max(F.col("period").isin(3, 4)).alias("went_to_extra_time"))
    result = matches.select(*SOURCE_COLUMNS).join(extra, MATCH_KEY, "left")
    for side in ("home", "away"):
        per_side = shootout.select(*MATCH_KEY, F.col("team_id").alias(side + "_team_id"),
            F.col("attempts").alias(side + "_shootout_attempts"), F.col("goals").alias(side + "_shootout_goals"))
        result = result.join(per_side, [*MATCH_KEY, side + "_team_id"], "left")
    for name in SHOOTOUT_COLUMNS:
        result = result.withColumn(name, F.coalesce(F.col(name), F.lit(0)).cast("long"))
    result = result.withColumn("went_to_penalties", (F.col("home_shootout_attempts") + F.col("away_shootout_attempts")) > 0)
    result = result.withColumn("winner_team_id", F.when(winner_home(), F.col("home_team_id")).when(winner_away(), F.col("away_team_id")))
    result = result.withColumn("winner_team_name", F.when(winner_home(), F.col("home_team_name")).when(winner_away(), F.col("away_team_name")))
    result = result.withColumn("result_method", method()).withColumn("display_score", display()).select(*OUTPUT_COLUMNS).cache()
    try:
        return result, validate_output(result, matches, competition_id=competition_id, season_id=season_id)
    except Exception:
        result.unpersist()
        raise
