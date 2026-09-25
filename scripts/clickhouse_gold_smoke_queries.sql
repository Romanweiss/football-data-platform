-- Read-only Gold analytics after check_clickhouse_gold_model.py passes.
-- One materialized Gold build per dataset/context is a precondition.
-- Names may vary by match. Group totals by source identity and use min(name)
-- only as a deterministic display label, never as cross-source entity resolution.

SELECT team_id, min(team_name) AS team_name, sum(pass_attempts) AS passes,
       sum(shot_count) AS shots, sum(shot_xg) AS xg, sum(shot_goals) AS shot_goals
FROM football.team_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY team_id ORDER BY xg DESC, team_id;

SELECT match_id, team_id, team_name, shot_count, shot_xg, shot_goals
FROM football.team_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
ORDER BY match_id, team_id;

SELECT player_id, min(player_name) AS player_name, sum(event_count) AS events,
       sum(pass_attempts) AS passes, sum(shot_count) AS shots, sum(shot_xg) AS xg, sum(shot_goals) AS shot_goals
FROM football.player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY player_id ORDER BY events DESC, player_id;

SELECT player_id, min(player_name) AS player_name, sum(shot_xg) AS xg, sum(shot_count) AS shots
FROM football.player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY player_id ORDER BY xg DESC, player_id LIMIT 20;

SELECT player_id, min(player_name) AS player_name, sum(shot_count) AS shots, sum(shot_xg) AS xg
FROM football.player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY player_id ORDER BY shots DESC, player_id LIMIT 20;

SELECT team_id, min(team_name) AS team_name, count() AS matches, avg(shot_xg) AS average_xg_per_match
FROM football.team_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY team_id ORDER BY average_xg_per_match DESC, team_id;

SELECT match_id, team_id, team_name, player_id, player_name
FROM football.player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32} AND event_count = 0
ORDER BY match_id, team_id, player_id;

SELECT player_id, min(player_name) AS player_name, sum(under_pressure_events) AS under_pressure_events,
       sum(counterpress_events) AS counterpress_events
FROM football.player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY player_id ORDER BY under_pressure_events DESC, counterpress_events DESC, player_id LIMIT 20;
