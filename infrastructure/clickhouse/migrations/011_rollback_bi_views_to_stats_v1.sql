-- EXPLICIT ROLLBACK ONLY, not a forward migration to apply after 010.
-- Preserve v2 tables and all catalog history. Keep BI paused until both views validate.
CREATE OR REPLACE VIEW football.bi_team_match_stats
SQL SECURITY INVOKER
AS
SELECT
    t.competition_id AS competition_id,
    t.season_id AS season_id,
    t.match_id AS match_id,
    m.match_date AS match_date,
    m.kick_off AS kick_off,
    m.match_week AS match_week,
    m.competition_stage_id AS competition_stage_id,
    m.competition_stage_name AS competition_stage_name,
    m.home_team_id AS home_team_id,
    m.home_team_name AS home_team_name,
    m.away_team_id AS away_team_id,
    m.away_team_name AS away_team_name,
    m.home_score AS home_score,
    m.away_score AS away_score,
    t.team_id AS team_id,
    t.team_name AS team_name,
    t.team_id = m.home_team_id AS is_home,
    if(is_home, m.away_team_id, m.home_team_id) AS opponent_team_id,
    if(is_home, m.away_team_name, m.home_team_name) AS opponent_team_name,
    if(is_home, m.home_score, m.away_score) AS goals_for,
    if(is_home, m.away_score, m.home_score) AS goals_against,
    toInt32(goals_for) - toInt32(goals_against) AS goal_difference,
    multiIf(isNull(r.winner_team_id), 'D', t.team_id = r.winner_team_id, 'W', 'L') AS match_result,
    r.went_to_extra_time AS went_to_extra_time,
    r.went_to_penalties AS went_to_penalties,
    r.home_shootout_goals AS home_shootout_goals,
    r.away_shootout_goals AS away_shootout_goals,
    r.winner_team_id AS winner_team_id,
    r.winner_team_name AS winner_team_name,
    r.result_method AS result_method,
    r.display_score AS display_score,
    t.event_count AS event_count,
    t.pass_attempts AS pass_attempts,
    t.shot_count AS shot_count,
    t.shot_xg AS shot_xg,
    t.shot_goals AS shot_goals,
    t.under_pressure_events AS under_pressure_events,
    t.counterpress_events AS counterpress_events,
    t.players_with_events AS players_with_events
FROM football.team_match_stats AS t
INNER JOIN football.matches AS m
    ON t.competition_id = m.competition_id
    AND t.season_id = m.season_id
    AND t.match_id = m.match_id
INNER JOIN football.match_results AS r
    ON t.competition_id = r.competition_id
    AND t.season_id = r.season_id
    AND t.match_id = r.match_id;

CREATE OR REPLACE VIEW football.bi_player_match_stats
SQL SECURITY INVOKER
AS
SELECT
    p.competition_id AS competition_id,
    p.season_id AS season_id,
    p.match_id AS match_id,
    m.match_date AS match_date,
    m.kick_off AS kick_off,
    m.competition_stage_id AS competition_stage_id,
    m.competition_stage_name AS competition_stage_name,
    m.home_team_id AS home_team_id,
    m.home_team_name AS home_team_name,
    m.away_team_id AS away_team_id,
    m.away_team_name AS away_team_name,
    m.home_score AS home_score,
    m.away_score AS away_score,
    p.team_id AS team_id,
    p.team_name AS team_name,
    if(p.team_id = m.home_team_id, m.away_team_id, m.home_team_id) AS opponent_team_id,
    if(p.team_id = m.home_team_id, m.away_team_name, m.home_team_name) AS opponent_team_name,
    p.team_id = m.home_team_id AS is_home,
    p.player_id AS player_id,
    p.player_name AS player_name,
    r.went_to_extra_time AS went_to_extra_time,
    r.went_to_penalties AS went_to_penalties,
    r.home_shootout_goals AS home_shootout_goals,
    r.away_shootout_goals AS away_shootout_goals,
    r.winner_team_id AS winner_team_id,
    r.winner_team_name AS winner_team_name,
    r.result_method AS result_method,
    r.display_score AS display_score,
    p.event_count AS event_count,
    p.pass_attempts AS pass_attempts,
    p.shot_count AS shot_count,
    p.shot_xg AS shot_xg,
    p.shot_goals AS shot_goals,
    p.under_pressure_events AS under_pressure_events,
    p.counterpress_events AS counterpress_events
FROM football.player_match_stats AS p
INNER JOIN football.matches AS m
    ON p.competition_id = m.competition_id
    AND p.season_id = m.season_id
    AND p.match_id = m.match_id
INNER JOIN football.match_results AS r
    ON p.competition_id = r.competition_id
    AND p.season_id = r.season_id
    AND p.match_id = r.match_id;
