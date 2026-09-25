"""Small immutable Silver -> ClickHouse contracts. No Spark or service IO."""

from dataclasses import dataclass, replace
from types import MappingProxyType


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    transform_version: str
    columns: tuple[tuple[str, str], ...]
    select_expressions: tuple[str, ...]
    identity_columns: tuple[str, ...]
    order_by: tuple[str, ...]
    clickhouse_table: str
    clickhouse_database: str = "football"
    context_columns: tuple[str, ...] = ("competition_id", "season_id")
    has_match_count: bool = True
    artifact_kind: str = "events"
    required_columns: tuple[str, ...] = ()
    invalid_predicates: tuple[str, ...] = ()
    two_teams_per_match: bool = False

    @property
    def target(self):
        return f"{self.clickhouse_database}.{self.clickhouse_table}" if self.clickhouse_database else self.clickhouse_table

    @property
    def target_columns(self):
        return (*self.columns, ("silver_build_id", "FixedString(64)"), ("loaded_at", "DateTime64(3, 'UTC')"))


def _spec(dataset, columns, identity, order, **options):
    expressions = []
    for name, kind in columns:
        if kind in ("UUID", "Nullable(UUID)"):
            # toUUID propagates a nullable String's NULL and rejects malformed
            # non-null text; accurateCast(..., Nullable(UUID)) can hide it as NULL.
            expression = f"toUUID(`{name}`)"
        elif kind.startswith("LowCardinality"):
            expression = f"CAST(`{name}`, '{kind}')"
        else:
            expression = f"accurateCast(`{name}`, '{kind}')"
        expressions.append(f"{expression} AS `{name}`")
    return DatasetSpec(dataset, dataset + "_v1", columns, tuple(expressions), identity,
                       order, dataset, **options)


CONTEXT_COLUMNS = (("competition_id", "UInt32"), ("season_id", "UInt32"))
EVENT_ORDER = ("competition_id", "season_id", "match_id", "period", "event_index", "event_id")
EVENT_IDENTITY = ("match_id", "event_id")
EVENT_HEAD = (
    *CONTEXT_COLUMNS, ("match_id", "UInt64"), ("event_id", "UUID"),
    ("event_index", "UInt32"), ("period", "UInt8"), ("timestamp", "String"),
    ("minute", "UInt16"), ("second", "UInt8"),
)
TEAM_PLAYER = (
    ("team_id", "UInt32"), ("team_name", "LowCardinality(String)"),
    ("player_id", "Nullable(UInt32)"), ("player_name", "Nullable(String)"),
)
DOMAIN_HEAD = (*EVENT_HEAD, *TEAM_PLAYER, ("start_x", "Nullable(Float64)"), ("start_y", "Nullable(Float64)"))

EVENT_CORE = _spec("event_core", (
    *EVENT_HEAD, ("type_id", "UInt16"), ("type_name", "LowCardinality(String)"), ("possession", "UInt16"),
    ("possession_team_id", "Nullable(UInt32)"), ("possession_team_name", "Nullable(String)"),
    ("play_pattern_id", "Nullable(UInt16)"), ("play_pattern_name", "Nullable(String)"),
    *TEAM_PLAYER, ("position_id", "Nullable(UInt16)"), ("position_name", "Nullable(String)"),
    ("location_x", "Nullable(Float64)"), ("location_y", "Nullable(Float64)"),
    ("duration", "Nullable(Float64)"), ("under_pressure", "Nullable(Bool)"), ("counterpress", "Nullable(Bool)"),
), EVENT_IDENTITY, EVENT_ORDER)

PASSES = _spec("pass_events", (
    *DOMAIN_HEAD, ("recipient_id", "Nullable(UInt32)"), ("recipient_name", "Nullable(String)"),
    ("pass_length", "Nullable(Float64)"), ("pass_angle", "Nullable(Float64)"),
    ("end_x", "Nullable(Float64)"), ("end_y", "Nullable(Float64)"),
    ("height_id", "Nullable(UInt16)"), ("height_name", "Nullable(String)"),
    ("body_part_id", "Nullable(UInt16)"), ("body_part_name", "Nullable(String)"),
    ("pass_type_id", "Nullable(UInt16)"), ("pass_type_name", "Nullable(String)"),
    ("outcome_id", "Nullable(UInt16)"), ("outcome_name", "Nullable(String)"),
    ("technique_id", "Nullable(UInt16)"), ("technique_name", "Nullable(String)"),
    ("cross", "Nullable(Bool)"), ("cut_back", "Nullable(Bool)"), ("switch", "Nullable(Bool)"),
    ("shot_assist", "Nullable(Bool)"), ("goal_assist", "Nullable(Bool)"),
    ("aerial_won", "Nullable(Bool)"), ("through_ball", "Nullable(Bool)"),
), EVENT_IDENTITY, EVENT_ORDER, required_columns=("match_id", "event_id", "event_index", "team_id"))

SHOTS = _spec("shot_events", (
    *DOMAIN_HEAD, ("statsbomb_xg", "Float64"), ("end_x", "Nullable(Float64)"),
    ("end_y", "Nullable(Float64)"), ("end_z", "Nullable(Float64)"), ("key_pass_id", "Nullable(UUID)"),
    ("body_part_id", "Nullable(UInt16)"), ("body_part_name", "Nullable(String)"),
    ("shot_type_id", "Nullable(UInt16)"), ("shot_type_name", "Nullable(String)"),
    ("technique_id", "Nullable(UInt16)"), ("technique_name", "Nullable(String)"),
    ("outcome_id", "UInt16"), ("outcome_name", "Nullable(String)"),
    ("first_time", "Nullable(Bool)"), ("open_goal", "Nullable(Bool)"), ("one_on_one", "Nullable(Bool)"),
    ("aerial_won", "Nullable(Bool)"), ("deflected", "Nullable(Bool)"),
), EVENT_IDENTITY, EVENT_ORDER,
    required_columns=("match_id", "event_id", "event_index", "team_id", "statsbomb_xg", "outcome_id"),
    invalid_predicates=("NOT isFinite(statsbomb_xg) OR statsbomb_xg < 0 OR statsbomb_xg > 1",))

TEAMS = _spec("teams", (
    *CONTEXT_COLUMNS, ("team_id", "UInt32"), ("team_name", "LowCardinality(String)"),
), ("team_id",), ("competition_id", "season_id", "team_id"), has_match_count=False,
    artifact_kind="lineups", required_columns=("team_id", "team_name"))

PLAYERS = _spec("players", (
    *CONTEXT_COLUMNS, ("player_id", "UInt32"), ("player_name", "String"),
    ("player_nickname", "Nullable(String)"), ("country_id", "Nullable(UInt32)"),
    ("country_name", "LowCardinality(Nullable(String))"),
), ("player_id",), ("competition_id", "season_id", "player_id"), has_match_count=False,
    artifact_kind="lineups", required_columns=("player_id", "player_name"))

MATCH_SQUADS = _spec("match_squads", (
    *CONTEXT_COLUMNS, ("match_id", "UInt64"), ("team_id", "UInt32"), ("team_name", "LowCardinality(String)"),
    ("player_id", "UInt32"), ("player_name", "String"), ("player_nickname", "Nullable(String)"),
    ("jersey_number", "Nullable(UInt16)"), ("country_id", "Nullable(UInt32)"), ("country_name", "Nullable(String)"),
), ("match_id", "team_id", "player_id"), ("competition_id", "season_id", "match_id", "team_id", "player_id"),
    artifact_kind="lineups", required_columns=("match_id", "team_id", "player_id", "team_name", "player_name"),
    two_teams_per_match=True)

MATCHES = _spec("matches", (
    *CONTEXT_COLUMNS, ("match_id", "UInt64"), ("match_date", "Date"), ("kick_off", "String"),
    ("match_week", "Nullable(UInt16)"), ("competition_stage_id", "UInt16"), ("competition_stage_name", "LowCardinality(String)"),
    ("home_team_id", "UInt32"), ("home_team_name", "LowCardinality(String)"),
    ("away_team_id", "UInt32"), ("away_team_name", "LowCardinality(String)"),
    ("home_score", "UInt16"), ("away_score", "UInt16"), ("stadium_id", "Nullable(UInt32)"), ("stadium_name", "Nullable(String)"),
    ("referee_id", "Nullable(UInt32)"), ("referee_name", "Nullable(String)"),
), ("match_id",), ("competition_id", "season_id", "match_date", "match_id"), artifact_kind="matches",
    required_columns=("competition_id", "season_id", "match_id", "match_date", "competition_stage_id", "competition_stage_name",
                      "home_team_id", "home_team_name", "away_team_id", "away_team_name", "home_score", "away_score"),
    invalid_predicates=("home_team_id = away_team_id", "home_score < 0", "away_score < 0"))
# Silver preserves unknown kickoff as NULL. The specified serving String uses an
# explicit empty-string sentinel, not implicit input_format_null_as_default.
# Date32 -> Date can clamp even under accurateCast. Check epoch days as UInt16
# first. Nullable integer targets similarly must reject non-null overflow rather
# than turning it into NULL; genuine source NULLs remain NULL.
MATCHES = replace(MATCHES, select_expressions=tuple(
    ("accurateCast(ifNull(`kick_off`, ''), 'String') AS `kick_off`" if name == "kick_off" else
     "accurateCast(accurateCast(toInt64(`match_date`), 'UInt16'), 'Date') AS `match_date`" if name == "match_date" else
     f"if(isNull(`{name}`), NULL, accurateCast(assumeNotNull(`{name}`), '{kind[9:-1]}')) AS `{name}`"
     if kind.startswith("Nullable(UInt") else expression)
    for (name, kind), expression in zip(MATCHES.columns, MATCHES.select_expressions, strict=True)
))

SPECS = MappingProxyType({spec.dataset: spec for spec in (EVENT_CORE, PASSES, SHOTS, TEAMS, PLAYERS, MATCH_SQUADS, MATCHES)})
CLI_DATASETS = MappingProxyType({
    "event-core": "event_core", "passes": "pass_events", "shots": "shot_events",
    "teams": "teams", "players": "players", "match-squads": "match_squads", "matches": "matches",
})
