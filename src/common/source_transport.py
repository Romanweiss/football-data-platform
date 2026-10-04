"""Shared bounded transport retries for public source requests; no storage writes."""
import errno
import json
import re
import socket
import ssl
import sys
import time
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit


def transport_reason(error):
    """Unwrap the downloader's cause without exposing arbitrary exception text."""
    while error.__cause__ is not None:
        error = error.__cause__
    return error.reason if isinstance(error, URLError) and not isinstance(error, HTTPError) else error


def transient_failure(error):
    reason = transport_reason(error)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    if isinstance(reason, ssl.SSLEOFError):
        return True
    if isinstance(reason, ssl.SSLError):
        return False
    if isinstance(reason, HTTPError):
        return reason.code in (429, 500, 502, 503, 504)
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return (isinstance(reason, (TimeoutError, ConnectionResetError, ConnectionAbortedError,
                               BrokenPipeError, IncompleteRead, RemoteDisconnected))
            or isinstance(reason, OSError) and reason.errno in
            (errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE))


def safe_failure(method, url, error, attempts):
    reason = transport_reason(error)
    parsed = urlsplit(url)
    # Only public source location is relevant. Never include URL credentials/query
    # or error messages, which can contain proxy credentials/environment values.
    result = {"method": method, "url": urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", "")),
              "hostname": parsed.hostname, "exception": type(error).__name__,
              "reason_type": type(reason).__name__, "attempts": attempts}
    if isinstance(reason, ssl.SSLCertVerificationError):
        result.update(category="CERTIFICATE_VERIFY_FAILED", message="Certificate verification failed")
    elif isinstance(reason, ssl.SSLEOFError):
        result.update(category="TLS_EOF", message="TLS connection closed unexpectedly")
    elif isinstance(reason, ssl.SSLError):
        result.update(category="TLS_ERROR", message="TLS protocol error")
    elif isinstance(reason, HTTPError):
        result.update(category="HTTP_STATUS", http_status=reason.code)
    elif isinstance(reason, socket.gaierror):
        result.update(category="DNS_FAILURE", message="DNS lookup failed")
    elif isinstance(reason, TimeoutError):
        result.update(category="TIMEOUT", message="Network operation timed out")
    elif isinstance(reason, ConnectionResetError):
        result.update(category="CONNECTION_RESET", message="Connection reset")
    else:
        result.update(category="SOURCE_REQUEST_FAILED", message="Source request failed")
    ssl_reason = getattr(reason, "reason", None) if isinstance(reason, ssl.SSLError) else None
    if isinstance(ssl_reason, str) and re.fullmatch(r"[A-Z0-9_]+", ssl_reason):
        result["ssl_reason"] = ssl_reason
    return result


class SourceAccessError(RuntimeError):
    def __init__(self, method, url, error, attempts):
        super().__init__("Public source request failed")
        self.diagnostics = safe_failure(method, url, error, attempts)
        self.original_error = error


def source_request(method, url, operation):
    """Three attempts, 1s/2s backoff, only transient source transport errors."""
    for attempt in range(1, 4):
        try:
            return operation(url)
        except Exception as error:
            if attempt == 3 or not transient_failure(error):
                raise SourceAccessError(method, url, error, attempt) from None
            print("Public source request retry: " + json.dumps(safe_failure(method, url, error, attempt)), file=sys.stderr)
            time.sleep(2 ** (attempt - 1))
