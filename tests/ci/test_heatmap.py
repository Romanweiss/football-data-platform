"""Pressure feature completeness and bounded/offline CI contracts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class HeatmapCompletenessTests(unittest.TestCase):
    def test_required_sources_and_runbook_exist(self):
        for name in ('application/heatmap.py', 'tests/application/test_heatmap.py',
                     'frontend/src/pressureDensity.ts', 'frontend/tests/density.test.tsx',
                     'frontend/src/components/PressureHeatmap.tsx', 'frontend/tests/heatmap.test.tsx',
                     'frontend/tests/smoke/pressure-heatmap.spec.ts', 'docs/stage9b2.md',
                     'tests/integration/test_clickhouse_heatmap.py',
                     'docs/stage9b1-deployment.md'):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_synthetic_browser_is_in_existing_offline_fixture_gate(self):
        config = (ROOT / 'frontend/playwright.ci.config.ts').read_text(encoding='utf-8')
        self.assertIn('**/pressure-heatmap.spec.ts', config)
        self.assertIn('grep: /synthetic contexts:/', config)
        self.assertIn('reuseExistingServer: false', config)
        for name in ('ci-fast.yml', 'ci-integration.yml'):
            workflow = (ROOT / '.github/workflows' / name).read_text(encoding='utf-8')
            self.assertNotIn('secrets.', workflow)

    def test_packaged_ci_image_contains_both_readmes_required_by_contracts(self):
        dockerfile = (ROOT / 'ci/Dockerfile').read_text(encoding='utf-8')
        copies = [line.split()[1:-1] for line in dockerfile.splitlines() if line.startswith('COPY ')]
        self.assertTrue(any({'README.md', 'README.ru.md', '.gitignore'} <= set(paths) for paths in copies))
        original = (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
        ci_rules = (ROOT / 'ci/Dockerfile.dockerignore').read_text(encoding='utf-8').splitlines()
        self.assertEqual(ci_rules, original + ['', '# CI boundary tests need the public rules file, never the ignored private files.', '!.gitignore'])
