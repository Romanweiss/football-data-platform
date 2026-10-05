"""Serving adapters: registered-build reconciliation and existing reference/metric rules."""
from src.dq.model import Rule


def resolve(run, connection, client):
    from src.analytics.model import current_builds
    from src.analytics.gold_model import current_gold_builds
    from src.analytics.specs import SPECS
    from src.analytics.gold_specs import V2_SPECS, RESULTS
    from src.common.postgres import find_silver_build
    selected = {}
    for layer, specs in (('silver', SPECS), ('gold', {**V2_SPECS, 'match_results': RESULTS})):
        for dataset, spec in specs.items():
            rule = Rule(f'serving.{layer}.{dataset}.registered_build', 'reconciliation', 'serving', dataset,
                        'Serving schema, single build, row count and load catalog agree')
            def read():
                if layer == 'gold':
                    return current_gold_builds(client, connection, specs={dataset:spec}, **run.context)[dataset]
                build_id = current_builds(client, connection, specs={dataset:spec}, **run.context)[dataset]
                return find_silver_build(connection, dataset=dataset, build_id=build_id, **run.context)
            ok, row = run.call(rule, read)
            if not ok:
                continue
            run.results[-1]['build_id'] = row['build_id']
            selected[layer + '/' + dataset] = row
            run.record(Rule(f'serving.{layer}.{dataset}.row_count', 'operational', 'serving', dataset,
                            'Registered serving row count', 'INFO'), observed=row['row_count'], build_id=row['build_id'])
            run.record(Rule(f'operational.{layer}.{dataset}.build_timestamp', 'operational', layer, dataset,
                            'Successful registered build timestamp (Unix seconds), no freshness SLA', 'INFO'),
                       observed=row['created_at'].timestamp(), build_id=row['build_id'])
            table = 'clickhouse_loads' if layer == 'silver' else 'clickhouse_gold_loads'
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT extract(epoch FROM loaded_at)::double precision FROM metadata.{table} '
                               f'WHERE competition_id=%s AND season_id=%s AND {layer}_build_id=%s '
                               'AND clickhouse_table=%s',
                               (run.context['competition_id'], run.context['season_id'], row['build_id'], spec.clickhouse_table))
                timestamp = cursor.fetchone()[0]
            run.record(Rule(f'operational.{layer}.{dataset}.load_timestamp', 'operational', 'serving', dataset,
                            'Successful load timestamp (Unix seconds), no freshness SLA', 'INFO'),
                       observed=timestamp, build_id=row['build_id'])
    return selected


def references(run, connection, client):
    from src.analytics.matches_model import check_model
    from src.analytics.gold_specs import V2_SPECS
    def report(name, actual, expected, valid, hard):
        run.record(Rule('serving.references.' + name, 'referential', 'serving', 'model',
                        'Reference count: ' + name, 'ERROR' if hard else 'INFO'),
                   passed=valid if hard else True, observed=actual, expected=expected if hard else None)
    run.call(Rule('serving.references_valid', 'referential', 'serving', 'model',
                  'Registered serving builds and hard references remain consistent'),
             lambda: check_model(client, connection, gold_specs=V2_SPECS, report=report, **run.context))


def gold(run, connection, client):
    from src.analytics.gold_model import check_model
    from src.analytics.gold_specs import V2_SPECS
    def report(name, actual, expected, valid):
        run.record(Rule('serving.gold.' + name, 'reconciliation', 'serving', 'model',
                        'Gold/Silver aggregate comparison: ' + name),
                   passed=valid, observed=actual, expected=expected)
    run.call(Rule('serving.gold_lineage_metrics', 'reconciliation', 'serving', 'model',
                  'Gold lineage and Silver performance metrics remain consistent'),
             lambda: check_model(client, connection, gold_specs=V2_SPECS, report=report, **run.context))


def results(run):
    from scripts.check_clickhouse_match_results import main
    from src.orchestration.commands import context_args
    def validate():
        if main(['--bi', *context_args(run.context)]) != 0:
            raise ValueError('Result/BI validator failed')
    run.call(Rule('serving.match_results.source_scores_shootout_bi', 'semantic', 'serving', 'match_results',
                  'Result coverage, lineage, source scores, shootout evidence and BI projection'), validate)


def bronze_membership(run, client, ids, build):
    rule = Rule('silver.matches.bronze_membership', 'reconciliation', 'silver', 'matches',
                'Exact match membership equals the verified Bronze parent')
    if ids is None or build is None:
        run.record(rule, skip=True, reason='prerequisite failed')
        return
    def query():
        # Only three scalars leave ClickHouse. No event/player rows are collected.
        return client.query('''SELECT count(),uniqExact(match_id),countIf(match_id NOT IN %(ids)s)
            FROM football.matches WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s
              AND silver_build_id=%(build_id)s''',
            parameters={**run.context, 'build_id':build['build_id'], 'ids':tuple(ids)}, settings={'readonly':1}).result_rows[0]
    ok, counts = run.call(Rule('operational.bronze_silver_membership_query', 'operational', 'silver', 'matches',
                              'Read aggregate Bronze/Silver membership'), query, build_id=build['build_id'])
    if ok:
        run.record(rule, passed=tuple(counts)==(len(ids),len(ids),0), observed=counts[0],
                   expected=len(ids), build_id=build['build_id'])


def stable(run, client, builds):
    from src.analytics.specs import SPECS
    from src.analytics.gold_specs import V2_SPECS, RESULTS
    def verify():
        for key, row in builds.items():
            layer, dataset = key.split('/')
            spec = (SPECS if layer == 'silver' else {**V2_SPECS,'match_results':RESULTS})[dataset]
            counts = client.query(f'''SELECT count(),uniqExact({layer}_build_id),
                countIf({layer}_build_id != %(build_id)s) FROM {spec.target}
                WHERE competition_id=%(competition_id)s AND season_id=%(season_id)s''',
                parameters={**run.context, 'build_id':row['build_id']}, settings={'readonly':1}).result_rows[0]
            if tuple(counts) != (row['row_count'],1,0):
                raise ValueError('Serving snapshot changed during DQ')
    run.call(Rule('serving.build_snapshot_stable', 'source_integrity', 'serving', 'model',
                  'Serving build IDs and counts unchanged throughout validation'), verify)
