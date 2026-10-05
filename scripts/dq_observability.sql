-- Grafana 7B contract: SELECT-only on platform metadata, not Airflow internals.
-- Provision a dedicated read-only role in 7B; never use the platform writer role.

-- Latest completed scope INCLUDING failures; partial scopes are not full-platform PASS.
SELECT e.competition_id, e.season_id, e.suite, e.execution_id, e.finished_at,
       e.status, r.layer,
       count(*) FILTER (WHERE r.status='PASS') AS passed,
       count(*) FILTER (WHERE r.status='FAIL') AS failed,
       count(*) FILTER (WHERE r.status='WARN') AS warnings,
       count(*) FILTER (WHERE r.status='SKIP') AS skipped
FROM metadata.dq_latest_executions e
JOIN metadata.dq_results r USING (execution_id)
GROUP BY e.competition_id,e.season_id,e.suite,e.execution_id,e.finished_at,e.status,r.layer
ORDER BY e.competition_id,e.season_id,e.suite,r.layer;

-- Numeric observations over time, with exact rule/context/build identity.
SELECT e.competition_id,e.season_id,e.suite,r.rule_id,r.build_id,r.checked_at,
       (r.observed #>> '{}')::numeric AS observed
FROM metadata.dq_executions e JOIN metadata.dq_results r USING (execution_id)
WHERE jsonb_typeof(r.observed)='number'
ORDER BY r.checked_at DESC LIMIT 1000;

-- Failures remain visible even after a later PASS; no deletion/repair actions.
SELECT e.competition_id,e.season_id,e.execution_id,e.suite,e.airflow_dag_id,
       e.airflow_run_id,e.airflow_task_id,r.rule_id,r.build_id,r.checked_at,r.message
FROM metadata.dq_executions e JOIN metadata.dq_results r USING (execution_id)
WHERE r.status='FAIL'
ORDER BY r.checked_at DESC LIMIT 100;

-- Successful build/load timestamps are evidence, not a daily freshness SLA.
SELECT 'silver' AS layer,dataset,competition_id,season_id,build_id,created_at AS built_at
FROM metadata.silver_builds
UNION ALL
SELECT 'gold',dataset,competition_id,season_id,build_id,created_at
FROM metadata.gold_builds;
