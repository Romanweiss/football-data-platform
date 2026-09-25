CREATE TABLE IF NOT EXISTS football.matches
(
    competition_id UInt32,
    season_id UInt32,
    match_id UInt64,
    match_date Date,
    kick_off String,
    match_week Nullable(UInt16),
    competition_stage_id UInt16,
    competition_stage_name LowCardinality(String),
    home_team_id UInt32,
    home_team_name LowCardinality(String),
    away_team_id UInt32,
    away_team_name LowCardinality(String),
    home_score UInt16,
    away_score UInt16,
    stadium_id Nullable(UInt32),
    stadium_name Nullable(String),
    referee_id Nullable(UInt32),
    referee_name Nullable(String),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_date, match_id)
SETTINGS non_replicated_deduplication_window = 1000;
