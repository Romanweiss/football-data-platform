"""Offline boto3 configuration checks; the client factory is mocked."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from src.common.s3 import create_s3_client


class S3ClientTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "S3_ENDPOINT": "https://s3.example.invalid",
            "S3_REGION": "test-region",
            "S3_ACCESS_KEY": "synthetic-access-key",
            "S3_SECRET_KEY": "synthetic-secret-key",
            "AWS_CA_BUNDLE": "/etc/ssl/certs/ca-certificates.crt",
        }
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        self.factory = self.enterContext(patch("src.common.s3.boto3.client"))

    def test_standard_retries_and_explicit_timeouts(self):
        create_s3_client()
        config = self.factory.call_args.kwargs["config"]
        self.assertEqual(config.retries, {"mode": "standard", "max_attempts": 5})
        self.assertEqual(config.connect_timeout, 10)
        self.assertEqual(config.read_timeout, 60)
        self.factory.assert_called_once()

    def test_sigv4_virtual_endpoint_region_credentials_and_ca_are_preserved(self):
        self.assertIs(create_s3_client(), self.factory.return_value)
        options = self.factory.call_args.kwargs
        self.assertEqual(self.factory.call_args.args, ("s3",))
        self.assertEqual(options["config"].signature_version, "s3v4")
        self.assertEqual(options["config"].s3, {"addressing_style": "virtual"})
        for argument, variable in (
            ("endpoint_url", "S3_ENDPOINT"), ("region_name", "S3_REGION"),
            ("aws_access_key_id", "S3_ACCESS_KEY"), ("aws_secret_access_key", "S3_SECRET_KEY"),
        ):
            self.assertEqual(options[argument], self.environment[variable])
        # Let botocore resolve AWS_CA_BUNDLE exactly as before; never override verification.
        self.assertNotIn("verify", options)
        self.assertEqual(os.environ["AWS_CA_BUNDLE"], self.environment["AWS_CA_BUNDLE"])

    def test_factory_does_not_log_credentials(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertNoLogs(level="DEBUG"):
            create_s3_client()
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
