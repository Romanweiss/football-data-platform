"""Pure SQL fixtures for SELECT-only tests of the exact BI view projections."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infrastructure/clickhouse/migrations/006_create_bi_views.sql"
CHECKS = ROOT / "scripts/check_clickhouse_bi_views.sql"


def statements(path):
    return [sql.strip() for sql in path.read_text().split(";") if sql.strip()]


def view_selects():
    return [statement.split("\nAS\n", 1)[1] for statement in statements(MIGRATION)]


def synthetic_ctes(*, duplicate_matches=False, invalid_team=False, duplicate_players=False, bad_score=False):
    matches = """SELECT toUInt32(43) AS competition_id, toUInt32(106) AS season_id,
        number + 1 AS match_id, toDate('2022-11-21') + toIntervalDay(number) AS match_date,
        '13:00:00.000' AS kick_off, toNullable(toUInt16(1)) AS match_week,
        toUInt16(10) AS competition_stage_id, 'Group Stage' AS competition_stage_name,
        toUInt32(10) AS home_team_id, 'Home' AS home_team_name,
        toUInt32(20) AS away_team_id, 'Away' AS away_team_name,
        toUInt16(multiIf(number = 0, 2, number = 1, 0, 1)) AS home_score,
        toUInt16(multiIf(number = 0, 1, number = 1, 0, 3)) AS away_score FROM numbers(3)"""
    teams = """SELECT toUInt32(43) AS competition_id, toUInt32(106) AS season_id,
        intDiv(number, 2) + 1 AS match_id, toUInt32(if(modulo(number, 2) = 0, 10, 20)) AS team_id,
        if(modulo(number, 2) = 0, 'Home', 'Away') AS team_name,
        toUInt64(1) AS event_count, toUInt64(1) AS pass_attempts, toUInt64(1) AS shot_count,
        toFloat64(0.1) AS shot_xg, toUInt64(99) AS shot_goals, toUInt64(1) AS under_pressure_events,
        toUInt64(1) AS counterpress_events, toUInt64(1) AS players_with_events FROM numbers(6)"""
    if invalid_team:
        teams = teams.replace("toUInt32(if(modulo(number, 2) = 0, 10, 20))", "toUInt32(999)")
    players = "SELECT *, team_id + 100 AS player_id, concat('Player ', toString(team_id)) AS player_name FROM test_teams"
    if duplicate_matches:
        matches += " UNION ALL " + matches
    if duplicate_players:
        players += " UNION ALL " + players
    team_view, player_view = view_selects()
    if bad_score:
        team_view = team_view.replace("if(is_home, m.home_score, m.away_score) AS goals_for", "toUInt16(99) AS goals_for")
    mapping = {"football.matches": "test_matches", "football.team_match_stats": "test_teams", "football.player_match_stats": "test_players",
               "football.bi_team_match_stats": "test_team_view", "football.bi_player_match_stats": "test_player_view"}
    def substitute(sql):
        for name, replacement in mapping.items():
            sql = sql.replace(name, replacement)
        return sql
    ctes = ("WITH test_matches AS (" + matches + "), test_teams AS (" + teams + "), test_players AS (" + players
            + "), test_team_view AS (" + substitute(team_view) + "), test_player_view AS (" + substitute(player_view) + ") ")
    return ctes, substitute
