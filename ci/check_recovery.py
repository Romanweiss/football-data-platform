"""Synthetic PG/CH restore integration. No live services, env files or S3."""
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.recovery.operations import Drill, validate_target, wait_for_clickhouse, wait_for_postgres
from src.recovery.runtime import (
    RecoveryError, ch_query, digest, docker, pg_args, pg_baseline, pg_query, pg_snapshot, require, run,
)


def main():
    target = 'football-drill-ci' + uuid.uuid4().hex[:12]
    validate_target(target)
    drill = Drill(target)
    try:
        env = ['POSTGRES_USER=drill_admin', 'POSTGRES_DB=drill_control', 'POSTGRES_PASSWORD=synthetic-only']
        source = drill.start('pgsource', 'postgres:17.6-alpine3.22', mounts=['/var/lib/postgresql/data'], environment=env)
        dest = drill.start('pgtarget', 'postgres:17.6-alpine3.22', mounts=['/var/lib/postgresql/data'], environment=env)
        for container in (source, dest):
            wait_for_postgres(container)
        pg_query(source, "CREATE TABLE fixture(id int PRIMARY KEY,build_id text,xg double precision); "
                 "INSERT INTO fixture VALUES(1,'synthetic-build',2.758305926),(2,'synthetic-build',2.272617949);")
        with pg_snapshot(source) as snapshot:
            baseline = pg_baseline(source, snapshot)
            # A concurrent source write must not enter either dump or snapshot baseline.
            pg_query(source, "INSERT INTO fixture VALUES(3,'later-build',0)")
            dump = run(pg_args(source, 'pg_dump', '--format=custom', '--snapshot=' + snapshot))
        docker('exec', '-i', dest, 'pg_restore', '-U', 'drill_admin', '-d', 'drill_control', '--exit-on-error', data=dump)
        require(pg_baseline(dest) == baseline, 'SYNTHETIC_PG_SNAPSHOT_RESTORE_MISMATCH')
        env = ['CLICKHOUSE_DB=football', 'CLICKHOUSE_USER=drill_admin', 'CLICKHOUSE_PASSWORD=synthetic-only']
        ch = drill.start('ch', 'clickhouse/clickhouse-server:25.8.23.13-alpine',
                         mounts=['/var/lib/clickhouse', '/var/log/clickhouse-server'], environment=env)
        wait_for_clickhouse(ch)
        ddl = '(id UInt32,build_id String,xg Nullable(Float64)) ENGINE=MergeTree ORDER BY id'
        ch_query(ch, 'CREATE TABLE football.source ' + ddl)
        ch_query(ch, 'CREATE TABLE football.target ' + ddl)
        ch_query(ch, "INSERT INTO football.source VALUES (1,'synthetic-build',2.758305926),(2,'synthetic-build',NULL)")
        raw = ch_query(ch, 'SELECT * FROM football.source FORMAT Native')
        ch_query(ch, 'INSERT INTO football.target FORMAT Native', raw)
        before = ch_query(ch, 'SELECT * FROM football.source ORDER BY ALL FORMAT JSONEachRow')
        after = ch_query(ch, 'SELECT * FROM football.target ORDER BY ALL FORMAT JSONEachRow')
        require(digest(before) == digest(after), 'SYNTHETIC_CH_RESTORE_MISMATCH')
        # Replaying a Native insert would duplicate rows: demonstrate why drills require fresh targets.
        ch_query(ch, 'INSERT INTO football.target FORMAT Native', raw)
        require(int(ch_query(ch, 'SELECT count()-uniqExact(id) FROM football.target')) == 2, 'DUPLICATE_DETECTION_FAILED')
        print('Synthetic PostgreSQL snapshot/restore, ClickHouse Native/precision/duplicates and isolation: PASS')
    finally:
        drill.cleanup()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Recovery integration FAIL: ' + (str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__))
        sys.exit(1)
