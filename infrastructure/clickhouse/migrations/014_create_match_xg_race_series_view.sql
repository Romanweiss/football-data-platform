-- Long-form presentation only. Existing cumulative values are not recomputed.
CREATE VIEW IF NOT EXISTS football.bi_match_xg_race_series
SQL SECURITY INVOKER
AS
SELECT
    competition_id,
    season_id,
    match_id,
    match_label,
    event_order,
    event_id,
    event_index,
    period,
    minute,
    second,
    home_team_id AS team_id,
    home_team_name AS team_name,
    toUInt8(1) AS is_home,
    home_cumulative_xg AS cumulative_xg
FROM football.bi_match_xg_race
UNION ALL
SELECT
    competition_id,
    season_id,
    match_id,
    match_label,
    event_order,
    event_id,
    event_index,
    period,
    minute,
    second,
    away_team_id AS team_id,
    away_team_name AS team_name,
    toUInt8(0) AS is_home,
    away_cumulative_xg AS cumulative_xg
FROM football.bi_match_xg_race;
