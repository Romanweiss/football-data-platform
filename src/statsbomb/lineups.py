"""Logical identity of canonical StatsBomb lineup artifacts."""

import re


class LineupArtifactError(ValueError):
    """A lineup artifact cannot be assigned an unambiguous match identity."""


def extract_match_id_from_lineups_url(url: str) -> int:
    """Accept only canonical HTTPS lineups URLs with positive BIGINT ids."""
    match = re.fullmatch(
        r"https://raw\.githubusercontent\.com/hudl/open-data/master/data/lineups/"
        r"([1-9][0-9]{0,18})\.json",
        url,
    ) if isinstance(url, str) else None
    if match is None or int(match[1]) > 2**63 - 1:
        raise LineupArtifactError("Expected a canonical StatsBomb lineups/<match_id>.json URL.")
    return int(match[1])
