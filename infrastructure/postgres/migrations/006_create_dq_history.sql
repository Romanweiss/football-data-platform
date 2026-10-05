BEGIN;

CREATE TABLE IF NOT EXISTS metadata.dq_executions (
    execution_id UUID PRIMARY KEY,
    contract_version INTEGER NOT NULL CHECK (contract_version = 1),
    competition_id BIGINT NOT NULL CHECK (competition_id BETWEEN 1 AND 4294967295),
    season_id BIGINT NOT NULL CHECK (season_id BETWEEN 1 AND 4294967295),
    suite TEXT NOT NULL CHECK (suite ~ '^[a-z][a-z0-9_.]{0,119}$'),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL CHECK (finished_at >= started_at),
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'WARN', 'SKIP')),
    airflow_dag_id VARCHAR(250),
    airflow_run_id VARCHAR(250),
    airflow_task_id VARCHAR(250),
    CHECK ((airflow_dag_id IS NULL AND airflow_run_id IS NULL AND airflow_task_id IS NULL)
        OR (airflow_dag_id IS NOT NULL AND airflow_run_id IS NOT NULL AND airflow_task_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS metadata.dq_results (
    execution_id UUID NOT NULL REFERENCES metadata.dq_executions(execution_id),
    rule_id TEXT NOT NULL CHECK (rule_id ~ '^[a-z][a-z0-9_.]{2,159}$'),
    checked_at TIMESTAMPTZ NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('source_integrity', 'structural', 'referential',
        'semantic', 'reconciliation', 'regression', 'operational')),
    layer TEXT NOT NULL CHECK (layer IN ('bronze', 'silver', 'gold', 'serving', 'api', 'operational')),
    dataset TEXT NOT NULL CHECK (dataset ~ '^[a-z][a-z0-9_]{0,63}$'),
    build_id CHAR(64) CHECK (build_id ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'WARN', 'SKIP')),
    severity TEXT NOT NULL CHECK (severity IN ('ERROR', 'WARNING', 'INFO')),
    observed JSONB,
    expected JSONB,
    message VARCHAR(300) NOT NULL,
    PRIMARY KEY (execution_id, rule_id),
    CHECK (status <> 'FAIL' OR severity = 'ERROR'),
    CHECK (status <> 'WARN' OR severity IN ('WARNING', 'INFO')),
    CHECK (observed IS NULL OR jsonb_typeof(observed) IN ('number', 'boolean', 'null')),
    CHECK (expected IS NULL OR jsonb_typeof(expected) IN ('number', 'boolean', 'null'))
);

CREATE INDEX IF NOT EXISTS dq_executions_context_suite_time_idx
    ON metadata.dq_executions (competition_id, season_id, suite, finished_at DESC, execution_id);
CREATE INDEX IF NOT EXISTS dq_results_build_rule_idx ON metadata.dq_results (build_id, rule_id);

-- Read-only monitoring source: latest execution of each exact scope, including FAIL.
-- A successful unrelated scope must never mask a failed scope or overwrite history.
CREATE OR REPLACE VIEW metadata.dq_latest_executions AS
SELECT DISTINCT ON (competition_id, season_id, suite) *
FROM metadata.dq_executions
ORDER BY competition_id, season_id, suite, finished_at DESC, execution_id DESC;

COMMIT;
