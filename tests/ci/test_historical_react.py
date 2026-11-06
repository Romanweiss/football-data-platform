"""PET-3C completeness, bounded same-origin transport and synthetic CI separation."""
from pathlib import Path
import json
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    'frontend/src/historical/types.ts', 'frontend/src/historical/source.ts',
    'frontend/src/historical/filters.ts', 'frontend/src/historical/messages.ts',
    'frontend/src/historical/HistoricalCompetitions.tsx', 'frontend/src/historical/historical.css',
    'frontend/tests/historical-fixtures.ts', 'frontend/tests/historical-source.test.ts',
    'frontend/tests/historical.test.tsx', 'frontend/tests/smoke/historical.spec.ts',
    'frontend/tests/historical-live.spec.ts', 'frontend/playwright.historical.config.ts',
    'docs/pet3c-historical-react.md',
)


class HistoricalReactContracts(unittest.TestCase):
    def test_source_tests_and_runbook_are_complete_and_non_secret(self):
        for name in FILES:
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertFalse(secret_findings((ROOT / name).read_text(encoding='utf-8')), name)

    def test_production_adapter_never_imports_test_fixtures_or_live_provider(self):
        for name in FILES[:6]:
            source = (ROOT / name).read_text(encoding='utf-8')
            for forbidden in ('historical-fixtures', 'createSyntheticLeague', 'football-data.org', 'localStorage',
                              'process.env', 'Authorization', 'X-Auth-Token'):
                self.assertNotIn(forbidden, source, name)
        source = (ROOT / FILES[1]).read_text(encoding='utf-8')
        for required in ("'/api/v1/competitions/historical'", "redirect: 'error'", "credentials: 'same-origin'",
                         '1024 * 1024', 'sameHistoricalContext', 'rows.length > 100', 'reader.cancel()'):
            self.assertIn(required, source)

    def test_ci_browser_is_mocked_and_real_gold_browser_is_opt_in(self):
        config = (ROOT / 'frontend/playwright.ci.config.ts').read_text()
        self.assertIn('**/historical.spec.ts', config)
        self.assertNotIn('historical-live.spec.ts', config)
        source = (ROOT / FILES[9]).read_text()
        for required in ('synthetic contexts:', 'route.fulfill', 'AxeBuilder', 'page.goBack()', 'page.goForward()', 'page.reload()'):
            self.assertIn(required, source)
        self.assertIn("PET3C_ISOLATED_BROWSER !== 'true'", (ROOT / FILES[11]).read_text())
        typescript = json.loads((ROOT / 'frontend/tsconfig.json').read_text())
        self.assertIn('playwright.historical.config.ts', typescript['include'])

    def test_runbook_preserves_source_only_and_production_boundaries(self):
        text = (ROOT / FILES[12]).read_text(encoding='utf-8')
        for value in ('189', '36', '394', 'UNKNOWN', 'INCOMPLETE', 'source-reported', '503',
                      'not deployed', 'Stage 8C: PARTIAL', 'coverage', 'pagination'):
            self.assertIn(value, text)


if __name__ == '__main__':
    unittest.main()
