"""Isolated PET-3 source completeness and security boundaries; no services."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import yaml
from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = (".gitattributes", "src/openfootball_etl/__init__.py", "src/openfootball_etl/contract.py",
    "src/openfootball_etl/pipeline.py", "src/openfootball_etl/spark_job.py", "src/openfootball_etl/clickhouse.py",
    "scripts/openfootball_etl.py", "scripts/openfootball_spark.py", "src/orchestration/openfootball_historical_dag.py",
    "tests/test_openfootball_etl.py", "tests/openfootball_etl_fakes.py", "tests/spark/test_openfootball_etl.py",
    "tests/integration/test_openfootball_etl.py", "tests/airflow/test_openfootball_dag.py", "tests/ci/test_openfootball_etl.py",
    "docs/pet3-openfootball-etl.md", ".github/workflows/ci-integration.yml", "ci/Dockerfile")


class OpenFootballETLContracts(unittest.TestCase):
    def test_verified_batch_identity_without_acquired_source_or_clock(self):
        from src.openfootball_etl.contract import SEMANTIC, SOURCE_SHA
        from src.openfootball_etl.pipeline import build_id
        metadata_only = SimpleNamespace(manifest=SimpleNamespace(content_sha256=SOURCE_SHA), semantic_digest=SEMANTIC)
        self.assertEqual("ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc", build_id(metadata_only))

    def test_existing_jobs_explicitly_execute_all_synthetic_integration_suites(self):
        fast = yaml.load((ROOT / ".github/workflows/ci-fast.yml").read_text(), Loader=yaml.BaseLoader)
        fast_runs = "\n".join(s.get("run", "") for s in fast["jobs"]["python"]["steps"])
        for command in ("discover -s tests -p 'test_*.py'", "discover -s tests/ci -p 'test_*.py'"):
            self.assertIn(command, fast_runs)
        workflow = yaml.load((ROOT / ".github/workflows/ci-integration.yml").read_text(), Loader=yaml.BaseLoader)
        spark_runs = "\n".join(s.get("run", "") for s in workflow["jobs"]["spark-airflow"]["steps"])
        self.assertIn("test_context test_openfootball_etl; do", spark_runs)
        self.assertIn("tests/airflow/test_dag.py", spark_runs)
        self.assertIn("tests/airflow/test_openfootball_dag.py", spark_runs)
        recovery_steps = workflow["jobs"]["recovery"]["steps"]
        run = next(s["run"] for s in recovery_steps if "--require-isolated" in s.get("run", ""))
        for required in ("--network none", "--pull never", "--tmpfs /var/lib/clickhouse", "pet3.scope=openfootball-etl",
                         "PET3_SYNTHETIC_CLICKHOUSE_CONTAINER=", "tests/integration/test_openfootball_etl.py",
                         "trap '", 'docker stop --time 10 "$container_id"'):
            self.assertIn(required, run)
        self.assertNotIn("continue-on-error", str(recovery_steps))
        self.assertIn(".gitattributes", (ROOT / "ci/Dockerfile").read_text())

    def test_transform_hash_bytes_have_cross_platform_checkout_policy(self):
        text = (ROOT / ".gitattributes").read_text()
        self.assertEqual(["src/openfootball_etl/*.py text eol=lf"],
                         [line for line in text.splitlines() if line.strip() and not line.startswith("#")])
        for path in (ROOT / "src/openfootball_etl").glob("*.py"):
            self.assertNotIn(b"\r\n", path.read_bytes())

    def test_complete_publishable_set_no_secret_signatures(self):
        for name in FILES:
            with self.subTest(name=name):
                self.assertFalse(secret_findings((ROOT / name).read_text(encoding="utf-8")))

    def test_no_production_connectors_in_new_etl(self):
        forbidden = {"boto3", "psycopg", "requests", "urllib", "src.common.s3", "src.common.postgres"}
        for path in (ROOT / "src/openfootball_etl").glob("*.py"):
            imports = set()
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    imports.update(a.name for a in node.names)
                if isinstance(node, ast.ImportFrom):
                    imports.add(node.module)
            self.assertFalse(imports & forbidden)

    def test_new_dag_is_opt_in_not_in_live_discovery(self):
        self.assertFalse((ROOT / "dags/openfootball_historical_dag.py").exists())
        text = (ROOT / "src/orchestration/openfootball_historical_dag.py").read_text()
        self.assertIn("schedule=None", text)
        self.assertIn("is_paused_upon_creation=True", text)
        self.assertIn('"--confirm-isolated"', text)

    def test_serving_uses_one_atomic_bundle_and_no_destructive_sql(self):
        text = (ROOT / "src/openfootball_etl/clickhouse.py").read_text()
        self.assertIn("EXCHANGE TABLES", text)
        self.assertIn("ISOLATION_ATTESTATION", text)
        for forbidden in ("DROP TABLE", "TRUNCATE", "ALTER TABLE", "DELETE FROM", "football.event_core"):
            self.assertNotIn(forbidden, text)

    def test_document_preserves_semantics_and_limits(self):
        text = (ROOT / "docs/pet3-openfootball-etl.md").read_text()
        for fact in ("INCOMPLETE", "394", "Stage 8C: PARTIAL", "date-only", "633", "no production", "NOT_ATOMIC"):
            self.assertIn(fact, text)
