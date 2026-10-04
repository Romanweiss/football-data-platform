"""Production source GET retry and framing tests; all I/O is synthetic."""
import io
import json
import ssl
import unittest
from contextlib import redirect_stderr
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch
from src.common.http import DownloadError, download_bytes


class ProductionRetryTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://example.invalid/source.json'
        self.remote = self.enterContext(patch('src.common.http.urlopen'))
        self.sleep = self.enterContext(patch('src.common.source_transport.time.sleep'))
        self.errors = self.enterContext(redirect_stderr(io.StringIO()))
        self.response = MagicMock()
        self.response.status, self.response.headers = 200, {}
        self.response.read.return_value = b'[]'
        self.remote.return_value.__enter__.return_value = self.response

    def test_first_get_success_is_one_attempt(self):
        self.assertEqual(download_bytes(self.url), b'[]')
        self.assertEqual(self.remote.call_count, 1)
        self.sleep.assert_not_called()

    def test_one_and_two_transient_failures_then_success(self):
        for failures in (1, 2):
            with self.subTest(failures=failures):
                self.remote.reset_mock()
                self.sleep.reset_mock()
                context = MagicMock()
                context.__enter__.return_value = self.response
                self.remote.side_effect = [URLError(ssl.SSLEOFError('synthetic-secret'))] * failures + [context]
                self.assertEqual(download_bytes(self.url), b'[]')
                self.assertEqual(self.remote.call_count, failures + 1)
                self.assertEqual([c.args for c in self.sleep.call_args_list], [(1,), (2,)][:failures])
        self.assertNotIn('synthetic-secret', self.errors.getvalue())

    def test_exhausted_timeout_is_exactly_three_attempts(self):
        self.remote.side_effect = URLError(TimeoutError('synthetic-secret'))
        with self.assertRaises(DownloadError) as caught:
            download_bytes(self.url)
        self.assertEqual(self.remote.call_count, 3)
        self.assertEqual([c.args for c in self.sleep.call_args_list], [(1,), (2,)])
        self.assertNotIn('synthetic-secret', str(caught.exception) + self.errors.getvalue())

    def test_certificate_hostname_and_permanent_http_errors_do_not_retry(self):
        for error in (URLError(ssl.SSLCertVerificationError('hostname synthetic-secret')),
                      HTTPError(self.url, 404, 'synthetic-secret', {}, None),
                      HTTPError(self.url, 403, 'synthetic-secret', {}, None)):
            with self.subTest(error=type(error).__name__):
                self.remote.reset_mock()
                self.remote.side_effect = error
                with self.assertRaises(DownloadError): download_bytes(self.url)
                self.assertEqual(self.remote.call_count, 1)
        self.sleep.assert_not_called()

    def test_content_validation_error_is_not_retried(self):
        self.response.read.side_effect = ValueError('synthetic-content-secret')
        with self.assertRaises(DownloadError): download_bytes(self.url)
        self.assertEqual(self.remote.call_count, 1)
        self.sleep.assert_not_called()

    def test_short_content_length_is_discarded_before_retry_success(self):
        self.response.headers = {'Content-Length': '2'}
        self.response.read.side_effect = [b'[', b'[]']
        self.assertEqual(download_bytes(self.url), b'[]')
        self.assertEqual(self.remote.call_count, 2)
        self.assertEqual(self.remote.return_value.__exit__.call_count, 2)
        self.sleep.assert_called_once_with(1)

    def test_malformed_complete_content_is_not_a_get_retry(self):
        self.response.read.return_value = b'not-json'
        with self.assertRaises(json.JSONDecodeError): json.loads(download_bytes(self.url))
        self.assertEqual(self.remote.call_count, 1)
        self.sleep.assert_not_called()

    def test_no_tls_override_or_sensitive_url_in_failure(self):
        self.remote.side_effect = URLError(ssl.SSLEOFError('synthetic-secret'))
        with self.assertRaises(DownloadError) as caught:
            download_bytes('https://user:synthetic-secret@example.invalid/source.json?token=synthetic-secret')
        self.assertEqual(self.remote.call_args.kwargs, {'timeout': 30})
        self.assertNotIn('synthetic-secret', str(caught.exception) + self.errors.getvalue())

    def test_preflight_get_does_not_nest_three_attempt_policies(self):
        from scripts.check_statsbomb_source import get_bytes
        self.remote.side_effect = URLError(TimeoutError())
        with self.assertRaises(DownloadError): get_bytes(self.url)
        self.assertEqual(self.remote.call_count, 3)
        self.assertEqual([c.args for c in self.sleep.call_args_list], [(1,), (2,)])


if __name__ == '__main__':
    unittest.main()
