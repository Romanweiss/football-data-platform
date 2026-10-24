"""CI boundary regressions; no platform connections."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml
from ci.check_repository import PUBLICATION_REQUIRED, publication_contract, workflow_contract, secret_findings
from ci.databases import guard
from ci.run_unittest import enter_context, install_compatibility

ROOT = Path(__file__).resolve().parents[2]


class CIContractTests(unittest.TestCase):
    def test_publication_requires_all_delivery_and_recovery_sources_in_git(self):
        publication_contract(PUBLICATION_REQUIRED)
        for missing in PUBLICATION_REQUIRED:
            with self.subTest(missing=missing), self.assertRaisesRegex(AssertionError, 'missing from Git index'):
                publication_contract(PUBLICATION_REQUIRED - {missing})

    def test_publication_rejects_private_artifacts_before_content_reads(self):
        for name in ('.env', '.passes', 'keys.txt', 'backups/manifest.json', 'backups/production.dump.enc',
                     '.recovery-keys/recovery.key', 'data/work/state.json', 'restore.sql.dump',
                     'frontend/node_modules/package.json', 'frontend/test-results/report.json',
                     'data/raw/object.json', '.tmp/runtime.json', 'tmp/key-material.json',
                     'restore.sqlite3', 'archive.backup', 'private.pfx', 'host-ca.crt', 'host-ca.cer',
                     'FootballRecoveryVault/s3/receipt.json', 'FootballPlatformBackups/s3/manifest.json'):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                publication_contract(PUBLICATION_REQUIRED | {name})

    def test_s3_recovery_is_explicit_on_both_linux_versions_and_windows(self):
        fast = yaml.load((ROOT / '.github/workflows/ci-fast.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertIn('python ci/check_s3_recovery.py', [s.get('run') for s in fast['jobs']['python']['steps']])
        integration = yaml.load((ROOT / '.github/workflows/ci-integration.yml').read_text(), Loader=yaml.BaseLoader)
        job = integration['jobs']['s3-recovery-windows']
        self.assertEqual(job['runs-on'], 'windows-2022')
        self.assertEqual(job['defaults']['run']['shell'], 'powershell')
        self.assertGreaterEqual(int(job['timeout-minutes']), 20)
        setup = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/setup-python@'))
        self.assertEqual(setup['with']['python-version'], '3.12.10')
        linux_setup = next(s for s in integration['jobs']['recovery']['steps']
                           if s.get('uses', '').startswith('actions/setup-python@'))
        self.assertEqual(linux_setup['with']['python-version'], '3.12.14')
        recovery_run = next(s['run'] for s in job['steps'] if 'python ci/check_s3_recovery.py' in s.get('run', ''))
        self.assertIn('SetTokenInformation(identity.Token, 4,', recovery_run)
        self.assertIn('Assign(identity.User)', recovery_run)
        self.assertIn('Assign(previous)', recovery_run)
        self.assertIn('} finally {', recovery_run)
        self.assertIn('$scope.Dispose()', recovery_run)
        self.assertIn('exit $testExit', recovery_run)
        self.assertNotIn('continue-on-error', job)
        self.assertNotIn('if', job)
        self.assertFalse(any('upload-artifact' in s.get('uses', '') for s in job['steps']))
        invalid = deepcopy(integration)
        invalid['jobs']['recovery']['runs-on'] = 'windows-2022'
        with self.assertRaises(AssertionError):
            workflow_contract(invalid)

    def test_s3_sources_cannot_be_omitted_from_publication(self):
        for name in ('src/recovery/s3_archive.py', 'src/recovery/s3_safety.py', 'requirements/recovery-s3.txt',
                     'ci/check_s3_recovery.py', 'tests/test_s3_windows_acl.py'):
            self.assertIn(name, PUBLICATION_REQUIRED)

    def test_offline_restore_sources_required_and_discovered_without_operator_execution(self):
        paths = {'src/recovery/s3_offline_restore.py', 'scripts/restore_s3_offline.py',
                 'tests/test_s3_offline_restore.py', 'docs/stage8c-r2-4a2-4a.md'}
        for path in paths:
            self.assertIn(path, PUBLICATION_REQUIRED)
            with self.assertRaises(AssertionError):
                publication_contract(PUBLICATION_REQUIRED - {path})
        self.assertIn(ROOT / 'tests/test_s3_offline_restore.py', list((ROOT / 'tests').glob('test_s3_*.py')))
        gate = (ROOT / 'ci/check_s3_recovery.py').read_text()
        self.assertNotIn('restore_s3_offline.py', gate)

    def test_windows_host_and_manual_escrow_sources_are_required_and_discovered(self):
        sources = ('s3_host', 's3_diagnostics', 's3_manual_drill')
        scripts = ('check_s3_host_readiness', 'show_synthetic_escrow_key', 'receive_synthetic_escrow_key')
        for name in sources:
            self.assertIn(f'src/recovery/{name}.py', PUBLICATION_REQUIRED)
        for name in scripts:
            self.assertIn(f'scripts/{name}.py', PUBLICATION_REQUIRED)
        for name in (*sources, 's3_escrow'):
            path = f'tests/test_{name}.py'
            self.assertIn(path, PUBLICATION_REQUIRED)
            self.assertIn(ROOT / path, list((ROOT / 'tests').glob('test_s3_*.py')))
        for suffix in ('', '-5', '-6', '-7', '-publication'):
            self.assertIn(f'docs/stage8c-r2-4a1{suffix}.md', PUBLICATION_REQUIRED)

    def test_s3_gate_forbids_network_and_does_not_invoke_operator(self):
        source = (ROOT / 'ci/check_s3_recovery.py').read_text()
        self.assertIn("patch('socket.socket'", source)
        self.assertIn("patch('socket.create_connection'", source)
        self.assertIn("pattern='test_s3_*.py'", source)
        self.assertIn("pattern='test_recovery.py'", source)
        self.assertIn('importlib.util.find_spec', source)
        self.assertIn('install_compatibility()', source)
        self.assertNotIn('build_sources(', source)
        self.assertNotIn('s3_backup.py create', source)

    def test_production_key_helpers_are_publishable_but_private_state_is_not(self):
        for name in ('src/recovery/s3_key_escrow.py', 'scripts/show_s3_recovery_key.py',
                     'scripts/receive_s3_recovery_key.py', 'tests/test_s3_key_escrow.py',
                     'tests/test_s3_key_recovery.py', 'docs/stage8c-r2-4a2-1.md',
                     'docs/stage8c-r2-4a2-2.md'):
            self.assertIn(name, PUBLICATION_REQUIRED)
        for name in ('FootballRecoveryVault/s3/key.recovery-attempt.json',
                     'FootballRecoveryVault/s3/key.json', 'FootballRecoveryVault/s3/key.key'):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                publication_contract(PUBLICATION_REQUIRED | {name})
        gate = (ROOT / 'ci/check_s3_recovery.py').read_text()
        self.assertIn("pattern='test_s3_*.py'", gate)
        for name in ('test_s3_key_escrow.py', 'test_s3_key_recovery.py'):
            self.assertIn(ROOT / 'tests' / name, list((ROOT / 'tests').glob('test_s3_*.py')))

    def test_context_compatibility_retains_return_value_and_deferred_cleanup(self):
        calls = []
        class Context:
            def __enter__(self):
                calls.append('enter')
                return 'value'
            def __exit__(self, *args):
                calls.append(args)
        case = unittest.TestCase()
        self.assertEqual(enter_context(case, Context()), 'value')
        self.assertEqual(calls, ['enter'])
        case.doCleanups()
        self.assertEqual(calls, ['enter', (None, None, None)])

    def test_context_cleanup_runs_after_failed_test_without_hiding_failure(self):
        calls = []
        class Context:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                calls.append(args)
                return True
        class FailingCase(unittest.TestCase):
            def runTest(self):
                enter_context(self, Context())
                self.fail('synthetic failure')
        result = FailingCase().run()
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(calls, [(None, None, None)])

    def test_context_compatibility_preserves_native_method_when_available(self):
        original = getattr(unittest.TestCase, 'enterContext', None)
        install_compatibility()
        self.assertIs(unittest.TestCase.enterContext, original or enter_context)

    def test_fast_python_gate_covers_both_actual_runtime_versions(self):
        document = yaml.load((ROOT / '.github/workflows/ci-fast.yml').read_text(), Loader=yaml.BaseLoader)
        job = document['jobs']['python']
        self.assertEqual(job['strategy']['matrix']['python-version'], ['3.10.12', '3.12.14'])
        self.assertEqual(job['strategy']['fail-fast'], 'false')
        setup = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/setup-python@'))
        self.assertEqual(setup['with']['python-version'], '${{ matrix.python-version }}')
        self.assertIn('${{ matrix.python-version }}', job['name'])

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
