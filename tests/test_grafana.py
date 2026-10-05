"""Offline dashboard/provisioning/security contract checks, no runtime secrets."""
import json
import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from infrastructure.grafana.verify import render, frame_rows
from infrastructure.grafana import bootstrap

ROOT = Path(__file__).resolve().parents[1]
GRAFANA = ROOT / 'infrastructure/grafana'


class GrafanaContractTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = json.loads((GRAFANA / 'dashboards/platform_dq.json').read_text(encoding='utf-8'))

    def test_provisioning_identity_and_native_postgresql(self):
        datasource = (GRAFANA / 'provisioning/datasources/platform.yaml').read_text()
        provider = (GRAFANA / 'provisioning/dashboards/platform.yaml').read_text()
        for required in ('uid: football-metadata-dq', 'user: grafana_reader', 'editable: false',
                         'password: $GRAFANA_READER_PASSWORD', 'database: $POSTGRES_DB'):
            self.assertIn(required, datasource)
        self.assertIn('allowUiUpdates: false', provider)
        self.assertIn('path: /etc/grafana/dashboards', provider)
        self.assertEqual(self.dashboard['uid'], 'football-platform-dq')
        self.assertEqual(self.dashboard['title'], 'Football Data Platform — Data Quality')
        self.assertEqual(self.dashboard['time']['from'], 'now-90d')
        for panel in self.dashboard['panels']:
            self.assertEqual(panel['datasource']['uid'], 'football-metadata-dq')
            self.assertTrue(all(t['rawSql'].startswith('SELECT ') for t in panel['targets']))

    def test_chained_dynamic_context_and_rule_variables(self):
        variables = {v['name']: v for v in self.dashboard['templating']['list']}
        self.assertEqual(set(variables), {'competition','season','layer','dataset','severity','status','rule_id'})
        self.assertIn('${competition:sqlstring}', variables['season']['query'])
        for variable in variables.values():
            self.assertIn('observability.', variable['query'])
            self.assertFalse(variable['multi'])
        for name in ('layer','dataset','severity','status','rule_id'):
            self.assertEqual(variables[name]['current']['value'], '__all')
            self.assertFalse(variables[name]['includeAll'])  # sentinel gets SQL-quoted normally

    def test_current_health_does_not_sum_or_time_filter_history(self):
        panels = {p['id']: p for p in self.dashboard['panels']}
        for id_ in range(1, 7):
            query = panels[id_]['targets'][0]['rawSql']
            self.assertIn('observability.dq_current_executions', query)
            self.assertNotIn('$__timeFilter', query)
            self.assertNotIn('${status:', query)
        self.assertNotIn('${competition', panels[8]['targets'][0]['rawSql'])
        for id_ in (9, 10, 12, 13):
            self.assertIn('$__timeFilter', panels[id_]['targets'][0]['rawSql'])
            self.assertIn('LIMIT ', panels[id_]['targets'][0]['rawSql'])

    def test_explicit_status_mappings_and_bounded_drilldown(self):
        panel = next(p for p in self.dashboard['panels'] if p['id'] == 1)
        values = panel['fieldConfig']['defaults']['mappings'][0]['options']
        self.assertEqual(panel['options']['reduceOptions']['fields'], '/^status$/')
        self.assertEqual(set(values), {'PASS','FAIL','WARN','SKIP'})
        self.assertEqual(values['FAIL']['color'], 'red')
        self.assertEqual(values['WARN']['color'], 'orange')
        self.assertNotEqual(values['SKIP']['color'], values['FAIL']['color'])
        self.assertTrue(all(v['text'].startswith(k) for k,v in values.items()))
        recent = next(p for p in self.dashboard['panels'] if p['id'] == 9)
        self.assertIn('var-rule_id=', json.dumps(recent['fieldConfig']))

    def test_migration_reuses_latest_scope_and_does_not_mutate_dq(self):
        migration = (ROOT / 'infrastructure/postgres/migrations/007_create_dq_observability_views.sql').read_text()
        self.assertIn('metadata.dq_latest_executions', migration)
        self.assertIn("WHERE e.suite = 'full'", migration)
        self.assertEqual(migration.count('CREATE OR REPLACE VIEW observability.'), 4)
        for forbidden in ('INSERT INTO', 'UPDATE metadata.', 'DELETE FROM', 'TRUNCATE', 'DROP '):
            self.assertNotIn(forbidden, migration)
        self.assertIn("jsonb_typeof(r.observed) = 'number'", migration)

    def test_compose_has_local_auth_health_persistence_and_no_pipeline_dependency(self):
        compose = (ROOT / 'compose.yaml').read_text()
        service = compose.split('  football-grafana:\n')[1].split('\n  football-airflow-bootstrap:')[0]
        self.assertIn('grafana/grafana:13.0.1', service)
        self.assertIn('127.0.0.1:${GRAFANA_HOST_PORT:-13000}:3000', service)
        self.assertIn('GF_AUTH_ANONYMOUS_ENABLED: "false"', service)
        self.assertIn('GF_SECURITY_ADMIN_PASSWORD__FILE:', service)
        self.assertIn('football_grafana_data:/var/lib/grafana', service)
        self.assertIn('/api/health', service)
        remaining = compose.split('  football-airflow-bootstrap:')[1]
        self.assertNotIn('football-grafana', remaining.split('\nvolumes:\n')[0])

    def test_no_credential_fields_in_dashboard_and_runtime_only_passwords(self):
        serialized = json.dumps(self.dashboard).lower()
        for forbidden in ('password', 'postgres://', 'postgresql://', 's3_access_key', 's3_secret_key', 'securejsondata'):
            self.assertNotIn(forbidden, serialized)
        bootstrap = (GRAFANA / 'bootstrap.py').read_text()
        self.assertIn('secrets.token_urlsafe', bootstrap)
        self.assertIn("open(path, 'x'", bootstrap)
        self.assertIn('NOCREATEDB', bootstrap)
        self.assertIn('NOCREATEROLE', bootstrap)
        self.assertIn('REVOKE TEMP ON DATABASE', bootstrap)
        self.assertNotIn('GRANT ALL', bootstrap)
        self.assertNotIn('GRANT SELECT ON ALL', bootstrap)

    def test_numeric_observations_do_not_fabricate_boolean_pass_values(self):
        panels = {p['id']: p for p in self.dashboard['panels']}
        self.assertIn('numeric_observed IS NOT NULL', panels[13]['targets'][0]['rawSql'])
        self.assertNotIn('coalesce', panels[13]['targets'][0]['rawSql'].lower())
        self.assertIn('observed::text', panels[10]['targets'][0]['rawSql'])
        self.assertIn('to_timestamp(numeric_observed::double precision)', panels[14]['targets'][0]['rawSql'])

    def test_verification_renderer_escapes_text_and_preserves_null_frames(self):
        self.assertEqual(render("SELECT ${rule_id:sqlstring}", {'rule_id': "x' OR true--"}), "SELECT 'x'' OR true--'")
        frame = {'frames':[{'schema':{'fields':[{'name':'value'}]},'data':{'values':[[None,10]]}}]}
        self.assertEqual(frame_rows(frame), [{'value':None},{'value':10}])

    def test_bootstrap_preserves_existing_secrets_and_does_not_log_values(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('reader_password','admin_password'):
                (root / name).write_text('synthetic-private-' + name)
            writer, reader = MagicMock(), MagicMock()
            cur = writer.__enter__.return_value.cursor.return_value.__enter__.return_value
            cur.fetchone.side_effect = [('view',), ('grafana_reader',False,False,False,False,False,False),
                                       (False,), ('fixture_database',)]
            cur.fetchall.return_value = []
            output = io.StringIO()
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap, 'create_postgres_connection', return_value=writer), \
                 patch.object(bootstrap, 'reader_connection', return_value=reader), patch.object(bootstrap.os, 'chown'), \
                 patch.object(bootstrap.os, 'chmod'), patch.object(bootstrap.secrets, 'token_urlsafe', side_effect=AssertionError('No rotation')), \
                 contextlib.redirect_stdout(output):
                bootstrap.bootstrap()
            self.assertNotIn('synthetic-private', output.getvalue())
            for name in ('reader_password','admin_password'):
                self.assertEqual((root / name).read_text(), 'synthetic-private-' + name)
            self.assertFalse(any('CREATE ROLE' in str(call) for call in cur.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
