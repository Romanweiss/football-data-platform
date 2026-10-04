"""Choose exact selected-parent membership independently of Spark."""

import re

from src.common.bronze import BronzeIntegrityError
from src.common.s3_paths import s3a_uri
from src.statsbomb.events import EventArtifactError, extract_match_id_from_events_url
from src.statsbomb.lineups import LineupArtifactError, extract_match_id_from_lineups_url


def select_parent_event_artifacts(parent_match_ids: list[int], artifacts: list[dict]) -> list[dict]:
    """Require one latest event artifact per parent id; ignore other tournaments."""
    return _select_parent_artifacts(parent_match_ids, artifacts, extract_match_id_from_events_url, EventArtifactError, "event")


def select_parent_lineup_artifacts(parent_match_ids: list[int], artifacts: list[dict]) -> list[dict]:
    return _select_parent_artifacts(parent_match_ids, artifacts, extract_match_id_from_lineups_url, LineupArtifactError, "lineup")


def _select_parent_artifacts(parent_match_ids, artifacts, extract_id, error_type, label):
    if not parent_match_ids or any(type(value) is not int or value <= 0 for value in parent_match_ids):
        raise error_type("Parent must contain positive integer match ids.")
    required = set(parent_match_ids)
    if len(required) != len(parent_match_ids):
        raise error_type("Duplicate parent match id.")
    selected = {}
    for artifact in artifacts:
        match_id = extract_id(artifact["source_url"])
        if match_id not in required:
            continue
        if match_id in selected:
            raise error_type(f"Duplicate latest {label} artifact for match_id={match_id}.")
        selected[match_id] = {**artifact, "match_id": match_id}
    missing = required - selected.keys()
    if missing:
        raise error_type(f"Missing {label} artifacts for parent match ids: {sorted(missing)}.")
    return [selected[match_id] for match_id in sorted(required)]


def event_artifact_s3a_path(artifact: dict) -> str:
    """Cross-check URL identity against the path Spark will use for match_id."""
    match_id = extract_match_id_from_events_url(artifact["source_url"])
    match = re.search(
        r"/match_id=([1-9][0-9]*)/sha256=([0-9a-f]{64})/events\.json$",
        artifact["object_key"],
    )
    if match is None or int(match[1]) != match_id or match[2] != artifact["sha256"]:
        raise BronzeIntegrityError("Bronze event path identity/hash does not match its catalog source.")
    return s3a_uri(artifact["s3_bucket"], artifact["object_key"])


def lineup_artifact_s3a_path(artifact: dict) -> str:
    """Cross-check lineup URL identity, immutable path and catalog SHA-256."""
    match_id = extract_match_id_from_lineups_url(artifact["source_url"])
    match = re.search(
        r"/lineups/(?:competition_id=[1-9][0-9]*/season_id=[1-9][0-9]*/)?match_id=([1-9][0-9]*)/sha256=([0-9a-f]{64})/lineups\.json$",
        artifact["object_key"],
    )
    if match is None or int(match[1]) != match_id or match[2] != artifact["sha256"]:
        raise BronzeIntegrityError("Bronze lineup path identity/hash does not match its catalog source.")
    return s3a_uri(artifact["s3_bucket"], artifact["object_key"])
