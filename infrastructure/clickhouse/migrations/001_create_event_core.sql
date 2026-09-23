-- Apply manually; existing init SQL and volumes are not modified.
CREATE TABLE IF NOT EXISTS football.event_core
(
    competition_id UInt32,
    season_id UInt32,
    match_id UInt64,
    event_id UUID,
    event_index UInt32,
    period UInt8,
    timestamp String,
    minute UInt16,
    second UInt8,
    type_id UInt16,
    type_name LowCardinality(String),
    possession UInt16,
    possession_team_id Nullable(UInt32),
    possession_team_name Nullable(String),
    play_pattern_id Nullable(UInt16),
    play_pattern_name Nullable(String),
    team_id UInt32,
    team_name LowCardinality(String),
    player_id Nullable(UInt32),
    player_name Nullable(String),
    position_id Nullable(UInt16),
    position_name Nullable(String),
    location_x Nullable(Float32),
    location_y Nullable(Float32),
    duration Nullable(Float32),
    under_pressure Nullable(Bool),
    counterpress Nullable(Bool),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_id, period, event_index, event_id)
SETTINGS non_replicated_deduplication_window = 1000;
