"""CI-only migration/fixture harness. Requires isolated services and empty state."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def guard(kind):
    required = {'PLATFORM_CI_EPHEMERAL': 'true'}
    required.update({'POSTGRES_HOST': 'ci-postgres', 'POSTGRES_DB': 'football_ci', 'POSTGRES_USER': 'ci'}
                    if kind == 'postgres' else {'CLICKHOUSE_HOST': 'ci-clickhouse', 'CLICKHOUSE_DB': 'football', 'CLICKHOUSE_USER': 'ci'})
    if any(os.environ.get(k) != v for k, v in required.items()):
        raise RuntimeError('CI harness requires its isolated synthetic service configuration')


def run_tests(patterns):
    # Existing root/offline and integration files share module names. Their
    # fixture imports also amend sys.path, so execute each existing unittest
    # entrypoint in a fresh interpreter rather than mixing their import caches.
    paths = sorted({path for pattern in patterns for path in (ROOT / 'tests/integration').glob(pattern)})
    if not paths:
        raise RuntimeError('No integration tests selected')
    for path in paths:
        print('Integration suite: ' + path.name, flush=True)
        subprocess.run([sys.executable, str(path)], check=True, timeout=180)


def postgres():
    guard('postgres')
    from src.common.postgres import create_postgres_connection
    from src.dq.model import Run, Rule
    from src.dq.store import persist
    from infrastructure.grafana.bootstrap import bootstrap
    with create_postgres_connection() as connection:
        connection.autocommit = True
        with connection.cursor() as cur:
            cur.execute("SELECT current_database(), to_regnamespace('metadata')")
            if cur.fetchone() != ('football_ci', None):
                raise RuntimeError('CI PostgreSQL must be a fresh empty football_ci database')
            files = sorted((ROOT / 'infrastructure/postgres/init').glob('*.sql'))
            files += sorted((ROOT / 'infrastructure/postgres/migrations').glob('*.sql'))
            for cycle in (1, 2):
                for path in files:
                    cur.execute(path.read_text(encoding='utf-8'))
                    print(f'PostgreSQL migration pass={cycle}: {path.name}', flush=True)
        # Tiny *synthetic* history for existing live-baseline assertions; no football payloads.
        # IDs match those tests, but these are not real WC/Bundesliga acceptance results.
        with connection.transaction():
            for competition, season in ((43, 106), (9, 281)):
                ctx = {'competition_id': competition, 'season_id': season}
                for _ in range(2):
                    run = Run(ctx, 'full')
                    run.record(Rule('ci.fixture', 'structural', 'silver', 'events', 'Synthetic CI baseline'))
                    if competition == 9:
                        for suffix in ('one', 'two'):
                            run.record(Rule('ci.golden.' + suffix, 'regression', 'api', 'analysis', 'Synthetic inapplicable rule'),
                                       skip=True, reason='not applicable')
                    persist(connection, run.report())
                with connection.cursor() as cur:
                    cur.execute('''INSERT INTO metadata.silver_builds
                        (source,dataset,competition_id,season_id,transform_version,input_fingerprint,
                         schema_sha256,build_id,s3_bucket,s3_prefix,row_count,file_count)
                        VALUES ('statsbomb','event_core',%s,%s,'ci_fixture',%s,%s,%s,'ci-invalid',%s,1,1)''',
                                (competition, season, 'a'*64, 'b'*64, 'c'*64, f'ci/{competition}/{season}'))
    bootstrap()  # Only the fresh CI server; private generated reader files live in tmpfs.
    run_tests(['test_*postgres.py'])


def clickhouse():
    guard('clickhouse')
    from src.common.clickhouse import create_clickhouse_client
    with closing(create_clickhouse_client()) as client:
        if client.query("SELECT count() FROM system.tables WHERE database='football'").first_row[0]:
            raise RuntimeError('CI ClickHouse must have an empty football database')
        migrations = sorted((ROOT / 'infrastructure/clickhouse/migrations').glob('*.sql'))
        def apply(path):
            # Current migrations have no procedural bodies/semicolon string literals.
            text = '\n'.join(line for line in path.read_text(encoding='utf-8').splitlines()
                             if not line.lstrip().startswith('--'))
            for statement in text.split(';'):
                if statement.strip():
                    client.command(statement)
            print('ClickHouse migration: ' + path.name, flush=True)
        for _ in range(2):
            for path in migrations:
                if path.name.startswith('011_'):
                    continue  # 011 is rollback, not a forward migration!
                apply(path)
        rollback = next(p for p in migrations if p.name.startswith('011_'))
        cutover = next(p for p in migrations if p.name.startswith('010_'))
        apply(rollback)
        assert 'team_match_stats_v2' not in client.command('SHOW CREATE TABLE football.bi_team_match_stats')
        apply(cutover)
        assert 'team_match_stats_v2' in client.command('SHOW CREATE TABLE football.bi_team_match_stats')
        for (name,) in client.query("SELECT name FROM system.tables WHERE database='football' AND engine='View'").result_rows:
            client.query(f'SELECT * FROM football.`{name}` LIMIT 0')
        columns = dict(row[:2] for row in client.query('DESCRIBE TABLE football.event_core').result_rows)
        assert all(columns[k] == 'Nullable(Float64)' for k in ('location_x', 'location_y', 'duration'))
    run_tests(['test_clickhouse_*.py', 'test_match_results.py'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', choices=('postgres', 'clickhouse'))
    args = parser.parse_args()
    try:
        globals()[args.database]()
    except Exception as exc:
        print('CI database gate failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
