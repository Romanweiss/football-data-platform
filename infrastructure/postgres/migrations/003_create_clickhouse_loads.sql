BEGIN;

CREATE SCHEMA IF NOT EXISTS metadata;

CREATE TABLE IF NOT EXISTS metadata.clickhouse_loads (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    competition_id BIGINT NOT NULL,
    season_id BIGINT NOT NULL,
    silver_build_id CHAR(64) NOT NULL CHECK (silver_build_id ~ '^[0-9a-f]{64}$'),
    input_fingerprint CHAR(64) NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_sha256 CHAR(64) NOT NULL CHECK (schema_sha256 ~ '^[0-9a-f]{64}$'),
    s3_bucket TEXT NOT NULL,
    s3_prefix TEXT NOT NULL,
    clickhouse_database TEXT NOT NULL,
    clickhouse_table TEXT NOT NULL,
    row_count BIGINT NOT NULL CHECK (row_count > 0),
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (clickhouse_database, clickhouse_table, silver_build_id)
);

CREATE INDEX IF NOT EXISTS clickhouse_loads_source_dataset_context_idx
    ON metadata.clickhouse_loads (source, dataset, competition_id, season_id);

COMMIT;
