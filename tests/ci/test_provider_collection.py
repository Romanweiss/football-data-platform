"""Synthetic collection publication inputs and existing offline CI boundaries."""
from pathlib import Path
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "src/providers/collection.py", "src/providers/reconciliation.py",
    "tests/provider_collection_fakes.py", "tests/test_provider_collection.py",
    "tests/fixtures/provider_collection_scenarios.json", "tests/ci/test_provider_collection.py",
    "docs/stage9c2-collection.md",
)


class ProviderCollectionContracts(unittest.TestCase):
    def test_complete_synthetic_source_set_and_stage_a_preserved(self):
        for name in (*FILES, "docs/stage9c2-provider-adapter.md", "src/providers/models.py",
                     "src/providers/validation.py", "src/providers/adapter.py"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_security_signatures_in_explicit_new_source_set_only(self):
        for name in FILES:
            self.assertFalse(secret_findings((ROOT / name).read_text(encoding="utf-8")), name)

    def test_no_workflow_or_credentials_required(self):
        workflow = (ROOT / ".github/workflows/ci-fast.yml").read_text(encoding="utf-8")
        for text in ("'3.10.12'", "'3.12.14'", "discover -s tests -p 'test_*.py'",
                     "discover -s tests/ci -p 'test_*.py'"):
            self.assertIn(text, workflow)
        self.assertNotIn("secrets.", workflow)

    def test_runbook_has_explicit_non_production_limits(self):
        document = (ROOT / "docs/stage9c2-collection.md").read_text(encoding="utf-8")
        for text in ("PROVIDER_UNDECIDED", "Real-source onboarding: BLOCKED", "Stage 8C: PARTIAL",
                     "one-build-per-context", "tie-breakers", "not an atomic", "No real sleep",
                     "144", "108", "36", "3000"):
            self.assertIn(text, document)
