-- Read-only: apply 007/load first. Never touches S3. Bind competition_id and season_id explicitly.
SELECT 'coverage' AS check_name,
    (SELECT count() FROM football.matches WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s) AS expected,
    (SELECT count() FROM football.match_results WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s) AS actual,
    (SELECT uniqExact(match_id) FROM football.match_results WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s) AS identities,
    throwIf(expected=0 OR actual!=expected OR identities!=actual, 'Match results coverage/grain mismatch') AS assertion;

SELECT 'source_values' AS check_name, count() AS joined,
    countIf(r.match_date!=m.match_date OR r.kick_off!=m.kick_off
        OR r.competition_stage_id!=m.competition_stage_id OR r.competition_stage_name!=m.competition_stage_name
        OR r.home_team_id!=m.home_team_id OR r.away_team_id!=m.away_team_id
        OR r.home_team_name!=m.home_team_name OR r.away_team_name!=m.away_team_name
        OR r.home_score!=m.home_score OR r.away_score!=m.away_score) AS invalid,
    throwIf(invalid!=0 OR joined!=(SELECT count() FROM football.match_results WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s),
        'Match results differ from source matches') AS assertion
FROM football.match_results r INNER JOIN football.matches m USING (competition_id,season_id,match_id)
WHERE r.competition_id=%(competition_id)s AND r.season_id=%(season_id)s;

SELECT 'extra_time' AS check_name, countIf(r.went_to_extra_time!=e.extra_time) AS invalid,
    throwIf(invalid!=0, 'Extra-time evidence mismatch') AS assertion
FROM football.match_results r LEFT JOIN
    (SELECT competition_id,season_id,match_id,countIf(period IN (3,4))>0 AS extra_time
     FROM football.event_core GROUP BY competition_id,season_id,match_id) e USING (competition_id,season_id,match_id)
WHERE r.competition_id=%(competition_id)s AND r.season_id=%(season_id)s;

SELECT 'shootout_counts' AS check_name,
    countIf(r.home_shootout_attempts!=s.home_attempts OR r.away_shootout_attempts!=s.away_attempts
        OR r.home_shootout_goals!=s.home_goals OR r.away_shootout_goals!=s.away_goals
        OR r.went_to_penalties!=(s.home_attempts+s.away_attempts>0)) AS invalid,
    throwIf(invalid!=0, 'Shootout counts differ from exact event-key join') AS assertion
FROM football.match_results r LEFT JOIN (
    SELECT m.competition_id AS competition_id,m.season_id AS season_id,m.match_id AS match_id,
        countIf(e.period=5 AND s.team_id=m.home_team_id) AS home_attempts,
        countIf(e.period=5 AND s.team_id=m.away_team_id) AS away_attempts,
        countIf(e.period=5 AND s.team_id=m.home_team_id AND s.outcome_id=97) AS home_goals,
        countIf(e.period=5 AND s.team_id=m.away_team_id AND s.outcome_id=97) AS away_goals
    FROM football.matches m INNER JOIN football.event_core e USING (competition_id,season_id,match_id)
    INNER JOIN football.shot_events s USING (competition_id,season_id,match_id,event_id)
    GROUP BY m.competition_id,m.season_id,m.match_id
) s USING (competition_id,season_id,match_id)
WHERE r.competition_id=%(competition_id)s AND r.season_id=%(season_id)s;
