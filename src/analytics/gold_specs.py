"""Explicit immutable Gold serving contracts. No Spark or business recomputation."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class GoldSpec:
    dataset: str
    columns: tuple[tuple[str, str], ...]
    identity_columns: tuple[str, ...]
    two_teams_per_match: bool = False
    clickhouse_database: str = "football"
    table_override: str | None = None
    context_columns: tuple[str, ...] = ("competition_id", "season_id")
    has_match_count: bool = True

    @property
    def transform_version(self):
        return self.dataset + "_v1"

    @property
    def clickhouse_table(self):
        return self.table_override or self.dataset

    @property
    def target(self):
        return f"{self.clickhouse_database}.{self.clickhouse_table}" if self.clickhouse_database else self.clickhouse_table

    @property
    def order_by(self):
        return (*self.context_columns, *self.identity_columns)

    @property
    def target_columns(self):
        return (*self.columns, ("gold_build_id", "FixedString(64)"), ("loaded_at", "DateTime64(3, 'UTC')"))

    @property
    def required_columns(self):
        # Metrics also must not be NULL: no input/insert NULL-to-default coercion.
        return tuple(name for name, _ in self.columns)

    @property
    def select_expressions(self):
        return tuple(f"{'CAST' if kind.startswith('LowCardinality') else 'accurateCast'}(`{name}`, '{kind}') AS `{name}`"
                     for name, kind in self.columns)

    @property
    def invalid_predicates(self):
        metrics = [name for name, _ in self.columns if name in (*COUNT_METRICS, "players_with_events", "shot_xg")]
        return (*[f"`{name}` < 0" for name in metrics], "NOT isFinite(shot_xg)", "shot_goals > shot_count")


COUNT_METRICS = ("event_count", "pass_attempts", "shot_count", "shot_goals", "under_pressure_events", "counterpress_events")
HEAD = (("competition_id", "UInt32"), ("season_id", "UInt32"), ("match_id", "UInt64"),
        ("team_id", "UInt32"), ("team_name", "LowCardinality(String)"))
METRICS = (("event_count", "UInt64"), ("pass_attempts", "UInt64"), ("shot_count", "UInt64"),
           ("shot_xg", "Float64"), ("shot_goals", "UInt64"), ("under_pressure_events", "UInt64"), ("counterpress_events", "UInt64"))
TEAM = GoldSpec("team_match_stats", (*HEAD, *METRICS, ("players_with_events", "UInt64")), ("match_id", "team_id"), True)
PLAYER = GoldSpec("player_match_stats", (*HEAD, ("player_id", "UInt32"), ("player_name", "String"), *METRICS),
                  ("match_id", "team_id", "player_id"))
SPECS = MappingProxyType({spec.dataset: spec for spec in (TEAM, PLAYER)})
CLI_DATASETS = MappingProxyType({"team-match-stats": TEAM.dataset, "player-match-stats": PLAYER.dataset})
