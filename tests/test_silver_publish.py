"""Publication/recovery state machine with in-memory S3 and mocked Spark/PG."""

import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ReadTimeoutError

from silver_fakes import FakeS3, artifact, seed_output, specification
from src.silver import publish
from src.silver.build_identity import calculate_build_id, silver_prefix
from src.silver.diagnostics import PublishDiagnostics
from src.silver.manifest import SilverIntegrityError


class SilverPublishTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeS3()
        self.inputs = [artifact(1), artifact(2)]
        self.spec = specification(self.inputs)
        self.bucket = "test-bucket"
        self.prefix = silver_prefix(self.spec, calculate_build_id(self.spec))
        self.record = None
        self.order = []
        self.find = self.enterContext(patch.object(publish, "find_silver_build", side_effect=lambda *a, **kw: self.record))
        self.register = self.enterContext(patch.object(publish, "register_silver_build", side_effect=self.register_record))
        self.write = self.enterContext(patch.object(publish, "write_new_silver", side_effect=self.write_output))
        self.readback = self.enterContext(patch.object(publish, "validate_readback", side_effect=lambda *a, **kw: self.order.append("readback")))
        self.params = {
            "spark": MagicMock(), "frame": MagicMock(), "counts": {"row_count": 6, "match_count": 2},
            "inputs": self.inputs, "specification": self.spec, "bucket": self.bucket,
            "client": self.client, "connection": MagicMock(),
        }

    def write_output(self, frame, uri):
        self.order.append("write")
        self.assertEqual(uri, f"s3a://{self.bucket}/{self.prefix}")
        seed_output(self.client, self.bucket, self.prefix)

    def register_record(self, connection, **record):
        self.assertIn("readback", self.order)
        self.assertIn((self.bucket, self.prefix + "_SUCCESS"), self.client.objects)
        self.assertIn((self.bucket, self.prefix + "_manifest.json"), self.client.objects)
        self.order.append("register")
        self.record = record
        return True

    def run_publish(self):
        return publish.publish_build(**self.params)

    def test_new_build_registers_only_after_validation_and_manifest(self):
        result = self.run_publish()
        self.assertEqual(self.order, ["write", "readback", "register"])
        self.assertEqual(result["catalog"], "REGISTERED")
        self.assertEqual(result["file_count"], 4)
        self.assertEqual(result["output_status"], "CREATED")

    def test_complete_existing_build_skips_write_and_registration(self):
        self.run_publish()
        before = dict(self.client.objects)
        result = self.run_publish()
        self.assertEqual(self.write.call_count, 1)
        self.assertEqual(self.register.call_count, 1)
        self.assertEqual(self.readback.call_count, 2)
        self.assertEqual(result["catalog"], "ALREADY_REGISTERED")
        self.assertEqual(result["output_status"], "UNCHANGED / ALREADY_BUILT")
        self.assertEqual(before, self.client.objects)

    def test_db_failure_then_recovery_does_not_rewrite_or_delete(self):
        self.register.side_effect = RuntimeError("synthetic DB failure")
        with self.assertRaises(RuntimeError):
            self.run_publish()
        before = dict(self.client.objects)
        self.register.side_effect = self.register_record
        result = self.run_publish()
        self.assertEqual(self.write.call_count, 1)
        self.assertEqual(before, self.client.objects)
        self.assertEqual(result["catalog"], "REGISTERED")

    def test_complete_parquet_missing_manifest_recovers_without_write(self):
        seed_output(self.client, self.bucket, self.prefix)
        self.run_publish()
        self.write.assert_not_called()
        self.assertIn((self.bucket, self.prefix + "_manifest.json"), self.client.objects)
        self.register.assert_called_once()

    def test_manifest_failure_then_recovery_skips_parquet_write(self):
        with patch.object(publish, "ensure_manifest", side_effect=RuntimeError("manifest failed")):
            with self.assertRaises(RuntimeError):
                self.run_publish()
        self.register.assert_not_called()
        self.run_publish()
        self.assertEqual(self.write.call_count, 1)

    def test_partial_prefix_fails_without_mutation(self):
        self.client.seed(self.bucket, self.prefix + "part-00000.snappy.parquet")
        before = dict(self.client.objects)
        with self.assertRaisesRegex(SilverIntegrityError, "no _SUCCESS"):
            self.run_publish()
        self.write.assert_not_called()
        self.register.assert_not_called()
        self.assertEqual(before, self.client.objects)

    def test_corrupt_readback_leaves_output_and_never_registers(self):
        self.readback.side_effect = SilverIntegrityError("read-back mismatch")
        with self.assertRaises(SilverIntegrityError):
            self.run_publish()
        self.register.assert_not_called()
        self.assertIn((self.bucket, self.prefix + "_SUCCESS"), self.client.objects)
        self.assertNotIn((self.bucket, self.prefix + "_manifest.json"), self.client.objects)

    def test_registered_but_missing_output_is_not_recreated(self):
        self.record = {"id": 99}
        with self.assertRaisesRegex(SilverIntegrityError, "output is missing"):
            self.run_publish()
        self.write.assert_not_called()

    def test_existing_manifest_inventory_change_is_rejected(self):
        self.run_publish()
        self.client.seed(self.bucket, self.prefix + "part-00000-test.snappy.parquet", b"modified bytes")
        with self.assertRaisesRegex(SilverIntegrityError, "manifest does not match"):
            self.run_publish()
        self.assertEqual(self.write.call_count, 1)

    def test_existing_catalog_conflict_fails(self):
        self.run_publish()
        self.record["row_count"] = 999
        with self.assertRaisesRegex(SilverIntegrityError, "catalog record conflicts"):
            self.run_publish()
        self.assertEqual(self.write.call_count, 1)

    def test_registered_build_missing_manifest_is_corrupt_not_repaired(self):
        self.run_publish()
        self.client.objects.pop((self.bucket, self.prefix + "_manifest.json"))
        with self.assertRaisesRegex(SilverIntegrityError, "missing its manifest"):
            self.run_publish()
        self.assertEqual(self.write.call_count, 1)
        self.assertEqual(self.register.call_count, 1)

    def test_spark_write_failure_does_not_cleanup_partial_output(self):
        def fail(frame, uri):
            self.client.seed(self.bucket, self.prefix + "part-partial.snappy.parquet")
            raise RuntimeError("write failed")
        self.write.side_effect = fail
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertIn((self.bucket, self.prefix + "part-partial.snappy.parquet"), self.client.objects)
        self.register.assert_not_called()
        self.assertFalse(any(call[0] == "put" for call in self.client.calls))

    def test_racing_duplicate_registration_validates_returned_catalog(self):
        def duplicate(connection, **record):
            self.record = record
            return False
        self.register.side_effect = duplicate
        self.assertEqual(self.run_publish()["catalog"], "ALREADY_REGISTERED")

    def test_failure_context_distinguishes_output_manifest_and_registration(self):
        cases = (
            ("find_silver_build", "PostgreSQL registration", self.prefix),
            ("inspect_silver_output", "Silver output validation", self.prefix),
            ("write_new_silver", "Silver output write", self.prefix),
            ("make_manifest", "manifest", self.prefix + "_manifest.json"),
            ("read_manifest", "manifest", self.prefix + "_manifest.json"),
            ("validate_readback", "Silver output validation", self.prefix),
            ("ensure_manifest", "manifest", self.prefix + "_manifest.json"),
            ("register_silver_build", "PostgreSQL registration", self.prefix),
        )
        for operation, stage, key in cases:
            with self.subTest(operation=operation):
                self.client.objects.clear()
                diagnostics = PublishDiagnostics()
                diagnostics.set("child HEAD preflight", "HeadObject", match_id=99, key="stale.json")
                error = ReadTimeoutError(endpoint_url="https://synthetic-private-credential.example.invalid")
                with patch.object(publish, operation, side_effect=error), self.assertRaises(ReadTimeoutError) as caught:
                    publish.publish_build(**self.params, diagnostics=diagnostics)
                self.assertIs(caught.exception, error)  # No wrapping or manual retry.
                diagnostic = diagnostics.failure(caught.exception)
                for field in (f'stage="{stage}"', f'operation="{operation}"', 'match_id=n/a',
                              f'key="{key}"', 'exception=ReadTimeoutError'):
                    self.assertIn(field, diagnostic)
                self.assertNotIn("private-credential", diagnostic)
                self.assertNotIn("stale.json", diagnostic)

    def test_output_integrity_error_keeps_its_class_and_stage(self):
        diagnostics = PublishDiagnostics()
        self.client.seed(self.bucket, self.prefix + "part-partial.snappy.parquet")
        with self.assertRaises(SilverIntegrityError) as caught:
            publish.publish_build(**self.params, diagnostics=diagnostics)
        diagnostic = diagnostics.failure(caught.exception, integrity=True)
        self.assertIn('stage="Silver output validation"', diagnostic)
        self.assertIn("exception=SilverIntegrityError category=integrity", diagnostic)
        self.assertNotIn("ReadTimeoutError", diagnostic)
        self.write.assert_not_called()
        self.register.assert_not_called()


if __name__ == "__main__":
    unittest.main()
