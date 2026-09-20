"""Small HTTP downloader using the standard library and default TLS trust."""

from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class DownloadError(RuntimeError):
    """A source could not be downloaded completely."""


def download_bytes(url: str) -> bytes:
    """Download the full HTTP response as bytes with a 30-second timeout."""
    request = Request(
        url,
        headers={"User-Agent": "football-data-platform/0.1 (StatsBomb Bronze ingestion)"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise DownloadError(f"HTTP {response.status} while downloading {url}")
            return response.read()
    except HTTPError as error:
        error.close()
        raise DownloadError(f"HTTP {error.code} while downloading {url}") from error
    except (OSError, HTTPException) as error:
        raise DownloadError(
            f"Could not download {url} ({type(error).__name__}); "
            "check network connectivity, TLS certificates and the HTTP response."
        ) from error
