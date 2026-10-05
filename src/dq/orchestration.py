"""Small Airflow result adapter; PostgreSQL remains authoritative DQ storage."""
from src.dq.cli import execute, exit_code


class DQGateError(RuntimeError):
    def __init__(self, summary):
        self.summary = summary
        super().__init__('Persistent DQ gate failed')


def validate(request, suite, **kwargs):
    report = execute(request['context'], suite=suite, airflow=request.get('airflow'), **kwargs)
    summary = dict(dq_execution_id=report['execution_id'], dq_status=report['status'],
                   dq_counts=report['counts'], dq_persisted=report['persisted'],
                   dq_failed_rules=[r['rule_id'] for r in report['results'] if r['status']=='FAIL'][:10])
    if exit_code(report):
        raise DQGateError(summary)
    return summary
