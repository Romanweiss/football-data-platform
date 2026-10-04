"""Public-source preflight only: no S3, database clients or registration."""
import argparse
import errno
import json
import re
import socket
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.checksum import sha256_bytes
from src.common.http import download_bytes
from src.statsbomb.context import (add_context_arguments, context_from_args, CATALOG_URL, SOURCE_BASE_URL,
                                   catalog_context, matches_context, matches_url)


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


def source_request(method, url, operation):
    """Preflight-only retries: three attempts, 1s/2s backoff, default TLS trust."""
    for attempt in range(1, 4):
        try:
            return operation(url)
        except Exception as error:
            if attempt == 3 or not transient_failure(error):
                raise SourceAccessError(method, url, error, attempt) from None
            print("Public source request retry: " + json.dumps(safe_failure(method, url, error, attempt)), file=sys.stderr)
            time.sleep(2 ** (attempt - 1))


def head_once(url):
    with urlopen(Request(url, method="HEAD"), timeout=30) as response:
        if response.status != 200:
            raise ValueError("Source file is unavailable")
    return url


def head(url):
    return source_request("HEAD", url, head_once)


def get_bytes(url):
    return source_request("GET", url, download_bytes)


def inspect_source(context):
    catalog_raw = get_bytes(CATALOG_URL)
    metadata = catalog_context(catalog_raw, **context)
    raw = get_bytes(matches_url(**context))
    ids = matches_context(raw, **context)
    urls = [f"{SOURCE_BASE_URL}/{kind}/{match_id}.json" for match_id in ids for kind in ("events", "lineups")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        verified = list(pool.map(head, urls))
    rows = json.loads(raw)
    return {**context, "competition_name": metadata.get("competition_name"), "season_name": metadata.get("season_name"),
            "matches_url": matches_url(**context), "catalog_sha256": sha256_bytes(catalog_raw),
            "matches_sha256": sha256_bytes(raw), "match_count": len(ids),
            "team_count": len({row[side + "_team"][side + "_team_id"] for row in rows for side in ("home", "away")}),
            "events_available": len(verified) // 2, "lineups_available": len(verified) // 2,
            "match_ids": ids, "source_urls": verified}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_context_arguments(parser)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_source(context_from_args(args)), indent=2))
        return 0
    except Exception as error:
        detail = " " + json.dumps(error.diagnostics) if isinstance(error, SourceAccessError) else ""
        print(f"Public source preflight failed: exception={type(error).__name__}{detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
