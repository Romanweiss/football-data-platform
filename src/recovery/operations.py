"""Explicit live backup and networkless, disposable restore drill."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
import uuid

from src.recovery.archive import Archive, SCHEMA_VERSION, exclusive_write, load_archive, private_directory
from src.recovery.runtime import (
    RecoveryError, ch_baseline, ch_json, ch_query, container_info, digest, docker, encoded,
    identifier, pg_args, pg_baseline, pg_json, pg_query, pg_snapshot, reconcile, registry,
    require, run, source_container,
)

ROOT = Path(__file__).resolve().parents[2]
PG_SERVICES = {'platform': 'football-postgres', 'airflow': 'football-airflow-db', 'superset': 'football-superset-db'}
CURRENT_STAGE = 'preflight'
CURRENT_BACKUP_ID = None


def notify(stage):
    global CURRENT_STAGE
    CURRENT_STAGE = stage
    print('stage=' + stage, flush=True)


def context_summary(container):
    return {
        'matches': ch_json(container, 'SELECT competition_id,season_id,count() AS matches '
                           'FROM football.matches GROUP BY ALL ORDER BY ALL'),
        'selected_xg': ch_json(container, 'SELECT competition_id,season_id,match_id,team_id,'
            'round(shot_xg,12) AS shot_xg FROM football.bi_match_team_stats '
            'WHERE match_id IN (3869685,3895052) ORDER BY ALL'),
        'views': ch_json(container, "SELECT name FROM system.tables WHERE database='football' AND engine='View' ORDER BY name"),
    }


def pg_properties(container, snapshot=None):
    return {
        'database': pg_json(container, 'SELECT datname,pg_get_userbyid(datdba) AS owner,datacl::text AS acl '
                            'FROM pg_database WHERE datname=current_database()', snapshot),
        'extensions': pg_json(container, 'SELECT extname,extversion FROM pg_extension ORDER BY extname', snapshot),
        'roles': pg_json(container, "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
                        "rolreplication,rolbypassrls,rolconfig FROM pg_roles WHERE rolname NOT LIKE 'pg_%' "
                        "AND rolname <> 'drill_admin' ORDER BY rolname", snapshot),
        'schema': pg_json(container, "SELECT table_schema,table_name,column_name,ordinal_position,data_type,"
                         "is_nullable,column_default FROM information_schema.columns WHERE table_schema "
                         "NOT IN ('pg_catalog','information_schema') ORDER BY 1,2,4", snapshot),
        'grants': pg_json(container, "SELECT grantor,grantee,table_schema,table_name,privilege_type,is_grantable "
                         "FROM information_schema.table_privileges WHERE table_schema NOT IN "
                         "('pg_catalog','information_schema') ORDER BY 1,2,3,4,5,6", snapshot),
        'relations': pg_json(container, "SELECT n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner) AS owner,"
                             "ARRAY(SELECT a::text FROM unnest(c.relacl) a ORDER BY a::text) AS acl "
                             "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                             "WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' "
                             "ORDER BY 1,2", snapshot),
        'memberships': pg_json(container, "SELECT pg_get_userbyid(roleid) AS role,pg_get_userbyid(member) AS member,"
                               "admin_option,inherit_option,set_option FROM pg_auth_members ORDER BY 1,2", snapshot),
        'constraints': pg_json(container, "SELECT n.nspname,c.conname,cl.relname,pg_get_constraintdef(c.oid) AS definition "
                              "FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
                              "LEFT JOIN pg_class cl ON cl.oid=c.conrelid "
                              "WHERE n.nspname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2,3", snapshot),
    }


def canonical_database_acl(rows):
    """ACL entry order is not semantic. Refuse complex quoting rather than guess."""
    result = []
    for row in rows:
        row = dict(row)
        if row['acl'] is not None:
            require(bool(re.fullmatch(r'\{[A-Za-z0-9_=*/,]*\}', row['acl'])), 'UNSUPPORTED_DATABASE_ACL_ENCODING')
            row['acl'] = sorted(row['acl'][1:-1].split(','))
        result.append(row)
    return result


def canonical_columns(rows):
    """Logical column order, excluding attnum holes left by dropped columns."""
    positions, result = {}, []
    for row in sorted(rows, key=lambda r: (r['table_schema'], r['table_name'], r['ordinal_position'])):
        row = dict(row)
        key = row['table_schema'], row['table_name']
        positions[key] = positions.get(key, 0) + 1
        row['ordinal_position'] = positions[key]
        result.append(row)
    return result


def source_inventory():
    return {service: container_info(source_container(service)) for service in
            (*PG_SERVICES.values(), 'football-clickhouse', 'football-grafana')}


def s3_inventory(catalog):
    source = source_container('football-airflow-scheduler')
    code = (ROOT / 'src/recovery/s3_inventory.py').read_text(encoding='utf-8')
    raw = docker('exec', '-i', source, '/usr/bin/python3', '-c', code, data=encoded(catalog), timeout=900)
    result = json.loads(raw)
    require('error' not in result, 'S3_INVENTORY_FAILED')
    return result


GRAFANA_SNAPSHOT = """
import sqlite3,sys
source=sqlite3.connect('file:/source/grafana.db?mode=ro',uri=True,timeout=20)
target=sqlite3.connect(':memory:')
source.backup(target)
assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
sys.stdout.buffer.write(target.serialize())
"""


def grafana_snapshot(inventory):
    mounts = inventory['football-grafana']['mounts']
    volumes = [m['Name'] for m in mounts if m['Destination'] == '/var/lib/grafana' and m['Type'] == 'volume']
    require(volumes == ['football_grafana_data'], 'UNEXPECTED_GRAFANA_VOLUME')
    return docker('run', '--rm', '--network', 'none', '--user', '0:0',
                  '--mount', 'type=volume,src=football_grafana_data,dst=/source,readonly',
                  '--entrypoint', 'python', 'football-python-tools:3.12', '-c', GRAFANA_SNAPSHOT)


def require_sqlite_serialization():
    import sqlite3
    require(hasattr(sqlite3.Connection, 'serialize') and hasattr(sqlite3.Connection, 'deserialize'),
            'RECOVERY_REQUIRES_SQLITE_SERIALIZATION_USE_PYTHON_3_12')


def sqlite_connection_summary(db):
    require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLITE_INTEGRITY_FAILED')
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: db.execute('SELECT count(*) FROM ' + identifier(name)).fetchone()[0] for name in tables}


def sqlite_summary(raw):
    import sqlite3
    require_sqlite_serialization()
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(raw)
        return sqlite_connection_summary(db)
    finally:
        db.close()


GRAFANA_RESTORE = """
import sqlite3,sys,json
db=sqlite3.connect(':memory:')
db.deserialize(sys.stdin.buffer.read())
db.execute('PRAGMA query_only=ON')
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
result={name:db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
print(json.dumps(result,sort_keys=True))
"""


def create_backup():
    global CURRENT_BACKUP_ID
    # Fail before Docker/source IO or creating keys/artifacts on unsupported hosts.
    require_sqlite_serialization()
    start = time.monotonic()
    identity = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
    CURRENT_BACKUP_ID = identity
    print('backup_id=' + identity, flush=True)
    # Refuse real backups on CI runners, even if credentials were accidentally injected.
    require(not os.environ.get('CI') and not os.environ.get('GITHUB_ACTIONS'), 'LIVE_BACKUP_FORBIDDEN_IN_CI')
    inventory = source_inventory()
    notify('source-inventory-confirmed')
    private_directory(ROOT / 'backups')
    private_directory(ROOT / '.recovery-keys')
    directory = ROOT / 'backups' / identity
    directory.mkdir(mode=0o700)
    key = os.urandom(32)
    exclusive_write(ROOT / '.recovery-keys' / (identity + '.key'), key)
    manifest = {'backup_id': identity, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'schema_version': SCHEMA_VERSION, 'artifacts': [], 'encryption': 'AES-256-GCM; HMAC-SHA256 manifest',
        'consistency_status': 'INCOMPLETE', 'verification_status': 'NOT_RESTORED',
        'git_head': run(['git', 'rev-parse', 'HEAD']).decode().strip()}
    archive = Archive(directory, key, manifest)
    details = {'postgres': {}, 'source_inventory': inventory}
    for name, service in PG_SERVICES.items():
        notify('backup-postgres-' + name)
        source = source_container(service)
        version = pg_query(source, 'SHOW server_version').decode().strip().split()[0]
        require(version == '17.6', 'UNSUPPORTED_POSTGRES_VERSION')
        client_version = docker('exec', source, 'pg_dump', '--version').decode()
        require('17.6' in client_version, 'POSTGRES_CLIENT_SERVER_MISMATCH')
        with pg_snapshot(source) as snapshot:
            dump = run(pg_args(source, 'pg_dump', '--format=custom', '--create', '--snapshot=' + snapshot))
            require(dump.startswith(b'PGDMP'), 'INVALID_POSTGRES_DUMP')
            archive.add(name + '.dump.enc', dump, component=name, method='pg_dump custom exported snapshot', version=version)
            baseline = pg_baseline(source, snapshot)
            properties = pg_properties(source, snapshot)
            if name == 'platform':
                details['catalog'] = registry(source, snapshot)
        roles = docker('exec', source, 'sh', '-c',
                       'exec pg_dumpall --roles-only --no-role-passwords -U "$POSTGRES_USER"')
        archive.add(name + '.roles.enc', roles, component=name, method='roles without password hashes', version=version)
        details['postgres'][name] = {'version': version, 'baseline': baseline, 'properties': properties,
                                    'image': inventory[service]['image']}
    notify('backup-clickhouse')
    source = source_container('football-clickhouse')
    version = ch_query(source, 'SELECT version()').decode().strip()
    require(version == '25.8.23.13', 'UNSUPPORTED_CLICKHOUSE_VERSION')
    require(int(ch_query(source, "SELECT count() FROM system.mutations WHERE database='football' AND NOT is_done")) == 0,
            'ACTIVE_CLICKHOUSE_MUTATION')
    details['clickhouse_version'] = version
    details['serving'] = ch_baseline(source)
    details['schemas'] = {r['name']: ch_query(source, 'SHOW CREATE TABLE football.' + identifier(r['name']) +
                         ' FORMAT TabSeparatedRaw').decode().strip()
                         for r in ch_json(source, "SELECT name FROM system.tables WHERE database='football' ORDER BY name")}
    for table in details['serving']:
        raw = ch_query(source, 'SELECT * FROM football.' + identifier(table) + ' FORMAT Native')
        archive.add('ch-' + table + '.native.enc', raw, component='clickhouse', method='SELECT Native', version=version)
    require(ch_baseline(source) == details['serving'], 'SERVING_CHANGED_DURING_BACKUP')
    details['contexts'] = context_summary(source)
    require(details['contexts']['matches'] == [
        {'competition_id': 9, 'season_id': 281, 'matches': 34},
        {'competition_id': 43, 'season_id': 106, 'matches': 64}], 'CONTEXT_BASELINE_MISMATCH')
    details['reconciliation'] = reconcile(details['catalog'], details['serving'])
    notify('backup-grafana')
    sqlite = grafana_snapshot(inventory)
    details['grafana'] = sqlite_summary(sqlite)
    archive.add('grafana.sqlite.enc', sqlite, component='grafana', method='SQLite online backup API', version='13.0.1')
    notify('read-only-s3-inventory')
    details['s3'] = s3_inventory(details['catalog'])
    require(registry(source_container('football-postgres')) == details['catalog'], 'CATALOG_CHANGED_DURING_BACKUP')
    require(ch_baseline(source) == details['serving'], 'SERVING_CHANGED_DURING_BACKUP')
    details['configuration_sha256'] = {
        str(p.relative_to(ROOT)).replace('\\', '/'): digest(p.read_bytes())
        for folder in ('infrastructure/postgres', 'infrastructure/clickhouse', 'infrastructure/grafana/provisioning',
                       'infrastructure/grafana/dashboards')
        for p in sorted((ROOT / folder).rglob('*')) if p.is_file() and p.suffix in ('.sql', '.xml', '.yaml', '.yml', '.json')}
    archive.add('details.json.enc', encoded(details), component='recovery', method='catalog and baseline', version='1')
    manifest.update(consistency_status='PASS', verification_status='CHECKSUM_VERIFIED_NOT_YET_RESTORED',
        contexts=details['contexts']['matches'], build_ids=sorted({row['build_id'] for layer in ('silver', 'gold')
            for row in details['catalog'][layer + '_builds']}),
        backup_seconds=round(time.monotonic() - start, 3),
        consistency_model='Per-PG snapshot; fenced stable published catalog/serving; S3 GET manifests and metadata inventory; not global atomicity')
    archive.seal()
    load_archive(ROOT, identity)
    return {'backup_id': identity, 'status': 'BACKUP_VERIFIED', 'seconds': manifest['backup_seconds'],
            'encrypted_bytes': sum(a['file_size'] for a in manifest['artifacts']), 'restore_tested': False}


def validate_target(target):
    require(bool(re.fullmatch(r'football-drill-[a-z0-9]{8,24}', target)), 'ISOLATED_TARGET_REQUIRED')
    # Prefix collisions on any existing Docker resource are refused, regardless of its labels.
    for kind in ('container', 'volume', 'network'):
        args = ('ps', '-a', '--format', '{{.Names}}') if kind == 'container' else (kind, 'ls', '--format', '{{.Name}}')
        names = docker(*args).decode().splitlines()
        require(not any(name == target or name.startswith(target + '-') or name.startswith(target + '_') for name in names),
                'TARGET_RESOURCE_ALREADY_EXISTS')
    return target


def restore_plan(identity, target):
    archive, details = load_archive(ROOT, identity)
    validate_target(target)
    return {'backup_id': identity, 'target': target, 'network': 'none', 'ports': [], 'storage': 'new tmpfs only',
        'components': ['platform', 'airflow', 'superset', 'clickhouse', 'grafana'],
        'real_s3_connection': False, 'contexts': archive.manifest['contexts'],
        'status': 'PLAN_VALIDATED', 'source_versions': {k: v['version'] for k, v in details['postgres'].items()}}


def assert_isolated(container, target):
    info = container_info(container)
    require(info['labels'].get('com.docker.compose.project') == target and info['labels'].get('football.recovery') == '8c',
            'TARGET_LABEL_MISMATCH')
    require(info['network'] == 'none' and not info['ports'], 'TARGET_NETWORK_OR_PORT_UNSAFE')
    require(all(m['Type'] == 'tmpfs' for m in info['mounts']), 'TARGET_PERSISTENT_MOUNT_REFUSED')
    return info


class Drill:
    def __init__(self, target):
        self.target, self.created = target, []

    def start(self, name, image, *, mounts, environment):
        full = self.target + '-' + name
        args = ['run', '-d', '--name', full, '--network', 'none',
                '--label', 'com.docker.compose.project=' + self.target, '--label', 'football.recovery=8c']
        for mount in mounts:
            args += ['--tmpfs', mount]
        for entry in environment:
            args += ['-e', entry]  # Synthetic isolated credentials only.
        container = docker(*args, image).decode().strip()
        self.created.append(container)
        assert_isolated(container, self.target)
        return container

    def cleanup(self):
        for container in reversed(self.created):
            assert_isolated(container, self.target)
            # Exact IDs created by this invocation; tmpfs data is intentionally disposable.
            docker('rm', '-f', container)


def wait_for(check):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            check()
            return
        except RecoveryError:
            time.sleep(1)
    raise RecoveryError('ISOLATED_SERVICE_START_TIMEOUT')


def wait_for_postgres(container):
    # PostgreSQL's init-only server accepts Unix sockets but NOT TCP. Avoid that race.
    wait_for(lambda: docker('exec', container, 'pg_isready', '-h', '127.0.0.1', '-U', 'drill_admin', '-d', 'drill_control'))
    pg_query(container, 'SELECT 1')


def wait_for_clickhouse(container):
    def ready():
        # The image's entrypoint starts and stops an initialization server first.
        # Wait until PID 1 has exec'd the final server; a transient SELECT 1 is insufficient.
        executable = docker('exec', container, 'cat', '/proc/1/comm').decode().strip()
        require(executable == 'clickhouse-serv', 'CLICKHOUSE_INITIALIZING')
        require(int(ch_query(container, "SELECT count() FROM system.databases WHERE name='football'")) == 1,
                'CLICKHOUSE_DATABASE_INITIALIZING')
    wait_for(ready)


def restore_drill(identity, target, confirmed=False):
    require(confirmed, 'EXPLICIT_ISOLATION_CONFIRMATION_REQUIRED')
    restore_plan(identity, target)  # Full authentication before any target is created.
    archive, details = load_archive(ROOT, identity)
    start = time.monotonic()
    before = source_inventory()
    drill = Drill(target)
    results = {}
    try:
        for name in PG_SERVICES:
            notify('restore-postgres-' + name)
            config = details['postgres'][name]
            container = drill.start(name, config['image'], mounts=['/var/lib/postgresql/data'], environment=[
                'POSTGRES_USER=drill_admin', 'POSTGRES_DB=drill_control', 'POSTGRES_PASSWORD=isolated-synthetic-only'])
            wait_for_postgres(container)
            # Restore roles without authentication material. Preserve dump ownership and ACLs.
            pg_query(container, archive.read(name + '.roles.enc').decode())
            docker('exec', '-i', container, 'pg_restore', '--list', data=archive.read(name + '.dump.enc'))
            docker('exec', '-i', container, 'pg_restore', '-U', 'drill_admin', '-d', 'drill_control',
                   '--create', '--exit-on-error', data=archive.read(name + '.dump.enc'))
            database = config['properties']['database'][0]['datname']
            require(database != 'drill_control', 'DATABASE_NAME_COLLISION')
            # Docker exec override selects only the restored DB, never source credentials.
            baseline, properties, restored_catalog = validate_restored_pg(container, database, name)
            require(baseline == config['baseline'], 'RESTORED_POSTGRES_ROWS_DIFFER')
            for field in properties:
                actual, expected = properties[field], config['properties'][field]
                if field == 'database':
                    actual, expected = canonical_database_acl(actual), canonical_database_acl(expected)
                if field == 'schema':
                    actual, expected = canonical_columns(actual), canonical_columns(expected)
                require(actual == expected, 'RESTORED_POSTGRES_' + field.upper() + '_DIFFER')
            if name == 'platform':
                require(restored_catalog == details['catalog'], 'RESTORED_BUILD_REGISTRY_DIFFERS')
            results[name] = {'status': 'PASS', 'tables': len(baseline), 'rows': sum(v['rows'] for v in baseline.values())}
            docker('stop', '-t', '5', container)
        notify('restore-clickhouse')
        container = drill.start('clickhouse', details['source_inventory']['football-clickhouse']['image'],
            mounts=['/var/lib/clickhouse', '/var/log/clickhouse-server'], environment=[
                'CLICKHOUSE_DB=football', 'CLICKHOUSE_USER=drill_admin',
                'CLICKHOUSE_PASSWORD=isolated-synthetic-only', 'CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1'])
        wait_for_clickhouse(container)
        for table in details['serving']:
            ch_query(container, details['schemas'][table])
            ch_query(container, 'INSERT INTO football.' + identifier(table) + ' FORMAT Native',
                     archive.read('ch-' + table + '.native.enc'))
        pending = {k: v for k, v in details['schemas'].items() if k not in details['serving']}
        while pending:
            done = []
            for name, ddl in pending.items():
                try:
                    ch_query(container, ddl)
                    done.append(name)
                except RecoveryError:
                    pass  # Dependency order only; raw server errors remain suppressed.
            require(done, 'VIEW_DEPENDENCIES_NOT_RESTORED')
            for name in done:
                pending.pop(name)
        require(ch_baseline(container) == details['serving'], 'RESTORED_SERVING_DIFFERS')
        require(context_summary(container) == details['contexts'], 'RESTORED_CONTEXT_AGGREGATES_DIFFER')
        for table, expected in details['schemas'].items():
            actual = ch_query(container, 'SHOW CREATE TABLE football.' + identifier(table) + ' FORMAT TabSeparatedRaw').decode().strip()
            require(actual == expected, 'RESTORED_CLICKHOUSE_SCHEMA_DIFFERS')
        results['clickhouse'] = {'status': 'PASS', 'tables': len(details['serving']),
            'rows': sum(v['rows'] for v in details['serving'].values()), 'contexts': details['contexts'],
            'reconciliation': reconcile(details['catalog'], details['serving'])}
        notify('restore-grafana-sqlite')
        grafana = json.loads(docker('run', '--rm', '-i', '--network', 'none', '--read-only',
            '--name', target + '-grafana', '--label', 'com.docker.compose.project=' + target,
            '--label', 'football.recovery=8c', '--entrypoint', 'python', 'football-python-tools:3.12',
            '-c', GRAFANA_RESTORE, data=archive.read('grafana.sqlite.enc')))
        require(grafana == details['grafana'], 'GRAFANA_RESTORE_DIFFERS')
        results['grafana'] = {'status': 'PASS', 'tables': len(details['grafana']), 'application_started': False}
        for service, info in before.items():
            current = container_info(info['id'])
            require(current['id'] == info['id'] and current['started'] == info['started'], 'SOURCE_SERVICE_CHANGED')
        results['source_services_unchanged'] = True
    finally:
        drill.cleanup()
    report = {'backup_id': identity, 'target': target, 'status': 'PASS', 'scope': 'LOCAL_DATABASE_RESTORE',
        'restore_seconds': round(time.monotonic() - start, 3), 'components': results,
        'remote_s3_restore_tested': False, 'runtime_secret_files_restored': False, 'temporary_targets_removed': True,
        'manifest_sha256': digest((archive.directory / 'manifest.json').read_bytes())}
    report['authentication'] = hmac.new(archive.key, encoded(report), hashlib.sha256).hexdigest()
    exclusive_write(archive.directory / ('drill-' + target + '.json'), encoded(report))
    return report


def validate_restored_pg(container, database, name):
    target = (container, database)
    return pg_baseline(target), pg_properties(target), registry(target) if name == 'platform' else None
