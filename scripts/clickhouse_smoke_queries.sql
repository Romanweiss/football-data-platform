-- Read-only analytics. Pin one build to avoid summing different snapshots.
-- Run with clickhouse-client --param_build_id=<verified 64hex build ID> --multiquery.
SELECT count() AS total_events
FROM football.event_core WHERE silver_build_id = {build_id:String};

SELECT match_id, count() AS events
FROM football.event_core WHERE silver_build_id = {build_id:String}
GROUP BY match_id ORDER BY events DESC, match_id LIMIT 10;

SELECT type_name, count() AS events
FROM football.event_core WHERE silver_build_id = {build_id:String}
GROUP BY type_name ORDER BY events DESC, type_name;

SELECT team_name, count() AS events
FROM football.event_core WHERE silver_build_id = {build_id:String}
GROUP BY team_name ORDER BY events DESC, team_name;

SELECT match_id, event_id, period, event_index, type_name, team_name, player_name
FROM football.event_core
WHERE silver_build_id = {build_id:String}
  AND match_id = (
      SELECT min(match_id) FROM football.event_core WHERE silver_build_id = {build_id:String}
  )
ORDER BY period, event_index, event_id LIMIT 30;
