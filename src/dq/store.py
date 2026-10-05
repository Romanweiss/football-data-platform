"""Append-only completed executions in the existing platform PostgreSQL."""
from psycopg.types.json import Jsonb


def persist(connection, report):
    # No upsert/update: retries are separate UUID executions, not replacement PASSes.
    with connection.transaction(), connection.cursor() as cursor:
        airflow = report['airflow']
        cursor.execute('''INSERT INTO metadata.dq_executions
            (execution_id,contract_version,competition_id,season_id,suite,started_at,finished_at,
             status,airflow_dag_id,airflow_run_id,airflow_task_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            tuple(report[k] for k in ('execution_id','contract_version','competition_id','season_id',
                                     'suite','started_at','finished_at','status')) +
            tuple(airflow.get(k) for k in ('dag_id','run_id','task_id')))
        cursor.executemany('''INSERT INTO metadata.dq_results
            (execution_id,rule_id,checked_at,category,layer,dataset,build_id,status,severity,observed,expected,message)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            [(report['execution_id'], *(r[k] for k in ('rule_id','timestamp','category','layer','dataset',
              'build_id','status','severity')), Jsonb(r['observed']), Jsonb(r['expected']), r['message'])
             for r in report['results']])


def summary(connection, ctx, suite='full', *, build_id=None):
    """Latest exact scope compared with its previous successful execution (not latest PASS)."""
    with connection.cursor() as cursor:
        cursor.execute('''SELECT execution_id::text,status,finished_at FROM metadata.dq_executions e
            WHERE competition_id=%s AND season_id=%s AND suite=%s
              AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM metadata.dq_results r
                   WHERE r.execution_id=e.execution_id AND r.build_id=%s))
            ORDER BY finished_at DESC,execution_id DESC LIMIT 1''',
            (ctx['competition_id'], ctx['season_id'], suite, build_id, build_id))
        latest = cursor.fetchone()
        if latest is None:
            return dict(**ctx, suite=suite, status='SKIP', message='No completed execution', results=[])
        cursor.execute('''SELECT execution_id::text FROM metadata.dq_executions e
            WHERE competition_id=%s AND season_id=%s AND suite=%s AND status='PASS'
              AND (finished_at,execution_id)<(%s,%s::uuid)
              AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM metadata.dq_results r
                   WHERE r.execution_id=e.execution_id AND r.build_id=%s))
            ORDER BY finished_at DESC,execution_id DESC LIMIT 1''',
            (ctx['competition_id'], ctx['season_id'], suite, latest[2], latest[0], build_id, build_id))
        previous = cursor.fetchone()
        cursor.execute('''SELECT r.rule_id,r.layer,r.dataset,r.build_id,r.status,r.severity,
                    r.observed,r.expected,r.message,p.build_id,p.status,p.observed,p.expected
            FROM metadata.dq_results r LEFT JOIN metadata.dq_results p
                ON p.execution_id=%s::uuid AND p.rule_id=r.rule_id
            WHERE r.execution_id=%s::uuid ORDER BY r.layer,r.rule_id''',
            (previous[0] if previous else None, latest[0]))
        results = []
        for row in cursor.fetchall():
            value = dict(zip(('rule_id','layer','dataset','build_id','status','severity',
                              'observed','expected','message'), row[:9]))
            value['previous'] = dict(zip(('build_id','status','observed','expected'), row[9:])) if row[10] else None
            value['changed'] = previous is not None and (row[10] is None or
                (row[3], row[4], row[6], row[7]) != tuple(row[9:]))
            results.append(value)
        cursor.execute('''SELECT rule_id FROM metadata.dq_results WHERE execution_id=%s::uuid
            AND rule_id NOT IN (SELECT rule_id FROM metadata.dq_results WHERE execution_id=%s::uuid)
            ORDER BY rule_id''', (previous[0] if previous else None, latest[0]))
        removed = [row[0] for row in cursor.fetchall()]
        from src.dq.model import STATUSES, state
        return dict(**ctx, suite=suite, build_id_filter=build_id, execution_id=latest[0], status=latest[1],
                    finished_at=latest[2].isoformat(), previous_success=previous[0] if previous else None,
                    counts={s: sum(r['status'] == s for r in results) for s in STATUSES},
                    layers={layer:state([r for r in results if r['layer']==layer])
                            for layer in sorted({r['layer'] for r in results})},
                    added_rules=[r['rule_id'] for r in results if previous and r['previous'] is None],
                    removed_rules=removed, results=results)
