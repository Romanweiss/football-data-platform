CREATE TABLE IF NOT EXISTS football.team_match_stats
(
    competition_id UInt32,
    season_id UInt32,
    match_id UInt64,
    team_id UInt32,
    team_name LowCardinality(String),
    event_count UInt64,
    pass_attempts UInt64,
    shot_count UInt64,
    shot_xg Float64,
    shot_goals UInt64,
    under_pressure_events UInt64,
    counterpress_events UInt64,
    players_with_events UInt64,
    gold_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_id, team_id)
SETTINGS non_replicated_deduplication_window = 1000;

CREATE TABLE IF NOT EXISTS football.player_match_stats
(
    competition_id UInt32,
    season_id UInt32,
    match_id UInt64,
    team_id UInt32,
    team_name LowCardinality(String),
    player_id UInt32,
    player_name String,
    event_count UInt64,
    pass_attempts UInt64,
    shot_count UInt64,
    shot_xg Float64,
    shot_goals UInt64,
    under_pressure_events UInt64,
    counterpress_events UInt64,
    gold_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_id, team_id, player_id)
SETTINGS non_replicated_deduplication_window = 1000;
