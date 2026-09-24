CREATE TABLE IF NOT EXISTS football.pass_events
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
    team_id UInt32,
    team_name LowCardinality(String),
    player_id Nullable(UInt32),
    player_name Nullable(String),
    start_x Nullable(Float64),
    start_y Nullable(Float64),
    recipient_id Nullable(UInt32),
    recipient_name Nullable(String),
    pass_length Nullable(Float64),
    pass_angle Nullable(Float64),
    end_x Nullable(Float64),
    end_y Nullable(Float64),
    height_id Nullable(UInt16),
    height_name Nullable(String),
    body_part_id Nullable(UInt16),
    body_part_name Nullable(String),
    pass_type_id Nullable(UInt16),
    pass_type_name Nullable(String),
    outcome_id Nullable(UInt16),
    outcome_name Nullable(String),
    technique_id Nullable(UInt16),
    technique_name Nullable(String),
    cross Nullable(Bool),
    cut_back Nullable(Bool),
    switch Nullable(Bool),
    shot_assist Nullable(Bool),
    goal_assist Nullable(Bool),
    aerial_won Nullable(Bool),
    through_ball Nullable(Bool),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_id, period, event_index, event_id)
SETTINGS non_replicated_deduplication_window = 1000;

CREATE TABLE IF NOT EXISTS football.shot_events
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
    team_id UInt32,
    team_name LowCardinality(String),
    player_id Nullable(UInt32),
    player_name Nullable(String),
    start_x Nullable(Float64),
    start_y Nullable(Float64),
    statsbomb_xg Float64,
    end_x Nullable(Float64),
    end_y Nullable(Float64),
    end_z Nullable(Float64),
    key_pass_id Nullable(UUID),
    body_part_id Nullable(UInt16),
    body_part_name Nullable(String),
    shot_type_id Nullable(UInt16),
    shot_type_name Nullable(String),
    technique_id Nullable(UInt16),
    technique_name Nullable(String),
    outcome_id UInt16,
    outcome_name Nullable(String),
    first_time Nullable(Bool),
    open_goal Nullable(Bool),
    one_on_one Nullable(Bool),
    aerial_won Nullable(Bool),
    deflected Nullable(Bool),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_id, period, event_index, event_id)
SETTINGS non_replicated_deduplication_window = 1000;

CREATE TABLE IF NOT EXISTS football.teams
(
    competition_id UInt32,
    season_id UInt32,
    team_id UInt32,
    team_name LowCardinality(String),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, team_id)
SETTINGS non_replicated_deduplication_window = 1000;

CREATE TABLE IF NOT EXISTS football.players
(
    competition_id UInt32,
    season_id UInt32,
    player_id UInt32,
    player_name String,
    player_nickname Nullable(String),
    country_id Nullable(UInt32),
    country_name LowCardinality(Nullable(String)),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, player_id)
SETTINGS non_replicated_deduplication_window = 1000;

CREATE TABLE IF NOT EXISTS football.match_squads
(
    competition_id UInt32,
    season_id UInt32,
    match_id UInt64,
    team_id UInt32,
    team_name LowCardinality(String),
    player_id UInt32,
    player_name String,
    player_nickname Nullable(String),
    jersey_number Nullable(UInt16),
    country_id Nullable(UInt32),
    country_name Nullable(String),
    silver_build_id FixedString(64),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY (competition_id, season_id)
ORDER BY (competition_id, season_id, match_id, team_id, player_id)
SETTINGS non_replicated_deduplication_window = 1000;
