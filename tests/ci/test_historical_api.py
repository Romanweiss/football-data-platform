"""PET-3B publication completeness and production separation, no live clients."""
import ast
from pathlib import Path
import unittest

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = ("application/historical.py", "application/historical_repository.py", "application/historical_views.py",
         "application/urls.py", "scripts/check_historical_api.py", "tests/application/test_historical_api.py",
         "tests/application/integration_historical_api.py", "tests/ci/test_historical_api.py", "docs/pet3b-historical-api.md",
         "tests/integration/test_historical_api.py", ".github/workflows/ci-integration.yml")


class HistoricalApiContracts(unittest.TestCase):
    def test_existing_jobs_discover_offline_and_database_backed_historical_tests(self):
        fast = (ROOT / ".github/workflows/ci-fast.yml").read_text()
        self.assertIn("discover -s tests/application -p 'test_*.py'", fast)
        self.assertIn("discover -s tests/ci -p 'test_*.py'", fast)
        integration = (ROOT / ".github/workflows/ci-integration.yml").read_text()
        self.assertIn("checks python tests/integration/test_historical_api.py", integration)
        self.assertIn("python tests/integration/test_historical_handoff.py --require-isolated", integration)
        self.assertIn("-r requirements/recovery.txt -r requirements/api.txt", integration)
        self.assertNotIn("check_historical_api.py --gold-store", integration)
        source = (ROOT / "tests/integration/test_historical_api.py").read_text()
        self.assertIn('guard("clickhouse")', source)
        self.assertIn("self.data = gold()", source)
    def test_complete_source_set_has_no_secret_signatures(self):
        for name in FILES:
            with self.subTest(name=name):
                self.assertFalse(secret_findings((ROOT / name).read_text(encoding="utf-8")))

    def test_api_imports_no_storage_writers_or_production_connection_factory(self):
        for name in FILES[:3]:
            source = (ROOT / name).read_text(encoding="utf-8")
            imports = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
            self.assertFalse(imports & {"src.common.clickhouse", "src.common.postgres", "src.common.s3",
                                        "src.openfootball_etl.pipeline", "src.openfootball_etl.clickhouse"})
            for forbidden in ("INSERT INTO", "CREATE TABLE", "ALTER TABLE", "DROP TABLE", "boto3", "psycopg"):
                self.assertNotIn(forbidden, source)

    def test_reader_is_disabled_by_default_has_no_production_fallback(self):
        source = (ROOT / "application/historical_repository.py").read_text()
        self.assertIn('os.environ.get("HISTORICAL_API_ENABLED") != "true"', source)
        self.assertNotIn('os.environ.get("CLICKHOUSE_', source)
        self.assertIn("readonly=1", source)
        self.assertIn("row_digest(rows) != digest", source)
        self.assertIn("{database:Identifier}", source)

    def test_explicit_pinned_production_gate_and_image_packaging(self):
        source = (ROOT / "application/historical_connection.py").read_text()
        for gate in ("HISTORICAL_PRODUCTION_AUTHORIZATION", "HISTORICAL_PINNED_BATCH", "HISTORICAL_DATASET_ID",
                     "HISTORICAL_EXPECTED_SERVER_UUID", "serverUUID()", "Atomic"):
            self.assertIn(gate, source)
        self.assertNotIn('os.environ.get("CLICKHOUSE_', source)
        dockerfile = (ROOT / "docker/api/Dockerfile").read_text()
        self.assertIn("COPY src/providers /app/src/providers", dockerfile)
        self.assertIn("src/openfootball_etl/serving_contract.py /app/src/openfootball_etl/", dockerfile)
        for name in ("application/historical_connection.py", "src/openfootball_etl/serving_contract.py",
                     "src/openfootball_etl/persistent.py", "tests/application/test_historical_production.py",
                     "tests/test_historical_handoff.py", "scripts/check_historical_handoff.py",
                     "tests/integration/historical_handoff_http.py", "tests/integration/test_historical_handoff.py",
                     "ci/check_delivery.py", "docs/pet3d-production-readiness.md"):
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertFalse(secret_findings((ROOT / name).read_text(encoding="utf8")))

    def test_runbook_does_not_claim_production_or_verified_scores(self):
        source = (ROOT / "docs/pet3b-historical-api.md").read_text(encoding="utf-8")
        for fact in ("NOT_READY", "503", "UNKNOWN", "INCOMPLETE", "189", "394", "source_reported_only",
                     "Stage 8C: PARTIAL", "not deployed", "internal network"):
            self.assertIn(fact, source)
