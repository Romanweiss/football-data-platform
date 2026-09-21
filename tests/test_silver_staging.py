"""Offline staging/selection tests; no network or database access."""

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from botocore.response import StreamingBody

from src.common.bronze import BronzeIntegrityError
from src.common.checksum import sha256_bytes
from src.silver.staging import select_event_artifacts, stage_event_artifact
from src.statsbomb.events import EventArtifactError

BASE = "https://raw.githubusercontent.com/hudl/open-data/master/data/events/"


class ArtifactSelectionTests(unittest.TestCase):
    def test_preserves_order_and_applies_limit(self):
        artifacts = [{"source_url": BASE + f"{n}.json"} for n in (10, 2, 3)]
        self.assertEqual(select_event_artifacts(artifacts), artifacts)
        self.assertEqual(select_event_artifacts(artifacts, limit=2), artifacts[:2])
        self.assertEqual(select_event_artifacts(artifacts, limit=99), artifacts)

    def test_empty_catalog_rejected(self):
        with self.assertRaisesRegex(EventArtifactError, "ingest Bronze first"):
            select_event_artifacts([])

    def test_invalid_url_after_limit_is_still_rejected(self):
        with self.assertRaises(EventArtifactError):
            select_event_artifacts([{"source_url": BASE + "1.json"}, {"source_url": "invalid"}], limit=1)

    def test_duplicate_logical_source_rejected_before_limit(self):
        artifacts = [{"source_url": BASE + "1.json", "id": n} for n in (8, 9)]
        with self.assertRaisesRegex(EventArtifactError, "Duplicate logical event source"):
            select_event_artifacts(artifacts, limit=1)

    def test_invalid_limits_rejected(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(EventArtifactError):
                select_event_artifacts([{"source_url": BASE + "1.json"}], limit=limit)


class StageEventArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "bronze_events"
        self.client = MagicMock(spec=["get_object"])
        self.raw = b'[ {"id": "synthetic-event", "extra": 1} ]\r\n'
        self.artifact = {
            "source_url": BASE + "7.json", "s3_bucket": "catalog-bucket",
            "object_key": "catalog/key", "sha256": sha256_bytes(self.raw), "size_bytes": len(self.raw),
        }

    def test_reader_receives_catalog_identity_and_bytes_are_not_reserialized(self):
        with patch("src.silver.staging.read_bronze_object", return_value=self.raw) as reader:
            result = stage_event_artifact(self.client, self.artifact, staging_dir=self.directory)
        reader.assert_called_once_with(
            self.client, bucket="catalog-bucket", key="catalog/key", checksum=sha256_bytes(self.raw),
        )
        self.assertEqual(result, self.directory / "match_id=7.json")
        self.assertEqual(result.read_bytes(), self.raw)

    def test_real_reader_verifies_sha_and_closes_body(self):
        stream = io.BytesIO(self.raw)
        self.client.get_object.return_value = {"Body": StreamingBody(stream, len(self.raw))}
        result = stage_event_artifact(self.client, self.artifact, staging_dir=self.directory)
        self.assertEqual(result.read_bytes(), self.raw)
        self.assertTrue(stream.closed)
        self.client.get_object.assert_called_once_with(Bucket="catalog-bucket", Key="catalog/key")

    def test_checksum_failure_does_not_replace_existing_local_copy(self):
        self.directory.mkdir()
        target = self.directory / "match_id=7.json"
        target.write_bytes(b"previous verified copy")
        stream = io.BytesIO(b"corrupted")
        self.client.get_object.return_value = {"Body": StreamingBody(stream, 9)}
        with self.assertRaises(BronzeIntegrityError):
            stage_event_artifact(self.client, self.artifact, staging_dir=self.directory)
        self.assertEqual(target.read_bytes(), b"previous verified copy")
        self.assertTrue(stream.closed)

    def test_invalid_url_does_not_download_or_create_directory(self):
        self.artifact["source_url"] = "https://example.invalid/7.json"
        with self.assertRaises(EventArtifactError):
            stage_event_artifact(self.client, self.artifact, staging_dir=self.directory)
        self.client.get_object.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_repeat_replaces_only_own_local_file(self):
        self.directory.mkdir()
        unrelated = self.directory / "keep.txt"
        unrelated.write_bytes(b"keep")
        with patch("src.silver.staging.read_bronze_object", side_effect=[b"first", self.raw]):
            stage_event_artifact(self.client, self.artifact, staging_dir=self.directory)
            result = stage_event_artifact(self.client, self.artifact, staging_dir=self.directory)
        self.assertEqual(result.read_bytes(), self.raw)
        self.assertEqual(unrelated.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
