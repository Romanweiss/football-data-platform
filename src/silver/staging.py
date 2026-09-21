"""Stage checksum-verified Bronze bytes without modifying remote objects."""

from pathlib import Path

from botocore.client import BaseClient

from src.common.bronze_reader import read_bronze_object
from src.statsbomb.events import EventArtifactError, extract_match_id_from_events_url


def select_event_artifacts(artifacts: list[dict], *, limit: int | None = None) -> list[dict]:
    """Validate the entire latest-only catalog result before applying a limit.

    Preserve the stable SQL source_url order. Duplicate logical sources should
    have been resolved by the catalog query; reject them instead of overwriting
    one staged match with another version accidentally.
    """
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise EventArtifactError("Artifact limit must be a positive integer.")
    seen = set()
    for artifact in artifacts:
        match_id = extract_match_id_from_events_url(artifact["source_url"])
        if match_id in seen:
            raise EventArtifactError(f"Duplicate logical event source for match_id={match_id}.")
        seen.add(match_id)
    if not artifacts:
        raise EventArtifactError("No registered statsbomb/match_events artifacts; ingest Bronze first.")
    return artifacts[:limit]


def stage_event_artifact(
    client: BaseClient, artifact: dict, *, staging_dir: Path
) -> Path:
    """Write original, verified bytes to match_id=<id>.json; never delete S3 data."""
    match_id = extract_match_id_from_events_url(artifact["source_url"])
    raw = read_bronze_object(
        client, bucket=artifact["s3_bucket"], key=artifact["object_key"],
        checksum=artifact["sha256"],
    )
    staging_dir.mkdir(parents=True, exist_ok=True)
    target = staging_dir / f"match_id={match_id}.json"
    if target.is_symlink():
        raise EventArtifactError("Staging target must not be a symbolic link.")
    target.write_bytes(raw)
    return target
