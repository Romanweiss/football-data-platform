"""Deterministic identity for an immutable Silver dataset build."""

import json
import re

from src.common.checksum import sha256_bytes
from src.common.s3_paths import s3a_uri
from src.statsbomb.events import extract_match_id_from_events_url
from src.statsbomb.lineups import extract_match_id_from_lineups_url

TRANSFORM_VERSION = "event_core_v1"
LINEUP_DATASETS = ("teams", "players", "match_squads")
DIMENSION_DATASETS = ("teams", "players")
SILVER_DATASETS = ("event_core", "pass_events", "shot_events", *LINEUP_DATASETS, "matches")
MATCH_INPUT_FIELDS = ("source", "dataset", "source_url", "s3_bucket", "object_key", "sha256")
INPUT_FIELDS = ("match_id", "source_url", "s3_bucket", "object_key", "sha256")
SPEC_FIELDS = (
    "source", "layer", "dataset", "competition_id", "season_id",
    "transform_version", "input_fingerprint", "schema_sha256",
)


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def require_sha256(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA-256 digest.")


def canonical_inputs(artifacts: list[dict], *, artifact_kind: str = "events") -> list[dict]:
    if artifact_kind == "matches":
        if len(artifacts) != 1:
            raise ValueError("Matches requires one immutable Bronze parent.")
        item = {name: artifacts[0][name] for name in MATCH_INPUT_FIELDS}
        if (item["source"] != "statsbomb" or item["dataset"] != "world_cup_2022_matches"
                or not re.fullmatch(r"https://raw\.githubusercontent\.com/(?:hudl|statsbomb)/open-data/master/data/matches/43/106\.json", item["source_url"])):
            raise ValueError("Unexpected matches parent source/context.")
        require_sha256(item["sha256"])
        s3a_uri(item["s3_bucket"], item["object_key"])
        return [item]
    extract_id = {"events": extract_match_id_from_events_url, "lineups": extract_match_id_from_lineups_url}[artifact_kind]
    inputs = [{name: artifact[name] for name in INPUT_FIELDS} for artifact in artifacts]
    seen = set()
    for item in inputs:
        match_id = item["match_id"]
        if type(match_id) is not int or match_id != extract_id(item["source_url"]):
            raise ValueError("Input match identity does not match its canonical URL.")
        if match_id in seen:
            raise ValueError("Duplicate input match identity.")
        seen.add(match_id)
        require_sha256(item["sha256"])
        s3a_uri(item["s3_bucket"], item["object_key"])
    if not inputs:
        raise ValueError("Silver build requires inputs.")
    return sorted(inputs, key=lambda item: item["match_id"])


def input_fingerprint(artifacts: list[dict], *, artifact_kind: str = "events") -> str:
    return sha256_bytes(canonical_json(canonical_inputs(artifacts, artifact_kind=artifact_kind)))


def build_specification(
    *, input_fingerprint: str, schema_sha256: str, transform_version: str,
    competition_id: int, season_id: int, dataset: str = "event_core",
) -> dict:
    require_sha256(input_fingerprint)
    require_sha256(schema_sha256)
    if not transform_version or type(competition_id) is not int or type(season_id) is not int:
        raise ValueError("Invalid Silver build context.")
    if dataset not in SILVER_DATASETS:
        raise ValueError("Unsupported Silver dataset.")
    return {
        "source": "statsbomb", "layer": "silver", "dataset": dataset,
        "competition_id": competition_id, "season_id": season_id,
        "transform_version": transform_version,
        "input_fingerprint": input_fingerprint, "schema_sha256": schema_sha256,
    }


def calculate_build_id(specification: dict) -> str:
    # Whitelist the contract: timestamps, machine paths and other extra fields
    # must not enter identity (or leak into its serialized specification).
    return sha256_bytes(canonical_json({name: specification[name] for name in SPEC_FIELDS}))


def silver_prefix(specification: dict, build_id: str) -> str:
    require_sha256(build_id)
    if specification["dataset"] not in SILVER_DATASETS:
        raise ValueError("Unsupported Silver dataset.")
    return (
        f"football/silver/statsbomb/{specification['dataset']}/"
        f"competition_id={specification['competition_id']}/"
        f"season_id={specification['season_id']}/build_id={build_id}/"
    )
