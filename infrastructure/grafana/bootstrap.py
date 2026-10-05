"""One-off private credential/ACL bootstrap; no secret values in normal output."""
import os
from pathlib import Path
import secrets
import sys

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.postgres import create_postgres_connection

ROOT = Path('/run/grafana-secrets')
VIEWS = ('dq_execution_history', 'dq_current_executions', 'dq_rule_history', 'dq_current_results')


def reader_connection():
    # Runtime-only consumer; callers must never print DSNs or raw exceptions.
    return psycopg.connect(host=os.environ['POSTGRES_HOST'], port=os.environ['POSTGRES_PORT'],
                           dbname=os.environ['POSTGRES_DB'], user='grafana_reader',
                           password=(ROOT / 'reader_password').read_text().strip(), connect_timeout=10)


def bootstrap():
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chown(ROOT, 472, 0)
    os.chmod(ROOT, 0o750)
    with create_postgres_connection() as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('observability.dq_current_executions')")
            if cur.fetchone()[0] is None:
                raise RuntimeError('Apply migration 007 before bootstrapping')
            cur.execute("SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit "
                        "FROM pg_roles WHERE rolname='grafana_reader'")
            existing = cur.fetchone()
            if existing and (any(existing[1:]) or not (ROOT / 'reader_password').exists()):
                raise RuntimeError('Existing reader role needs operator review; no password rotation')
            if existing:
                cur.execute("SELECT EXISTS(SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname='grafana_reader')) "
                            "OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname='grafana_reader')) "
                            "OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='grafana_reader'))")
                if cur.fetchone()[0]:
                    raise RuntimeError('Reader ownership or memberships need operator review')
            for name in ('reader_password', 'admin_password'):
                path = ROOT / name
                if not path.exists():
                    with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o640)) as out:
                        out.write(secrets.token_urlsafe(40))
                    os.chown(path, 472, 0)
                if not path.stat().st_size:
                    raise RuntimeError('Empty secret file; operator recovery required')
            if not existing:
                # Secret-bearing role DDL must not enter routine PG statement/error logs.
                cur.execute("SET LOCAL log_statement = 'none'")
                cur.execute("SET LOCAL log_min_error_statement = 'panic'")
                cur.execute(sql.SQL('CREATE ROLE grafana_reader LOGIN NOSUPERUSER NOCREATEDB '
                                    'NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}')
                            .format(sql.Literal((ROOT / 'reader_password').read_text().strip())))
            cur.execute("SELECT current_database()")
            database = sql.Identifier(cur.fetchone()[0])
            # PostgreSQL's default PUBLIC TEMP grant would permit temporary DDL.
            # Preserve effective TEMP access for existing login roles, then remove
            # the PUBLIC grant in this platform DB only (never touch Airflow DB).
            cur.execute("SELECT rolname FROM pg_roles WHERE rolcanlogin AND rolname <> 'grafana_reader' "
                        "AND has_database_privilege(rolname,current_database(),'TEMP')")
            for (name,) in cur.fetchall():
                cur.execute(sql.SQL('GRANT TEMP ON DATABASE {} TO {}').format(database, sql.Identifier(name)))
            cur.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(database))
            cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO grafana_reader').format(database))
            cur.execute('GRANT USAGE ON SCHEMA observability TO grafana_reader')
            for view in VIEWS:
                cur.execute(sql.SQL('GRANT SELECT ON observability.{} TO grafana_reader').format(sql.Identifier(view)))
            cur.execute("ALTER ROLE grafana_reader SET default_transaction_read_only = on")
            cur.execute("ALTER ROLE grafana_reader SET statement_timeout = '10s'")
            cur.execute("ALTER ROLE grafana_reader SET idle_in_transaction_session_timeout = '15s'")
    with reader_connection() as connection:
        with connection.cursor() as cur:
            cur.execute('SELECT count(*) FROM observability.dq_current_executions')
            cur.fetchone()
    print('Grafana runtime secrets preserved; approved read-only views accessible')


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'init'
    if action == 'init':
        bootstrap()
    elif action == 'ui-password':
        # Explicit operator-only clipboard retrieval. Never called by tests/logging.
        sys.stdout.write((ROOT / 'admin_password').read_text().strip())
    else:
        raise ValueError('Unknown bootstrap action')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Grafana bootstrap failed: exception={type(exc).__name__}', file=sys.stderr)
        sys.exit(1)
