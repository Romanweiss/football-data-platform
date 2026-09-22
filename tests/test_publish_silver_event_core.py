"""CLI and full-parent selection tests with no real Spark, S3 or PostgreSQL."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from botocore.exceptions import ReadTimeoutError

from silver_fakes import FakeS3, artifact
from scripts import publish_silver_event_core as job
from src.common.bronze import BronzeIntegrityError
from src.common.checksum import sha256_bytes
from src.silver import publish
from src.silver.manifest import SilverIntegrityError


class PublishJobTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.pg = self.enterContext(patch.object(job, "create_postgres_connection"))
        self.client = FakeS3()
        self.enterContext(patch.object(job, "create_s3_client", return_value=self.client))
        parent_raw = b'[{"match_id": 1}, {"match_id": 2}, {"match_id": 3}]'
        self.parent = {"s3_bucket": "test-bucket", "object_key": "parent.json", "sha256": sha256_bytes(parent_raw)}
        self.client.seed("test-bucket", "parent.json", parent_raw)
        self.parent_lookup = self.enterContext(patch.object(job, "find_latest_ingestion_object", return_value=self.parent))
        self.inputs = [artifact(3), artifact(2), artifact(1), artifact(99)]
        for item in self.inputs:
            self.client.seed(item["s3_bucket"], item["object_key"], b"unused-event-body", {"sha256": item["sha256"]})
        self.lookup = self.enterContext(patch.object(job, "find_latest_ingestion_objects", return_value=self.inputs))
        self.spark_factory = self.enterContext(patch.object(job, "create_spark_session"))
        self.configure = self.enterContext(patch.object(job, "configure_s3a"))
        self.enterContext(patch.object(job, "runtime_versions", return_value={
            "Spark version": "4.2.0", "Hadoop version": "3.5.0", "S3A filesystem implementation": "S3AFileSystem",
        }))
        self.frame = MagicMock()
        self.frame.schema.json.return_value = '{"fields":[]}'
        self.build = self.enterContext(patch.object(job, "build_event_frame", side_effect=lambda spark, paths: (
            self.frame, {"row_count": len(paths) * 3, "match_count": len(paths)},
        )))
        self.publish = self.enterContext(patch.object(job, "publish_build", return_value={
            "file_count": 4, "build_id": "b" * 64, "output_uri": "s3a://test-bucket/output/",
            "catalog": "REGISTERED", "output_status": "CREATED",
        }))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.stdout))
        self.enterContext(redirect_stderr(self.stderr))

    def test_limit_without_check_only_is_rejected_before_io(self):
        with self.assertRaises(SystemExit) as caught:
            job.main(["--limit", "2"])
        self.assertEqual(caught.exception.code, 2)
        self.pg.assert_not_called()
        self.spark_factory.assert_not_called()

    def test_limit_two_check_only_reads_events_only_via_spark_and_never_publishes(self):
        self.assertEqual(job.main(["--limit", "2", "--check-only"]), 0)
        self.publish.assert_not_called()
        paths = self.build.call_args.args[1]
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(path.startswith("s3a://") for path in paths))
        self.assertEqual([call for call in self.client.calls if call[0] == "get"], [("get", "test-bucket", "parent.json")])
        self.assertEqual(len([call for call in self.client.calls if call[0] == "head"]), 2)
        self.assertFalse(any(call[0] == "put" for call in self.client.calls))
        for message in ("Parent matches: 3", "Bronze artifacts selected: 2", "Matches processed: 2",
                        "Events read: 6", "Input fingerprint:", "Schema SHA256:", "Calculated build_id:",
                        "CHECK ONLY - nothing published"):
            self.assertIn(message, self.stdout.getvalue())
        self.frame.unpersist.assert_called_once()
        self.spark_factory.return_value.stop.assert_called_once()

    def test_progress_is_reported_before_spark_reads(self):
        def build(spark, paths):
            output = self.stdout.getvalue()
            messages = [
                "Parent catalog artifact found", "Parent Bronze verified", "Parent matches discovered: 3",
                "Event artifacts selected: 2", "Bronze metadata preflight: 1/2, match_id=1",
                "Bronze metadata preflight: 2/2, match_id=2",
            ]
            positions = [output.index(message) for message in messages]
            self.assertEqual(positions, sorted(positions))
            return self.frame, {"row_count": 6, "match_count": 2}

        self.build.side_effect = build
        self.assertEqual(job.main(["--limit", "2", "--check-only"]), 0)

    def test_full_publish_uses_exact_parent_not_extra_league(self):
        self.assertEqual(job.main([]), 0)
        self.assertEqual([item["match_id"] for item in self.publish.call_args.kwargs["inputs"]], [1, 2, 3])
        self.assertIn("Silver event_core publish complete", self.stdout.getvalue())

    def test_missing_parent_child_fails_even_with_limit_one(self):
        self.lookup.return_value = [artifact(1), artifact(99)]
        self.assertEqual(job.main(["--limit", "1", "--check-only"]), 1)
        self.build.assert_not_called()
        self.publish.assert_not_called()
        self.assertIn('stage="membership"', self.stderr.getvalue())
        self.assertIn('operation="select_parent_event_artifacts"', self.stderr.getvalue())
        self.assertIn("exception=EventArtifactError", self.stderr.getvalue())

    def test_bad_metadata_fails_before_spark(self):
        item = artifact(1)
        self.client.objects[(item["s3_bucket"], item["object_key"])]["Metadata"] = {}
        self.assertEqual(job.main(["--check-only"]), 1)
        self.spark_factory.assert_not_called()
        self.assertIn("exception=BronzeIntegrityError category=integrity", self.stderr.getvalue())
        self.assertNotIn("ReadTimeoutError", self.stderr.getvalue())

    def test_parent_catalog_failure_is_separate_from_get_and_membership(self):
        self.parent_lookup.side_effect = RuntimeError("synthetic-private-credential")
        self.assertEqual(job.main(["--check-only"]), 1)
        self.assertIn('stage="parent catalog"', self.stderr.getvalue())
        self.assertIn('operation="find_latest_ingestion_object"', self.stderr.getvalue())
        self.assertNotIn("private-credential", self.stderr.getvalue())
        self.assertNotIn("Parent catalog artifact found", self.stdout.getvalue())
        self.assertFalse(any(call[0] == "get" for call in self.client.calls))

    def test_parent_get_timeout_has_safe_context(self):
        error = ReadTimeoutError(endpoint_url="https://synthetic-private-credential.example.invalid")
        with patch.object(self.client, "get_object", side_effect=error):
            self.assertEqual(job.main(["--check-only"]), 1)
        diagnostic = self.stderr.getvalue()
        for field in ('stage="parent GET/integrity"', 'operation="GetObject/verify_sha256"',
                      'match_id=n/a', 'key="parent.json"', 'exception=ReadTimeoutError'):
            self.assertIn(field, diagnostic)
        self.assertNotIn("private-credential", diagnostic)
        self.assertNotIn("Parent Bronze verified", self.stdout.getvalue())
        self.spark_factory.assert_not_called()

    def test_parent_checksum_error_remains_an_integrity_failure(self):
        self.client.seed("test-bucket", "parent.json", b"corrupt-parent")
        self.assertEqual(job.main(["--check-only"]), 1)
        self.assertIn('stage="parent GET/integrity"', self.stderr.getvalue())
        self.assertIn("exception=BronzeIntegrityError category=integrity", self.stderr.getvalue())
        self.assertNotIn("Parent Bronze verified", self.stdout.getvalue())
        self.spark_factory.assert_not_called()

    def test_child_head_timeout_identifies_current_match_without_manual_retries(self):
        original_head = self.client.head_object
        calls = []

        def head(**kwargs):
            calls.append(kwargs["Key"])
            if kwargs["Key"] == artifact(2)["object_key"]:
                raise ReadTimeoutError(endpoint_url="https://synthetic-private-credential.example.invalid")
            return original_head(**kwargs)

        with patch.object(self.client, "head_object", side_effect=head):
            self.assertEqual(job.main(["--check-only"]), 1)
        diagnostic = self.stderr.getvalue()
        for field in ('stage="child HEAD preflight"', 'operation="HeadObject/verify_metadata"',
                      'match_id=2', f'key="{artifact(2)["object_key"]}"', 'exception=ReadTimeoutError'):
            self.assertIn(field, diagnostic)
        self.assertEqual(calls, [artifact(1)["object_key"], artifact(2)["object_key"]])
        self.assertIn("Bronze metadata preflight: 2/3, match_id=2", self.stdout.getvalue())
        self.assertNotIn("private-credential", diagnostic)
        self.assertNotIn("category=integrity", diagnostic)
        self.spark_factory.assert_not_called()
        self.publish.assert_not_called()

    def test_spark_batch_failure_does_not_reuse_last_child_context(self):
        self.build.side_effect = RuntimeError("synthetic-private-credential")
        self.assertEqual(job.main(["--check-only"]), 1)
        for field in ('stage="Spark S3A read"', 'operation="read_transform_dq"', 'match_id=n/a', 'key=n/a'):
            self.assertIn(field, self.stderr.getvalue())
        self.assertNotIn("private-credential", self.stderr.getvalue())
        self.publish.assert_not_called()

    def test_spark_single_input_failure_keeps_known_object_context(self):
        self.build.side_effect = RuntimeError("synthetic-private-credential")
        self.assertEqual(job.main(["--check-only", "--limit", "1"]), 1)
        self.assertIn("match_id=1", self.stderr.getvalue())
        self.assertIn(f'key="{artifact(1)["object_key"]}"', self.stderr.getvalue())

    def test_raw_exceptions_and_credential_values_never_enter_diagnostics(self):
        credentials = {"S3_ACCESS_KEY": "synthetic-access-secret", "S3_SECRET_KEY": "synthetic-private-secret"}
        raw = "RAW_EXCEPTION " + " ".join(credentials.values())
        for error in (RuntimeError(raw), BronzeIntegrityError(raw), SilverIntegrityError(raw),
                      ReadTimeoutError(endpoint_url="https://example.invalid/" + raw)):
            with self.subTest(exception=type(error).__name__), patch.dict(os.environ, credentials):
                self.stdout.seek(0)
                self.stdout.truncate()
                self.stderr.seek(0)
                self.stderr.truncate()
                self.publish.side_effect = error
                self.assertEqual(job.main([]), 1)
                output = self.stdout.getvalue() + self.stderr.getvalue()
                for forbidden in (*credentials.values(), "RAW_EXCEPTION", "Traceback", "publish complete"):
                    self.assertNotIn(forbidden, output)
                self.assertIn(f"exception={type(error).__name__}", self.stderr.getvalue())

    def test_remote_error_never_leaks_details_or_reports_success(self):
        self.publish.side_effect = RuntimeError("synthetic-private-credential")
        self.assertEqual(job.main([]), 1)
        self.assertNotIn("private-credential", self.stderr.getvalue())
        self.assertNotIn("publish complete", self.stdout.getvalue())

    def test_manifest_timeout_context_reaches_cli_from_real_publisher(self):
        self.publish.side_effect = publish.publish_build
        error = ReadTimeoutError(endpoint_url="https://synthetic-private-credential.example.invalid")
        with (
            patch.object(publish, "find_silver_build", return_value=None),
            patch.object(publish, "inspect_silver_output", return_value=[{
                "object_key": "output/part-00000.snappy.parquet", "size_bytes": 10, "etag": "test-etag",
            }]),
            patch.object(publish, "read_manifest", side_effect=error),
        ):
            self.assertEqual(job.main([]), 1)
        for field in ('stage="manifest"', 'operation="read_manifest"', 'match_id=n/a',
                      '/_manifest.json"', 'exception=ReadTimeoutError'):
            self.assertIn(field, self.stderr.getvalue())
        self.assertNotIn("private-credential", self.stderr.getvalue())
        self.assertNotIn("publish complete", self.stdout.getvalue())

    def test_spark_cleanup_errors_cannot_leak_or_hide_primary_diagnostic(self):
        self.publish.side_effect = ReadTimeoutError(endpoint_url="https://synthetic-private-credential.example.invalid")
        self.frame.unpersist.side_effect = RuntimeError("synthetic-private-credential")
        self.spark_factory.return_value.stop.side_effect = RuntimeError("synthetic-private-credential")
        self.assertEqual(job.main([]), 1)
        diagnostic = self.stderr.getvalue()
        for field in ('exception=ReadTimeoutError', 'stage="Spark cleanup"',
                      'operation="unpersist"', 'operation="stop"'):
            self.assertIn(field, diagnostic)
        self.assertNotIn("private-credential", diagnostic)
        self.frame.unpersist.assert_called_once()
        self.spark_factory.return_value.stop.assert_called_once()

    def test_cleanup_failure_after_check_only_returns_nonzero_safely(self):
        self.spark_factory.return_value.stop.side_effect = RuntimeError("synthetic-private-credential")
        self.assertEqual(job.main(["--check-only"]), 1)
        self.assertIn('stage="Spark cleanup" operation="stop"', self.stderr.getvalue())
        self.assertNotIn("private-credential", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
