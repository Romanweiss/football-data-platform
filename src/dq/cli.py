"""Common human/JSON CLI and execution coordinator; rules live in layer adapters."""
import argparse
from contextlib import ExitStack, closing
import json

from src.analytics.context import add_context_arguments, context_from_args
from src.common.postgres import create_postgres_connection
from src.dq.model import Run, Rule
from src.dq.store import persist, summary
from src.orchestration.commands import digest

SUITES = ('full', 'bronze', 'artifact', 'references', 'gold', 'results', 'api', 'golden')


def execute(ctx, *, suite='full', layer=None, dataset=None, build_id=None, expected_inputs=None,
            parent_sha256=None, bronze_max_id=None, airflow=None, base_url='http://football-api:8000',
            persist_results=True):
    from src.dq import bronze, artifacts, serving, api
    from src.common.clickhouse import create_clickhouse_client
    from src.common.s3 import create_s3_client
    if suite not in SUITES:
        raise ValueError('Unknown suite')
    if suite == 'artifact':
        from src.analytics.specs import SPECS
        from src.analytics.gold_specs import V2_SPECS
        allowed = SPECS if layer == 'silver' else {**V2_SPECS, 'match_results': None} if layer == 'gold' else {}
        if dataset not in allowed:
            raise ValueError('Unknown artifact dataset/layer')
        digest(build_id)
    scope = f'artifact.{layer}.{dataset}' if suite == 'artifact' else suite
    run = Run(ctx, scope, airflow=airflow)
    try:
        with ExitStack() as stack:
            pg = stack.enter_context(closing(create_postgres_connection())) if suite not in ('api', 'golden') else None
            ch = stack.enter_context(closing(create_clickhouse_client())) if suite in ('full','artifact','references','gold','api') else None
            s3 = stack.enter_context(closing(create_s3_client())) if suite in ('full','bronze','artifact') else None
            if suite in ('full', 'bronze'):
                ids = bronze.check(run, pg, s3, parent_sha256=parent_sha256, bronze_max_id=bronze_max_id)
            if suite == 'full':
                builds = serving.resolve(run, pg, ch)
                for key, row in builds.items():
                    selected_layer, selected_dataset = key.split('/')
                    upstream = {k.split('/')[1]:v['build_id'] for k,v in builds.items()
                                if k in ('silver/event_core','silver/match_squads','silver/pass_events','silver/shot_events')}
                    artifacts.check(run, pg, s3, ch, layer=selected_layer, dataset=selected_dataset,
                                    build_id=row['build_id'], expected_inputs=upstream)
                serving.bronze_membership(run, ch, ids, builds.get('silver/matches'))
            if suite == 'artifact':
                artifacts.check(run, pg, s3, ch, layer=layer, dataset=dataset,
                                build_id=build_id, expected_inputs=expected_inputs)
            if suite in ('full', 'references'):
                serving.references(run, pg, ch)
            if suite in ('full', 'gold'):
                serving.gold(run, pg, ch)
            if suite in ('full', 'results'):
                serving.results(run)
            if suite in ('full', 'api'):
                api.check(run, base_url=base_url)
                api.catalog(run, ch, base_url=base_url)
            if suite in ('full', 'golden'):
                api.check(run, base_url=base_url, golden=True)
                api.golden_views(run)
            if suite == 'full':
                serving.stable(run, ch, builds)
    except Exception:
        run.record(Rule('operational.dq_execution', 'operational', 'operational', 'pipeline',
                        'DQ execution dependencies must be available'), passed=False, reason='runtime failed')
    report = run.report()
    report['persisted'] = False
    if persist_results:
        try:
            # Independent connection: failure in a validator transaction must not
            # prevent recording its failure. Never write the platform build tables.
            with create_postgres_connection() as connection:
                persist(connection, report)
            report['persisted'] = True
        except Exception:
            report['persistence_error'] = 'DQ history write failed; no successful persistence claimed'
    return report


def exit_code(report):
    if 'persistence_error' in report:
        return 2
    return 1 if report['status'] == 'FAIL' else 0


def render(report, *, output_json=False):
    if output_json:
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return
    print(f"Context {report['competition_id']}/{report['season_id']} suite={report['suite']} status={report['status']}")
    if 'execution_id' in report:
        print('DQ execution: ' + report['execution_id'])
    for layer, status in report.get('layers', {}).items():
        print(f'{layer}: {status}')
    print('Rules: ' + ' '.join(f'{n} {s}' for s,n in report.get('counts', {}).items()))
    for r in report['results']:
        print(f"{r['status']} [{r['severity']}] {r['rule_id']}: {r['message']}"
              f" observed={r['observed']} expected={r['expected']} build={r['build_id'] or '-'}")
        if r.get('changed'):
            print('  Changed from previous successful execution: ' + json.dumps(r['previous'], sort_keys=True))
    if report.get('removed_rules'):
        print('Rules absent compared with previous PASS: ' + ', '.join(report['removed_rules']))
    if 'persisted' in report:
        print('Persisted: ' + str(report['persisted']))
    if 'persistence_error' in report:
        print(report['persistence_error'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_context_arguments(parser)
    parser.add_argument('--suite', choices=SUITES, default='full')
    parser.add_argument('--summary', action='store_true', help='Read latest execution and compare previous PASS of same scope')
    parser.add_argument('--output-json', action='store_true')
    parser.add_argument('--no-persist', action='store_true', help='Explicit diagnostic mode; never used by Airflow')
    parser.add_argument('--layer', choices=('silver','gold'))
    parser.add_argument('--dataset')
    parser.add_argument('--build-id')
    parser.add_argument('--silver-build', action='append', default=[])
    parser.add_argument('--parent-sha256')
    parser.add_argument('--bronze-max-id', type=int)
    parser.add_argument('--base-url', default='http://football-api:8000')
    for key in ('dag-id','run-id','task-id'):
        parser.add_argument('--airflow-' + key)
    args = parser.parse_args(argv)
    ctx = context_from_args(args)
    try:
        upstream = {}
        for pin in args.silver_build:
            key, sep, value = pin.partition('=')
            if not sep or key in upstream or key not in ('event_core','match_squads','pass_events','shot_events'):
                raise ValueError('Invalid Silver pin')
            upstream[key] = digest(value)
        for value in (args.build_id, args.parent_sha256):
            if value is not None:
                digest(value)
        if args.bronze_max_id is not None and args.bronze_max_id <= 0:
            raise ValueError('Invalid Bronze boundary')
        airflow = dict(dag_id=args.airflow_dag_id, run_id=args.airflow_run_id, task_id=args.airflow_task_id)
        airflow = airflow if any(airflow.values()) else None
        if args.summary:
            scope = f'artifact.{args.layer}.{args.dataset}' if args.suite == 'artifact' else args.suite
            with create_postgres_connection() as connection:
                report = summary(connection, ctx, scope, build_id=args.build_id)
        else:
            report = execute(ctx, suite=args.suite, layer=args.layer, dataset=args.dataset,
                             build_id=args.build_id, expected_inputs=upstream, parent_sha256=args.parent_sha256,
                             bronze_max_id=args.bronze_max_id, airflow=airflow, base_url=args.base_url,
                             persist_results=not args.no_persist)
        render(report, output_json=args.output_json)
        return exit_code(report)
    except Exception:
        # Do not reproduce argument strings, driver exceptions or environment values.
        if args.output_json:
            print(json.dumps({'status':'FAIL', 'error':'DQ configuration or summary unavailable'}))
        else:
            print('DQ configuration or summary unavailable')
        return 2
