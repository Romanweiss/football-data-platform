"""StatsBomb lineup schemas, source dimensions, squad bridge and Spark DQ."""

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.types import ArrayType, IntegerType, LongType, StringType, StructField, StructType

from src.silver.statsbomb.events import NAMED_ENTITY_SCHEMA

LINEUP_PLAYER_SCHEMA = StructType([
    StructField("player_id", LongType(), True),
    StructField("player_name", StringType(), True),
    StructField("player_nickname", StringType(), True),
    StructField("jersey_number", IntegerType(), True),
    StructField("country", NAMED_ENTITY_SCHEMA, True),
])
LINEUP_SCHEMA = StructType([
    StructField("team_id", LongType(), True),
    StructField("team_name", StringType(), True),
    StructField("lineup", ArrayType(LINEUP_PLAYER_SCHEMA, True), True),
])


class LineupQualityError(ValueError):
    """Lineup DQ failed; messages contain only field names and aggregate counts."""


def lineup_match_id(path_column):
    return F.regexp_extract(
        path_column, r"/lineups/match_id=([1-9][0-9]*)/sha256=[0-9a-f]{64}/lineups\.json$", 1,
    ).try_cast("long")


def read_s3a_lineups(spark, paths: list[str]) -> DataFrame:
    """Exact preflighted immutable keys; no wildcard or boto3 bulk GET."""
    return (
        spark.read.schema(LINEUP_SCHEMA).option("multiLine", "true").option("mode", "FAILFAST")
        .option("recursiveFileLookup", "true").json(paths)
        .withColumn("match_id", lineup_match_id(F.input_file_name()))
    )


def transform_match_squads(raw: DataFrame, *, competition_id: int, season_id: int) -> DataFrame:
    return raw.select("match_id", "team_id", "team_name", F.explode("lineup").alias("player")).select(
        F.lit(competition_id).cast("long").alias("competition_id"),
        F.lit(season_id).cast("long").alias("season_id"),
        "match_id", "team_id", "team_name",
        F.col("player.player_id").alias("player_id"),
        F.col("player.player_name").alias("player_name"),
        F.col("player.player_nickname").alias("player_nickname"),
        F.col("player.jersey_number").alias("jersey_number"),
        F.col("player.country.id").alias("country_id"),
        F.col("player.country.name").alias("country_name"),
    )


def _identity_consistency(df: DataFrame, identity: str, attributes: tuple[str, ...]) -> None:
    # countDistinct ignores NULL, so NULL + one known value is consistent.
    counts = df.groupBy(identity).agg(*[F.countDistinct(name).alias(name) for name in attributes])
    conflicts = counts.filter(F.greatest(*[F.col(name) for name in attributes], F.lit(0)) > 1).count()
    if conflicts:
        raise LineupQualityError(f"Conflicting {identity} identity attributes: {conflicts}.")


def transform_teams(squads: DataFrame, *, competition_id: int, season_id: int) -> DataFrame:
    _identity_consistency(squads, "team_id", ("team_name",))
    return squads.groupBy("team_id").agg(F.min("team_name").alias("team_name")).select(
        F.lit(competition_id).cast("long").alias("competition_id"),
        F.lit(season_id).cast("long").alias("season_id"), "team_id", "team_name",
    )


def transform_players(squads: DataFrame, *, competition_id: int, season_id: int) -> DataFrame:
    attributes = ("player_name", "player_nickname", "country_id", "country_name")
    _identity_consistency(squads, "player_id", attributes)
    return squads.groupBy("player_id").agg(*[F.min(name).alias(name) for name in attributes]).select(
        F.lit(competition_id).cast("long").alias("competition_id"),
        F.lit(season_id).cast("long").alias("season_id"), "player_id", *attributes,
    )


def _counts(df, required, informational=()):
    return df.agg(
        F.count("*").alias("row_count"),
        *[F.count(F.when(F.col(name).isNull(), 1)).alias(f"null_{name}") for name in (*required, *informational)],
    ).first().asDict()


def validate_match_squads(squads: DataFrame, *, raw: DataFrame, match_ids: list[int]) -> dict[str, int]:
    if not match_ids or any(type(value) is not int or value <= 0 for value in match_ids) or len(set(match_ids)) != len(match_ids):
        raise LineupQualityError("DQ requires distinct positive selected match ids.")
    required = ("match_id", "team_id", "team_name", "player_id", "player_name")
    optional = ("player_nickname", "jersey_number", "country_id", "country_name")
    counts = _counts(squads, required, optional)
    counts.update(raw.agg(
        F.count("*").alias("raw_lineup_team_rows"),
        F.coalesce(F.sum(F.coalesce(F.size("lineup"), F.lit(0))), F.lit(0)).alias("raw_lineup_player_rows"),
        F.count(F.when(F.col("lineup").isNull() | (F.size("lineup") == 0), 1)).alias("empty_lineup_rows"),
        F.count(F.when(F.col("match_id").isNull() | ~F.col("match_id").isin(match_ids), 1)).alias("invalid_raw_match_rows"),
        F.count(F.when(F.col("team_id").isNull() | F.col("team_name").isNull(), 1)).alias("invalid_raw_team_rows"),
    ).first().asDict())
    counts.update(squads.agg(
        F.countDistinct("match_id").alias("match_count"),
        F.count(F.when(~F.col("match_id").isin(match_ids), 1)).alias("unexpected_match_rows"),
    ).first().asDict())
    counts["duplicate_keys"] = squads.groupBy("match_id", "team_id", "player_id").count().filter(F.col("count") > 1).count()
    counts["matches_without_two_teams"] = (
        squads.groupBy("match_id").agg(F.countDistinct("team_id").alias("teams"))
        .filter(F.col("teams") != 2).count()
    )
    # An empty team disappears with explode; check raw pairs explicitly, not just output counts.
    counts["empty_match_team_pairs"] = (
        raw.select("match_id", "team_id").distinct()
        .join(squads.select("match_id", "team_id").distinct(), ["match_id", "team_id"], "left_anti").count()
    )
    print("DQ match_squads: " + ", ".join(f"{name}={value}" for name, value in counts.items() if name not in {f"null_{key}" for key in optional}))
    print("Informational NULLs match_squads: " + ", ".join(f"{name}={counts[f'null_{name}']}" for name in optional))
    if (
        counts["row_count"] == 0 or counts["row_count"] != counts["raw_lineup_player_rows"]
        or counts["match_count"] != len(match_ids) or any(counts[f"null_{name}"] for name in required)
        or any(counts[name] for name in (
            "empty_lineup_rows", "invalid_raw_match_rows", "invalid_raw_team_rows", "unexpected_match_rows",
            "duplicate_keys", "matches_without_two_teams", "empty_match_team_pairs",
        ))
    ):
        raise LineupQualityError("match_squads DQ failed; see aggregate diagnostics.")
    return counts


def _validate_dimension(df, *, identity, required, optional=()):
    counts = _counts(df, required, optional)
    counts["duplicate_keys"] = df.groupBy(identity).count().filter(F.col("count") > 1).count()
    print(f"DQ {identity}: " + ", ".join(f"{name}={value}" for name, value in counts.items()))
    if counts["row_count"] == 0 or counts["duplicate_keys"] or any(counts[f"null_{name}"] for name in required):
        raise LineupQualityError(f"{identity} dimension DQ failed; see aggregate diagnostics.")
    return counts


def validate_teams(teams: DataFrame) -> dict[str, int]:
    return _validate_dimension(teams, identity="team_id", required=("team_id", "team_name"))


def validate_players(players: DataFrame) -> dict[str, int]:
    return _validate_dimension(
        players, identity="player_id", required=("player_id", "player_name"),
        optional=("player_nickname", "country_id", "country_name"),
    )


def validate_references(squads: DataFrame, teams: DataFrame, players: DataFrame) -> dict[str, int]:
    counts = {
        "missing_team_references": squads.select("team_id").distinct().join(teams.select("team_id"), "team_id", "left_anti").count(),
        "missing_player_references": squads.select("player_id").distinct().join(players.select("player_id"), "player_id", "left_anti").count(),
    }
    print("Referential DQ: " + ", ".join(f"{name}={value}" for name, value in counts.items()))
    if any(counts.values()):
        raise LineupQualityError("Lineup referential DQ failed; see aggregate diagnostics.")
    return counts


def build_lineup_frame(spark, paths: list[str], match_ids: list[int], *, dataset: str, competition_id: int, season_id: int):
    """Validate all three related views; return only the requested publication frame."""
    raw = read_s3a_lineups(spark, paths).cache()
    cached = [raw]
    output = None
    try:
        context = {"competition_id": competition_id, "season_id": season_id}
        squads = transform_match_squads(raw, **context).cache()
        cached.append(squads)
        squad_counts = validate_match_squads(squads, raw=raw, match_ids=match_ids)
        teams = transform_teams(squads, **context).cache()
        cached.append(teams)
        players = transform_players(squads, **context).cache()
        cached.append(players)
        team_counts = validate_teams(teams)
        player_counts = validate_players(players)
        validate_references(squads, teams, players)
        output, counts = {
            "teams": (teams, team_counts), "players": (players, player_counts),
            "match_squads": (squads, squad_counts),
        }[dataset]
        counts.update(
            input_match_count=squad_counts["match_count"],
            raw_lineup_team_rows=squad_counts["raw_lineup_team_rows"],
            raw_lineup_player_rows=squad_counts["raw_lineup_player_rows"],
        )
        return output, counts
    finally:
        for frame in cached:
            if frame is not output:
                frame.unpersist()
