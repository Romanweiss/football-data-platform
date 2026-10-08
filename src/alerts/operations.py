"""Operational failures without DQ evidence; never infer rules from raw exceptions."""
from datetime import datetime, timezone
from uuid import uuid4
import os
import sys

from src.alerts.policy import identity, airflow_reference
from src.alerts.store import apply, dispatch, enabled


def operation_observation(request, *, passed, source_access=False):
    step = request['step']
    source = step in ('source','parent','children','source_discovery')
    cls = 'SOURCE_ACCESS_FAILURE' if source_access else 'PIPELINE_FAILURE'
    ctx = request.get('context')
    key, record = identity(cls, ctx, 'pipeline', 'bronze' if source else request.get('layer') or 'operational',
                           request.get('dataset') or 'pipeline', 'pipeline.' + step,
                           (request.get('build') or {}).get('build_id'))
    ref = airflow_reference(request.get('airflow'))
    return dict(dedup_key=key, **record, status='PASS' if passed else 'FAIL', severity='ERROR',
                observed_at=datetime.now(timezone.utc).isoformat(), observation_id=str(uuid4()), dq_execution_id=None,
                **{'airflow_' + k:ref.get(k) for k in ('dag_id','run_id','task_id')})


def observe_operation(request, *, passed, source_access=False, dq_reported=False):
    if not enabled() or request.get('test_mode'):
        return {'enabled':False}
    try:
        from src.common.postgres import create_postgres_connection
        with create_postgres_connection() as connection:
            with connection.transaction():
                # Persisted DQ owns its own alert. Do not add a duplicate pipeline FAIL.
                if passed or dq_reported:
                    actions = [apply(connection,operation_observation(request,passed=True,source_access=kind))
                               for kind in (False,True)]
                else:
                    actions = [apply(connection,operation_observation(request,passed=False,source_access=source_access))]
            deliveries = dispatch(connection,provider=os.environ.get('PLATFORM_ALERT_PROVIDER','log'))
        return {'enabled':True,'actions':actions,'delivery':deliveries}
    except Exception:
        print('Operational alert observer unavailable; platform commits preserved', file=sys.stderr)
        return {'enabled':True,'available':False}
