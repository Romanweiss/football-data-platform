"""Live metadata-only acceptance. Synthetic evidence is always rolled back."""
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from psycopg.errors import InsufficientPrivilege
from src.common.postgres import create_postgres_connection
from src.dq.model import Run, Rule
from src.dq.store import persist
from infrastructure.grafana.bootstrap import reader_connection
from infrastructure.grafana.verify import render

C = {'competition_id':4294967293, 'season_id':4294967293}
GRAFANA = Path(__file__).resolve().parents[2] / 'infrastructure/grafana'


class ObservabilityTests(unittest.TestCase):
    def test_latest_full_failure_partial_pass_warn_skip_and_rollback(self):
        with create_postgres_connection() as connection:
            with connection.transaction(force_rollback=True):
                success = Run(C, 'full')
                success.record(Rule('test.volume', 'structural', 'silver', 'events', 'Synthetic volume'), observed=10, expected=10, build_id='a'*64)
                persist(connection, success.report())
                failed = Run(C, 'full')
                failed.record(Rule('test.volume', 'structural', 'silver', 'events', 'Synthetic volume'), passed=False, observed=11, expected=10, build_id='a'*64)
                failed.record(Rule('test.optional', 'operational', 'api', 'matches', 'Synthetic optional', 'WARNING'), passed=False)
                failed.record(Rule('test.not_applicable', 'regression', 'serving', 'bi', 'Synthetic skip'), skip=True, reason='not applicable')
                persist(connection, failed.report())
                partial = Run(C, 'api')
                partial.record(Rule('test.partial', 'operational', 'api', 'matches', 'Synthetic partial'))
                persist(connection, partial.report())
                variables = dict(competition=C['competition_id'],season=C['season_id'],
                                 layer='__all',dataset='__all',severity='__all',status='__all',rule_id='__all')
                dashboard = json.loads((GRAFANA / 'dashboards/platform_dq.json').read_text())
                with connection.cursor() as cur:
                    cur.execute('SET LOCAL ROLE grafana_reader')
                    cur.execute('SELECT status,passed,failed,warnings,skipped,execution_id '
                                'FROM observability.dq_current_executions WHERE competition_id=%s AND season_id=%s',
                                (C['competition_id'],C['season_id']))
                    self.assertEqual(cur.fetchone(), ('FAIL',0,1,1,1,UUID(failed.execution_id)))
                    for panel in dashboard['panels']:
                        cur.execute(render(panel['targets'][0]['rawSql'], variables))
                        rows = cur.fetchall()
                        if panel['id'] == 1:
                            self.assertEqual(rows, [('FAIL',)])
                        elif panel['id'] == 9:
                            self.assertEqual({r[7] for r in rows}, {'FAIL','WARN','SKIP'})
                        elif panel['id'] == 12:
                            self.assertEqual(len(rows), 3)
                    cur.execute("SELECT numeric_observed FROM observability.dq_rule_history WHERE rule_id='test.optional' AND competition_id=%s", (C['competition_id'],))
                    self.assertIsNone(cur.fetchone()[0])
                    cur.execute('RESET ROLE')
            with connection.cursor() as cur:
                cur.execute('SELECT count(*) FROM metadata.dq_executions WHERE competition_id=%s AND season_id=%s',
                            (C['competition_id'], C['season_id']))
                self.assertEqual(cur.fetchone()[0], 0)

    def test_actual_reader_has_no_writes_ddl_underlying_tables_or_ownership(self):
        with reader_connection() as connection:
            with connection.cursor() as cur:
                cur.execute('SHOW transaction_read_only')
                self.assertEqual(cur.fetchone()[0], 'on')
                connection.rollback()
                # ACLs, not the easily overridden default, must block writes/DDL.
                cur.execute('SET SESSION default_transaction_read_only=off')
                connection.commit()
                cur.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")
                self.assertEqual(cur.fetchone(), (False,)*5)
                cur.execute("SELECT count(*) FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)")
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)")
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute("SELECT count(*) FROM pg_namespace WHERE has_schema_privilege(oid,'CREATE')")
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute("SELECT count(*) FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace "
                            "WHERE n.nspname='metadata' AND t.relkind IN ('r','v','m') "
                            "AND (has_table_privilege(t.oid,'SELECT') OR has_table_privilege(t.oid,'INSERT') "
                            "OR has_table_privilege(t.oid,'UPDATE') OR has_table_privilege(t.oid,'DELETE'))")
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute("SELECT has_database_privilege(current_database(),'CREATE'),has_database_privilege(current_database(),'TEMP')")
                self.assertEqual(cur.fetchone(), (False,False))
                connection.rollback()
                for statement in (
                    'INSERT INTO metadata.dq_executions SELECT * FROM metadata.dq_executions WHERE false',
                    'UPDATE metadata.dq_results SET message=message WHERE false',
                    'DELETE FROM metadata.dq_results WHERE false',
                    'CREATE TABLE observability.grafana_permission_probe (id integer)',
                    'CREATE TABLE public.grafana_permission_probe (id integer)',
                    'CREATE TEMP TABLE grafana_permission_probe (id integer)',
                    'SELECT * FROM metadata.dq_results LIMIT 0',
                ):
                    with self.subTest(operation=statement.split()[0]):
                        with connection.transaction(force_rollback=True):
                            with self.assertRaises(InsufficientPrivilege):
                                cur.execute(statement)

    def test_queries_match_live_latest_full_not_history(self):
        with create_postgres_connection() as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT competition_id,season_id,status,passed,failed,warnings,skipped '
                            'FROM observability.dq_current_executions ORDER BY competition_id,season_id')
                rows = cur.fetchall()
                self.assertTrue({(43,106),(9,281)} <= {(row[0],row[1]) for row in rows})
                # Reconcile with authoritative Stage 7A tables, not stale fixture counts.
                cur.execute("SELECT e.competition_id,e.season_id,e.status,"
                            "count(*) FILTER(WHERE r.status='PASS'),count(*) FILTER(WHERE r.status='FAIL'),"
                            "count(*) FILTER(WHERE r.status='WARN'),count(*) FILTER(WHERE r.status='SKIP') "
                            "FROM metadata.dq_latest_executions e JOIN metadata.dq_results r USING(execution_id) "
                            "WHERE e.suite='full' GROUP BY e.competition_id,e.season_id,e.status ORDER BY 1,2")
                self.assertEqual(rows, cur.fetchall())
                cur.execute("SELECT count(*) FROM observability.dq_execution_history WHERE suite='full'")
                self.assertGreater(cur.fetchone()[0], len(rows))


if __name__ == '__main__':
    unittest.main()
