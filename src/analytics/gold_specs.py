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
    version: str = "v1"

    @property
    def transform_version(self):
        return self.dataset + "_" + self.version

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
        return tuple(name for name, kind in self.columns if not kind.startswith("Nullable"))

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


@dataclass(frozen=True)
class MatchResultsSpec(GoldSpec):
    @property
    def order_by(self):
        return (*self.context_columns, "match_date", "match_id")

    @property
    def invalid_predicates(self):
        home_wins = "if(went_to_penalties, home_shootout_goals>away_shootout_goals, home_score>away_score)"
        away_wins = "if(went_to_penalties, away_shootout_goals>home_shootout_goals, away_score>home_score)"
        expected_id = f"multiIf({home_wins},home_team_id,{away_wins},away_team_id,0)"
        expected_name = f"multiIf({home_wins},home_team_name,{away_wins},away_team_name,'')"
        expected_method = "multiIf(went_to_penalties,'PENALTIES',isNull(winner_team_id),'DRAW',went_to_extra_time,'EXTRA_TIME','REGULATION')"
        score = "concat(toString(home_score),'-',toString(away_score))"
        display = f"if(went_to_penalties,concat({score},' (',toString(home_shootout_goals),'-',toString(away_shootout_goals),' pens)'),{score})"
        return ("home_team_id=away_team_id", "home_score<0 OR away_score<0",
            "home_shootout_attempts<0 OR away_shootout_attempts<0 OR home_shootout_goals<0 OR away_shootout_goals<0",
            "home_shootout_goals>home_shootout_attempts OR away_shootout_goals>away_shootout_attempts",
            "went_to_penalties AND (home_shootout_goals=away_shootout_goals OR isNull(winner_team_id) "
            "OR home_shootout_attempts=0 OR away_shootout_attempts=0 OR home_score!=away_score)",
            "NOT went_to_penalties AND (home_shootout_attempts!=0 OR away_shootout_attempts!=0 OR home_shootout_goals!=0 OR away_shootout_goals!=0)",
            f"ifNull(winner_team_id,0)!={expected_id}", f"ifNull(winner_team_name,'')!={expected_name}",
            f"isNull(winner_team_id)!=NOT ({home_wins} OR {away_wins})", "isNull(winner_team_id)!=isNull(winner_team_name)",
            f"result_method!={expected_method}", f"display_score!={display}")


RESULTS = MatchResultsSpec("match_results", (
    ("competition_id", "UInt32"), ("season_id", "UInt32"), ("match_id", "UInt64"),
    ("match_date", "Date"), ("kick_off", "String"), ("competition_stage_id", "UInt16"), ("competition_stage_name", "LowCardinality(String)"),
    ("home_team_id", "UInt32"), ("home_team_name", "LowCardinality(String)"),
    ("away_team_id", "UInt32"), ("away_team_name", "LowCardinality(String)"), ("home_score", "UInt16"), ("away_score", "UInt16"),
    ("went_to_extra_time", "Bool"), ("went_to_penalties", "Bool"),
    ("home_shootout_attempts", "UInt64"), ("away_shootout_attempts", "UInt64"),
    ("home_shootout_goals", "UInt64"), ("away_shootout_goals", "UInt64"),
    ("winner_team_id", "Nullable(UInt32)"), ("winner_team_name", "Nullable(String)"),
    ("result_method", "LowCardinality(String)"), ("display_score", "String"),
), ("match_id",))
# Keep the existing v1 cross-model stats contract separate from result semantics.
LOAD_SPECS = MappingProxyType({**SPECS, RESULTS.dataset: RESULTS})
CLI_DATASETS = MappingProxyType({"team-match-stats": TEAM.dataset, "player-match-stats": PLAYER.dataset, "match-results": RESULTS.dataset})
