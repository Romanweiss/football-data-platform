"""Domain CLI through shared orchestration with mocked Spark and in-memory S3."""

from context_fixtures import CONTEXT_ARGS, BRONZE_ARGS

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from scripts import publish_silver_event_domains as cli
from silver_fakes import FakeS3, artifact
from src.common.checksum import sha256_bytes
from src.silver import job


class DomainCliTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.client = FakeS3()
        parent = b'[{"match_id": 1, "competition": {"competition_id": 43}, "season": {"season_id": 106}}, {"match_id": 2, "competition": {"competition_id": 43}, "season": {"season_id": 106}}, {"match_id": 3, "competition": {"competition_id": 43}, "season": {"season_id": 106}}]'
        self.client.seed("test-bucket", "parent.json", parent)
        self.pg = self.enterContext(patch.object(job, "create_postgres_connection"))
        self.s3 = self.enterContext(patch.object(job, "create_s3_client", return_value=self.client))
        self.enterContext(patch.object(job, "find_matches_parent", return_value={
            "s3_bucket": "test-bucket", "object_key": "parent.json", "sha256": sha256_bytes(parent),
        }))
        self.inputs = [artifact(3), artifact(99), artifact(1), artifact(2)]
        for item in self.inputs:
            self.client.seed(item["s3_bucket"], item["object_key"], metadata={"sha256": item["sha256"]})
        self.lookup = self.enterContext(patch.object(job, "find_latest_ingestion_objects", return_value=self.inputs))
        self.spark = self.enterContext(patch.object(job, "create_spark_session"))
        self.enterContext(patch.object(job, "configure_s3a"))
        self.enterContext(patch.object(job, "runtime_versions", return_value={"Spark version": "4.2.0", "Hadoop version": "3.5.0"}))
        self.frame = MagicMock()
        self.frame.schema.json.return_value = '{"fields":[]}'
        self.build = self.enterContext(patch.object(cli, "build_domain_frame", side_effect=lambda spark, paths, ids, **kw: (
            self.frame, {"row_count": len(ids) * 3, "match_count": len(ids), "input_row_count": len(ids) * 10},
        )))
        self.publish = self.enterContext(patch.object(job, "publish_build", return_value={
            "file_count": 4, "build_id": "b" * 64, "output_uri": "s3a://test-bucket/output/",
            "catalog": "REGISTERED", "output_status": "CREATED",
        }))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.stdout))
        self.enterContext(redirect_stderr(self.stderr))

    def test_invalid_dataset_missing_dataset_and_partial_publish_rejected_before_io(self):
        for args in ([], ["--dataset", "invalid"], ["--dataset", "event_core"], ["--dataset", "both"],
                     ["--dataset", "passes", "--limit", "2"], ["--dataset", "shots", "--limit", "1"],
                     ["--dataset", "passes", "--check-only", "--limit", "0"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as caught:
                cli.main(args)
            self.assertEqual(caught.exception.code, 2)
        self.pg.assert_not_called()
        self.s3.assert_not_called()
        self.spark.assert_not_called()

    def test_check_only_limits_exact_parent_and_has_no_publication(self):
        for choice, dataset in (("passes", "pass_events"), ("shots", "shot_events")):
            with self.subTest(dataset=dataset):
                self.client.calls.clear()
                self.assertEqual(cli.main(BRONZE_ARGS + ["--dataset", choice, "--limit", "2", "--check-only"]), 0)
                self.assertEqual(self.build.call_args.args[2], [1, 2])
                self.assertEqual(self.build.call_args.kwargs, {"dataset": choice, "competition_id": 43, "season_id": 106})
                self.assertTrue(all(path.startswith("s3a://") for path in self.build.call_args.args[1]))
                self.publish.assert_not_called()
                self.assertEqual([call for call in self.client.calls if call[0] == "get"], [("get", "test-bucket", "parent.json")])
                self.assertEqual(sum(call[0] == "head" for call in self.client.calls), 2)
                self.assertFalse(any(call[0] in ("put", "list") for call in self.client.calls))
                for message in (f"Dataset: {dataset}", f"Transform version: {dataset}_v1", "Spark version: 4.2.0",
                                "Hadoop version: 3.5.0", "Parent matches: 3", "Bronze artifacts selected: 2",
                                "Matches processed: 2", "Input events: 20", "Domain events: 6", "DQ: PASSED",
                                "Input fingerprint:", "Schema SHA256:", "Build ID:", "CHECK ONLY - nothing published"):
                    self.assertIn(message, self.stdout.getvalue())

    def test_full_publish_uses_one_dataset_and_all_parent_inputs(self):
        for choice, dataset in (("passes", "pass_events"), ("shots", "shot_events")):
            with self.subTest(dataset=dataset):
                self.publish.reset_mock()
                self.assertEqual(cli.main(BRONZE_ARGS + ["--dataset", choice]), 0)
                self.publish.assert_called_once()
                arguments = self.publish.call_args.kwargs
                self.assertEqual([item["match_id"] for item in arguments["inputs"]], [1, 2, 3])
                self.assertEqual(arguments["specification"]["dataset"], dataset)
                self.assertEqual(arguments["specification"]["transform_version"], dataset + "_v1")
                self.assertEqual(arguments["specification"]["competition_id"], 43)
                self.assertEqual(arguments["specification"]["season_id"], 106)

    def test_missing_match_is_rejected_before_limit_and_before_spark(self):
        self.lookup.return_value = [artifact(1), artifact(99)]
        self.assertEqual(cli.main(BRONZE_ARGS + ["--dataset", "passes", "--limit", "1", "--check-only"]), 1)
        self.spark.assert_not_called()
        self.publish.assert_not_called()
        self.assertIn('stage="membership"', self.stderr.getvalue())

    def test_duplicate_match_fails_before_spark(self):
        self.lookup.return_value = self.inputs + [artifact(1)]
        self.assertEqual(cli.main(BRONZE_ARGS + ["--dataset", "shots", "--check-only"]), 1)
        self.spark.assert_not_called()
        self.publish.assert_not_called()

    def test_build_failure_never_publishes_or_exposes_raw_exception(self):
        self.build.side_effect = ValueError("synthetic-private-credential")
        self.assertEqual(cli.main(BRONZE_ARGS + ["--dataset", "passes"]), 1)
        self.publish.assert_not_called()
        self.assertNotIn("private-credential", self.stderr.getvalue())
        self.assertNotIn("DQ: PASSED", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
