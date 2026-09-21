"""Offline job orchestration tests; Spark and all external clients are mocked."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import build_silver_event_core as job
from src.common.bronze import BronzeIntegrityError

BASE = "https://raw.githubusercontent.com/hudl/open-data/master/data/events/"


class SilverJobTests(unittest.TestCase):
    def setUp(self):
        self.pg = self.enterContext(patch.object(job, "create_postgres_connection"))
        self.lookup = self.enterContext(patch.object(job, "find_latest_ingestion_objects"))
        self.s3 = self.enterContext(patch.object(job, "create_s3_client"))
        self.stage = self.enterContext(patch.object(job, "stage_event_artifact"))
        self.build = self.enterContext(patch.object(job, "build_local_preview"))
        self.lookup.return_value = [{"source_url": BASE + f"{n}.json"} for n in (1, 2, 3)]
        self.stage.side_effect = lambda client, artifact, **kwargs: Path(
            "/app/data/work/bronze_events/match_id=" + artifact["source_url"].rsplit("/", 1)[1]
        )
        self.build.return_value = {
            "match_count": 2, "row_count": 5, "spark_version": "4.2.0", "output_partitions": 4,
        }
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.stdout))
        self.enterContext(redirect_stderr(self.stderr))

    def test_limit_and_summary_after_successful_local_write(self):
        def build(paths):
            self.assertNotIn("build complete", self.stdout.getvalue())
            self.assertEqual(len(paths), 2)
            self.pg.return_value.__exit__.assert_called_once_with(None, None, None)
            self.s3.return_value.close.assert_called_once()
            return self.build.return_value

        self.build.side_effect = build
        self.assertEqual(job.main(["--limit", "2"]), 0)
        self.lookup.assert_called_once_with(
            self.pg.return_value.__enter__.return_value, source="statsbomb", dataset="match_events",
        )
        self.assertEqual(self.stage.call_count, 2)
        self.assertEqual([call.args[1] for call in self.stage.call_args_list], self.lookup.return_value[:2])
        for message in (
            "Silver event_core build complete", "Bronze artifacts selected: 2", "Matches processed: 2",
            "Events read: 5", "Events written: 5", "Output partitions: 4",
            "Output: data/work/silver/event_core", "Spark version: 4.2.0",
        ):
            self.assertIn(message, self.stdout.getvalue())

    def test_no_limit_stages_all_artifacts(self):
        self.assertEqual(job.main([]), 0)
        self.assertEqual(self.stage.call_count, 3)

    def test_invalid_limit_never_accesses_catalog(self):
        for limit in ("0", "-1", "word", "1.5"):
            with self.subTest(limit=limit), self.assertRaises(SystemExit) as caught:
                job.main(["--limit", limit])
            self.assertEqual(caught.exception.code, 2)
        self.pg.assert_not_called()

    def test_bad_or_duplicate_source_after_limit_never_stages(self):
        for second in ("invalid", BASE + "1.json"):
            self.lookup.return_value = [{"source_url": BASE + "1.json"}, {"source_url": second}]
            self.assertEqual(job.main(["--limit", "1"]), 1)
        self.s3.assert_not_called()
        self.build.assert_not_called()

    def test_empty_catalog_never_stages(self):
        self.lookup.return_value = []
        self.assertEqual(job.main([]), 1)
        self.s3.assert_not_called()
        self.build.assert_not_called()

    def test_checksum_failure_never_starts_spark(self):
        self.stage.side_effect = BronzeIntegrityError("SHA-256 mismatch")
        self.assertEqual(job.main([]), 1)
        self.build.assert_not_called()
        self.assertNotIn("build complete", self.stdout.getvalue())
        self.s3.return_value.close.assert_called_once()

    def test_catalog_failure_is_nonzero_and_does_not_leak_details(self):
        self.lookup.side_effect = RuntimeError("synthetic private credential")
        self.assertEqual(job.main([]), 1)
        self.s3.assert_not_called()
        self.assertNotIn("private credential", self.stderr.getvalue())

    def test_write_failure_never_reports_success_or_leaks_data(self):
        self.build.side_effect = RuntimeError("synthetic private payload")
        self.assertEqual(job.main([]), 1)
        self.assertNotIn("build complete", self.stdout.getvalue())
        self.assertNotIn("private payload", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
