-- Read-only checks, after Stage 3E/3D model checks. Every failure raises an error.
-- Supply competition_id and season_id as ClickHouse query parameters.
SELECT 'team_row_count' AS check_name,
    (SELECT count() FROM football.bi_team_match_stats WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}) AS actual,
    (SELECT count() FROM football.team_match_stats WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}) AS expected,
    throwIf(actual != expected OR expected = 0, 'BI team row count mismatch or empty source') AS assertion;

SELECT 'player_row_count' AS check_name,
    (SELECT count() FROM football.bi_player_match_stats WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}) AS actual,
    (SELECT count() FROM football.player_match_stats WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32}) AS expected,
    throwIf(actual != expected OR expected = 0, 'BI player row count mismatch or empty source') AS assertion;

SELECT 'team_grain' AS check_name, count() AS rows, uniqExact(tuple(match_id, team_id)) AS identities,
    throwIf(rows != identities, 'BI duplicate team grain') AS assertion
FROM football.bi_team_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32};

SELECT 'player_grain' AS check_name, count() AS rows, uniqExact(tuple(match_id, team_id, player_id)) AS identities,
    throwIf(rows != identities, 'BI duplicate player grain') AS assertion
FROM football.bi_player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32};

SELECT 'team_derived_fields' AS check_name,
    countIf(isNull(opponent_team_id) OR isNull(opponent_team_name) OR team_id = opponent_team_id
        OR (team_id != home_team_id AND team_id != away_team_id)
        OR goals_for < 0 OR goals_against < 0 OR match_result NOT IN ('W', 'D', 'L')
        OR goal_difference != toInt32(goals_for) - toInt32(goals_against)) AS invalid_rows,
    throwIf(invalid_rows != 0, 'BI invalid team derived fields') AS assertion
FROM football.bi_team_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32};

SELECT 'official_match_score' AS check_name,
    countIf(v.goals_for != if(v.team_id = m.home_team_id, m.home_score, m.away_score)
        OR v.goals_against != if(v.team_id = m.home_team_id, m.away_score, m.home_score)
        OR v.is_home != (v.team_id = m.home_team_id)
        OR v.opponent_team_id != if(v.team_id = m.home_team_id, m.away_team_id, m.home_team_id)
        OR v.opponent_team_name != if(v.team_id = m.home_team_id, m.away_team_name, m.home_team_name)
        OR v.match_result != multiIf(
            if(v.team_id = m.home_team_id, m.home_score, m.away_score) > if(v.team_id = m.home_team_id, m.away_score, m.home_score), 'W',
            if(v.team_id = m.home_team_id, m.home_score, m.away_score) < if(v.team_id = m.home_team_id, m.away_score, m.home_score), 'L', 'D')) AS invalid_rows,
    throwIf(invalid_rows != 0, 'BI goals/result differ from official match score') AS assertion
FROM football.bi_team_match_stats AS v
INNER JOIN football.matches AS m
    ON v.competition_id = m.competition_id AND v.season_id = m.season_id AND v.match_id = m.match_id
WHERE v.competition_id = {competition_id:UInt32} AND v.season_id = {season_id:UInt32};

SELECT 'player_opponent' AS check_name,
    countIf(isNull(opponent_team_id) OR isNull(opponent_team_name) OR team_id = opponent_team_id
        OR (team_id != home_team_id AND team_id != away_team_id)
        OR is_home != (team_id = home_team_id)
        OR opponent_team_id != if(is_home, away_team_id, home_team_id)
        OR opponent_team_name != if(is_home, away_team_name, home_team_name)) AS invalid_rows,
    throwIf(invalid_rows != 0, 'BI invalid player opponent') AS assertion
FROM football.bi_player_match_stats
WHERE competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32};
