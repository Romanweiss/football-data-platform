"""Real tmpfs ClickHouse + Django HTTP concurrency. Synthetic pins only in this test.

Uses a native CLI result adapter, not an authenticated production SDK connection.
Production factories/gates are never patched or called. No external dataset needed.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from openfootball_etl_fakes import gold
from application import historical_repository as repository_module
from application.historical_repository import HistoricalRepository
from src.openfootball_etl import persistent, serving_contract
from src.openfootball_etl.clickhouse import IMAGE
from src.openfootball_etl.contract import ETLError, row_digest
from src.openfootball_etl.serving_contract import DatasetContract, MODE, RECORDS
from src.recovery import runtime as io

BASE = "/api/v1/competitions/historical/uefa-champions-league/2024"


class NativeReadOnlyClient:
    def __init__(self, container, barrier=None):
        self.container, self.barrier = container, barrier

    def query(self, sql, *, parameters, settings):
        assert settings == {"readonly": 1}
        assert sql.startswith("SELECT ") and ";" not in sql
        flags = ["--param_" + key + "=" + str(value) for key, value in parameters.items()]
        raw = io.docker("exec", self.container, "clickhouse-client", "--output_format_json_quote_64bit_integers=0",
            *flags, "--query", sql + " SETTINGS readonly=1 FORMAT JSON")
        result = json.loads(raw)
        names = [column["name"] for column in result["meta"]]
        if self.barrier is not None and "stage_round_coverage WHERE" in sql:
            self.barrier()
        return SimpleNamespace(column_names=names, result_rows=[tuple(row[name] for name in names) for row in result["data"]])


class HistoricalHandoffIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "--require-isolated" not in ORIGINAL_ARGS:
            raise RuntimeError("EXPLICIT_ISOLATED_HISTORICAL_TEST_REQUIRED")
        cls.container = None
        cls.name = "pet3d-fix-ch-" + uuid.uuid4().hex[:12]
        cls.addClassCleanup(cls.cleanup)
        cls.container = io.docker("run", "-d", "--pull", "never", "--name", cls.name, "--network", "none",
            "--label", "pet3d.scope=historical-rehearsal", "--cpus", "2", "--memory", "1536m",
            "--ulimit", "nofile=262144:262144", "--tmpfs", "/var/lib/clickhouse:rw,size=2g",
            "--tmpfs", "/var/log/clickhouse-server:rw,size=64m", IMAGE).decode().strip()
        io.require(len(cls.container) == 64 and all(c in "0123456789abcdef" for c in cls.container), "CREATED_ID_REQUIRED")
        for _ in range(60):
            try:
                io.docker("exec", cls.container, "clickhouse-client", "--query", "SELECT 1", timeout=5)
                break
            except io.RecoveryError:
                time.sleep(0.5)
        else:
            raise RuntimeError("SYNTHETIC_CLICKHOUSE_TIMEOUT")
        io.docker("exec", cls.container, "clickhouse-client", "--query", "CREATE DATABASE football ENGINE=Atomic")
        cls.data = gold()
        first = cls.data["historical_fixtures"][0]
        cls.contract = DatasetContract(first["batch_id"], first["source_sha256"], "f" * 64,
            tuple((name, len(rows), row_digest(rows)) for name, rows in cls.data.items()))
        # Test-only synthetic fingerprints; no runtime flag permits this in production.
        for module in (serving_contract, persistent, repository_module):
            patcher = patch.object(module, "PINNED", cls.contract)
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        cls.publisher = persistent.PersistentPublisher.rehearsal(cls.name,
            expected_namespace=io.digest(b"[]"), confirm_isolated=True)

    @classmethod
    def cleanup(cls):
        if cls.container:
            io.docker("stop", "--time", "15", cls.container)
            io.docker("rm", cls.container)
            print("HISTORICAL_SYNTHETIC_OWNED_CONTAINER_REMOVED=" + cls.container)

    def setUp(self):
        @contextmanager
        def opened():
            yield HistoricalRepository(NativeReadOnlyClient(self.container), "football", contract=self.contract, mode=MODE)
        self.patch = patch("application.historical_views.open_historical_repository", side_effect=opened)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_01_partial_publish_replay_and_wrong_batch(self):
        def interrupted():
            raise RuntimeError("SYNTHETIC_INTERRUPTION")
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_INTERRUPTION"):
            self.publisher.publish(self.data, fault=interrupted)
        self.assertEqual(503, Client(HTTP_HOST="localhost").get(BASE).status_code)
        self.publisher.expected_namespace = self.publisher.fingerprint()  # Explicit test-only retry acknowledgement.
        receipt = self.publisher.publish(self.data)
        self.assertEqual("CREATED", receipt["status"])
        self.assertEqual("REUSED", self.publisher.publish(self.data)["status"])
        self.assertEqual(200, Client(HTTP_HOST="localhost").get(BASE).status_code)
        self.assertEqual(sum(len(r) for r in self.data.values()), self.publisher.query(
            "SELECT count() AS n FROM " + self.publisher.table(RECORDS))[0]["n"])
        wrong = deepcopy(self.data)
        wrong["historical_fixtures"][0]["batch_id"] = "b" * 64
        with self.assertRaises(ETLError):
            self.publisher.publish(wrong)
        self.assertEqual(200, Client(HTTP_HOST="localhost").get(BASE).status_code)
        self.publisher.rollback(receipt)
        self.assertEqual(503, Client(HTTP_HOST="localhost").get(BASE).status_code)

    def test_02_concurrent_http_during_exchange_returns_503_not_partial_bundle(self):
        receipt = self.publisher.publish(self.data)
        arrived = [Event() for _ in range(3)]
        release = Event()
        def request(index):
            def barrier():
                arrived[index].set()
                if not release.wait(30):
                    raise TimeoutError("SYNTHETIC_READER_BARRIER_TIMEOUT")
            @contextmanager
            def opened():
                yield HistoricalRepository(NativeReadOnlyClient(self.container, barrier), "football",
                    contract=self.contract, mode=MODE)
            return opened
        # Each request uses its own repository/client; no shared mutable result cache.
        with patch("application.historical_views.open_historical_repository") as factory, ThreadPoolExecutor(max_workers=3) as pool:
            import threading
            local = threading.local()
            factory.side_effect = lambda: local.opened()
            def fetch(index):
                local.opened = request(index)
                response = Client(HTTP_HOST="localhost").get(BASE)
                return response.status_code, response.json()
            futures = [pool.submit(fetch, index) for index in range(3)]
            try:
                self.assertTrue(all(event.wait(30) for event in arrived))
                self.publisher.rollback(receipt)
            finally:
                release.set()
            for future in futures:
                status, body = future.result(timeout=30)
                self.assertEqual(503, status)
                self.assertNotIn("summary", body)
        # New requests observe the old NOT_READY state, then the complete approved bundle.
        self.assertEqual(503, Client(HTTP_HOST="localhost").get(BASE).status_code)
        restored = self.publisher.publish(self.data)
        self.assertEqual(200, Client(HTTP_HOST="localhost").get(BASE).status_code)
        self.publisher.rollback(restored)

    def test_03_wrong_fingerprint_and_rollback_conflict_preserve_previous(self):
        receipt = self.publisher.publish(self.data)
        bad = deepcopy(self.data)
        bad["historical_fixtures"][0]["home_name"] = "Not the synthetic pinned team"
        with self.assertRaises(ETLError):
            self.publisher.publish(bad)
        with self.assertRaises(ETLError):
            self.publisher.rollback({**receipt, "published_uuid": str(uuid.uuid4())})
        self.assertEqual(200, Client(HTTP_HOST="localhost").get(BASE).status_code)
        self.publisher.rollback(receipt)
        self.assertEqual("EMPTY", self.publisher.validate(allow_empty=True))

    def test_04_reader_fingerprint_and_uuid_fences_reject_changes(self):
        receipt = self.publisher.publish(self.data)
        wrong = replace(self.contract, datasets=tuple((name, count, "0" * 64) for name, count, _ in self.contract.datasets))
        with patch.object(repository_module, "PINNED", wrong):
            with self.assertRaises(Exception) as error:
                HistoricalRepository(NativeReadOnlyClient(self.container), "football", contract=wrong, mode=MODE).load()
            self.assertEqual(503, error.exception.status)
        repository = HistoricalRepository(NativeReadOnlyClient(self.container), "football", contract=self.contract, mode=MODE)
        with patch.object(repository, "generation", side_effect=[[{"uuid": "before"}], [{"uuid": "after"}]]):
            with self.assertRaises(Exception) as error:
                repository.load()
            self.assertEqual(503, error.exception.status)
        self.publisher.rollback(receipt)


ORIGINAL_ARGS = tuple(sys.argv)
if __name__ == "__main__":
    if "--require-isolated" not in sys.argv:
        raise SystemExit("EXPLICIT_ISOLATED_HISTORICAL_TEST_REQUIRED")
    sys.argv.remove("--require-isolated")
    unittest.main()
