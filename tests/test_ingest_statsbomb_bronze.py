"""Offline tests: all S3 and HTTP calls are replaced with mocks."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, call, patch

from botocore.exceptions import ClientError, EndpointConnectionError

from scripts import ingest_statsbomb_bronze as ingestion
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError


def s3_error(code, status):
    return ClientError(
        {
            "Error": {"Code": code, "Message": "synthetic-access synthetic-secret"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "HeadObject",
    )


class UploadIfChangedTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=["head_object", "put_object"])
        self.data = b'[\r\n  {"id": 1, "label": "Raw  JSON"}\r\n]\n'
        self.checksum = sha256_bytes(self.data)
        self.params = {
            "bucket": "test-bucket",
            "key": ingestion.SOURCES[0][1],
            "data": self.data,
            "checksum": self.checksum,
            "source_url": ingestion.SOURCES[0][0],
        }

    def test_same_checksum_skips_upload(self):
        self.client.head_object.return_value = {"Metadata": {"sha256": self.checksum}}
        self.assertFalse(ingestion.upload_if_changed(self.client, **self.params))
        self.client.head_object.assert_called_once_with(
            Bucket="test-bucket", Key=self.params["key"]
        )
        self.client.put_object.assert_not_called()

    def test_missing_object_uploads_original_bytes_and_metadata(self):
        for code in ("404", "NoSuchKey", "NotFound", None):
            with self.subTest(code=code):
                self.client.reset_mock()
                self.client.head_object.side_effect = s3_error(code, 404)
                self.assertTrue(ingestion.upload_if_changed(self.client, **self.params))
                self.client.put_object.assert_called_once_with(
                    Bucket="test-bucket",
                    Key=self.params["key"],
                    Body=self.data,
                    ContentType="application/json",
                    Metadata={
                        "source": "statsbomb",
                        "layer": "bronze",
                        "sha256": self.checksum,
                        "source_url": self.params["source_url"],
                    },
                )
                self.assertIs(self.client.put_object.call_args.kwargs["Body"], self.data)

    def test_changed_checksum_uploads(self):
        self.client.head_object.return_value = {"Metadata": {"sha256": "old-checksum"}}
        self.assertTrue(ingestion.upload_if_changed(self.client, **self.params))
        self.client.put_object.assert_called_once()

    def test_missing_checksum_uploads(self):
        for response in ({}, {"Metadata": {}}):
            with self.subTest(response=response):
                self.client.reset_mock()
                self.client.head_object.return_value = response
                self.assertTrue(ingestion.upload_if_changed(self.client, **self.params))
                self.client.put_object.assert_called_once()

    def test_other_head_errors_propagate_without_upload(self):
        for code, status in (
            ("AccessDenied", 403),
            ("500", 500),
            ("SignatureDoesNotMatch", 403),
            ("NoSuchBucket", 404),
        ):
            with self.subTest(code=code):
                error = s3_error(code, status)
                self.client.head_object.side_effect = error
                with self.assertRaises(ClientError) as caught:
                    ingestion.upload_if_changed(self.client, **self.params)
                self.assertIs(caught.exception, error)
        self.client.put_object.assert_not_called()

    def test_put_error_propagates(self):
        self.client.head_object.return_value = {"Metadata": {}}
        error = s3_error("AccessDenied", 403)
        self.client.put_object.side_effect = error
        with self.assertRaises(ClientError) as caught:
            ingestion.upload_if_changed(self.client, **self.params)
        self.assertIs(caught.exception, error)

    def test_network_error_is_not_treated_as_missing_object(self):
        self.client.head_object.side_effect = EndpointConnectionError(
            endpoint_url="https://example.invalid"
        )
        with self.assertRaises(EndpointConnectionError):
            ingestion.upload_if_changed(self.client, **self.params)
        self.client.put_object.assert_not_called()


class IngestionMainTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.factory = self.enterContext(patch.object(ingestion, "create_s3_client"))
        self.download = self.enterContext(patch.object(ingestion, "download_bytes"))
        self.client = MagicMock(spec=["head_object", "put_object"])
        self.factory.return_value = self.client
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.errors = self.enterContext(redirect_stderr(io.StringIO()))

    def test_first_run_uploads_and_second_run_is_unchanged(self):
        data = (b'[ {"competition_id": 43} ]\n', b'[\r\n {"match_id": 1}\r\n]\n')
        self.download.side_effect = (*data, *data)
        stored = {}

        def head(*, Bucket, Key):
            if Key not in stored:
                raise s3_error("404", 404)
            return {"Metadata": stored[Key]["Metadata"]}

        def put(**kwargs):
            stored[kwargs["Key"]] = kwargs

        self.client.head_object.side_effect = head
        self.client.put_object.side_effect = put

        self.assertEqual(ingestion.main(), 0)
        self.assertEqual(self.client.put_object.call_count, 2)
        self.assertIn("Downloaded: 2\nUploaded: 2\nUnchanged: 0", self.output.getvalue())
        expected_sources = (
            (
                "https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json",
                "football/bronze/statsbomb/competitions/competitions.json",
            ),
            (
                "https://raw.githubusercontent.com/hudl/open-data/master/data/matches/43/106.json",
                "football/bronze/statsbomb/matches/competition_id=43/season_id=106/matches.json",
            ),
        )
        self.assertEqual(self.download.call_args_list, [call(url) for url, _ in expected_sources])
        self.assertEqual(set(stored), {key for _, key in expected_sources})
        for raw, (url, key) in zip(data, expected_sources):
            self.assertIs(stored[key]["Body"], raw)
            self.assertEqual(stored[key]["Metadata"]["source_url"], url)
            self.assertIn(f"UPLOADED: {key}", self.output.getvalue())
            self.assertIn(f"Bytes: {len(raw)}", self.output.getvalue())
            self.assertIn(f"SHA256: {sha256_bytes(raw)}", self.output.getvalue())

        self.output.seek(0)
        self.output.truncate()
        self.assertEqual(ingestion.main(), 0)
        self.assertEqual(self.client.put_object.call_count, 2)
        self.assertIn("Downloaded: 2\nUploaded: 0\nUnchanged: 2", self.output.getvalue())
        for _, key in expected_sources:
            self.assertIn(f"UNCHANGED: {key}", self.output.getvalue())
        self.assertEqual(self.errors.getvalue(), "")

    def test_summary_counts_mixed_results(self):
        self.download.side_effect = (b"existing", b"new")
        self.client.head_object.side_effect = (
            {"Metadata": {"sha256": sha256_bytes(b"existing")}},
            s3_error("404", 404),
        )
        self.assertEqual(ingestion.main(), 0)
        self.client.put_object.assert_called_once()
        self.assertIn("Downloaded: 2\nUploaded: 1\nUnchanged: 1", self.output.getvalue())

    def test_missing_bucket_fails_before_any_external_call(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ingestion.main(), 2)
        self.factory.assert_not_called()
        self.download.assert_not_called()

    def test_download_failure_stops_before_s3_access(self):
        self.download.side_effect = DownloadError("HTTP 503 while downloading source")
        self.assertEqual(ingestion.main(), 1)
        self.client.head_object.assert_not_called()
        self.client.put_object.assert_not_called()
        self.assertIn("HTTP 503", self.errors.getvalue())
        self.assertNotIn("ingestion complete", self.output.getvalue())

    def test_access_denied_is_reported_without_exception_message(self):
        self.download.return_value = b"[]"
        self.client.head_object.side_effect = s3_error("AccessDenied", 403)
        self.assertEqual(ingestion.main(), 1)
        self.client.put_object.assert_not_called()
        self.assertEqual(self.download.call_count, 1)
        self.assertIn("HTTP 403, code AccessDenied", self.errors.getvalue())
        self.assertNotIn("synthetic-access", self.errors.getvalue())
        self.assertNotIn("synthetic-secret", self.errors.getvalue())
        self.assertNotIn("ingestion complete", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
