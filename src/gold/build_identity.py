"""Canonical Gold identity; no timestamps, runtime state or credentials."""

from src.common.checksum import sha256_bytes
from src.common.s3_paths import s3a_uri
from src.silver.build_identity import SILVER_DATASETS, SPEC_FIELDS, canonical_json, require_sha256

DATASETS = {"team-match-stats": "team_match_stats", "player-match-stats": "player_match_stats", "match-results": "match_results"}
OUTPUT_PARTITIONS = {"team_match_stats": 1, "player_match_stats": 2, "match_results": 1}
REQUIRED_INPUTS = ("event_core", "match_squads", "pass_events", "shot_events")
RESULT_INPUTS = ("event_core", "matches", "shot_events")
INPUT_FIELDS = ("dataset", "build_id", "transform_version", "schema_sha256", "s3_bucket", "s3_prefix")


def required_inputs(dataset):
    return RESULT_INPUTS if dataset == "match_results" else REQUIRED_INPUTS


def canonical_inputs(builds: list[dict]) -> list[dict]:
    items = [{field: build[field] for field in INPUT_FIELDS} for build in builds]
    seen = set()
    for item in items:
        if item["dataset"] not in SILVER_DATASETS or item["dataset"] in seen:
            raise ValueError("Unsupported or duplicate Silver input dataset.")
        seen.add(item["dataset"])
        for field in ("build_id", "schema_sha256"):
            require_sha256(item[field])
        if not isinstance(item["transform_version"], str) or not item["transform_version"]:
            raise ValueError("Missing Silver transform version.")
        s3a_uri(item["s3_bucket"], item["s3_prefix"])
    if not items:
        raise ValueError("Gold requires explicit Silver inputs.")
    return sorted(items, key=lambda item: item["dataset"])


def input_fingerprint(builds: list[dict]) -> str:
    return sha256_bytes(canonical_json(canonical_inputs(builds)))


def build_specification(*, dataset: str, competition_id: int, season_id: int,
                        transform_version: str, input_fingerprint: str, schema_sha256: str) -> dict:
    if dataset not in OUTPUT_PARTITIONS or not transform_version:
        raise ValueError("Unsupported Gold dataset/version.")
    if any(type(value) is not int or value <= 0 for value in (competition_id, season_id)):
        raise ValueError("Invalid Gold context.")
    require_sha256(input_fingerprint)
    require_sha256(schema_sha256)
    return dict(layer="gold", source="statsbomb", dataset=dataset, competition_id=competition_id,
                season_id=season_id, transform_version=transform_version,
                input_fingerprint=input_fingerprint, schema_sha256=schema_sha256)


def calculate_build_id(specification: dict) -> str:
    return sha256_bytes(canonical_json({field: specification[field] for field in SPEC_FIELDS}))


def gold_prefix(specification: dict, build_id: str) -> str:
    require_sha256(build_id)
    if specification["layer"] != "gold" or specification["source"] != "statsbomb" or specification["dataset"] not in OUTPUT_PARTITIONS:
        raise ValueError("Invalid Gold specification.")
    return (f"football/gold/statsbomb/{specification['dataset']}/"
            f"competition_id={specification['competition_id']}/season_id={specification['season_id']}/build_id={build_id}/")
