BEGIN;

-- Rule observation watermark: late/replayed executions must not reopen old issues.
CREATE TABLE IF NOT EXISTS metadata.alert_rule_state (
    dedup_key CHAR(64) PRIMARY KEY CHECK (dedup_key ~ '^[0-9a-f]{64}$'),
    observed_at TIMESTAMPTZ NOT NULL,
    observation_id UUID NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS','FAIL','WARN','SKIP'))
);

-- Each row is one incident episode; resolved episodes remain historical.
CREATE TABLE IF NOT EXISTS metadata.alerts (
    alert_id UUID PRIMARY KEY,
    dedup_key CHAR(64) NOT NULL CHECK (dedup_key ~ '^[0-9a-f]{64}$'),
    alert_class TEXT NOT NULL CHECK (alert_class IN
        ('DATA_QUALITY_FAILURE','PIPELINE_FAILURE','SOURCE_ACCESS_FAILURE','SERVING_FAILURE')),
    competition_id BIGINT CHECK (competition_id BETWEEN 1 AND 4294967295),
    season_id BIGINT CHECK (season_id BETWEEN 1 AND 4294967295),
    scope TEXT NOT NULL,
    layer TEXT NOT NULL,
    dataset TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    build_id CHAR(64) CHECK (build_id ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('OPEN','RESOLVED')),
    created_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    dq_execution_id UUID REFERENCES metadata.dq_executions(execution_id),
    CHECK ((competition_id IS NULL) = (season_id IS NULL)),
    CHECK ((status='OPEN' AND resolved_at IS NULL) OR (status='RESOLVED' AND resolved_at IS NOT NULL))
);
-- Additive on re-application too: first partial 7C may already have this table.
ALTER TABLE metadata.alerts ADD COLUMN IF NOT EXISTS airflow_dag_id VARCHAR(250);
ALTER TABLE metadata.alerts ADD COLUMN IF NOT EXISTS airflow_run_id VARCHAR(250);
ALTER TABLE metadata.alerts ADD COLUMN IF NOT EXISTS airflow_task_id VARCHAR(250);
CREATE UNIQUE INDEX IF NOT EXISTS alerts_one_open_issue_idx
    ON metadata.alerts(dedup_key) WHERE status='OPEN';
CREATE INDEX IF NOT EXISTS alerts_context_time_idx
    ON metadata.alerts(competition_id,season_id,created_at DESC);

-- Append-only delivery events. STARTED without a terminal event is ambiguous:
-- never automatically resend after a crash (operator review, not an alert storm).
CREATE TABLE IF NOT EXISTS metadata.alert_delivery_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id UUID NOT NULL REFERENCES metadata.alerts(alert_id),
    attempt_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    delivery_status TEXT NOT NULL CHECK (delivery_status IN ('STARTED','SENT','FAILED')),
    provider TEXT NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{0,31}$'),
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 0 AND 3),
    reason TEXT NOT NULL CHECK (reason IN ('delivery started','delivered','transient exhausted','provider rejected','invalid configuration')),
    UNIQUE(attempt_id,delivery_status)
);

CREATE TABLE IF NOT EXISTS metadata.source_discovery_runs (
    discovery_id UUID PRIMARY KEY,
    checked_at TIMESTAMPTZ NOT NULL,
    catalog_sha256 CHAR(64) NOT NULL CHECK (catalog_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS metadata.source_discovery_observations (
    discovery_id UUID NOT NULL REFERENCES metadata.source_discovery_runs(discovery_id),
    competition_id BIGINT NOT NULL CHECK (competition_id BETWEEN 1 AND 4294967295),
    season_id BIGINT NOT NULL CHECK (season_id BETWEEN 1 AND 4294967295),
    entry_sha256 CHAR(64) NOT NULL CHECK (entry_sha256 ~ '^[0-9a-f]{64}$'),
    matches_sha256 CHAR(64) CHECK (matches_sha256 ~ '^[0-9a-f]{64}$'),
    registered BOOLEAN NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('BASELINE','NEW','UNCHANGED','CHANGED','MISSING')),
    PRIMARY KEY(discovery_id,competition_id,season_id)
);

COMMIT;
