-- Additive visual contracts only. Do not replace Stage 4D or Overview views.
-- Windows use explicit ROWS frames. No synthetic shots or coordinate changes.
CREATE VIEW IF NOT EXISTS football.bi_match_xg_race
SQL SECURITY INVOKER
AS
SELECT
    s.competition_id AS competition_id,
    s.season_id AS season_id,
    s.match_id AS match_id,
    s.match_label AS match_label,
    s.match_date AS match_date,
    s.event_id AS event_id,
    s.event_index AS event_index,
    s.team_id AS team_id,
    s.team_name AS team_name,
    s.player_id AS player_id,
    s.player_name AS player_name,
    s.period AS period,
    s.minute AS minute,
    s.second AS second,
    s.statsbomb_xg AS statsbomb_xg,
    s.outcome_id AS outcome_id,
    s.outcome_name AS outcome_name,
    s.is_shootout AS is_shootout,
    s.is_extra_time AS is_extra_time,
    o.home_team_id AS home_team_id,
    o.home_team_name AS home_team_name,
    o.away_team_id AS away_team_id,
    o.away_team_name AS away_team_name,
    toUInt32(s.minute) * 60 + toUInt32(s.second) AS event_time_seconds,
    row_number() OVER (PARTITION BY s.competition_id, s.season_id, s.match_id ORDER BY s.period, s.minute, s.second, s.event_index) AS event_order,
    sum(s.statsbomb_xg) OVER team_progress AS team_cumulative_xg,
    sumIf(s.statsbomb_xg, s.team_id = o.home_team_id) OVER match_progress AS home_cumulative_xg,
    sumIf(s.statsbomb_xg, s.team_id = o.away_team_id) OVER match_progress AS away_cumulative_xg
FROM football.bi_match_shots AS s
INNER JOIN football.bi_match_overview AS o
    ON s.competition_id = o.competition_id
    AND s.season_id = o.season_id
    AND s.match_id = o.match_id
WHERE s.is_shootout = 0
WINDOW
    team_progress AS (PARTITION BY s.competition_id, s.season_id, s.match_id, s.team_id
        ORDER BY s.period, s.minute, s.second, s.event_index ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
    match_progress AS (PARTITION BY s.competition_id, s.season_id, s.match_id
        ORDER BY s.period, s.minute, s.second, s.event_index ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

CREATE VIEW IF NOT EXISTS football.bi_match_shot_map
SQL SECURITY INVOKER
AS
SELECT
    s.competition_id AS competition_id,
    s.season_id AS season_id,
    s.match_id AS match_id,
    s.match_label AS match_label,
    s.match_date AS match_date,
    s.event_id AS event_id,
    s.event_index AS event_index,
    s.team_id AS team_id,
    s.team_name AS team_name,
    s.player_id AS player_id,
    s.player_name AS player_name,
    s.period AS period,
    s.minute AS minute,
    s.second AS second,
    s.statsbomb_xg AS statsbomb_xg,
    s.outcome_id AS outcome_id,
    s.outcome_name AS outcome_name,
    s.is_shootout AS is_shootout,
    s.is_extra_time AS is_extra_time,
    s.start_x AS start_x,
    s.start_y AS start_y,
    s.end_x AS end_x,
    s.end_y AS end_y,
    s.end_z AS end_z,
    toBool(s.outcome_id = 97) AS is_goal
FROM football.bi_match_shots AS s
WHERE s.is_shootout = 0;

CREATE VIEW IF NOT EXISTS football.bi_match_shootout
SQL SECURITY INVOKER
AS
SELECT
    s.competition_id AS competition_id,
    s.season_id AS season_id,
    s.match_id AS match_id,
    s.match_label AS match_label,
    s.match_date AS match_date,
    s.event_id AS event_id,
    s.event_index AS event_index,
    s.team_id AS team_id,
    s.team_name AS team_name,
    s.player_id AS player_id,
    s.player_name AS player_name,
    s.period AS period,
    s.minute AS minute,
    s.second AS second,
    s.statsbomb_xg AS statsbomb_xg,
    s.outcome_id AS outcome_id,
    s.outcome_name AS outcome_name,
    s.is_shootout AS is_shootout,
    s.is_extra_time AS is_extra_time,
    o.home_team_id AS home_team_id,
    o.home_team_name AS home_team_name,
    o.away_team_id AS away_team_id,
    o.away_team_name AS away_team_name,
    row_number() OVER (PARTITION BY s.competition_id, s.season_id, s.match_id ORDER BY s.event_index) AS shootout_order,
    row_number() OVER (PARTITION BY s.competition_id, s.season_id, s.match_id, s.team_id ORDER BY s.event_index) AS team_attempt_number,
    toBool(s.outcome_id = 97) AS is_goal,
    countIf(s.outcome_id = 97 AND s.team_id = o.home_team_id) OVER shootout_progress AS home_shootout_goals_after,
    countIf(s.outcome_id = 97 AND s.team_id = o.away_team_id) OVER shootout_progress AS away_shootout_goals_after
FROM football.bi_match_shots AS s
INNER JOIN football.bi_match_overview AS o
    ON s.competition_id = o.competition_id
    AND s.season_id = o.season_id
    AND s.match_id = o.match_id
WHERE s.is_shootout = 1
WINDOW shootout_progress AS (PARTITION BY s.competition_id, s.season_id, s.match_id
    ORDER BY s.event_index ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);
