"""Synthetic-only frontend source completeness and transport isolation."""
from pathlib import Path
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    'frontend/src/current/types.ts', 'frontend/src/current/synthetic.ts',
    'frontend/src/current/source.ts', 'frontend/src/current/filters.ts',
    'frontend/src/current/messages.ts', 'frontend/src/current/CurrentCompetitions.tsx',
    'frontend/src/current/current.css', 'frontend/tests/current-data.test.ts',
    'frontend/tests/current.test.tsx', 'frontend/tests/smoke/current-competitions.spec.ts',
    'docs/stage9c4-current-competitions-ui.md',
)


class CurrentCompetitionsContracts(unittest.TestCase):
    def test_complete_source_test_and_runbook_bundle(self):
        for name in FILES:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_current_modules_have_no_provider_http_or_credential_transport(self):
        for name in FILES[:7]:
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(')
            self.assertNotIn('process.env', text)
            self.assertNotIn('football-data.org', text)
            self.assertNotIn('api-football', text)
        source = (ROOT / 'frontend/src/current/source.ts').read_text(encoding='utf-8')
        self.assertIn('createSyntheticLeague', source)
        self.assertNotIn("from '../api'", source)

    def test_synthetic_provenance_capability_and_localization_boundaries(self):
        types = (ROOT / FILES[0]).read_text(encoding='utf-8')
        for value in ("dataKind: 'synthetic'", 'sourceRevision: null', 'eventCoordinates: false', 'xg: false'):
            self.assertIn(value, types)
        messages = (ROOT / FILES[4]).read_text(encoding='utf-8')
        for value in ('DEMO DATA — SYNTHETIC', 'ДЕМО-ДАННЫЕ — СИНТЕТИЧЕСКИЕ', 'DATOS DEMO — SINTÉTICOS'):
            self.assertIn(value, messages)

    def test_fixture_browser_is_in_existing_networkless_ci_path(self):
        config = (ROOT / 'frontend/playwright.ci.config.ts').read_text(encoding='utf-8')
        self.assertIn('**/current-competitions.spec.ts', config)
        self.assertIn('synthetic contexts:', config)
        browser = (ROOT / FILES[9]).read_text(encoding='utf-8')
        for value in ('AxeBuilder', 'page.goBack()', 'page.goForward()', 'page.reload()',
                      'current-fixtures.png', 'current-standings.png', 'expect(apiCalls).toEqual([])'):
            self.assertIn(value, browser)

    def test_new_files_contain_no_high_confidence_secret_signatures(self):
        for name in FILES:
            self.assertFalse(secret_findings((ROOT / name).read_text(encoding='utf-8')), name)


if __name__ == '__main__':
    unittest.main()
