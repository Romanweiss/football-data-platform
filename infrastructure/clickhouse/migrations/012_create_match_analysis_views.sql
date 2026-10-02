-- Additive Match Analysis views only. Apply manually after Stage 4C validation.
-- All labels come from bi_match_overview. Preserve every shot including period 5.
CREATE VIEW IF NOT EXISTS football.bi_match_overview
SQL SECURITY INVOKER
AS
SELECT
    r.competition_id AS competition_id,
    r.season_id AS season_id,
    r.match_id AS match_id,
    r.match_date AS match_date,
    r.kick_off AS kick_off,
    r.competition_stage_id AS competition_stage_id,
    r.competition_stage_name AS competition_stage_name,
    r.home_team_id AS home_team_id,
    r.home_team_name AS home_team_name,
    r.away_team_id AS away_team_id,
    r.away_team_name AS away_team_name,
    r.home_score AS home_score,
    r.away_score AS away_score,
    r.went_to_extra_time AS went_to_extra_time,
    r.went_to_penalties AS went_to_penalties,
    r.home_shootout_attempts AS home_shootout_attempts,
    r.away_shootout_attempts AS away_shootout_attempts,
    r.home_shootout_goals AS home_shootout_goals,
    r.away_shootout_goals AS away_shootout_goals,
    r.winner_team_id AS winner_team_id,
    r.winner_team_name AS winner_team_name,
    r.result_method AS result_method,
    r.display_score AS display_score,
    m.match_week AS match_week,
    m.stadium_id AS stadium_id,
    m.stadium_name AS stadium_name,
    m.referee_id AS referee_id,
    m.referee_name AS referee_name,
    concat(toString(r.match_date), ' | ', r.home_team_name, ' - ', r.away_team_name) AS match_label
FROM football.match_results AS r
INNER JOIN football.matches AS m
    ON r.competition_id = m.competition_id
    AND r.season_id = m.season_id
    AND r.match_id = m.match_id;

CREATE VIEW IF NOT EXISTS football.bi_match_team_stats
SQL SECURITY INVOKER
AS
SELECT
    t.competition_id AS competition_id,
    t.season_id AS season_id,
    t.match_id AS match_id,
    t.match_date AS match_date,
    t.kick_off AS kick_off,
    t.match_week AS match_week,
    t.competition_stage_id AS competition_stage_id,
    t.competition_stage_name AS competition_stage_name,
    t.home_team_id AS home_team_id,
    t.home_team_name AS home_team_name,
    t.away_team_id AS away_team_id,
    t.away_team_name AS away_team_name,
    t.home_score AS home_score,
    t.away_score AS away_score,
    t.team_id AS team_id,
    t.team_name AS team_name,
    t.is_home AS is_home,
    t.opponent_team_id AS opponent_team_id,
    t.opponent_team_name AS opponent_team_name,
    t.goals_for AS goals_for,
    t.goals_against AS goals_against,
    t.goal_difference AS goal_difference,
    t.match_result AS match_result,
    t.went_to_extra_time AS went_to_extra_time,
    t.went_to_penalties AS went_to_penalties,
    t.home_shootout_goals AS home_shootout_goals,
    t.away_shootout_goals AS away_shootout_goals,
    t.winner_team_id AS winner_team_id,
    t.winner_team_name AS winner_team_name,
    t.result_method AS result_method,
    t.display_score AS display_score,
    t.event_count AS event_count,
    t.pass_attempts AS pass_attempts,
    t.shot_count AS shot_count,
    t.shot_xg AS shot_xg,
    t.shot_goals AS shot_goals,
    t.under_pressure_events AS under_pressure_events,
    t.counterpress_events AS counterpress_events,
    t.players_with_events AS players_with_events,
    o.match_label AS match_label
FROM football.bi_team_match_stats AS t
INNER JOIN football.bi_match_overview AS o
    ON t.competition_id = o.competition_id
    AND t.season_id = o.season_id
    AND t.match_id = o.match_id;

CREATE VIEW IF NOT EXISTS football.bi_match_player_stats
SQL SECURITY INVOKER
AS
SELECT
    p.competition_id AS competition_id,
    p.season_id AS season_id,
    p.match_id AS match_id,
    p.match_date AS match_date,
    p.kick_off AS kick_off,
    p.competition_stage_id AS competition_stage_id,
    p.competition_stage_name AS competition_stage_name,
    p.home_team_id AS home_team_id,
    p.home_team_name AS home_team_name,
    p.away_team_id AS away_team_id,
    p.away_team_name AS away_team_name,
    p.home_score AS home_score,
    p.away_score AS away_score,
    p.team_id AS team_id,
    p.team_name AS team_name,
    p.opponent_team_id AS opponent_team_id,
    p.opponent_team_name AS opponent_team_name,
    p.is_home AS is_home,
    p.player_id AS player_id,
    p.player_name AS player_name,
    p.went_to_extra_time AS went_to_extra_time,
    p.went_to_penalties AS went_to_penalties,
    p.home_shootout_goals AS home_shootout_goals,
    p.away_shootout_goals AS away_shootout_goals,
    p.winner_team_id AS winner_team_id,
    p.winner_team_name AS winner_team_name,
    p.result_method AS result_method,
    p.display_score AS display_score,
    p.event_count AS event_count,
    p.pass_attempts AS pass_attempts,
    p.shot_count AS shot_count,
    p.shot_xg AS shot_xg,
    p.shot_goals AS shot_goals,
    p.under_pressure_events AS under_pressure_events,
    p.counterpress_events AS counterpress_events,
    o.match_label AS match_label
FROM football.bi_player_match_stats AS p
INNER JOIN football.bi_match_overview AS o
    ON p.competition_id = o.competition_id
    AND p.season_id = o.season_id
    AND p.match_id = o.match_id;

CREATE VIEW IF NOT EXISTS football.bi_match_shots
SQL SECURITY INVOKER
AS
SELECT
    s.competition_id AS competition_id,
    s.season_id AS season_id,
    s.match_id AS match_id,
    s.event_id AS event_id,
    s.event_index AS event_index,
    s.period AS period,
    s.timestamp AS timestamp,
    s.minute AS minute,
    s.second AS second,
    s.team_id AS team_id,
    s.team_name AS team_name,
    s.player_id AS player_id,
    s.player_name AS player_name,
    s.start_x AS start_x,
    s.start_y AS start_y,
    s.statsbomb_xg AS statsbomb_xg,
    s.end_x AS end_x,
    s.end_y AS end_y,
    s.end_z AS end_z,
    s.key_pass_id AS key_pass_id,
    s.body_part_id AS body_part_id,
    s.body_part_name AS body_part_name,
    s.shot_type_id AS shot_type_id,
    s.shot_type_name AS shot_type_name,
    s.technique_id AS technique_id,
    s.technique_name AS technique_name,
    s.outcome_id AS outcome_id,
    s.outcome_name AS outcome_name,
    s.first_time AS first_time,
    s.open_goal AS open_goal,
    s.one_on_one AS one_on_one,
    s.aerial_won AS aerial_won,
    s.deflected AS deflected,
    s.period = 5 AS is_shootout,
    s.period IN (3, 4) AS is_extra_time,
    o.match_label AS match_label,
    o.match_date AS match_date,
    o.competition_stage_name AS competition_stage_name,
    o.display_score AS display_score,
    o.result_method AS result_method,
    o.went_to_extra_time AS went_to_extra_time,
    o.went_to_penalties AS went_to_penalties,
    o.winner_team_id AS winner_team_id,
    o.winner_team_name AS winner_team_name
FROM football.shot_events AS s
INNER JOIN football.bi_match_overview AS o
    ON s.competition_id = o.competition_id
    AND s.season_id = o.season_id
    AND s.match_id = o.match_id;
