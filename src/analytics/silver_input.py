"""Resolve and verify event_core metadata; never download Parquet bodies."""

import os

from src.common.postgres import find_latest_silver_build, find_silver_build
from src.common.s3_paths import selectel_virtual_url
from src.silver.build_identity import (
    calculate_build_id, input_fingerprint, require_sha256, silver_prefix,
)
from src.silver.manifest import SilverIntegrityError, inspect_silver_output, read_manifest
from src.analytics.specs import EVENT_CORE

CONTEXT = {"source": "statsbomb", "dataset": "event_core", "competition_id": 43, "season_id": 106}


def resolve_silver_build(connection, build_id: str | None = None, *, spec=EVENT_CORE) -> dict:
    context = {**CONTEXT, "dataset": spec.dataset}
    if build_id is None:
        build = find_latest_silver_build(connection, **context)
    else:
        require_sha256(build_id)
        build = find_silver_build(
            connection, dataset=spec.dataset, competition_id=CONTEXT["competition_id"],
            season_id=CONTEXT["season_id"], build_id=build_id,
        )
    if build is None:
        raise SilverIntegrityError("No matching registered Silver build.")
    if build_id is not None and build.get("build_id") != build_id:
        raise SilverIntegrityError("Exact Silver build lookup returned a different identity.")
    if any(build.get(name) != value for name, value in context.items()):
        raise SilverIntegrityError("Silver build context mismatch.")
    if build.get("transform_version") != spec.transform_version:
        raise SilverIntegrityError("Unsupported Silver transform version for this dataset.")
    for name in ("build_id", "input_fingerprint", "schema_sha256"):
        require_sha256(build[name])
    for name in ("row_count", "file_count"):
        if type(build.get(name)) is not int or build[name] <= 0:
            raise SilverIntegrityError("Silver catalog requires positive row/file counts.")
    if build["s3_bucket"] != os.environ.get("S3_BUCKET"):
        raise SilverIntegrityError("Silver catalog bucket differs from configured S3_BUCKET.")
    if build["s3_prefix"] != silver_prefix(build, build["build_id"]):
        raise SilverIntegrityError("Silver catalog prefix does not match the exact build.")
    # Validate the endpoint and prefix before any cloud call.
    selectel_virtual_url(build["s3_prefix"])
    return build


def verify_silver_manifest(client, build: dict, *, spec=EVENT_CORE) -> dict:
    if build.get("dataset") != spec.dataset or build.get("transform_version") != spec.transform_version:
        raise SilverIntegrityError("Silver build does not match dataset specification.")
    bucket, prefix = build["s3_bucket"], build["s3_prefix"]
    manifest = read_manifest(client, bucket=bucket, prefix=prefix, build_id=build["build_id"])
    if manifest is None:
        raise SilverIntegrityError("Registered Silver build has no manifest.")
    fields = (
        *CONTEXT, "transform_version", "input_fingerprint", "schema_sha256",
        "build_id", "row_count", "file_count",
    )
    if any(manifest.get(name) != build[name] for name in fields):
        raise SilverIntegrityError("Silver manifest differs from PostgreSQL catalog.")
    if manifest.get("layer") != "silver" or calculate_build_id(manifest) != build["build_id"]:
        raise SilverIntegrityError("Silver manifest identity mismatch.")
    try:
        fingerprint = input_fingerprint(manifest["inputs"], artifact_kind=spec.artifact_kind)
    except (KeyError, TypeError, ValueError):
        raise SilverIntegrityError("Silver manifest input lineage is malformed.") from None
    if fingerprint != build["input_fingerprint"]:
        raise SilverIntegrityError("Silver manifest input fingerprint mismatch.")
    matches = manifest.get("match_count")
    if spec.has_match_count and (
        type(matches) is not int or not 0 < matches <= build["row_count"]
        or matches != (build["row_count"] if spec.artifact_kind == "matches" else len(manifest["inputs"]))
    ):
        raise SilverIntegrityError("Silver manifest match_count is invalid.")
    files = inspect_silver_output(client, bucket=bucket, prefix=prefix)
    if files is None or len(files) != build["file_count"] or files != manifest.get("files"):
        raise SilverIntegrityError("Silver file count/inventory differs from manifest.")
    return manifest


def parquet_url(build: dict) -> str:
    # The wildcard is application-owned, never accepted from CLI/catalog/env.
    return selectel_virtual_url(build["s3_prefix"]) + "part-*.parquet"
