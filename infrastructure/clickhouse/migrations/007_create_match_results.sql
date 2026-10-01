CREATE TABLE IF NOT EXISTS football.match_results
(
    competition_id UInt32,
    season_id UInt32,
    match_id UInt64,
    match_date Date,
    kick_off String,
    competition_stage_id UInt16,
    competition_stage_name LowCardinality(String),
    home_team_id UInt32,
    home_team_name LowCardinality(String),
    away_team_id UInt32,
    away_team_name LowCardinality(String),
    home_score UInt16,
    away_score UInt16,
    went_to_extra_time Bool,
    went_to_penalties Bool,
    home_shootout_attempts UInt64,
    away_shootout_attempts UInt64,
    home_shootout_goals UInt64,
    away_shootout_goals UInt64,
    winner_team_id Nullable(UInt32),
    winner_team_name Nullable(String),
    result_method LowCardinality(String),
    display_score String,
    gold_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_date, match_id)
SETTINGS non_replicated_deduplication_window = 1000;
