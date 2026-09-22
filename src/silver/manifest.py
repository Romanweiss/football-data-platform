"""Immutable Silver manifests and exact-prefix inventory; no delete operations."""

import json
import re
from contextlib import closing

from botocore.exceptions import ClientError

from src.common.checksum import sha256_bytes
from src.common.s3_paths import s3a_uri
from src.silver.build_identity import (
    DIMENSION_DATASETS, LINEUP_DATASETS, SPEC_FIELDS, calculate_build_id, canonical_inputs, canonical_json, input_fingerprint,
)


class SilverIntegrityError(RuntimeError):
    """An existing Silver destination is partial or inconsistent; never overwrite."""


def is_missing(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")


def inspect_silver_output(client, *, bucket: str, prefix: str) -> list[dict] | None:
    """Return sorted part inventory, None for absent prefix, or fail closed."""
    s3a_uri(bucket, prefix)
    if not prefix.endswith("/"):
        raise ValueError("Silver prefix must end with a single slash.")
    objects = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            objects[item["Key"]] = item
    if not objects:
        return None
    if prefix + "_SUCCESS" not in objects:
        raise SilverIntegrityError("Existing Silver prefix has no _SUCCESS; no overwrite or cleanup allowed.")
    try:
        client.head_object(Bucket=bucket, Key=prefix + "_SUCCESS")
    except ClientError as error:
        if is_missing(error):
            raise SilverIntegrityError("Silver _SUCCESS disappeared after listing.") from None
        raise
    parts = []
    for key, item in sorted(objects.items()):
        if key == prefix and item["Size"] != 0:
            raise SilverIntegrityError("Silver directory marker has unexpected content.")
        if key in (prefix, prefix + "_SUCCESS", prefix + "_manifest.json"):
            continue
        name = key.removeprefix(prefix)
        if not re.fullmatch(r"part-[^/]+\.snappy\.parquet", name) or item["Size"] <= 0:
            raise SilverIntegrityError("Silver prefix contains unexpected or empty output objects.")
        parts.append({"object_key": key, "size_bytes": item["Size"], "etag": item.get("ETag", "")})
    if not parts:
        raise SilverIntegrityError("Silver prefix has _SUCCESS but no Parquet part files.")
    return parts


def make_manifest(specification: dict, inputs: list[dict], counts: dict, files: list[dict]) -> dict:
    """Whitelist fields; exclude timestamps, credentials and ambient environment."""
    artifact_kind = "lineups" if specification["dataset"] in LINEUP_DATASETS else "events"
    is_dimension = specification["dataset"] in DIMENSION_DATASETS
    if specification["input_fingerprint"] != input_fingerprint(inputs, artifact_kind=artifact_kind):
        raise SilverIntegrityError("Manifest inputs do not match the build specification fingerprint.")
    match_count = counts.get("input_match_count") if is_dimension else counts.get("match_count")
    if counts["row_count"] <= 0 or match_count != len(inputs) or not files:
        raise SilverIntegrityError("Manifest requires nonempty, fully validated output.")
    inventory = [
        {name: item[name] for name in ("object_key", "size_bytes", "etag")}
        for item in files
    ]
    result = {
        **{name: specification[name] for name in SPEC_FIELDS},
        "build_id": calculate_build_id(specification),
        "row_count": counts["row_count"],
        "file_count": len(files), "inputs": canonical_inputs(inputs, artifact_kind=artifact_kind),
        "files": sorted(inventory, key=lambda item: item["object_key"]),
    }
    if not is_dimension:
        result["match_count"] = counts["match_count"]
    return result


def read_manifest(client, *, bucket: str, prefix: str, build_id: str) -> dict | None:
    try:
        response = client.get_object(Bucket=bucket, Key=prefix + "_manifest.json")
    except ClientError as error:
        if is_missing(error):
            return None
        raise
    with closing(response["Body"]) as body:
        raw = body.read(1024 * 1024 + 1)
    metadata = response.get("Metadata", {})
    if (
        len(raw) > 1024 * 1024 or metadata.get("build_id") != build_id
        or metadata.get("sha256") != sha256_bytes(raw)
    ):
        raise SilverIntegrityError("Silver manifest build_id/checksum metadata is inconsistent.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise SilverIntegrityError("Silver manifest is not valid UTF-8 JSON.") from None
    if not isinstance(result, dict) or result.get("build_id") != build_id:
        raise SilverIntegrityError("Silver manifest has an incompatible build identity.")
    return result


def validate_manifest(actual: dict, expected: dict) -> None:
    if canonical_json(actual) != canonical_json(expected):
        raise SilverIntegrityError("Existing Silver manifest does not match inputs/schema/counts/file inventory.")


def ensure_manifest(client, *, bucket: str, prefix: str, manifest: dict) -> None:
    """Conditional create; an existing identical manifest is never rewritten."""
    build_id = manifest["build_id"]
    existing = read_manifest(client, bucket=bucket, prefix=prefix, build_id=build_id)
    if existing is not None:
        validate_manifest(existing, manifest)
        return
    raw = canonical_json(manifest)
    try:
        client.put_object(
            Bucket=bucket, Key=prefix + "_manifest.json", Body=raw,
            ContentType="application/json", IfNoneMatch="*",
            Metadata={"build_id": build_id, "sha256": sha256_bytes(raw)},
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in ("412", "PreconditionFailed"):
            raise
    # Verify either our acknowledged write or the winner of a conditional race.
    existing = read_manifest(client, bucket=bucket, prefix=prefix, build_id=build_id)
    if existing is None:
        raise SilverIntegrityError("Silver manifest was not found after conditional create.")
    validate_manifest(existing, manifest)
