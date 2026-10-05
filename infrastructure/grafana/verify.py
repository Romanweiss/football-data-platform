"""Read-only Grafana acceptance client; credentials stay inside the runtime.

Only safe counts/identities are output, never headers, passwords or raw errors.
POST /api/ds/query executes SELECTs; it does not mutate platform or Grafana state.
"""
import base64
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from infrastructure.grafana.bootstrap import ROOT

DATASOURCE = 'football-metadata-dq'
DASHBOARD = 'football-platform-dq'
BASE = 'http://football-grafana:3000'


def render(query, variables):
    def replace(match):
        return "'" + str(variables[match[1]]).replace("'", "''") + "'"
    query = re.sub(r'\$\{(\w+):sqlstring\}', replace, query)
    return re.sub(r'\$__timeFilter\((\w+)\)',
                  r"\1 BETWEEN clock_timestamp()-interval '90 days' AND clock_timestamp()", query)


def frame_rows(result):
    return [dict(zip([f['name'] for f in frame['schema']['fields']], row, strict=True))
            for frame in result.get('frames', []) for row in zip(*frame['data']['values'])]


def verify():
    # This application client privately consumes the generated runtime credential.
    # No retrieval command, env dump, header or response body is logged.
    password = (ROOT / 'admin_password').read_text().strip()
    authorization = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(BASE + path, data=data,
                      headers={'Authorization': authorization, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=20) as response:
            return json.load(response)

    health = request('/api/health')
    assert health['database'] == 'ok', 'health'
    datasource = request('/api/datasources/uid/' + DATASOURCE)
    assert datasource['user'] == 'grafana_reader' and datasource['readOnly'], 'read-only datasource'
    assert datasource['secureJsonFields']['password'], 'encrypted password present'
    assert not datasource.get('secureJsonData'), 'no exposed password'
    assert request('/api/datasources/uid/' + DATASOURCE + '/health')['status'] == 'OK', 'datasource health'
    dashboard = request('/api/dashboards/uid/' + DASHBOARD)['dashboard']
    expected = json.loads((Path(__file__).parent / 'dashboards/platform_dq.json').read_text())
    assert dashboard['uid'] == expected['uid'], 'dashboard uid'
    assert [p['targets'] for p in dashboard['panels']] == [p['targets'] for p in expected['panels']], 'panel provisioning'
    assert dashboard['templating']['list'] == expected['templating']['list'], 'variable provisioning'

    def query(sql, format_='table'):
        result = request('/api/ds/query', {'from': 'now-90d', 'to': 'now', 'queries': [{
            'refId': 'A', 'datasource': {'type': datasource['type'], 'uid': DATASOURCE},
            'rawSql': sql, 'rawQuery': True, 'format': format_}]})['results']['A']
        if result.get('error'):
            raise RuntimeError('Grafana SELECT query failed')
        return frame_rows(result)

    contexts = query('SELECT competition_id,season_id,status,passed,failed,warnings,skipped '
                     'FROM observability.dq_current_executions ORDER BY competition_id,season_id')
    total_queries = 0
    for context in contexts:
        variables = dict(competition=context['competition_id'], season=context['season_id'],
                         layer='__all', dataset='__all', severity='__all', status='__all', rule_id='__all')
        for variable in dashboard['templating']['list']:
            options = query(render(variable['query'], variables))
            assert options, 'variable options: ' + variable['name']
            total_queries += 1
        for panel in dashboard['panels']:
            target = panel['targets'][0]
            query(render(target['rawSql'], variables), target['format'])
            total_queries += 1
        # Prove detail selectors return only the selected persisted rule/status.
        variables.update(layer='api', dataset='matches', severity='INFO', status='PASS', rule_id='api.match_count')
        rows = query(render(next(p for p in dashboard['panels'] if p['id'] == 10)['targets'][0]['rawSql'], variables))
        assert rows and all(r['rule_id'] == 'api.match_count' and r['status'] == 'PASS' for r in rows), 'filtered rule history'
        total_queries += 1
    print(json.dumps({'health': health, 'datasource': DATASOURCE, 'dashboard': DASHBOARD,
                      'datasource_id': datasource['id'], 'dashboard_id': dashboard['id'],
                      'verified_queries': total_queries, 'current_full_contexts': contexts}, indent=2))


if __name__ == '__main__':
    try:
        verify()
    except AssertionError as exc:
        # Assertions contain only static test labels, never response/error text.
        print(f'Grafana verification failed: check={exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f'Grafana verification failed: exception={type(exc).__name__}', file=sys.stderr)
        sys.exit(1)
