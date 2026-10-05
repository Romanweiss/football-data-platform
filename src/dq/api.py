"""Existing API contracts and explicit WC golden regression, never generic fixed counts."""
from src.dq.model import Rule


def check(run, *, base_url='http://football-api:8000', golden=False):
    from scripts.check_application_api import validate, make_request
    rule = Rule('golden.wc2022.api_contract' if golden else 'api.analysis_available',
                'regression' if golden else 'operational', 'api', 'analysis',
                'WC2022 pinned API contract' if golden else 'Context API catalogs and sampled analysis contract')
    if golden and run.context != {'competition_id':43, 'season_id':106}:
        run.record(rule, skip=True, reason='not applicable')
        return
    ok, result = run.call(rule, lambda: validate(make_request(base_url), **run.context, wc2022=golden))
    if ok:
        prefix = 'golden.wc2022.api' if golden else 'api'
        run.record(Rule(prefix + '.match_count', 'operational' if not golden else 'regression', 'api', 'matches',
                        'API match count', 'INFO'), observed=result['matches'])
        run.record(Rule(prefix + '.analyses_checked', 'operational', 'api', 'analysis',
                        'Number of sampled analyses checked', 'INFO'), observed=len(result['checked_match_ids']))


def golden_views(run):
    from scripts.check_clickhouse_match_visuals import main
    rule = Rule('golden.wc2022.stage4c_4d_4e', 'regression', 'serving', 'bi',
                'Unmodified WC2022 cutover, match analysis and match visual golden fixtures')
    if run.context != {'competition_id':43, 'season_id':106}:
        run.record(rule, skip=True, reason='not applicable')
        return
    def validate():
        if main([]) != 0:
            raise ValueError('Golden fixture failed')
    run.call(rule, validate)


def catalog(run, client, *, base_url):
    from scripts.check_application_api import make_request
    def compare():
        c = run.context
        status, data = make_request(base_url)(f"/competitions/{c['competition_id']}/seasons/{c['season_id']}/matches")
        if status != 200:
            raise ValueError('API catalog unavailable')
        ids = [r['match_id'] for r in data['matches']]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('Invalid API membership')
        row = client.query('''SELECT count(),uniqExact(match_id),countIf(match_id NOT IN %(ids)s)
            FROM football.bi_match_overview WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s''',
            parameters={**c, 'ids':tuple(ids)}, settings={'readonly':1}).result_rows[0]
        if tuple(row) != (len(ids),len(ids),0):
            raise ValueError('API membership differs from serving')
    run.call(Rule('api.catalog_serving_membership', 'reconciliation', 'api', 'matches',
                  'API match catalog equals ClickHouse context membership'), compare)
