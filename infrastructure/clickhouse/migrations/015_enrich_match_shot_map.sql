-- Preserve the applied 013 projection and append one display-only label.
CREATE OR REPLACE VIEW football.bi_match_shot_map
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
    toBool(s.outcome_id = 97) AS is_goal,
    concat(ifNull(s.player_name, 'Unknown player'), ' | ',
        toString(s.minute), ':', leftPad(toString(s.second), 2, '0'), ' | ',
        ifNull(s.outcome_name, 'Unknown outcome'), ' | #', toString(s.event_index)) AS shot_label
FROM football.bi_match_shots AS s
WHERE s.is_shootout = 0;
