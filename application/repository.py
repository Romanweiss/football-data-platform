"""Fixed projections of validated BI views. No joins or analytics in the API."""
from contextlib import contextmanager

from clickhouse_connect.driver.exceptions import Error as ClickHouseError
from src.common.clickhouse import create_clickhouse_client
from application.errors import ServingIntegrityError, unavailable
from application.serialization import serialize_row

CONTEXT = {"competition_id": 43, "season_id": 106}
CONTEXT_SQL = "competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}"
MATCH_FIELDS = tuple("competition_id season_id match_id match_label match_date kick_off competition_stage_id competition_stage_name home_team_id home_team_name away_team_id away_team_name home_score away_score display_score result_method went_to_extra_time went_to_penalties winner_team_id winner_team_name".split())
METRICS = tuple("event_count pass_attempts shot_count shot_xg shot_goals under_pressure_events counterpress_events".split())
PROJECTIONS = {
    "teams": ("football.bi_match_team_stats", (*"team_id team_name opponent_team_id opponent_team_name is_home goals_for goals_against goal_difference match_result".split(), *METRICS, "players_with_events"), "is_home DESC, team_id"),
    "players": ("football.bi_match_player_stats", (*"team_id team_name player_id player_name is_home".split(), *METRICS), "is_home DESC, team_id, player_id"),
    "shots": ("football.bi_match_shot_map", tuple("event_id event_index shot_label team_id team_name player_id player_name period minute second statsbomb_xg outcome_id outcome_name is_goal is_extra_time start_x start_y end_x end_y end_z".split()), "period, minute, second, event_index"),
    "xg_race": ("football.bi_match_xg_race_series", tuple("event_order event_id event_index period minute second team_id team_name is_home cumulative_xg".split()), "event_order, is_home DESC"),
    "shootout": ("football.bi_match_shootout", tuple("shootout_order team_attempt_number team_id team_name player_id player_name outcome_id outcome_name is_goal home_shootout_goals_after away_shootout_goals_after".split()), "shootout_order"),
}
# The existing readonly=1 profile forbids changing other query settings.
# Enforce the small response bound through constant LIMITs and a length guard.
QUERY_SETTINGS = {"readonly": 1}


class FootballRepository:
    def __init__(self, client):
        self.client = client

    def _query(self, sql, parameters=None):
        try:
            result = self.client.query(sql, parameters=parameters or {}, settings=QUERY_SETTINGS)
        except (ClickHouseError, OSError, TimeoutError):
            raise unavailable() from None
        if len(result.result_rows) > 10000:
            raise ServingIntegrityError("Serving result exceeds reviewed bound")
        return [serialize_row(dict(zip(result.column_names, row, strict=True))) for row in result.result_rows]

    def health(self):
        if self._query("SELECT 1 AS ok") != [{"ok": 1}]:
            raise unavailable()
        return {"status": "ok"}

    def matches(self):
        return self._query(
            f"SELECT {', '.join(MATCH_FIELDS)} FROM football.bi_match_overview WHERE {CONTEXT_SQL} "
            "ORDER BY match_date, kick_off, match_id LIMIT 10001", CONTEXT)

    def match(self, match_id):
        rows = self._query(
            f"SELECT {', '.join(MATCH_FIELDS)} FROM football.bi_match_overview WHERE {CONTEXT_SQL} "
            "AND match_id = {match_id:UInt64} LIMIT 2", {**CONTEXT, "match_id": match_id})
        if len(rows) > 1:
            raise ServingIntegrityError("Duplicate match identity")
        return rows[0] if rows else None

    def section(self, name, match_id, team_id=None):
        # name is a controller-owned constant, never a request SQL identifier.
        table, fields, ordering = PROJECTIONS[name]
        sql = f"SELECT {', '.join(fields)} FROM {table} WHERE {CONTEXT_SQL} AND match_id = {{match_id:UInt64}}"
        params = {**CONTEXT, "match_id": match_id}
        if team_id is not None:
            if name != "players":
                raise ValueError("Team filter only applies to players")
            sql += " AND team_id = {team_id:UInt32}"
            params["team_id"] = team_id
        return self._query(sql + f" ORDER BY {ordering} LIMIT 10001", params)


@contextmanager
def open_repository():
    # One client per request, reused for its fixed queries, never shared across
    # concurrent Django threads/ClickHouse sessions. No client opened at import.
    try:
        client = create_clickhouse_client()
    except (ClickHouseError, OSError, TimeoutError, ValueError):
        raise unavailable() from None
    try:
        yield FootballRepository(client)
    finally:
        client.close()
