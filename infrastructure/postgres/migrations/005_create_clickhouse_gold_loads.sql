BEGIN;

CREATE SCHEMA IF NOT EXISTS metadata;

CREATE TABLE IF NOT EXISTS metadata.clickhouse_gold_loads (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    competition_id BIGINT NOT NULL,
    season_id BIGINT NOT NULL,
    gold_build_id CHAR(64) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    schema_sha256 CHAR(64) NOT NULL,
    s3_bucket TEXT NOT NULL,
    s3_prefix TEXT NOT NULL,
    clickhouse_database TEXT NOT NULL,
    clickhouse_table TEXT NOT NULL,
    row_count BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT clickhouse_gold_loads_build_check CHECK (gold_build_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT clickhouse_gold_loads_input_check CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT clickhouse_gold_loads_schema_check CHECK (schema_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT clickhouse_gold_loads_rows_check CHECK (row_count > 0),
    CONSTRAINT clickhouse_gold_loads_identity_unique UNIQUE (clickhouse_database, clickhouse_table, gold_build_id)
);

CREATE INDEX IF NOT EXISTS clickhouse_gold_loads_source_dataset_context_idx
    ON metadata.clickhouse_gold_loads (source, dataset, competition_id, season_id);

COMMIT;
