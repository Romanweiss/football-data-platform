BEGIN;

CREATE SCHEMA IF NOT EXISTS metadata;

CREATE TABLE IF NOT EXISTS metadata.gold_builds (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    competition_id BIGINT NOT NULL,
    season_id BIGINT NOT NULL,
    transform_version TEXT NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    schema_sha256 CHAR(64) NOT NULL,
    build_id CHAR(64) NOT NULL,
    s3_bucket TEXT NOT NULL,
    s3_prefix TEXT NOT NULL,
    row_count BIGINT NOT NULL,
    file_count BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gold_builds_input_fingerprint_check CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT gold_builds_schema_sha256_check CHECK (schema_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT gold_builds_build_id_check CHECK (build_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT gold_builds_row_count_check CHECK (row_count > 0),
    CONSTRAINT gold_builds_file_count_check CHECK (file_count > 0),
    CONSTRAINT gold_builds_identity_unique UNIQUE (dataset, competition_id, season_id, build_id),
    CONSTRAINT gold_builds_location_unique UNIQUE (s3_bucket, s3_prefix)
);

CREATE INDEX IF NOT EXISTS gold_builds_source_dataset_context_idx
    ON metadata.gold_builds (source, dataset, competition_id, season_id);

COMMIT;
