"""Captured Docker IO. No raw command output or exceptions may reach logs."""
from contextlib import contextmanager
import hashlib
import json
import re
import subprocess


class RecoveryError(RuntimeError):
    """Only fixed, non-secret diagnostic codes are exposed by the CLI."""


def require(condition, code):
    if not condition:
        raise RecoveryError(code)


def run(args, *, data=None, timeout=600):
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError('COMMAND_UNAVAILABLE_OR_TIMEOUT') from None
    require(result.returncode == 0, 'COMMAND_FAILED_OUTPUT_SUPPRESSED')
    return result.stdout


def docker(*args, data=None, timeout=600):
    return run(['docker', *args], data=data, timeout=timeout)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def identifier(value):
    require(bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value)), 'UNSAFE_IDENTIFIER')
    return '"' + value + '"'


def source_container(service):
    ids = docker('ps', '-q', '--filter', 'label=com.docker.compose.project=football-data-platform',
                 '--filter', 'label=com.docker.compose.service=' + service).decode().split()
    require(len(ids) == 1, 'SOURCE_SERVICE_MISSING_OR_AMBIGUOUS')
    return ids[0]


def container_info(container):
    # Deliberately never inspect Config.Env, command or raw full inspect.
    template = ('{"id":{{json .Id}},"image":{{json .Image}},"created":{{json .Created}},'
                '"started":{{json .State.StartedAt}},"mounts":{{json .Mounts}},'
                '"network":{{json .HostConfig.NetworkMode}},"ports":{{json .HostConfig.PortBindings}},'
                '"labels":{{json .Config.Labels}}}')
    return json.loads(docker('inspect', '--format', template, container))


PG_SHELL = 'exec "$@" -U "$POSTGRES_USER" -d "$POSTGRES_DB"'


def pg_args(container, program='psql', *extra):
    selection = []
    if isinstance(container, tuple):
        container, database = container
        identifier(database)
        selection = ['-e', 'POSTGRES_DB=' + database]
    return ['docker', 'exec', '-i', *selection, container, 'sh', '-c', PG_SHELL, 'recovery', program, *extra]


def pg_query(container, sql, snapshot=None):
    if snapshot:
        require(bool(re.fullmatch(r'[0-9A-Fa-f-]+', snapshot)), 'INVALID_SNAPSHOT')
        sql = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '" + snapshot + "';\n" + sql + ';\nCOMMIT;'
    return run(pg_args(container, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1'), data=sql.encode())


@contextmanager
def pg_snapshot(container):
    # Keep the exporting transaction alive until dump AND baseline queries finish.
    process = subprocess.Popen(pg_args(container, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1'),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        process.stdin.write(b"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n")
        process.stdin.flush()
        snapshot = process.stdout.readline().decode().strip()
        require(bool(re.fullmatch(r'[0-9A-Fa-f-]+', snapshot)), 'SNAPSHOT_EXPORT_FAILED')
        yield snapshot
    finally:
        if process.poll() is None:
            process.communicate(b'ROLLBACK;\n', timeout=15)


def pg_baseline(container, snapshot=None):
    tables = json.loads(pg_query(container, "SELECT coalesce(json_agg(x), '[]') FROM ("
        "SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
        "ORDER BY 1,2) x", snapshot))
    result = {}
    for item in tables:
        table = identifier(item['schemaname']) + '.' + identifier(item['tablename'])
        raw = pg_query(container, 'COPY (SELECT row_to_json(t)::text AS row FROM ' + table +
                       ' t ORDER BY row_to_json(t)::text COLLATE "C") TO STDOUT', snapshot)
        result[item['schemaname'] + '.' + item['tablename']] = {
            'rows': raw.count(b'\n'), 'sha256': digest(raw)}
    return result


def pg_json(container, sql, snapshot=None):
    return json.loads(pg_query(container, "SELECT coalesce(json_agg(x), '[]') FROM (" + sql + ') x', snapshot))


CH_SHELL = 'exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" "$@"'


def ch_query(container, sql, data=None):
    # Query goes as a separate argv, credentials are expanded inside the source container only.
    return docker('exec', '-i', container, 'sh', '-c', CH_SHELL, 'recovery',
                  '--output_format_json_quote_64bit_integers=0', '--query', sql, data=data)


def ch_json(container, sql):
    return json.loads(ch_query(container, sql + ' FORMAT JSON'))['data']


def ch_baseline(container):
    result = {}
    tables = ch_json(container, "SELECT name,engine,sorting_key FROM system.tables WHERE database='football' ORDER BY name")
    for item in tables:
        require(item['engine'] in ('MergeTree', 'View'), 'UNSUPPORTED_CLICKHOUSE_ENGINE')
        if item['engine'] == 'View':
            continue
        table = 'football.' + identifier(item['name'])
        raw = ch_query(container, 'SELECT * FROM ' + table + ' ORDER BY ALL FORMAT JSONEachRow')
        columns = ch_json(container, 'DESCRIBE TABLE ' + table)
        build = next((x['name'] for x in columns if x['name'] in ('silver_build_id', 'gold_build_id')), None)
        require(build is not None, 'SERVING_BUILD_COLUMN_MISSING')
        groups = ch_json(container, 'SELECT competition_id,season_id,' + build +
                         ' AS build_id,count() AS rows FROM ' + table + ' GROUP BY ALL ORDER BY ALL')
        # ORDER BY is not a uniqueness constraint: count actual duplicate business keys.
        key = item['sorting_key']
        duplicate_count = int(ch_query(container, 'SELECT count() FROM (SELECT ' + key +
            ',count() AS n FROM ' + table + ' GROUP BY ' + key + ' HAVING n>1)'))
        result[item['name']] = {'rows': raw.count(b'\n'), 'sha256': digest(raw), 'groups': groups,
                                'duplicate_keys': duplicate_count, 'columns': columns}
    return result


def registry(container, snapshot=None):
    return {name: pg_json(container, 'SELECT * FROM metadata.' + name + ' ORDER BY id', snapshot)
            for name in ('ingestion_objects', 'silver_builds', 'gold_builds', 'clickhouse_loads', 'clickhouse_gold_loads')}


def reconcile(catalog, serving):
    """Exact published identities; neither choose latest nor rewrite registry history."""
    published = {}
    for layer in ('silver', 'gold'):
        for row in catalog[layer + '_builds']:
            published[(layer, row['dataset'], row['competition_id'], row['season_id'], row['build_id'])] = row
        for row in catalog['clickhouse_' + ('gold_' if layer == 'gold' else '') + 'loads']:
            identity = (layer, row['dataset'], row['competition_id'], row['season_id'], row[layer + '_build_id'])
            require(identity in published, 'LOADED_BUILD_NOT_PUBLISHED')
            parent = published[identity]
            for field in ('input_fingerprint', 'schema_sha256', 's3_bucket', 's3_prefix', 'row_count'):
                require(parent[field] == row[field], 'LOAD_REGISTRY_PARENT_MISMATCH')
    loads = {(row['clickhouse_table'], row['competition_id'], row['season_id'], row[layer + '_build_id']): row
             for layer in ('silver', 'gold')
             for row in catalog['clickhouse_' + ('gold_' if layer == 'gold' else '') + 'loads']}
    seen = set()
    for table, baseline in serving.items():
        require(baseline['duplicate_keys'] == 0, 'SERVING_DUPLICATE_KEYS')
        for group in baseline['groups']:
            identity = (table, int(group['competition_id']), int(group['season_id']), group['build_id'])
            require(identity in loads, 'SERVING_BUILD_NOT_REGISTERED')
            require(int(group['rows']) == loads[identity]['row_count'], 'SERVING_LOAD_COUNT_MISMATCH')
            seen.add(identity)
    require(seen == set(loads), 'REGISTERED_LOAD_MISSING_FROM_SERVING')
    return {'published_builds': len(published), 'loaded_builds': len(loads), 'status': 'PASS'}
