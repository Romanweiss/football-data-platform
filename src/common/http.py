"""Small HTTP downloader using the standard library and default TLS trust."""

import json
from http.client import IncompleteRead
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.common.source_transport import SourceAccessError, source_request


class DownloadError(RuntimeError):
    """A source could not be downloaded completely."""


def download_bytes(url: str) -> bytes:
    """Read complete bytes, with at most three transient-only GET attempts."""
    try:
        return source_request("GET", url, _download_once)
    except SourceAccessError as error:
        # No arbitrary exception text, URL userinfo/query or partial payload in logs.
        status = error.diagnostics.get("http_status")
        label = f"HTTP {status}" if status is not None else "Source GET"
        failure = DownloadError(label + " failed: " + json.dumps(error.diagnostics))
        failure.diagnostics = error.diagnostics
        raise failure from error.original_error


def _download_once(url: str) -> bytes:
    """Each attempt owns/closes its response; no bytes escape a failed read."""
    request = Request(
        url,
        headers={"User-Agent": "football-data-platform/0.1 (StatsBomb Bronze ingestion)"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise HTTPError(url, response.status, "Unexpected source status", response.headers, None)
            data = response.read()
            length = response.headers.get("Content-Length")
            if length is not None:
                expected = int(length)
                if len(data) < expected:
                    raise IncompleteRead(data, expected - len(data))
                if len(data) != expected:
                    raise DownloadError("Source response length mismatch.")
            return data
    except HTTPError as error:
        error.close()
        raise
