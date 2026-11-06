"""UX publication completeness/safety. Offline and no private bundle reads."""
import ast
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
PUBLICATION_FILES = (
    "docs/infra-audit-2026-11.md",
    "docs/superset-match-analysis-ux-review.md",
    "docs/superset-match-analysis-ux-acceptance.md",
    "docs/superset-match-analysis-ux3.md",
    "docs/superset-match-analysis-live-readiness.md",
    "src/analytics/superset_ux.py",
    "scripts/superset_semantic_safety.py",
    "scripts/superset_ux_metadata.py",
    "scripts/superset_ux_validate.py",
    "scripts/build_superset_ux_layout.py",
    "scripts/superset_ux_postgres.py",
    "scripts/check_superset_ux_postgres.py",
    "tests/test_superset_ux.py",
    "tests/test_superset_ux_postgres.py",
    "tests/integration/superset_ux_postgres_contracts.py",
    "tests/ci/test_superset_ux_publication.py",
)


class SupersetUXPublicationTests(unittest.TestCase):
    def test_exact_unit_is_available_in_git_snapshot(self):
        tracked = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
        self.assertTrue(set(PUBLICATION_FILES) <= tracked, "UX publication dependency missing")
        for name in PUBLICATION_FILES:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_offline_contract_modules_need_no_database_or_network_imports(self):
        for name in ("src/analytics/superset_ux.py", "scripts/superset_ux_postgres.py",
                     "tests/test_superset_ux.py", "tests/test_superset_ux_postgres.py"):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            direct = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            modules = {n.module.split(".")[0] for n in direct if isinstance(n, ast.ImportFrom)}
            modules.update(a.name.split(".")[0] for n in direct if isinstance(n, ast.Import) for a in n.names)
            self.assertFalse(modules & {"superset", "sqlalchemy", "requests", "urllib", "socket", "psycopg2"})

    def test_policy_and_live_gates_are_not_overstated(self):
        text = (ROOT / "docs/superset-match-analysis-live-readiness.md").read_text(encoding="utf-8")
        for phrase in ("desktop-first", "418/390", "NOT PASS", "22", "LEGAL_REVIEW_REQUIRED",
                       "live apply", "owner-only", "no-overwrite", "PARTIAL"):
            self.assertIn(phrase, text)
        runner = (ROOT / "scripts/check_superset_ux_postgres.py").read_text(encoding="utf-8")
        self.assertIn("--confirm-ephemeral-postgres", runner)
        self.assertNotIn("create_engine(", runner)


if __name__ == "__main__":
    unittest.main()
