"""Lineup CLI uses shared preflight and publication with no external IO."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from scripts import publish_silver_lineup_domains as cli
from silver_fakes import FakeS3
from test_lineup_inputs import lineup_artifact
from src.common.checksum import sha256_bytes
from src.silver import job


class LineupCliTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.client = FakeS3()
        parent = b'[{"match_id": 1}, {"match_id": 2}, {"match_id": 3}]'
        self.client.seed("test-bucket", "parent.json", parent)
        self.pg = self.enterContext(patch.object(job, "create_postgres_connection"))
        self.enterContext(patch.object(job, "create_s3_client", return_value=self.client))
        self.enterContext(patch.object(job, "find_latest_ingestion_object", return_value={
            "s3_bucket": "test-bucket", "object_key": "parent.json", "sha256": sha256_bytes(parent),
        }))
        inputs = [lineup_artifact(3), lineup_artifact(99), lineup_artifact(2), lineup_artifact(1)]
        for item in inputs:
            self.client.seed("test-bucket", item["object_key"], metadata={"sha256": item["sha256"]})
        self.lookup = self.enterContext(patch.object(job, "find_latest_ingestion_objects", return_value=inputs))
        self.spark = self.enterContext(patch.object(job, "create_spark_session"))
        self.enterContext(patch.object(job, "configure_s3a"))
        self.enterContext(patch.object(job, "runtime_versions", return_value={}))
        self.frame = MagicMock()
        self.frame.schema.json.return_value = '{"fields":[]}'
        self.build = self.enterContext(patch.object(cli, "build_lineup_frame", side_effect=lambda spark, paths, ids, **kw: (
            self.frame, {"row_count": 4, "input_match_count": len(ids),
                         "raw_lineup_team_rows": len(ids) * 2, "raw_lineup_player_rows": len(ids) * 4},
        )))
        self.publish = self.enterContext(patch.object(job, "publish_build", return_value={
            "file_count": 2, "build_id": "b" * 64, "output_uri": "s3a://test-bucket/output/",
            "catalog": "REGISTERED", "output_status": "CREATED",
        }))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.stdout))
        self.enterContext(redirect_stderr(self.stderr))

    def test_invalid_dataset_and_partial_publish_rejected_before_io(self):
        for args in ([], ["--dataset", "events"], ["--dataset", "all"], ["--dataset", "match_squads"],
                     ["--dataset", "teams", "--limit", "2"], ["--dataset", "players", "--check-only", "--limit", "0"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as caught:
                cli.main(args)
            self.assertEqual(caught.exception.code, 2)
        self.pg.assert_not_called()
        self.spark.assert_not_called()

    def test_check_only_all_choices_never_publish_or_get_bulk_bodies(self):
        for choice in cli.DATASETS:
            self.client.calls.clear()
            self.assertEqual(cli.main(["--dataset", choice, "--limit", "2", "--check-only"]), 0)
            self.assertEqual(self.lookup.call_args.kwargs["dataset"], "match_lineups")
            self.assertEqual(self.build.call_args.args[2], [1, 2])
            self.assertTrue(all(path.endswith("/lineups.json") and path.startswith("s3a://") for path in self.build.call_args.args[1]))
            self.assertEqual([call for call in self.client.calls if call[0] == "get"], [("get", "test-bucket", "parent.json")])
            self.assertEqual(sum(call[0] == "head" for call in self.client.calls), 2)
            self.assertFalse(any(call[0] in ("put", "list") for call in self.client.calls))
            for message in (f"Dataset: {cli.DATASETS[choice]}", "Parent matches: 3", "Bronze artifacts selected: 2",
                            "Matches processed: 2", "Raw lineup team rows: 4", "Raw lineup player rows: 8",
                            "Output rows: 4", "DQ: PASSED", "Input fingerprint:", "Schema SHA256:", "Build ID:",
                            "CHECK ONLY - nothing published"):
                self.assertIn(message, self.stdout.getvalue())
        self.publish.assert_not_called()

    def test_full_publish_uses_one_dataset_and_complete_parent(self):
        for choice, dataset in cli.DATASETS.items():
            self.publish.reset_mock()
            self.assertEqual(cli.main(["--dataset", choice]), 0)
            self.publish.assert_called_once()
            options = self.publish.call_args.kwargs
            self.assertEqual([item["match_id"] for item in options["inputs"]], [1, 2, 3])
            self.assertEqual(options["specification"]["dataset"], dataset)
            self.assertEqual(options["specification"]["transform_version"], dataset + "_v1")

    def test_missing_match_fails_even_with_limit_one(self):
        self.lookup.return_value = [lineup_artifact(1)]
        self.assertEqual(cli.main(["--dataset", "teams", "--limit", "1", "--check-only"]), 1)
        self.spark.assert_not_called()
        self.publish.assert_not_called()

    def test_duplicate_match_and_metadata_corruption_fail_before_spark(self):
        self.lookup.return_value.append(lineup_artifact(1))
        self.assertEqual(cli.main(["--dataset", "players", "--check-only"]), 1)
        self.lookup.return_value.pop()
        self.client.objects[("test-bucket", lineup_artifact(1)["object_key"])]["Metadata"] = {}
        self.assertEqual(cli.main(["--dataset", "players", "--check-only"]), 1)
        self.spark.assert_not_called()
        self.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
