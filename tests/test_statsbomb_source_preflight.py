"""Focused preflight transport tests; no external calls or real sleeps."""
import io
import json
import socket
import ssl
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from scripts import check_statsbomb_source as script
from src.common.http import DownloadError
from src.statsbomb.context import SourceContextError

URL = script.CATALOG_URL
CONTEXT = {"competition_id": 9, "season_id": 281}


class SourceTransportTests(unittest.TestCase):
    def setUp(self):
        self.sleep = self.enterContext(patch.object(script.time, "sleep"))
        self.stderr = self.enterContext(redirect_stderr(io.StringIO()))

    def test_retries_transient_failures_then_preserves_result(self):
        for reason in (ssl.SSLEOFError("synthetic-secret"), TimeoutError(), ConnectionResetError(),
                       ConnectionAbortedError(), BrokenPipeError(), IncompleteRead(b"", 1),
                       RemoteDisconnected(), socket.gaierror(socket.EAI_AGAIN, "synthetic-secret")):
            with self.subTest(reason=type(reason).__name__):
                self.sleep.reset_mock()
                operation = MagicMock(side_effect=[URLError(reason), b"original bytes"])
                self.assertEqual(script.source_request("GET", URL, operation), b"original bytes")
                self.assertEqual(operation.call_count, 2)
                self.sleep.assert_called_once_with(1)
        self.assertNotIn("synthetic-secret", self.stderr.getvalue())

    def test_retries_wrapped_downloader_cause_and_stops_at_three(self):
        error = DownloadError("synthetic-secret")
        error.__cause__ = URLError(ssl.SSLEOFError("synthetic-secret"))
        operation = MagicMock(side_effect=error)
        with self.assertRaises(script.SourceAccessError) as caught:
            script.source_request("GET", URL, operation)
        self.assertEqual(operation.call_count, 3)
        self.assertEqual([call.args for call in self.sleep.call_args_list], [(1,), (2,)])
        self.assertEqual(caught.exception.diagnostics["reason_type"], "SSLEOFError")
        self.assertEqual(caught.exception.diagnostics["attempts"], 3)
        self.assertNotIn("synthetic-secret", self.stderr.getvalue())

    def test_certificate_permanent_dns_and_other_tls_errors_never_retry(self):
        for reason in (ssl.SSLCertVerificationError("synthetic-secret"), ssl.SSLError("synthetic-secret"),
                       socket.gaierror(socket.EAI_NONAME, "synthetic-secret"), "synthetic-secret"):
            with self.subTest(reason=type(reason).__name__):
                operation = MagicMock(side_effect=URLError(reason))
                with self.assertRaises(script.SourceAccessError):
                    script.source_request("HEAD", URL, operation)
                operation.assert_called_once_with(URL)
        self.sleep.assert_not_called()
        self.assertNotIn("synthetic-secret", self.stderr.getvalue())

    def test_http_404_and_invalid_content_never_retry(self):
        for error in (HTTPError(URL, 404, "synthetic-secret", {}, None),
                      ValueError("synthetic-secret"), SourceContextError("synthetic-secret")):
            operation = MagicMock(side_effect=error)
            with self.assertRaises(script.SourceAccessError):
                script.source_request("GET", URL, operation)
            operation.assert_called_once_with(URL)
        self.sleep.assert_not_called()

    def test_http_transient_status_classification(self):
        for status in (429, 500, 502, 503, 504):
            self.assertTrue(script.transient_failure(HTTPError(URL, status, "", {}, None)))
        for status in (400, 401, 403, 404):
            self.assertFalse(script.transient_failure(HTTPError(URL, status, "", {}, None)))

    def test_head_uses_original_url_timeout_and_default_tls(self):
        response = MagicMock()
        response.status = 200
        with patch.object(script, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            self.assertEqual(script.head(URL), URL)
        self.assertEqual(open_url.call_args.args[0].get_method(), "HEAD")
        self.assertEqual(open_url.call_args.args[0].full_url, URL)
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 30})
        open_url.return_value.__exit__.assert_called_once()

    def test_failure_reports_public_location_and_safe_reason_only(self):
        url = "https://user:synthetic-secret@raw.githubusercontent.com/hudl/open-data/master/data/competitions.json?token=synthetic-secret"
        error = script.SourceAccessError("HEAD", url, URLError(ssl.SSLEOFError("synthetic-secret")), 3)
        with patch.object(script, "inspect_source", side_effect=error):
            self.assertEqual(script.main(["--competition-id", "9", "--season-id", "281"]), 1)
        output = self.stderr.getvalue()
        for expected in ("HEAD", URL, "raw.githubusercontent.com", "SSLEOFError", "TLS_EOF"):
            self.assertIn(expected, output)
        self.assertNotIn("synthetic-secret", output)


class StrictSourceContractTests(unittest.TestCase):
    def test_real_inventory_and_all_children_are_still_checked(self):
        catalog = json.dumps([dict(CONTEXT, competition_name="Test", season_name="Test")]).encode()
        parent = json.dumps([dict(match_id=1, competition={"competition_id": 9}, season={"season_id": 281},
                                 home_team={"home_team_id": 10}, away_team={"away_team_id": 20})]).encode()
        with patch.object(script, "download_bytes", side_effect=[catalog, parent]), \
             patch.object(script, "head", side_effect=lambda url: url) as head:
            result = script.inspect_source(CONTEXT)
        self.assertEqual((result["match_count"], result["events_available"], result["lineups_available"]), (1, 1, 1))
        self.assertEqual({call.args[0] for call in head.call_args_list},
                         {script.SOURCE_BASE_URL + "/events/1.json", script.SOURCE_BASE_URL + "/lineups/1.json"})

    def test_wrong_catalog_identity_stops_without_retry_or_child_checks(self):
        with patch.object(script, "download_bytes", return_value=b"[]") as download, \
             patch.object(script, "head") as head, patch.object(script.time, "sleep") as sleep:
            with self.assertRaises(SourceContextError): script.inspect_source(CONTEXT)
        download.assert_called_once_with(URL)
        head.assert_not_called()
        sleep.assert_not_called()

    def test_invalid_matches_content_is_not_retried(self):
        catalog = json.dumps([CONTEXT]).encode()
        with patch.object(script, "download_bytes", side_effect=[catalog, b"not JSON"]) as download, \
             patch.object(script, "head") as head, patch.object(script.time, "sleep") as sleep:
            with self.assertRaises(ValueError): script.inspect_source(CONTEXT)
        self.assertEqual(download.call_count, 2)
        head.assert_not_called()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
