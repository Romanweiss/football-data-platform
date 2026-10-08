"""Lightweight scheduled read-only checks; no ingestion, Spark or publication."""
import hashlib
import os

from src.orchestration.commands import GOLD, SILVER, context


def registered_contexts(connection, *, exclusions=None):
    """Fully load-registered StatsBomb contexts, not hardcoded API/catalog guesses."""
    excluded = set()
    for pair in (os.environ.get('PLATFORM_DQ_EXCLUDED_CONTEXTS','') if exclusions is None else exclusions).split(','):
        if pair.strip():
            parts = pair.strip().split('/')
            if len(parts) != 2 or any(not p.isdigit() for p in parts):
                raise ValueError('Invalid explicit DQ context exclusion')
            c = context(dict(zip(('competition_id','season_id'),map(int,parts))))
            excluded.add(tuple(c.values()))
    with connection.transaction(), connection.cursor() as cur:
        cur.execute('''WITH complete AS (SELECT competition_id,season_id FROM (
            SELECT competition_id,season_id,'silver/'||dataset AS dataset FROM metadata.clickhouse_loads
              WHERE source='statsbomb' AND dataset=ANY(%s)
            UNION ALL
            SELECT competition_id,season_id,'gold/'||dataset FROM metadata.clickhouse_gold_loads
              WHERE source='statsbomb' AND dataset=ANY(%s)
            ) registered GROUP BY competition_id,season_id
            HAVING count(DISTINCT dataset)=%s), known AS (
            SELECT DISTINCT e.competition_id,e.season_id FROM metadata.dq_executions e
            WHERE e.suite='full' AND EXISTS(SELECT 1 FROM metadata.silver_builds b
              WHERE b.source='statsbomb' AND b.competition_id=e.competition_id AND b.season_id=e.season_id)
            ) SELECT * FROM complete UNION SELECT * FROM known ORDER BY competition_id,season_id''',
                    (list(SILVER),list(GOLD),len(SILVER)+len(GOLD)))
        rows = cur.fetchall()
    if len(rows) > 100:
        raise ValueError('Context validation budget exceeded; explicit review required')
    return [context(dict(zip(('competition_id','season_id'),row))) for row in rows if tuple(row) not in excluded]


def scheduled_dq(ctx, airflow=None):
    from src.common.postgres import create_postgres_connection
    from src.dq.cli import execute, exit_code
    from src.dq.model import state
    from src.dq.orchestration import DQGateError
    ctx = context(ctx)
    with create_postgres_connection() as lease:
        with lease.transaction(), lease.cursor() as cur:
            key = int(hashlib.sha256(f"dq:{ctx['competition_id']}/{ctx['season_id']}".encode()).hexdigest()[:15],16)
            cur.execute('SELECT pg_try_advisory_lock(%s)', (key,))
            if not cur.fetchone()[0]:
                return {**ctx,'status':'BUSY','dq_persisted':False}
            # Existing cooperating loaders take this exact lock. Skip, never
            # compete with a serving write or pretend BUSY is a DQ execution.
            cur.execute('SELECT pg_try_advisory_lock(%s)', (0x466F6F7443483341,))
            if not cur.fetchone()[0]:
                return {**ctx,'status':'BUSY','dq_persisted':False}
        reports = [execute(ctx,suite=suite,airflow=airflow) for suite in ('references','gold','api')]
    summary = dict(**ctx,status='CHECKED',dq_status=state(reports),
                   dq_execution_ids=[r['execution_id'] for r in reports],
                   dq_counts={s:sum(r['counts'][s] for r in reports) for s in ('PASS','FAIL','WARN','SKIP')},
                   dq_persisted=all(r['persisted'] for r in reports))
    if any(exit_code(r) for r in reports):
        raise DQGateError(summary)
    return summary
