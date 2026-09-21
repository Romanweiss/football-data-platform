"""Offline Bronze reading tests with real StreamingBody over in-memory bytes."""

import io
import unittest
from unittest.mock import MagicMock

from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from src.common.bronze import BronzeIntegrityError
from src.common.bronze_reader import read_bronze_object
from src.common.checksum import sha256_bytes


class BronzeReaderTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=["get_object"])
        self.raw = b"\xffnot JSON\r\n"
        self.stream = io.BytesIO(self.raw)
        self.client.get_object.return_value = {
            "Body": StreamingBody(self.stream, len(self.raw)),
        }
        self.params = {"bucket": "catalog-bucket", "key": "catalog/key", "checksum": sha256_bytes(self.raw)}

    def test_returns_raw_bytes_without_json_parsing_and_closes_stream(self):
        self.assertEqual(read_bronze_object(self.client, **self.params), self.raw)
        self.client.get_object.assert_called_once_with(Bucket="catalog-bucket", Key="catalog/key")
        self.assertTrue(self.stream.closed)

    def test_checksum_mismatch_closes_stream_and_raises_integrity_error(self):
        self.params["checksum"] = "a" * 64
        with self.assertRaisesRegex(BronzeIntegrityError, "catalog checksum"):
            read_bronze_object(self.client, **self.params)
        self.assertTrue(self.stream.closed)

    def test_read_failure_still_closes_stream(self):
        body = MagicMock(spec=["read", "close"])
        body.read.side_effect = OSError("offline read failure")
        self.client.get_object.return_value = {"Body": body}
        with self.assertRaises(OSError):
            read_bronze_object(self.client, **self.params)
        body.close.assert_called_once()

    def test_missing_s3_object_error_propagates(self):
        error = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        self.client.get_object.side_effect = error
        with self.assertRaises(ClientError) as caught:
            read_bronze_object(self.client, **self.params)
        self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
