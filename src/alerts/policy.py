"""Pure, deterministic policy. Never forward free-text messages/errors."""
import hashlib
import json
import re
from urllib.parse import urlencode

from src.orchestration.commands import context, digest

CLASSES = ('DATA_QUALITY_FAILURE','PIPELINE_FAILURE','SOURCE_ACCESS_FAILURE','SERVING_FAILURE')


def airflow_reference(value):
    if value and (set(value) != {'dag_id','run_id','task_id'} or any(
            not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_.:+-]{1,250}',v) for v in value.values())):
        raise ValueError('Invalid notification Airflow reference')
    return value or {}


def classify(result):
    # Classification must be stable on FAIL and PASS: no message-text identity.
    if result['category'] != 'operational':
        return 'DATA_QUALITY_FAILURE'
    if result['layer'] == 'bronze':
        return 'SOURCE_ACCESS_FAILURE'
    if result['layer'] in ('serving','api'):
        return 'SERVING_FAILURE'
    return 'PIPELINE_FAILURE'


def identity(alert_class, ctx, scope, layer, dataset, rule_id, build_id=None):
    if alert_class not in CLASSES:
        raise ValueError('Invalid alert class')
    ctx = context(ctx) if ctx else {'competition_id':None,'season_id':None}
    for value in (scope, layer, dataset, rule_id):
        if not isinstance(value,str) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,159}', value):
            raise ValueError('Invalid alert identity')
    record = dict(alert_class=alert_class, **ctx, scope=scope, layer=layer, dataset=dataset,
                  rule_id=rule_id, build_id=digest(build_id) if build_id else None)
    key = hashlib.sha256(json.dumps({'version':1,**record},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return key, record


def observations(report):
    for row in report['results']:
        key, record = identity(classify(row), report, report['suite'], row['layer'],row['dataset'],
                               row['rule_id'],row['build_id'])
        yield dict(dedup_key=key, **record, status=row['status'], severity=row['severity'],
                   observed_at=report['finished_at'], observation_id=report['execution_id'],
                   dq_execution_id=report['execution_id'])


def notification(alert, airflow=None):
    # Messages are generated from validated identifiers, not raw persisted text.
    _, record = identity(alert['alert_class'],
                         {k:alert[k] for k in ('competition_id','season_id')} if alert['competition_id'] else None,
                         alert['scope'],alert['layer'],alert['dataset'],alert['rule_id'],alert['build_id'])
    params = {'var-competition':record['competition_id'],'var-season':record['season_id'],
              'var-rule_id':record['rule_id']} if record['competition_id'] else {}
    result = dict(project='football-data-platform', environment='local', alert_id=str(alert['alert_id']),
                  **record, status='OPEN', timestamp=alert['created_at'].isoformat(),
                  reason='Authoritative ERROR failure; inspect persisted evidence',
                  grafana='http://127.0.0.1:13000/d/football-platform-dq?' + urlencode(params))
    if airflow:
        result['airflow'] = airflow_reference(airflow)
        result['airflow_url'] = 'http://127.0.0.1:18080/dags/' + airflow['dag_id']
    return result
