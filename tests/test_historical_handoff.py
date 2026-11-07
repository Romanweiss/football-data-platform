"""Pure target/allowlist gates. No production writes or credential discovery."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.openfootball_etl.contract import ETLError
from src.openfootball_etl.persistent import PersistentPublisher, Target, allowed, permitted_sql
from src.openfootball_etl.serving_contract import AUTHORIZATION, PREFIX, validate_bundle


class HandoffGates(unittest.TestCase):
    def test_receipt_write_failure_does_not_skip_owned_container_cleanup(self):
        from scripts import check_historical_handoff as runner
        created = "a" * 64
        def docker(*args, **kwargs):
            return created.encode() if args[0] == "run" else b""
        def rehearsal(name, **kwargs):
            if name == "football-clickhouse":
                raise ETLError("ISOLATED_TARGET_REQUIRED")
            raise ValueError("SYNTHETIC_SETUP_FAILURE")
        with TemporaryDirectory(prefix="pet3d-cleanup-test-") as temporary, \
             patch("sys.argv", ["rehearsal", "--confirm-isolated-tests", "--gold-store", temporary,
                   "--api-image", "football-api:pet3d-fix-test", "--evidence", str(Path(temporary) / "receipt.json")]), \
             patch.object(runner, "gold_rows", return_value={}), \
             patch.object(runner.PersistentPublisher, "rehearsal", side_effect=rehearsal), \
             patch.object(runner.io, "docker", side_effect=docker) as calls, \
             patch.object(Path, "open", side_effect=PermissionError("synthetic-unwritable-evidence")):
            with self.assertRaisesRegex(RuntimeError, "EVIDENCE_PERSISTENCE_FAILED_AFTER_CLEANUP"):
                runner.main()
            self.assertIn(unittest.mock.call("stop", "--time", "15", created), calls.call_args_list)
            self.assertIn(unittest.mock.call("rm", created), calls.call_args_list)

    def test_no_production_authorization_never_inspects_docker(self):
        with patch("src.openfootball_etl.persistent.io.container_info") as inspect:
            for authorization in (None, "", "true"):
                with self.assertRaises(ETLError):
                    PersistentPublisher.production(authorization=authorization)
            with self.assertRaises(ETLError):
                PersistentPublisher(Target("a" * 64, "12345678-abcd-abcd-abcd-123456789abc", True), "")
            inspect.assert_not_called()

    def test_explicit_authorization_still_requires_exact_identity(self):
        with self.assertRaises(ETLError):
            PersistentPublisher.production(authorization=AUTHORIZATION)
        info = {"id": "b" * 64, "image": "sha256:" + "c" * 64, "labels": {}}
        with patch("src.openfootball_etl.persistent.io.container_info", return_value=info):
            with self.assertRaises(ETLError):
                PersistentPublisher.production(authorization=AUTHORIZATION, expected_container_id="a" * 64,
                    expected_image_id="sha256:" + "c" * 64)

    def test_allowlist_never_admits_statsbomb_or_arbitrary_names(self):
        for name in ("event_core", "football.records", "records", PREFIX + "foreign", PREFIX + "candidate_bad", "x;DROP TABLE t"):
            self.assertFalse(allowed(name))
        self.assertTrue(allowed(PREFIX + "records"))
        self.assertTrue(allowed(PREFIX + "candidate_" + "a" * 32))

    def test_rehearsal_cannot_target_production(self):
        with patch("src.openfootball_etl.persistent.io.container_info") as inspect:
            with self.assertRaises(ETLError):
                PersistentPublisher.rehearsal("football-clickhouse", expected_namespace="", confirm_isolated=True)
            inspect.assert_not_called()

    def test_transport_has_no_raw_sql_escape_hatch(self):
        for sql in ("DROP TABLE football.event_core", "TRUNCATE TABLE football." + PREFIX + "records",
                    "SELECT * FROM football.event_core", "CREATE USER x", "GRANT ALL ON *.* TO x",
                    "SELECT * FROM url('https://example.com')", "SELECT 1; DROP TABLE x",
                    "ALTER TABLE football." + PREFIX + "records DELETE WHERE 1"):
            self.assertFalse(permitted_sql(sql))
        publisher = object.__new__(PersistentPublisher)
        with patch("src.openfootball_etl.persistent.io.ch_query") as query:
            with self.assertRaises(ETLError):
                publisher.command("SELECT * FROM football.event_core")
            query.assert_not_called()

    def test_provenance_and_batch_gate_precedes_any_mutation(self):
        publisher = object.__new__(PersistentPublisher)
        publisher.target = Target("a" * 64, "12345678-abcd-abcd-abcd-123456789abc", False)
        with patch.object(publisher, "ensure") as ensure:
            with self.assertRaises(ETLError):
                publisher.publish({})
            ensure.assert_not_called()
        with self.assertRaises(ETLError):
            validate_bundle({})

    def test_namespace_and_server_identity_conflicts_are_fail_closed(self):
        target = Target("a" * 64, "12345678-abcd-abcd-abcd-123456789abc", True, "sha256:" + "b" * 64)
        info = {"id": target.container_id, "image": target.image_id, "labels": {
            "com.docker.compose.project": "football-data-platform", "com.docker.compose.service": "football-clickhouse"}}
        with patch("src.openfootball_etl.persistent.io.container_info", return_value=info), \
             patch.object(PersistentPublisher, "query", return_value=[{"server_uuid": "wrong"}]), \
             patch.object(PersistentPublisher, "command") as command:
            with self.assertRaises(ETLError) as error:
                PersistentPublisher(target, "f" * 64, authorization=AUTHORIZATION)
            self.assertEqual("SERVER_IDENTITY", error.exception.code)
            command.assert_not_called()
        with patch("src.openfootball_etl.persistent.io.container_info", return_value=info), \
             patch.object(PersistentPublisher, "query", side_effect=[[{"server_uuid": target.server_uuid}], [{"engine": "Atomic"}]]), \
             patch.object(PersistentPublisher, "fingerprint", return_value="e" * 64), \
             patch.object(PersistentPublisher, "command") as command:
            with self.assertRaises(ETLError) as error:
                PersistentPublisher(target, "f" * 64, authorization=AUTHORIZATION)
            self.assertEqual("NAMESPACE_DRIFT", error.exception.code)
            command.assert_not_called()
