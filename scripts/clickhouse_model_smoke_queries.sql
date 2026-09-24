-- Stage 3B read-only analytics, after check_clickhouse_model.py passes.
-- One materialized build per dataset/context is a precondition.
-- Parameters: competition_id UInt32, season_id UInt32.

SELECT team_id, team_name, count() AS passes
FROM football.pass_events
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY team_id, team_name ORDER BY passes DESC, team_id LIMIT 10;

-- Stage 2C README documents NULL outcome for a successful StatsBomb pass.
-- Source-specific interpretation, not a generic missing-value rule.
SELECT isNull(outcome_id) AS no_outcome_normally_complete, outcome_name, count() AS passes
FROM football.pass_events
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY no_outcome_normally_complete, outcome_name ORDER BY passes DESC;

SELECT team_id, team_name, count() AS shots
FROM football.shot_events
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY team_id, team_name ORDER BY shots DESC, team_id;

SELECT team_id, team_name, sum(statsbomb_xg) AS total_xg
FROM football.shot_events
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY team_id, team_name ORDER BY total_xg DESC, team_id;

SELECT player_id, player_name, count() AS shots, sum(statsbomb_xg) AS total_xg
FROM football.shot_events
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
GROUP BY player_id, player_name ORDER BY total_xg DESC, player_id;

SELECT match_id, team_id, team_name, player_id, player_name, jersey_number
FROM football.match_squads
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
ORDER BY match_id, team_id, player_id LIMIT 100;

SELECT s.player_id, p.player_name, count() AS shots, sum(s.statsbomb_xg) AS total_xg
FROM football.shot_events AS s LEFT JOIN football.players AS p
ON s.competition_id = p.competition_id AND s.season_id = p.season_id AND s.player_id = p.player_id
WHERE s.competition_id = {competition_id:UInt32} AND s.season_id = {season_id:UInt32}
GROUP BY s.player_id, p.player_name ORDER BY total_xg DESC, s.player_id
SETTINGS join_use_nulls = 1;

SELECT s.player_id, p.player_name, count() AS passes
FROM football.pass_events AS s LEFT JOIN football.players AS p
ON s.competition_id = p.competition_id AND s.season_id = p.season_id AND s.player_id = p.player_id
WHERE s.competition_id = {competition_id:UInt32} AND s.season_id = {season_id:UInt32}
GROUP BY s.player_id, p.player_name ORDER BY passes DESC, s.player_id
SETTINGS join_use_nulls = 1;

SELECT e.team_id, t.team_name, count() AS events
FROM football.event_core AS e LEFT JOIN football.teams AS t
ON e.competition_id = t.competition_id AND e.season_id = t.season_id AND e.team_id = t.team_id
WHERE e.competition_id = {competition_id:UInt32} AND e.season_id = {season_id:UInt32}
GROUP BY e.team_id, t.team_name ORDER BY events DESC, e.team_id
SETTINGS join_use_nulls = 1;

SELECT match_id, event_id, period, event_index, type_name, team_name, player_name
FROM football.event_core
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
  AND match_id = (
      SELECT min(match_id) FROM football.event_core
      WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}
  )
ORDER BY period, event_index, event_id LIMIT 30;
