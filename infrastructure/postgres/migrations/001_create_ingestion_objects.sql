BEGIN;

CREATE TABLE IF NOT EXISTS metadata.ingestion_objects (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    source_url TEXT NOT NULL,
    s3_bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ingestion_objects_sha256_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ingestion_objects_size_bytes_check CHECK (size_bytes >= 0),
    CONSTRAINT ingestion_objects_bucket_key_unique UNIQUE (s3_bucket, object_key)
);

CREATE INDEX IF NOT EXISTS ingestion_objects_source_dataset_idx
    ON metadata.ingestion_objects (source, dataset);

COMMIT;
