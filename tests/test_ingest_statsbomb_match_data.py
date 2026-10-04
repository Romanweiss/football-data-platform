"""Offline fan-out tests: catalog, S3 and HTTP are replaced with mocks."""

from context_fixtures import CONTEXT_ARGS, BRONZE_ARGS

import io
import json
import os
import ssl
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, call, patch

import psycopg
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from scripts import ingest_statsbomb_match_data as ingestion
from src.common.bronze import build_versioned_key
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError
from src.common.http import download_bytes as production_download
from http.client import IncompleteRead
from urllib.error import URLError
from src.common.postgres import IngestionObjectNotFoundError


def s3_error(code, status):
    return ClientError({
        "Error": {"Code": code, "Message": "synthetic-access synthetic-secret"},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }, "S3Operation")


class MatchFanOutTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"S3_BUCKET": "child-bucket"}, clear=True))
        self.pg_factory = self.enterContext(patch.object(ingestion, "create_postgres_connection"))
        self.find = self.enterContext(patch.object(ingestion, "find_matches_parent"))
        self.s3_factory = self.enterContext(patch.object(ingestion, "create_s3_client"))
        self.download = self.enterContext(patch.object(ingestion, "download_bytes"))
        self.register = self.enterContext(patch.object(ingestion, "register_ingestion_object"))
        self.children = self.enterContext(patch.object(ingestion, "find_latest_ingestion_objects", return_value=[]))
        self.connection = self.pg_factory.return_value.__enter__.return_value
        self.pg_factory.return_value.__exit__.return_value = False
        self.client = MagicMock(spec=["get_object", "head_object", "put_object"])
        self.s3_factory.return_value = self.client
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.errors = self.enterContext(redirect_stderr(io.StringIO()))
        self.stored = {}
        self.catalog = {}
        self.streams = []
        self.trace = []
        self.set_parent(b'[{"match_id": 90, "competition": {"competition_id": 43}, "season": {"season_id": 106}}, {"match_id": 12, "competition": {"competition_id": 43}, "season": {"season_id": 106}}, {"match_id": 90, "competition": {"competition_id": 43}, "season": {"season_id": 106}}, {"match_id": 7, "competition": {"competition_id": 43}, "season": {"season_id": 106}}]')
        self.payloads = {}
        for match_id in (90, 12, 7):
            for kind in ("events", "lineups"):
                # Deliberately retain whitespace; child JSON must not be reserialized.
                self.payloads[self.url(kind, match_id)] = (
                    '[\r\n  {"sample": "%s-%s"}\r\n]\n' % (kind, match_id)
                ).encode("utf-8")
        self.client.get_object.side_effect = self.get_parent
        self.client.head_object.side_effect = self.head
        self.client.put_object.side_effect = self.put
        self.download.side_effect = self.fetch
        self.register.side_effect = self.register_row

    @staticmethod
    def url(kind, match_id):
        return f"https://raw.githubusercontent.com/hudl/open-data/master/data/{kind}/{match_id}.json"

    def set_parent(self, raw):
        self.parent_raw = raw
        self.parent = {
            "s3_bucket": "catalog-bucket",
            "object_key": build_versioned_key("catalog/selected-parent", "matches.json", sha256_bytes(raw)),
            "sha256": sha256_bytes(raw), "size_bytes": len(raw), "first_seen_at": "2026-09-22",
        }
        self.find.return_value = self.parent

    def get_parent(self, *, Bucket, Key):
        if (Bucket, Key) in self.stored:
            raw = self.stored[(Bucket, Key)]["Body"]
            stream = io.BytesIO(raw)
            self.streams.append(stream)
            return {"Body": StreamingBody(stream, len(raw))}
        self.find.assert_called_with(
            self.connection, competition_id=43, season_id=106, sha256="a" * 64
        )
        self.assertEqual((Bucket, Key), (self.parent["s3_bucket"], self.parent["object_key"]))
        stream = io.BytesIO(self.parent_raw)
        self.streams.append(stream)
        self.trace.append(("parent_read", Key))
        return {"Body": StreamingBody(stream, len(self.parent_raw))}

    def fetch(self, url):
        self.assertTrue(self.streams[-1].closed)
        self.trace.append(("download", url))
        return self.payloads[url]

    def head(self, *, Bucket, Key):
        self.trace.append(("head", Key))
        if (Bucket, Key) not in self.stored:
            raise s3_error("404", 404)
        return {"Metadata": self.stored[(Bucket, Key)]["Metadata"]}

    def put(self, **kwargs):
        self.assertEqual(kwargs["IfNoneMatch"], "*")
        identity = (kwargs["Bucket"], kwargs["Key"])
        if identity in self.stored:
            raise s3_error("PreconditionFailed", 412)
        self.stored[identity] = kwargs
        self.trace.append(("put", kwargs["Key"]))

    def register_row(self, connection, **kwargs):
        self.assertIs(connection, self.connection)
        identity = (kwargs["s3_bucket"], kwargs["object_key"])
        self.assertIn(identity, self.stored)
        obj = self.stored[identity]
        self.assertEqual(kwargs["sha256"], obj["Metadata"]["sha256"])
        self.assertEqual(kwargs["size_bytes"], len(obj["Body"]))
        self.assertEqual(kwargs["dataset"], obj["Metadata"]["dataset"])
        self.assertEqual(kwargs["source_url"], obj["Metadata"]["source_url"])
        self.assertEqual(kwargs["source"], "statsbomb")
        self.trace.append(("register", kwargs["object_key"]))
        if identity in self.catalog:
            return False
        self.catalog[identity] = kwargs
        return True

    def reset_output(self):
        self.output.seek(0)
        self.output.truncate()

    def test_limit_two_uses_catalog_parent_and_exact_sequential_child_urls(self):
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        urls = [self.url(kind, match_id) for match_id in (90, 12) for kind in ("events", "lineups")]
        self.assertEqual(self.download.call_args_list, [call(url) for url in urls])
        self.client.get_object.assert_called_once_with(
            Bucket="catalog-bucket", Key=self.parent["object_key"]
        )
        self.find.assert_called_once_with(
            self.connection, competition_id=43, season_id=106, sha256="a" * 64
        )
        self.assertEqual(len(self.stored), 4)
        self.assertEqual(len(self.catalog), 4)
        expected_trace = [("parent_read", self.parent["object_key"])]
        for match_id in (90, 12):
            for kind, dataset in (("events", "match_events"), ("lineups", "match_lineups")):
                url = self.url(kind, match_id)
                raw = self.payloads[url]
                checksum = sha256_bytes(raw)
                key = f"football/bronze/statsbomb/{kind}/competition_id=43/season_id=106/match_id={match_id}/sha256={checksum}/{kind}.json"
                obj = self.stored[("child-bucket", key)]
                self.assertIs(obj["Body"], raw)
                self.assertEqual(obj["ContentType"], "application/json")
                self.assertEqual(obj["Metadata"], {
                    "source": "statsbomb", "layer": "bronze", "dataset": dataset,
                    "match_id": str(match_id), "sha256": checksum, "source_url": url,
                    "competition_id": "43", "season_id": "106",
                })
                expected_trace.extend([("download", url), ("head", key), ("put", key), ("register", key)])
                self.assertIn(f"{kind.upper()} UPLOADED: match_id={match_id}", self.output.getvalue())
                self.assertNotIn(raw.decode("utf-8"), self.output.getvalue())
        self.assertEqual(self.trace, expected_trace)
        self.assertIn("Discovered matches: 3", self.output.getvalue())
        self.assertIn("Objects downloaded: 4\nObjects uploaded: 4\nObjects unchanged: 0", self.output.getvalue())
        self.assertIn("Objects registered: 4\nObjects already registered: 0", self.output.getvalue())

    def test_without_limit_processes_all_unique_matches(self):
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 0)
        self.assertEqual(self.download.call_count, 6)
        self.assertEqual(len(self.catalog), 6)

    def test_limit_larger_than_match_list_processes_all_matches(self):
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "99"]), 0)
        self.assertEqual(self.download.call_count, 6)

    def test_invalid_limits_fail_before_any_io(self):
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value=value), self.assertRaises(SystemExit) as caught:
                ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", value])
            self.assertEqual(caught.exception.code, 2)
        self.pg_factory.assert_not_called()
        self.s3_factory.assert_not_called()
        self.download.assert_not_called()

    def test_repeat_is_unchanged_and_already_registered(self):
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        original_objects = dict(self.stored)
        original_rows = dict(self.catalog)
        self.reset_output()
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        self.assertEqual(self.client.put_object.call_count, 4)
        self.assertEqual(len(self.catalog), 4)
        for identity in original_objects:
            self.assertIs(self.stored[identity], original_objects[identity])
            self.assertIs(self.catalog[identity], original_rows[identity])
        self.assertIn("EVENTS UNCHANGED: match_id=90", self.output.getvalue())
        self.assertIn("LINEUPS UNCHANGED: match_id=90", self.output.getvalue())
        self.assertIn("Objects uploaded: 0\nObjects unchanged: 4", self.output.getvalue())
        self.assertIn("Objects registered: 0\nObjects already registered: 4", self.output.getvalue())

    def test_existing_children_without_catalog_are_registered_without_put(self):
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        self.catalog.clear()
        self.client.put_object.reset_mock()
        self.reset_output()
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        self.client.put_object.assert_not_called()
        self.assertEqual(len(self.catalog), 4)
        self.assertIn("Objects registered: 4", self.output.getvalue())

    def test_missing_parent_in_catalog_stops_before_s3_and_http(self):
        self.find.side_effect = IngestionObjectNotFoundError("Ingest the parent dataset first.")
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 1)
        self.s3_factory.assert_not_called()
        self.download.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("Ingest the parent dataset first", self.errors.getvalue())

    def test_missing_parent_in_s3_stops_before_child_work(self):
        self.client.get_object.side_effect = s3_error("NoSuchKey", 404)
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 1)
        self.download.assert_not_called()
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("HTTP 404", self.errors.getvalue())

    def test_parent_checksum_mismatch_closes_body_and_stops_before_children(self):
        self.parent_raw = b"[]"
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 1)
        self.assertTrue(self.streams[-1].closed)
        self.download.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("catalog checksum", self.errors.getvalue())

    def test_invalid_parent_json_stops_before_children(self):
        self.set_parent(b"private-invalid-source")
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 1)
        self.download.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("Invalid matches JSON", self.errors.getvalue())
        self.assertNotIn("private-invalid-source", self.errors.getvalue())

    def test_download_failure_stops_and_retry_preserves_completed_children(self):
        failed_url = self.url("lineups", 90)

        def fail_lineups(url):
            if url == failed_url:
                raise DownloadError("HTTP 503 while downloading lineups")
            return self.fetch(url)

        self.download.side_effect = fail_lineups
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 1)
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(len(self.stored), 1)
        self.assertEqual(len(self.catalog), 1)
        identity, obj = next(iter(self.stored.items()))
        row = self.catalog[identity]
        self.assertNotIn("ingestion complete", self.output.getvalue())
        self.download.side_effect = self.fetch
        self.reset_output()
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        self.assertIs(self.stored[identity], obj)
        self.assertIs(self.catalog[identity], row)
        self.assertIn("Objects uploaded: 3\nObjects unchanged: 1", self.output.getvalue())
        self.assertIn("Objects registered: 3\nObjects already registered: 1", self.output.getvalue())

    def test_failed_s3_upload_is_not_registered_and_later_matches_are_not_downloaded(self):
        def fail_lineups(**kwargs):
            if kwargs["Metadata"]["dataset"] == "match_lineups":
                raise s3_error("AccessDenied", 403)
            return self.put(**kwargs)

        self.client.put_object.side_effect = fail_lineups
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 1)
        self.assertEqual(self.download.call_count, 2)
        self.register.assert_called_once()
        self.assertEqual(len(self.catalog), 1)
        self.assertIn("HTTP 403", self.errors.getvalue())
        self.assertNotIn("synthetic-secret", self.errors.getvalue())
        self.assertNotIn("synthetic-access", self.errors.getvalue())

    def test_registration_failure_leaves_orphan_and_retry_repairs_without_reupload(self):
        def fail_lineups(connection, **kwargs):
            if kwargs["dataset"] == "match_lineups":
                raise psycopg.OperationalError("synthetic-password")
            return self.register_row(connection, **kwargs)

        self.register.side_effect = fail_lineups
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 1)
        self.assertEqual(len(self.stored), 2)
        self.assertEqual(len(self.catalog), 1)
        self.assertEqual(self.download.call_count, 2)
        self.assertNotIn("synthetic-password", self.errors.getvalue())
        originals = dict(self.stored)
        self.register.side_effect = self.register_row
        self.reset_output()
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "2"]), 0)
        self.assertEqual(self.client.put_object.call_count, 4)
        self.assertEqual(len(self.catalog), 4)
        for identity, obj in originals.items():
            self.assertIs(self.stored[identity], obj)
        self.assertIn("Objects uploaded: 2\nObjects unchanged: 2", self.output.getvalue())
        self.assertIn("Objects registered: 3\nObjects already registered: 1", self.output.getvalue())
        self.assertTrue(all(item[0] in {"get_object", "head_object", "put_object"} for item in self.client.method_calls))

    def test_invalid_existing_child_metadata_is_not_overwritten_or_registered(self):
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "1"]), 0)
        self.catalog.clear()
        obj = next(iter(self.stored.values()))
        obj["Metadata"]["sha256"] = "a" * 64
        self.client.put_object.reset_mock()
        self.register.reset_mock()
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "1"]), 1)
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertEqual(obj["Metadata"]["sha256"], "a" * 64)

    def test_empty_parent_list_rejected_without_child_requests(self):
        self.set_parent(b"[]")
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 1)
        self.download.assert_not_called()
        self.register.assert_not_called()
        self.assertIn("empty", self.errors.getvalue())

    def test_invalid_match_after_limit_still_invalidates_parent_before_writes(self):
        self.set_parent(json.dumps([{"match_id": 1, "competition": {"competition_id": 43}, "season": {"season_id": 106}}, {"match_id": True}]).encode("utf-8"))
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + ["--limit", "1"]), 1)
        self.download.assert_not_called()
        self.register.assert_not_called()

    def test_missing_target_bucket_fails_before_io(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ingestion.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64] + []), 2)
        self.pg_factory.assert_not_called()
        self.s3_factory.assert_not_called()


    def enable_catalog_reuse(self):
        self.children.side_effect = lambda connection, **args: [dict(row) for row in self.catalog.values() if row['dataset'] == args['dataset']]

    def test_cataloged_children_reused_without_remote_get_or_registration(self):
        args = CONTEXT_ARGS + ["--parent-sha256", "a" * 64, "--limit", "1"]
        self.assertEqual(ingestion.main(args), 0)
        self.enable_catalog_reuse()
        self.download.reset_mock()
        self.register.reset_mock()
        self.client.put_object.reset_mock()
        self.assertEqual(ingestion.main(args), 0)
        self.download.assert_not_called()
        self.register.assert_not_called()
        self.client.put_object.assert_not_called()
        self.assertTrue(all(stream.closed for stream in self.streams))

    def test_reused_child_content_corruption_fails_without_remote_get_or_put(self):
        args = CONTEXT_ARGS + ["--parent-sha256", "a" * 64, "--limit", "1"]
        self.assertEqual(ingestion.main(args), 0)
        self.enable_catalog_reuse()
        next(iter(self.stored.values()))['Body'] = b'[]'
        self.download.reset_mock()
        self.register.reset_mock()
        self.client.put_object.reset_mock()
        self.assertEqual(ingestion.main(args), 1)
        self.download.assert_not_called()
        self.register.assert_not_called()
        self.client.put_object.assert_not_called()

    def test_partial_catalog_fetches_only_missing_children(self):
        args = CONTEXT_ARGS + ["--parent-sha256", "a" * 64]
        self.assertEqual(ingestion.main(args + ['--limit', '1']), 0)
        self.enable_catalog_reuse()
        self.download.reset_mock()
        self.register.reset_mock()
        self.client.put_object.reset_mock()
        self.assertEqual(ingestion.main(args), 0)
        expected = [call(self.url(kind, mid)) for mid in (12, 7) for kind in ('events', 'lineups')]
        self.assertEqual(self.download.call_args_list, expected)
        self.assertEqual(self.register.call_count, 4)
        self.assertEqual(self.client.put_object.call_count, 4)
        self.assertEqual(len(self.catalog), 6)

    def test_foreign_context_catalog_artifacts_are_not_reused(self):
        self.children.return_value = [{'object_key': 'football/bronze/statsbomb/events/competition_id=9/season_id=281/match_id=90'}]
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ['--parent-sha256', 'a' * 64, '--limit', '1']), 0)
        self.assertEqual(self.download.call_count, 2)

    def test_catalog_source_key_mismatch_fails_before_remote_get_or_writes(self):
        args = CONTEXT_ARGS + ['--parent-sha256', 'a' * 64, '--limit', '1']
        self.assertEqual(ingestion.main(args), 0)
        self.enable_catalog_reuse()
        next(iter(self.catalog.values()))['object_key'] += '-invalid'
        self.download.reset_mock()
        self.register.reset_mock()
        self.client.put_object.reset_mock()
        self.assertEqual(ingestion.main(args), 1)
        self.download.assert_not_called()
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()

    def test_remote_retry_has_one_publication_registration_path_per_child(self):
        response = MagicMock()
        response.status, response.headers = 200, {}
        response.read.return_value = b'[]'
        context = MagicMock()
        context.__enter__.return_value = response
        self.download.side_effect = production_download
        with patch('src.common.http.urlopen', side_effect=[URLError(ssl.SSLEOFError()), context, context]) as remote, \
             patch('src.common.source_transport.time.sleep'):
            self.assertEqual(ingestion.main(CONTEXT_ARGS + ['--parent-sha256', 'a' * 64, '--limit', '1']), 0)
        self.assertEqual(remote.call_count, 3)
        self.assertEqual(self.client.put_object.call_count, 2)
        self.assertEqual(self.register.call_count, 2)

    def test_exhausted_partial_reads_never_reach_publication_or_registration(self):
        response = MagicMock()
        response.status, response.headers = 200, {}
        response.read.side_effect = IncompleteRead(b'partial-secret', 20)
        self.download.side_effect = production_download
        with patch('src.common.http.urlopen') as remote, patch('src.common.source_transport.time.sleep'):
            remote.return_value.__enter__.return_value = response
            self.assertEqual(ingestion.main(CONTEXT_ARGS + ['--parent-sha256', 'a' * 64]), 1)
        self.assertEqual(remote.call_count, 3)
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertNotIn('partial-secret', self.errors.getvalue())

    def test_invalid_child_content_is_not_published_or_retried(self):
        self.download.side_effect = None
        self.download.return_value = b'private-invalid-json'
        self.assertEqual(ingestion.main(CONTEXT_ARGS + ['--parent-sha256', 'a' * 64]), 1)
        self.download.assert_called_once()
        self.client.put_object.assert_not_called()
        self.register.assert_not_called()
        self.assertNotIn('private-invalid-json', self.errors.getvalue())


if __name__ == "__main__":
    unittest.main()
