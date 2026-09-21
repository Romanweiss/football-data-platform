"""Extract ordered match IDs from a verified StatsBomb matches artifact."""

import json


class MatchDataError(ValueError):
    """The parent matches artifact is not valid StatsBomb match-list data."""


def extract_match_ids(raw: bytes) -> list[int]:
    """Parse UTF-8 JSON and return unique integer IDs in their original order."""
    try:
        matches = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise MatchDataError("Matches artifact must contain valid UTF-8.") from None
    except json.JSONDecodeError as error:
        raise MatchDataError(
            f"Invalid matches JSON at line {error.lineno}, column {error.colno}."
        ) from None
    if not isinstance(matches, list):
        raise MatchDataError("Matches JSON root must be a list.")

    seen = set()
    match_ids = []
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise MatchDataError(f"Matches entry {index} must be an object.")
        if "match_id" not in match:
            raise MatchDataError(f"Matches entry {index} is missing match_id.")
        match_id = match["match_id"]
        # bool is a Python int subclass, but is not a JSON integer ID.
        if type(match_id) is not int:
            raise MatchDataError(f"Matches entry {index}: match_id must be an integer.")
        if match_id not in seen:
            seen.add(match_id)
            match_ids.append(match_id)
    return match_ids
