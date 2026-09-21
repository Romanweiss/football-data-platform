"""Logical identity of canonical StatsBomb event artifacts."""

import re


class EventArtifactError(ValueError):
    """An event artifact cannot be assigned an unambiguous match identity."""


def extract_match_id_from_events_url(url: str) -> int:
    """Accept only the canonical HTTPS events URL and a positive BIGINT id."""
    match = re.fullmatch(
        r"https://raw\.githubusercontent\.com/hudl/open-data/master/data/events/"
        r"([1-9][0-9]{0,18})\.json",
        url,
    ) if isinstance(url, str) else None
    if match is None or int(match[1]) > 2**63 - 1:
        # Do not echo an untrusted URL (it could contain credentials).
        raise EventArtifactError("Expected a canonical StatsBomb events/<match_id>.json URL.")
    return int(match[1])
