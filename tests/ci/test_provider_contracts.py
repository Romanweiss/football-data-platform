"""Foundation completeness and offline boundaries, using existing CI discovery."""
import ast
from pathlib import Path
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "src/providers/__init__.py", "src/providers/models.py", "src/providers/validation.py",
    "src/providers/adapter.py", "tests/test_provider_contracts.py", "tests/ci/test_provider_contracts.py",
    "tests/fixtures/provider_neutral_ucl.json", "tests/fixtures/provider_neutral_updates.json",
    "docs/stage9c2-provider-adapter.md",
)


class ProviderFoundationContracts(unittest.TestCase):
    def test_complete_source_set_exists(self):
        for name in FILES:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())

    def test_existing_python_matrix_discovers_new_offline_tests(self):
        workflow = (ROOT / ".github/workflows/ci-fast.yml").read_text(encoding="utf-8")
        for text in ("'3.10.12'", "'3.12.14'", "discover -s tests -p 'test_*.py'",
                     "discover -s tests/ci -p 'test_*.py'"):
            self.assertIn(text, workflow)
        dockerfile = (ROOT / "ci/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY src/ src/", dockerfile)
        self.assertIn("COPY tests/ tests/", dockerfile)

    def test_no_direct_network_persistence_credentials_or_import_time_execution(self):
        forbidden = {"requests", "httpx", "socket", "boto3", "psycopg", "clickhouse_connect",
                     "subprocess", "os", "urllib.request"}
        for path in (ROOT / "src/providers").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add(node.module)
            self.assertFalse(imports & forbidden, path.name)
            self.assertFalse(any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                                 for node in tree.body), path.name)

    def test_runbook_does_not_claim_live_onboarding(self):
        document = (ROOT / "docs/stage9c2-provider-adapter.md").read_text(encoding="utf-8")
        for fact in ("PROVIDER_UNDECIDED", "real-source onboarding: BLOCKED", "Stage 8C: PARTIAL",
                     "no network transport", "one-build-per-context", "Python 3.10"):
            self.assertIn(fact, document)

    def test_new_source_set_has_no_high_confidence_secret_signatures(self):
        # Explicit source allowlist, never ignored credentials or runtime state.
        for name in FILES:
            with self.subTest(name=name):
                self.assertFalse(secret_findings((ROOT / name).read_text(encoding="utf-8")))
