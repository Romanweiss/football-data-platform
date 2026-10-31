"""Publication completeness and offline-only football-data mapping boundaries."""
import ast
from pathlib import Path
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "src/providers/football_data.py", "src/providers/observed_window.py",
    "tests/football_data_fakes.py", "tests/test_football_data.py",
    "tests/test_football_data_consistency.py", "tests/fixtures/football_data_synthetic.json",
    "tests/ci/test_football_data.py", "docs/stage9c2-football-data-mapping.md",
)


class FootballDataOfflineContracts(unittest.TestCase):
    def test_complete_source_set_and_existing_dependencies(self):
        for name in (*FILES, "tests/provider_collection_fakes.py", "src/providers/models.py",
                     "src/providers/validation.py", "src/providers/reconciliation.py",
                     "src/providers/collection.py", "docs/stage9c2-provider-evaluation.md"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_explicit_new_files_have_no_high_confidence_secret_signatures(self):
        for name in FILES:
            self.assertFalse(secret_findings((ROOT / name).read_text(encoding="utf-8")), name)

    def test_new_modules_have_no_transport_or_storage_or_environment_imports(self):
        forbidden = {"os", "pathlib", "requests", "httpx", "urllib", "socket", "ssl", "subprocess",
                     "boto3", "botocore", "psycopg", "clickhouse_connect"}
        for name in ("football_data.py", "observed_window.py"):
            tree = ast.parse((ROOT / "src/providers" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & forbidden)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], forbidden)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"open", "print", "eval", "exec", "input"})

    def test_existing_linux_matrix_and_offline_discovery_cover_new_tests(self):
        workflow = (ROOT / ".github/workflows/ci-fast.yml").read_text(encoding="utf-8")
        for text in ("'3.10.12'", "'3.12.14'", "discover -s tests -p 'test_*.py'",
                     "discover -s tests/ci -p 'test_*.py'"):
            self.assertIn(text, workflow)
        self.assertNotIn("secrets.", workflow)

    def test_runbook_is_explicit_about_evidence_and_blocked_live_integration(self):
        doc = (ROOT / "docs/stage9c2-football-data-mapping.md").read_text(encoding="utf-8")
        for text in ("Offline mapping: READY", "Technical real-source integration: BLOCKED",
                     "LEGAL_REVIEW_REQUIRED", "Stage 8C: PARTIAL", "not an atomic",
                     "CALLER_SUPPLIED", "TOTAL", "HOME", "AWAY", "144", "36",
                     "SUSPENDED", "synthetic", "source_revision"):
            self.assertIn(text, doc)
