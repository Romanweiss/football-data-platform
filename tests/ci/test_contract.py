"""CI boundary regressions; no platform connections."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml
from ci.check_repository import workflow_contract, secret_findings
from ci.databases import guard

ROOT = Path(__file__).resolve().parents[2]


class CIContractTests(unittest.TestCase):
    def test_workflows_are_read_only_and_secret_free(self):
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            workflow_contract(document)
            for key, value in [('permissions', {'contents':'write'}), ('on', {'pull_request_target':{}})]:
                invalid = deepcopy(document)
                invalid[key] = value
                with self.assertRaises(AssertionError):
                    workflow_contract(invalid)

    def test_database_harness_rejects_live_or_missing_configuration(self):
        for environment in ({}, {'PLATFORM_CI_EPHEMERAL':'true','POSTGRES_HOST':'football-postgres',
                                 'POSTGRES_DB':'football_metadata','POSTGRES_USER':'ci'}):
            with patch.dict(os.environ, environment, clear=True):
                for kind in ('postgres','clickhouse'):
                    with self.assertRaises(RuntimeError):
                        guard(kind)

    def test_ci_services_have_no_ports_developer_mounts_or_external_network(self):
        config = yaml.safe_load((ROOT / 'ci/compose.yaml').read_text())
        self.assertTrue(config['networks']['isolated']['internal'])
        for service in config['services'].values():
            for forbidden in ('ports','volumes','env_file','external','container_name'):
                self.assertNotIn(forbidden, service)
        self.assertEqual(config['services']['checks']['environment']['POSTGRES_HOST'],'ci-postgres')

    def test_signature_findings_do_not_return_secret_values(self):
        fake = 'AK' + 'IA' + 'Z'*16
        result = secret_findings('label\n' + fake)
        self.assertEqual(result, [(2, 'aws-access-key')])
        self.assertNotIn(fake, str(result))
        self.assertEqual(secret_findings('S3_SECRET_KEY=change_me'), [])

    def test_browser_gate_selects_only_synthetic_tests(self):
        config = (ROOT / 'frontend/playwright.ci.config.ts').read_text()
        self.assertIn('grep: /synthetic contexts:/',config)
        self.assertIn('reuseExistingServer: false',config)
        self.assertNotIn('process.env.WEB_BASE_URL',config)


if __name__ == '__main__':
    unittest.main()
