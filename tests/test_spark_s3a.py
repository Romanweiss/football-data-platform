"""Offline S3A config and safe object path tests; no JVM required."""

import os
import unittest
from unittest.mock import MagicMock, patch

from src.common.s3_paths import s3a_uri
from src.common.spark_s3a import CREDENTIAL_PROVIDER, configure_s3a


class S3AConfigTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "S3_ENDPOINT": "https://s3.ru-3.storage.selcloud.ru", "S3_REGION": "ru-3",
            "AWS_ACCESS_KEY_ID": "synthetic-access-key", "AWS_SECRET_ACCESS_KEY": "synthetic-secret-key",
        }
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        self.spark = MagicMock()

    def test_endpoint_region_virtual_tls_provider_and_no_credentials(self):
        configure_s3a(self.spark)
        calls = self.spark.sparkContext._jsc.hadoopConfiguration.return_value.set.call_args_list
        options = {call.args[0]: call.args[1] for call in calls}
        self.assertEqual(options["fs.s3a.endpoint"], self.environment["S3_ENDPOINT"])
        self.assertEqual(options["fs.s3a.endpoint.region"], "ru-3")
        self.assertEqual(options["fs.s3a.path.style.access"], "false")
        self.assertEqual(options["fs.s3a.connection.ssl.enabled"], "true")
        self.assertEqual(options["fs.s3a.aws.credentials.provider"], CREDENTIAL_PROVIDER)
        self.assertEqual(options["fs.s3a.impl"], "org.apache.hadoop.fs.s3a.S3AFileSystem")
        serialized = repr(options) + repr(self.spark.conf.set.call_args_list)
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            self.assertNotIn(self.environment[name], serialized)
        self.assertNotIn("fs.s3a.access.key", options)
        self.assertNotIn("fs.s3a.secret.key", options)

    def test_directory_committer_fail_and_no_global_purge(self):
        configure_s3a(self.spark)
        options = dict(call.args for call in self.spark.sparkContext._jsc.hadoopConfiguration.return_value.set.call_args_list)
        self.assertEqual(options["fs.s3a.committer.name"], "directory")
        self.assertEqual(options["fs.s3a.committer.staging.conflict-mode"], "fail")
        self.assertEqual(options["fs.s3a.committer.staging.unique-filenames"], "true")
        self.assertEqual(options["fs.s3a.committer.abort.pending.uploads"], "true")
        self.assertEqual(options["fs.s3a.multipart.purge"], "false")
        self.assertEqual(options["mapreduce.outputcommitter.factory.scheme.s3a"], "org.apache.hadoop.fs.s3a.commit.S3ACommitterFactory")
        spark_options = dict(call.args for call in self.spark.conf.set.call_args_list)
        self.assertEqual(spark_options, {
            "spark.sql.sources.commitProtocolClass": "org.apache.spark.internal.io.cloud.PathOutputCommitProtocol",
            "spark.sql.parquet.output.committer.class": "org.apache.spark.internal.io.cloud.BindingParquetOutputCommitter",
        })

    def test_each_required_variable_validated_before_config(self):
        for name in self.environment:
            with self.subTest(name=name), patch.dict(os.environ, {name: " "}):
                with self.assertRaisesRegex(ValueError, name):
                    configure_s3a(self.spark)
        self.spark.conf.set.assert_not_called()

    def test_bad_endpoint_is_rejected_without_echoing_secret(self):
        for endpoint in (
            "http://s3.example.org", "https://user:secret@example.org", "https://example.org/bucket",
            "https://example.org?token=secret", "https://example.org#secret", " https://example.org",
        ):
            with patch.dict(os.environ, {"S3_ENDPOINT": endpoint}), self.assertRaises(ValueError) as caught:
                configure_s3a(self.spark)
            self.assertNotIn("secret", str(caught.exception))


class S3PathsTests(unittest.TestCase):
    def test_valid_key_and_prefix(self):
        self.assertEqual(s3a_uri("test-bucket", "football/key.json"), "s3a://test-bucket/football/key.json")
        self.assertEqual(s3a_uri("test-bucket", "football/build_id=abc/"), "s3a://test-bucket/football/build_id=abc/")

    def test_invalid_buckets(self):
        for bucket in ("", None, "ab", "Test-Bucket", "../bucket", "user:secret@bucket", "s3a://bucket", "127.0.0.1", "bad..bucket"):
            with self.subTest(bucket=bucket), self.assertRaises(ValueError):
                s3a_uri(bucket, "key")

    def test_invalid_keys_and_traversal(self):
        for key in ("", None, "/absolute", "C:/file", "../key", "a/../b", "a/./b", "a//b", "a//", "a\\b", "a/%2e%2e/b", "a?secret=x", "a#fragment", "a b", "a@b"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                s3a_uri("test-bucket", key)


if __name__ == "__main__":
    unittest.main()
