"""Offline registry source completeness and no storage/transport/credential boundary."""
import ast
from pathlib import Path
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    'src/providers/identity_registry.py', 'src/providers/observed_versions.py',
    'src/providers/registry_policy.py', 'tests/provider_identity_fakes.py',
    'tests/test_provider_identity.py', 'tests/test_provider_registry_policy.py',
    'tests/ci/test_identity_registry.py', 'docs/stage9c3-identity-consistency.md',
)


class IdentityRegistryContracts(unittest.TestCase):
    def test_complete_source_and_old_boundary_files(self):
        for name in (*FILES, 'src/providers/observed_window.py', 'src/providers/football_data.py',
                     'src/providers/collection.py', 'tests/football_data_fakes.py'):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_new_files_contain_no_high_confidence_secret_signatures(self):
        for name in FILES:
            self.assertFalse(secret_findings((ROOT / name).read_text(encoding='utf-8')), name)

    def test_production_modules_have_no_implicit_effects(self):
        forbidden = {'os', 'pathlib', 'subprocess', 'socket', 'requests', 'httpx', 'urllib',
                     'boto3', 'botocore', 'psycopg', 'clickhouse_connect'}
        for name in FILES[:3]:
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({alias.name.split('.')[0] for alias in node.names} & forbidden)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[0], forbidden)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {'open', 'print', 'input', 'eval', 'exec'})

    def test_existing_linux_matrix_discovers_all_new_tests_without_new_workflow(self):
        workflow = (ROOT / '.github/workflows/ci-fast.yml').read_text(encoding='utf-8')
        for value in ("'3.10.12'", "'3.12.14'", "discover -s tests -p 'test_*.py'",
                      "discover -s tests/ci -p 'test_*.py'"):
            self.assertIn(value, workflow)

    def test_runbook_separates_local_versions_atomicity_and_live_gates(self):
        doc = (ROOT / 'docs/stage9c3-identity-consistency.md').read_text(encoding='utf-8')
        for value in ('Offline identity/consistency: READY', 'Live read-only reconciliation: BLOCKED',
                      'LEGAL_REVIEW_REQUIRED', 'Stage 8C: PARTIAL', 'NOT_ATOMIC',
                      'source_revision=None', 'publish_authorized=False', 'unsigned',
                      'locally observed content', 'StatsBomb'):
            self.assertIn(value, doc)
