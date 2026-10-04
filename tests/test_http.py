"""HTTP tests replace urlopen; no internet access is used."""

import unittest
import io
from contextlib import redirect_stderr
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from unittest.mock import ANY, MagicMock, patch

from src.common.http import DownloadError, download_bytes


class DownloadBytesTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://example.invalid/source.json"
        self.urlopen = self.enterContext(patch("src.common.http.urlopen"))
        self.response = MagicMock()
        self.response.status = 200
        self.response.headers = {}
        self.sleep = self.enterContext(patch("src.common.source_transport.time.sleep"))
        self.errors = self.enterContext(redirect_stderr(io.StringIO()))
        self.urlopen.return_value.__enter__.return_value = self.response

    def test_preserves_bytes_and_sets_timeout_and_user_agent(self):
        raw = b'[\r\n  {"id": 1, "label": "raw"}\r\n]\n'
        self.response.read.return_value = raw
        self.assertIs(download_bytes(self.url), raw)
        self.urlopen.assert_called_once_with(ANY, timeout=30)
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, self.url)
        self.assertIn("football-data-platform", request.get_header("User-agent"))
        self.urlopen.return_value.__exit__.assert_called_once()

    def test_rejects_unexpected_status_without_reading_body(self):
        for status in (204, 206, 500):
            with self.subTest(status=status):
                self.response.status = status
                with self.assertRaisesRegex(DownloadError, f"HTTP {status}"):
                    download_bytes(self.url)
        self.response.read.assert_not_called()

    def test_reports_http_error(self):
        error = HTTPError(self.url, 404, "Not Found", {}, None)
        self.urlopen.side_effect = error
        with self.assertRaisesRegex(DownloadError, "HTTP 404") as caught:
            download_bytes(self.url)
        self.assertIs(caught.exception.__cause__, error)

    def test_reports_connection_and_timeout_errors(self):
        for error in (URLError("offline"), TimeoutError("timed out")):
            with self.subTest(error=type(error).__name__):
                self.urlopen.side_effect = error
                with self.assertRaises(DownloadError) as caught:
                    download_bytes(self.url)
                self.assertIs(caught.exception.__cause__, error)

    def test_rejects_incomplete_response(self):
        self.response.read.side_effect = IncompleteRead(b"partial", 100)
        with self.assertRaisesRegex(DownloadError, "IncompleteRead"):
            download_bytes(self.url)
        self.assertEqual(self.urlopen.call_count, 3)
        self.assertEqual(self.urlopen.return_value.__exit__.call_count, 3)


if __name__ == "__main__":
    unittest.main()
