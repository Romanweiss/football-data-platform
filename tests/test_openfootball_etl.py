"""Local ETL gates on synthetic inputs; no Docker, Spark, services or real bytes."""
from dataclasses import replace
from datetime import timedelta
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.openfootball_etl.contract import ETLError, proposal, row_digest, rows_from_proposal
from src.openfootball_etl.pipeline import bronze, build_id, initialize, inventory, seal, verify_phase, writer, write_new
from src.openfootball_etl.clickhouse import IsolatedClickHouse
from src.providers.openfootball import OpenFootballError, prepare_openfootball
from test_openfootball import NOW, mapping, payload


class OpenFootballETLTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="football-pet3-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def result(self):
        return prepare_openfootball(payload(), mapping=mapping(), observed_at=NOW)

    def test_wrong_hash_fails_before_parsing_or_metadata_interpretation(self):
        with patch("src.openfootball_etl.contract.prepare_openfootball") as adapter:
            with self.assertRaisesRegex(ETLError, "SOURCE_SHA256"):
                proposal(b"not-a-real-source", {}, NOW)
            adapter.assert_not_called()

    def cli(self):
        path = Path(__file__).resolve().parents[1] / "scripts/openfootball_etl.py"
        spec = importlib.util.spec_from_file_location("synthetic_openfootball_cli", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_cli_wrong_sha_stops_before_storage_and_container_io(self):
        source = self.root / "uefa.cl.json"
        source.write_bytes(b" " * 58305)
        receipt = self.root / "receipt.json"
        receipt.write_bytes(b"{}")
        store = self.root / "must-not-exist"
        args = SimpleNamespace(confirm_isolated=True, source=str(source), receipt=str(receipt), store=str(store), step="all")
        cli = self.cli()
        with patch.object(cli, "IsolatedClickHouse") as target, self.assertRaisesRegex(ETLError, "SOURCE_SHA256"):
            cli.run(args)
        target.assert_not_called()
        self.assertFalse(store.exists())

    def test_fatal_adapter_dq_stops_before_any_local_publication(self):
        source = payload()
        source["matches"][0]["team2"] = source["matches"][0]["team1"]
        with self.assertRaises(OpenFootballError) as raised:
            prepare_openfootball(source, mapping=mapping(), observed_at=NOW)
        cli = self.cli()
        store = self.root / "fatal-must-not-exist"
        with patch.object(cli, "verify_source", side_effect=raised.exception), \
             patch.object(cli, "IsolatedClickHouse") as target, self.assertRaisesRegex(OpenFootballError, "SELF_MATCH"):
            cli.run(SimpleNamespace(confirm_isolated=True, source="synthetic", receipt="synthetic", store=str(store)))
        target.assert_not_called()
        self.assertFalse(store.exists())

    def test_build_identity_excludes_observation_and_keeps_schema_code_source(self):
        result = self.result()
        self.assertEqual(build_id(result), build_id(replace(result, observed_at=NOW + timedelta(days=1))))
        with patch("src.openfootball_etl.pipeline.code_sha", return_value="f" * 64):
            self.assertNotEqual(build_id(result), build_id(replace(result, semantic_digest="a" * 64)))
        self.assertRegex(build_id(result), r'^[0-9a-f]{64}$')

    def test_source_specific_rows_are_date_only_null_canonical_and_immutable(self):
        result = self.result()
        rows = rows_from_proposal(result, "a" * 64)
        self.assertEqual(3, len(rows["fixtures"]))
        self.assertTrue(all(type(r["match_date"]).__name__ == "date" and r["kickoff_utc"] is None and
                            r["regulation_home"] is None and not r["standings_eligible"] for r in rows["fixtures"]))
        missing = next(r for r in rows["fixtures"] if r["result_availability"] == "MISSING")
        self.assertIsNone(missing["source_ft_home"])
        self.assertEqual("unknown", missing["status"])

    def test_foreign_store_is_not_repaired_or_overwritten(self):
        target = self.root / "foreign"
        target.mkdir()
        (target / "user.txt").write_text("synthetic-user-data")
        with self.assertRaisesRegex(ETLError, "FOREIGN_STORAGE"):
            initialize(target)
        self.assertFalse((target / "_isolated.json").exists())
        self.assertEqual("synthetic-user-data", (target / "user.txt").read_text())

    def test_writer_is_exclusive_and_removes_only_own_lock_after_error(self):
        store = initialize(self.root / "owned")
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with writer(store):
                with self.assertRaises(FileExistsError):
                    with writer(store):
                        self.fail("Second writer admitted")
                raise RuntimeError("synthetic")
        self.assertFalse((store / "_writer.lock").exists())
        self.assertTrue((store / "_isolated.json").exists())

    def test_phase_is_not_visible_until_success_and_existing_target_is_refused(self):
        store = initialize(self.root / "owned")
        attempt, final = store / "attempt", store / "sealed"
        attempt.mkdir()
        write_new(attempt / "synthetic.json", b"{}")
        manifest = {"files": inventory(attempt)}
        self.assertFalse(final.exists())
        seal(attempt, final, manifest)
        self.assertEqual(manifest, verify_phase(final))
        with self.assertRaisesRegex(ETLError, "NO_OVERWRITE"):
            seal(store / "new", final, manifest)
        (final / "synthetic.json").write_bytes(b"damaged")
        with self.assertRaisesRegex(ETLError, "ARTIFACT_INTEGRITY"):
            verify_phase(final)

    def test_bronze_replay_is_read_only_and_inconsistent_bytes_are_rejected(self):
        store = initialize(self.root / "owned")
        result = self.result()
        # Controlled synthetic local artifact only, not the strict real-source CLI gate.
        result = replace(result, manifest=replace(result.manifest, content_sha256="a" * 64, acquired_at=NOW))
        path, status = bronze(store, b"synthetic", {"fixture": True}, result)
        before = inventory(path)
        self.assertEqual("CREATED", status)
        self.assertEqual("REUSED", bronze(store, b"synthetic", {"fixture": True}, result)[1])
        self.assertEqual(before, inventory(path))
        with self.assertRaisesRegex(ETLError, "BRONZE_MISMATCH"):
            bronze(store, b"different", {"fixture": True}, result)

    def test_content_digest_is_order_invariant_and_preserves_nulls(self):
        a = [{"x": None, "date": "2025-01-01"}, {"x": 0, "date": "2025-01-02"}]
        self.assertEqual(row_digest(a), row_digest(list(reversed(a))))
        self.assertNotEqual(row_digest(a), row_digest([dict(r, x=0) for r in a]))

    def test_production_clickhouse_target_is_rejected_before_docker_io(self):
        with patch("src.openfootball_etl.clickhouse.io.docker") as docker:
            with self.assertRaisesRegex(ETLError, "ISOLATED_CONTAINER"):
                IsolatedClickHouse("football-clickhouse", "football")
            docker.assert_not_called()

    def test_false_isolation_attestation_blocks_even_allowlisted_name(self):
        import json
        fake = dict(id="0" * 64, image="clickhouse/clickhouse-server:25.8.23.13-alpine", network="bridge",
                    ports={}, mounts=[], labels={"pet3.scope": "openfootball-etl"})
        with patch("src.openfootball_etl.clickhouse.io.docker", return_value=json.dumps(fake).encode()), \
             self.assertRaisesRegex(ETLError, "ISOLATION_ATTESTATION"):
            IsolatedClickHouse("pet3-openfootball-ch-" + "0" * 12, "pet3_openfootball_" + "0" * 12)


if __name__ == "__main__":
    unittest.main()
