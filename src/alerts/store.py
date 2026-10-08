"""Transactional dedup/resolution and append-only delivery state."""
from datetime import datetime
import os
from uuid import uuid4

from psycopg.rows import dict_row

from src.alerts.policy import observations, notification
from src.alerts.transport import deliver, select_provider, InvalidProviderConfiguration, DELIVERY_BUDGET


def enabled():
    return os.environ.get('PLATFORM_ALERTS_ENABLED','false').lower() == 'true'


def apply(connection, observation):
    """Apply one observation; transaction belongs to caller. Stable lock handles first insert races."""
    key = observation['dedup_key']
    with connection.cursor() as cur:
        lock = int(key[:16],16)
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (lock if lock < 2**63 else lock-2**64,))
        cur.execute('SELECT observed_at,observation_id FROM metadata.alert_rule_state WHERE dedup_key=%s', (key,))
        previous = cur.fetchone()
        timestamp = datetime.fromisoformat(str(observation['observed_at']))
        if previous and (timestamp,str(observation['observation_id'])) <= (previous[0],str(previous[1])):
            return 'IGNORED'
        cur.execute('''INSERT INTO metadata.alert_rule_state(dedup_key,observed_at,observation_id,status)
            VALUES(%s,%s,%s,%s) ON CONFLICT(dedup_key) DO UPDATE SET
            observed_at=excluded.observed_at,observation_id=excluded.observation_id,status=excluded.status''',
            (key,timestamp,observation['observation_id'],observation['status']))
        cur.execute("SELECT alert_id FROM metadata.alerts WHERE dedup_key=%s AND status='OPEN'", (key,))
        active = cur.fetchone()
        if observation['status'] == 'FAIL' and observation['severity'] == 'ERROR':
            if active:
                cur.execute('UPDATE metadata.alerts SET last_seen_at=%s,dq_execution_id=%s WHERE alert_id=%s',
                            (timestamp,observation.get('dq_execution_id'),active[0]))
                return 'DEDUPLICATED'
            columns = ('dedup_key','alert_class','competition_id','season_id','scope','layer','dataset','rule_id','build_id')
            cur.execute('''INSERT INTO metadata.alerts(alert_id,dedup_key,alert_class,competition_id,season_id,
                scope,layer,dataset,rule_id,build_id,status,created_at,last_seen_at,dq_execution_id,
                airflow_dag_id,airflow_run_id,airflow_task_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',%s,%s,%s,%s,%s,%s)''',
                        (uuid4(), *(observation[c] for c in columns),timestamp,timestamp,observation.get('dq_execution_id'),
                         *(observation.get('airflow_'+k) for k in ('dag_id','run_id','task_id'))))
            return 'OPENED'
        if active and observation['status'] == 'PASS':
            cur.execute("UPDATE metadata.alerts SET status='RESOLVED',resolved_at=%s,last_seen_at=%s WHERE alert_id=%s",
                        (timestamp,timestamp,active[0]))
            return 'RESOLVED'
        # WARN, INFO and SKIP do not open, deliver, or falsely resolve an ERROR incident.
        return 'NO_ALERT'


def load_execution(connection, execution_id):
    with connection.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT * FROM metadata.dq_executions WHERE execution_id=%s', (execution_id,))
        report = cur.fetchone()
        if report is None:
            raise ValueError('No authoritative persisted DQ execution')
        report['execution_id'] = str(report['execution_id'])
        report['finished_at'] = report['finished_at'].isoformat()
        cur.execute('SELECT * FROM metadata.dq_results WHERE execution_id=%s ORDER BY rule_id', (execution_id,))
        report['results'] = cur.fetchall()
        return report


def evaluate(connection, execution_id, *, dry_run=False):
    with connection.transaction():
        report = load_execution(connection, execution_id)
        rows = list(observations(report))
        if dry_run:
            return {'dry_run':True,'eligible_failures':sum(r['status']=='FAIL' and r['severity']=='ERROR' for r in rows)}
        counts = {}
        for row in rows:
            action = apply(connection,row)
            counts[action] = counts.get(action,0)+1
        return counts


def dispatch(connection, *, provider='log', alert_id=None, dry_run=False):
    if dry_run:
        return {'dry_run':True,'deliveries':0}
    budget = DELIVERY_BUDGET.get()
    limit = 10 if budget is None else min(10,max(0,budget))
    # Caller supplies idle connection: state is committed before provider IO.
    with connection.transaction(), connection.cursor() as cur:
        cur.execute("SELECT alert_id FROM metadata.alerts a WHERE status='OPEN' "
                    "AND (%s::uuid IS NULL OR alert_id=%s::uuid) AND NOT EXISTS "
                    "(SELECT 1 FROM metadata.alert_delivery_events d WHERE d.alert_id=a.alert_id) "
                    "ORDER BY created_at,alert_id LIMIT %s", (alert_id,alert_id,limit))
        ids = [r[0] for r in cur.fetchall()]
    sent = failed = 0
    provider_label = 'log' if provider == 'log' else 'invalid'
    for id_ in ids:
        attempt = uuid4()
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT * FROM metadata.alerts WHERE alert_id=%s FOR UPDATE', (id_,))
            alert = cur.fetchone()
            cur.execute('SELECT 1 FROM metadata.alert_delivery_events WHERE alert_id=%s LIMIT 1', (id_,))
            if alert['status'] != 'OPEN' or cur.fetchone():
                continue
            airflow = {k:alert['airflow_'+k] for k in ('dag_id','run_id','task_id')} if alert['airflow_dag_id'] else None
            if alert['dq_execution_id']:
                cur.execute('SELECT airflow_dag_id,airflow_run_id,airflow_task_id FROM metadata.dq_executions WHERE execution_id=%s', (alert['dq_execution_id'],))
                link = cur.fetchone()
                if link['airflow_dag_id']:
                    airflow = dict(zip(('dag_id','run_id','task_id'),link.values()))
            message = notification(alert,airflow)
            cur.execute("INSERT INTO metadata.alert_delivery_events(alert_id,attempt_id,delivery_status,provider,attempts,reason) "
                        "VALUES(%s,%s,'STARTED',%s,0,'delivery started')", (id_,attempt,provider_label))
        if budget is not None:
            DELIVERY_BUDGET.set(DELIVERY_BUDGET.get()-1)
        try:
            transport = select_provider(provider)
        except InvalidProviderConfiguration:
            status, tries, reason = 'FAILED', 0, 'invalid configuration'
        else:
            status, tries, reason = deliver(transport,message)
        with connection.transaction(), connection.cursor() as cur:
            cur.execute('INSERT INTO metadata.alert_delivery_events(alert_id,attempt_id,delivery_status,provider,attempts,reason) '
                        'VALUES(%s,%s,%s,%s,%s,%s)', (id_,attempt,status,provider_label,tries,reason))
        sent += status == 'SENT'
        failed += status == 'FAILED'
    return {'sent':sent,'failed':failed}


def after_persistence(execution_id):
    """Best-effort observer, never reverses DQ or successful build commits."""
    if not enabled():
        return {'enabled':False}
    try:
        from src.common.postgres import create_postgres_connection
        with create_postgres_connection() as connection:
            state = evaluate(connection,execution_id)
            delivery = dispatch(connection,provider=os.environ.get('PLATFORM_ALERT_PROVIDER','log'))
        return {'enabled':True,'state':state,'delivery':delivery}
    except Exception:
        import sys
        print('Platform alert observer unavailable; DQ persistence remains authoritative', file=sys.stderr, flush=True)
        return {'enabled':True,'available':False}
