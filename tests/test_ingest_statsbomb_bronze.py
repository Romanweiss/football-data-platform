"""Offline tests for immutable S3 artifacts and PostgreSQL catalog recovery."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, call, patch

import psycopg
from botocore.exceptions import ClientError, EndpointConnectionError

from scripts import ingest_statsbomb_bronze as ingestion
from src.common import bronze
from src.common.bronze import build_versioned_key
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError


def s3_error(code, status):
    return ClientError(
        {
            "Error": {"Code": code, "Message": "synthetic-access synthetic-secret"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "S3Operation",
    )


def source_key(source, data):
    return build_versioned_key(source["base_prefix"], source["filename"], sha256_bytes(data))


class UploadImmutableObjectTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=["head_object", "put_object"])
        self.data = b'[\r\n  {"id": 1, "label": "Raw  JSON"}\r\n]\n'
        source = ingestion.SOURCES[0]
        self.params = {
            "bucket": "test-bucket", "key": source_key(source, self.data),
            "data": self.data, "checksum": sha256_bytes(self.data),
            "metadata": {
                "source": "statsbomb", "layer": "bronze", "sha256": sha256_bytes(self.data),
                "source_url": source["source_url"], "dataset": source["dataset"],
            },
        }

    def test_existing_version_is_verified_without_upload(self):
        metadata = {"sha256": self.params["checksum"], "custom": "keep-me"}
        self.client.head_object.return_value = {"Metadata": metadata}
        self.assertFalse(bronze.put_immutable_object(self.client, **self.params))
        self.client.head_object.assert_called_once_with(Bucket="test-bucket", Key=self.params["key"])
        self.client.put_object.assert_not_called()
        self.assertEqual(metadata, {"sha256": self.params["checksum"], "custom": "keep-me"})

    def test_missing_object_creates_original_bytes_with_metadata_and_condition(self):
        for code in ("404", "NoSuchKey", "NotFound", None):
            with self.subTest(code=code):
                self.client.reset_mock()
                self.client.head_object.side_effect = s3_error(code, 404)
                self.assertTrue(bronze.put_immutable_object(self.client, **self.params))
                self.client.put_object.assert_called_once_with(
                    Bucket="test-bucket", Key=self.params["key"], Body=self.data,
                    ContentType="application/json", IfNoneMatch="*",
                    Metadata={
                        "source": "statsbomb", "layer": "bronze", "sha256": self.params["checksum"],
                        "source_url": self.params["metadata"]["source_url"], "dataset": "competitions",
                    },
                )
                self.assertIs(self.client.put_object.call_args.kwargs["Body"], self.data)

    def test_missing_or_wrong_metadata_fails_without_overwriting(self):
        for response in ({}, {"Metadata": {}}, {"Metadata": {"sha256": "b" * 64}}):
            with self.subTest(response=response):
                self.client.head_object.return_value = response
                with self.assertRaisesRegex(bronze.BronzeIntegrityError, "integrity violation"):
                    bronze.put_immutable_object(self.client, **self.params)
        self.client.put_object.assert_not_called()

    def test_key_checksum_mismatch_fails_before_s3_access(self):
        self.params["key"] = build_versioned_key("football/bronze", "data.json", "b" * 64)
        with self.assertRaises(bronze.BronzeIntegrityError):
            bronze.put_immutable_object(self.client, **self.params)
        self.client.head_object.assert_not_called()
        self.client.put_object.assert_not_called()

    def test_other_head_errors_propagate_without_upload(self):
        for code, status in (("AccessDenied", 403), ("500", 500), ("NoSuchBucket", 404)):
            with self.subTest(code=code):
                error = s3_error(code, status)
                self.client.head_object.side_effect = error
                with self.assertRaises(ClientError) as caught:
                    bronze.put_immutable_object(self.client, **self.params)
                self.assertIs(caught.exception, error)
        self.client.put_object.assert_not_called()

    def test_put_error_propagates(self):
        self.client.head_object.side_effect = s3_error("404", 404)
        self.client.put_object.side_effect = s3_error("AccessDenied", 403)
        with self.assertRaises(ClientError):
            bronze.put_immutable_object(self.client, **self.params)

    def test_network_error_is_not_treated_as_missing_object(self):
        self.client.head_object.side_effect = EndpointConnectionError(endpoint_url="https://example.invalid")
        with self.assertRaises(EndpointConnectionError):
            bronze.put_immutable_object(self.client, **self.params)
        self.client.put_object.assert_not_called()

    def test_concurrent_creation_is_rechecked_after_precondition_failure(self):
        self.client.head_object.side_effect = [
            s3_error("404", 404), {"Metadata": {"sha256": self.params["checksum"]}},
        ]
        self.client.put_object.side_effect = s3_error("PreconditionFailed", 412)
        self.assertFalse(bronze.put_immutable_object(self.client, **self.params))
        self.assertEqual(self.client.head_object.call_count, 2)
        self.client.put_object.assert_called_once()
        self.assertEqual(self.client.put_object.call_args.kwargs["IfNoneMatch"], "*")

    def test_concurrent_creation_with_wrong_metadata_fails_without_retrying_put(self):
        self.client.head_object.side_effect = [s3_error("404", 404), {"Metadata": {"sha256": "wrong"}}]
        self.client.put_object.side_effect = s3_error("PreconditionFailed", 412)
        with self.assertRaises(bronze.BronzeIntegrityError):
            bronze.put_immutable_object(self.client, **self.params)
        self.client.put_object.assert_called_once()

    def test_conditional_conflict_is_not_silently_ignored(self):
        self.client.head_object.side_effect = s3_error("404", 404)
        self.client.put_object.side_effect = s3_error("ConditionalRequestConflict", 409)
        with self.assertRaises(ClientError):
            bronze.put_immutable_object(self.client, **self.params)


class IngestionMainTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}, clear=True))
        self.factory = self.enterContext(patch.object(ingestion, "create_s3_client"))
        self.pg_factory = self.enterContext(patch.object(ingestion, "create_postgres_connection"))
        self.register = self.enterContext(patch.object(ingestion, "register_ingestion_object"))
        self.download = self.enterContext(patch.object(ingestion, "download_bytes"))
        self.client = MagicMock(spec=["head_object", "put_object"])
        self.factory.return_value = self.client
        self.connection = self.pg_factory.return_value.__enter__.return_value
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.errors = self.enterContext(redirect_stderr(io.StringIO()))
        self.stored = {}
        self.catalog = {}
        self.data = (b'[ {"competition_id": 43} ]\n', b'[\r\n {"match_id": 1}\r\n]\n')
        self.download.side_effect = self.data
        self.client.head_object.side_effect = self.head
        self.client.put_object.side_effect = self.put
        self.register.side_effect = self.register_row

    def head(self, *, Bucket, Key):
        if Key not in self.stored:
            raise s3_error("404", 404)
        return {"Metadata": self.stored[Key]["Metadata"]}

    def put(self, **kwargs):
        self.assertEqual(kwargs["IfNoneMatch"], "*")
        key = kwargs["Key"]
        if key in self.stored:
            raise s3_error("PreconditionFailed", 412)
        self.stored[key] = kwargs

    def register_row(self, connection, **kwargs):
        self.assertIs(connection, self.connection)
        key = kwargs["object_key"]
        self.assertIn(key, self.stored)
        self.assertEqual(kwargs["sha256"], self.stored[key]["Metadata"]["sha256"])
        self.assertEqual(kwargs["size_bytes"], len(self.stored[key]["Body"]))
        identity = (kwargs["s3_bucket"], key)
        if identity in self.catalog:
            return False
        self.catalog[identity] = kwargs
        return True

    def reset_output(self):
        self.output.seek(0)
        self.output.truncate()

    def test_first_run_and_repeat_have_no_duplicate_objects_or_catalog_rows(self):
        self.assertEqual(ingestion.main(), 0)
        self.assertEqual(self.client.put_object.call_count, 2)
        self.assertEqual(len(self.catalog), 2)
        self.assertIn("Downloaded: 2\nUploaded: 2\nUnchanged: 0\nRegistered: 2\nAlready registered: 0", self.output.getvalue())
        self.assertEqual(self.download.call_args_list, [call(source["source_url"]) for source in ingestion.SOURCES])
        for raw, source in zip(self.data, ingestion.SOURCES):
            key = source_key(source, raw)
            self.assertIs(self.stored[key]["Body"], raw)
            self.assertEqual(self.stored[key]["Metadata"]["dataset"], source["dataset"])
            self.assertIn(f"REGISTERED: {key}", self.output.getvalue())
            self.assertIn(f"Bytes: {len(raw)}", self.output.getvalue())
            self.assertIn(f"SHA256: {sha256_bytes(raw)}", self.output.getvalue())

        self.reset_output()
        self.download.side_effect = self.data
        self.assertEqual(ingestion.main(), 0)
        self.assertEqual(self.client.put_object.call_count, 2)
        self.assertEqual(len(self.catalog), 2)
        self.assertIn("Uploaded: 0\nUnchanged: 2\nRegistered: 0\nAlready registered: 2", self.output.getvalue())

    def test_changed_source_creates_new_version_and_preserves_old_bytes(self):
        self.assertEqual(ingestion.main(), 0)
        original = dict(self.stored)
        changed = b'[ {"competition_id": 44} ]\n'
        self.download.side_effect = (changed, self.data[1])
        self.reset_output()
        self.assertEqual(ingestion.main(), 0)
        self.assertEqual(len(self.stored), 3)
        self.assertEqual(len(self.catalog), 3)
        for key, value in original.items():
            self.assertIs(self.stored[key], value)
        new_key = source_key(ingestion.SOURCES[0], changed)
        self.assertIs(self.stored[new_key]["Body"], changed)
        self.assertIn("Uploaded: 1\nUnchanged: 1\nRegistered: 1\nAlready registered: 1", self.output.getvalue())

    def test_existing_s3_versions_with_no_catalog_are_registered_without_upload(self):
        for source, raw in zip(ingestion.SOURCES, self.data):
            self.stored[source_key(source, raw)] = {"Body": raw, "Metadata": {"sha256": sha256_bytes(raw)}}
        self.assertEqual(ingestion.main(), 0)
        self.client.put_object.assert_not_called()
        self.assertEqual(len(self.catalog), 2)
        self.assertIn("Uploaded: 0\nUnchanged: 2\nRegistered: 2", self.output.getvalue())

    def test_postgres_error_preserves_s3_and_next_run_repairs_catalog(self):
        self.register.side_effect = psycopg.OperationalError("synthetic-password")
        self.assertEqual(ingestion.main(), 1)
        self.assertEqual(len(self.stored), 1)
        self.assertEqual(self.catalog, {})
        self.assertIn("PostgreSQL error", self.errors.getvalue())
        self.assertNotIn("synthetic-password", self.errors.getvalue())
        self.assertNotIn("REGISTERED:", self.output.getvalue())
        old_key, old_object = next(iter(self.stored.items()))

        self.register.side_effect = self.register_row
        self.download.side_effect = self.data
        self.assertEqual(ingestion.main(), 0)
        self.assertIs(self.stored[old_key], old_object)
        self.assertEqual(self.client.put_object.call_count, 2)
        self.assertEqual(len(self.catalog), 2)
        self.assertTrue(all(item[0] in {"head_object", "put_object"} for item in self.client.method_calls))

    def test_integrity_failure_prevents_registration_and_overwrite(self):
        key = source_key(ingestion.SOURCES[0], self.data[0])
        self.stored[key] = {"Body": self.data[0], "Metadata": {"sha256": "wrong"}}
        self.assertEqual(ingestion.main(), 1)
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("integrity violation", self.errors.getvalue())

    def test_legacy_flat_keys_are_not_read_or_modified(self):
        for source in ingestion.SOURCES:
            self.stored[f'{source["base_prefix"]}/{source["filename"]}'] = {"Body": b"legacy", "Metadata": {}}
        legacy = dict(self.stored)
        self.assertEqual(ingestion.main(), 0)
        self.assertEqual(len(self.stored), 4)
        for key, value in legacy.items():
            self.assertIs(self.stored[key], value)
            self.assertNotIn(call(Bucket="test-bucket", Key=key), self.client.head_object.call_args_list)

    def test_missing_bucket_fails_before_any_external_call(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ingestion.main(), 2)
        self.factory.assert_not_called()
        self.pg_factory.assert_not_called()
        self.download.assert_not_called()

    def test_download_failure_stops_before_s3_or_catalog_write(self):
        self.download.side_effect = DownloadError("HTTP 503 while downloading source")
        self.assertEqual(ingestion.main(), 1)
        self.client.head_object.assert_not_called()
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("HTTP 503", self.errors.getvalue())

    def test_access_denied_stops_before_catalog_write_without_logging_credentials(self):
        self.client.head_object.side_effect = s3_error("AccessDenied", 403)
        self.assertEqual(ingestion.main(), 1)
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("HTTP 403, code AccessDenied", self.errors.getvalue())
        self.assertNotIn("synthetic-secret", self.errors.getvalue())
        self.assertNotIn("synthetic-access", self.errors.getvalue())

    def test_upload_error_prevents_registration(self):
        self.client.put_object.side_effect = s3_error("AccessDenied", 403)
        self.assertEqual(ingestion.main(), 1)
        self.register.assert_not_called()
        self.assertEqual(self.catalog, {})

    def test_postgres_connection_failure_is_reported_without_password(self):
        self.pg_factory.side_effect = psycopg.OperationalError("synthetic-password")
        self.assertEqual(ingestion.main(), 1)
        self.download.assert_not_called()
        self.assertIn("PostgreSQL error", self.errors.getvalue())
        self.assertNotIn("synthetic-password", self.errors.getvalue())


if __name__ == "__main__":
    unittest.main()
