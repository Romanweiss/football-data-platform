"""Stage 7A schema tests: all synthetic rows are rolled back, no live data modified."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import unittest
from psycopg.errors import UniqueViolation, CheckViolation
from src.common.postgres import create_postgres_connection
from src.dq.model import Run, Rule
from src.dq.store import persist, summary


class DQSchemaTests(unittest.TestCase):
    def test_append_history_multiple_contexts_builds_failures_and_summary(self):
        c = {'competition_id':4294967293, 'season_id':4294967293}
        rule = Rule('test.grain', 'structural', 'silver', 'events', 'Synthetic rolled-back grain')
        with create_postgres_connection() as connection:
            with connection.transaction(force_rollback=True):
                a, b = Run(c, 'full'), Run(c, 'full')
                a.record(rule, build_id='a'*64, observed=10)
                b.record(rule, build_id='a'*64, passed=False, observed=11)
                persist(connection, a.report())
                persist(connection, b.report())
                result = summary(connection, c)
                self.assertEqual(result['execution_id'], b.execution_id)
                self.assertEqual(result['status'], 'FAIL')
                self.assertEqual(result['previous_success'], a.execution_id)
                self.assertTrue(result['results'][0]['changed'])
                with self.assertRaises(UniqueViolation):
                    persist(connection, b.report())
                with connection.cursor() as cur:
                    cur.execute('SELECT count(*) FROM metadata.dq_executions WHERE execution_id IN (%s,%s)',
                                (a.execution_id,b.execution_id))
                    self.assertEqual(cur.fetchone()[0], 2)
                other = Run({**c,'season_id':4294967292}, 'full')
                other.record(rule, build_id='b'*64)
                persist(connection, other.report())
                self.assertEqual(summary(connection, c)['status'], 'FAIL')
                linked = Run(c, 'full', airflow={'dag_id':'fixture','run_id':'manual__fixture','task_id':'validation'})
                linked.record(Rule('test.new_rule', 'operational', 'api', 'matches', 'Synthetic new rule'), observed=1)
                persist(connection, linked.report())
                changed = summary(connection, c)
                self.assertEqual(changed['added_rules'], ['test.new_rule'])
                self.assertEqual(changed['removed_rules'], ['test.grain'])
                self.assertTrue(changed['results'][0]['changed'])
                self.assertEqual(summary(connection, c, build_id='a'*64)['execution_id'], b.execution_id)
                invalid_payload = Run(c, 'full')
                invalid_payload.record(rule)
                report = invalid_payload.report()
                report['results'][0]['observed'] = {'event_json':'not permitted'}
                with self.assertRaises(CheckViolation):
                    persist(connection, report)
                with connection.cursor() as cur:
                    cur.execute('SELECT count(*) FROM metadata.dq_executions WHERE execution_id=%s', (report['execution_id'],))
                    self.assertEqual(cur.fetchone()[0], 0)
                invalid = Run(c, 'full').report()
                invalid['competition_id'] = 0
                with self.assertRaises(CheckViolation):
                    persist(connection, invalid)
            with connection.cursor() as cur:
                cur.execute('SELECT count(*) FROM metadata.dq_executions WHERE execution_id IN (%s,%s,%s)',
                            (a.execution_id,b.execution_id,other.execution_id))
                self.assertEqual(cur.fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
