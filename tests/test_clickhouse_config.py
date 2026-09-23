"""Offline client, URL and configuration contracts; no real credentials or IO."""

import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from src.common.clickhouse import create_clickhouse_client
from src.common.s3_paths import selectel_virtual_url

ROOT = Path(__file__).resolve().parents[1]
ENV = {
    "CLICKHOUSE_HOST": "football-clickhouse", "CLICKHOUSE_HTTP_PORT": "8123",
    "CLICKHOUSE_DB": "football", "CLICKHOUSE_USER": "test-user", "CLICKHOUSE_PASSWORD": "test-secret",
    "S3_ENDPOINT": "https://s3.ru-3.storage.selcloud.ru", "S3_BUCKET": "test-bucket",
}


class ClickHouseConfigTests(unittest.TestCase):
    @patch("src.common.clickhouse.clickhouse_connect.get_client")
    def test_internal_host_port_and_no_retry_or_raw_errors(self, factory):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertIs(create_clickhouse_client(), factory.return_value)
        options = factory.call_args.kwargs
        self.assertEqual(options["host"], "football-clickhouse")
        self.assertEqual(options["port"], 8123)
        self.assertEqual(options["password"], "test-secret")
        self.assertFalse(options["show_clickhouse_errors"])
        self.assertEqual(options["query_retries"], 0)
        self.assertNotIn("verify", options)

    def test_missing_variables_and_invalid_ports_do_not_echo_values(self):
        for name in ("CLICKHOUSE_HOST", "CLICKHOUSE_HTTP_PORT", "CLICKHOUSE_DB", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD"):
            with self.subTest(name=name), patch.dict(os.environ, {**ENV, name: ""}, clear=True):
                with self.assertRaises(ValueError) as caught:
                    create_clickhouse_client()
                self.assertIn(name, str(caught.exception))
                self.assertNotIn("test-secret", str(caught.exception))
        for port in ("0", "65536", "-1", "12.5", "secret-port", "8123\n"):
            with self.subTest(port=port), patch.dict(os.environ, {**ENV, "CLICKHOUSE_HTTP_PORT": port}, clear=True):
                with self.assertRaises(ValueError):
                    create_clickhouse_client()

    def test_host_rejects_url_userinfo(self):
        with patch.dict(os.environ, {**ENV, "CLICKHOUSE_HOST": "https://user:secret@host"}, clear=True):
            with self.assertRaisesRegex(ValueError, "hostname"):
                create_clickhouse_client()

    def test_virtual_url(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(selectel_virtual_url("football/silver/build_id=abc/part-1.parquet"),
                             "https://test-bucket.s3.ru-3.storage.selcloud.ru/football/silver/build_id=abc/part-1.parquet")

    def test_invalid_endpoint_bucket_and_key(self):
        endpoints = ("http://s3.ru-3.storage.selcloud.ru", "https://evil.example", "https://s3.ru-3.storage.selcloud.ru/",
                     "https://user:secret@s3.ru-3.storage.selcloud.ru", "https://s3.ru-3.storage.selcloud.ru?secret",
                     "https://s3.ru-3.storage.selcloud.ru:443", "https://s3.ru-3.storage.selcloud.ru\n")
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {**ENV, "S3_ENDPOINT": endpoint}, clear=True):
                with self.assertRaises(ValueError):
                    selectel_virtual_url("file.parquet")
        for bucket in ("", "a.b", "127.0.0.1", "A-Bucket", "aa", "bad/bucket", "a" * 64):
            with self.subTest(bucket=bucket), patch.dict(os.environ, {**ENV, "S3_BUCKET": bucket}, clear=True):
                with self.assertRaises(ValueError):
                    selectel_virtual_url("file.parquet")
        with patch.dict(os.environ, ENV, clear=True):
            for key in ("/x", "../x", "a//b", "a/../b", "a?secret", "a%2fb", "part-*.parquet", "{a,b}", "a\\b", "a\n"):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    selectel_virtual_url(key)

    def test_named_collection_no_unsupported_region_or_credentials(self):
        root = ET.parse(ROOT / "infrastructure/clickhouse/config.d/10_selectel_s3.xml").getroot()
        collection = root.find("named_collections/selectel_s3")
        self.assertEqual([node.tag for node in collection], ["access_key_id", "secret_access_key"])
        for node, name in zip(collection, ("S3_ACCESS_KEY", "S3_SECRET_KEY"), strict=True):
            self.assertEqual(node.attrib["from_env"], name)
            self.assertEqual(node.attrib["overridable"], "false")
            self.assertIsNone(node.text)


if __name__ == "__main__":
    unittest.main()
