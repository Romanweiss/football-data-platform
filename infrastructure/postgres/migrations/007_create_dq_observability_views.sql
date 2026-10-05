BEGIN;

CREATE SCHEMA IF NOT EXISTS observability;
REVOKE ALL ON SCHEMA observability FROM PUBLIC;

-- Views expose results, not new rules. Owner-mediated reads deliberately avoid
-- granting Grafana access to the underlying writer tables.
CREATE OR REPLACE VIEW observability.dq_execution_history AS
SELECT e.execution_id, e.competition_id, e.season_id, e.suite,
       e.started_at, e.finished_at, e.status,
       e.airflow_dag_id, e.airflow_run_id, e.airflow_task_id,
       count(r.rule_id) AS total_checks,
       count(r.rule_id) FILTER (WHERE r.status = 'PASS') AS passed,
       count(r.rule_id) FILTER (WHERE r.status = 'FAIL') AS failed,
       count(r.rule_id) FILTER (WHERE r.status = 'WARN') AS warnings,
       count(r.rule_id) FILTER (WHERE r.status = 'SKIP') AS skipped
FROM metadata.dq_executions e
LEFT JOIN metadata.dq_results r USING (execution_id)
GROUP BY e.execution_id;

-- Latest FULL scope, including failures. A later partial API PASS cannot mask it.
CREATE OR REPLACE VIEW observability.dq_current_executions AS
SELECT h.* FROM metadata.dq_latest_executions e
JOIN observability.dq_execution_history h USING (execution_id)
WHERE e.suite = 'full';

CREATE OR REPLACE VIEW observability.dq_rule_history AS
SELECT e.competition_id, e.season_id, e.suite, e.finished_at,
       r.execution_id, r.rule_id, r.checked_at, r.category, r.layer, r.dataset,
       r.build_id, r.status, r.severity, r.observed, r.expected, r.message,
       CASE WHEN jsonb_typeof(r.observed) = 'number'
            THEN (r.observed #>> '{}')::numeric END AS numeric_observed
FROM metadata.dq_executions e JOIN metadata.dq_results r USING (execution_id);

CREATE OR REPLACE VIEW observability.dq_current_results AS
SELECT r.* FROM observability.dq_current_executions e
JOIN observability.dq_rule_history r USING (execution_id);

COMMIT;
