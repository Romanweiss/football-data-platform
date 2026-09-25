"""Registered Gold resolution and metadata preflight. Never GET Parquet bodies."""

import os

from src.common.postgres import find_gold_build, find_latest_gold_build
from src.common.s3_paths import selectel_virtual_url
from src.gold.build_identity import SPEC_FIELDS, gold_prefix, require_sha256
from src.gold.manifest import GoldIntegrityError, inspect_output, make_manifest, read_manifest, validate_manifest

CONTEXT = {"source": "statsbomb", "competition_id": 43, "season_id": 106}


def resolve_gold_build(connection, build_id=None, *, spec):
    context = {**CONTEXT, "dataset": spec.dataset}
    if build_id is None:
        build = find_latest_gold_build(connection, **context)
    else:
        require_sha256(build_id)
        build = find_gold_build(connection, dataset=spec.dataset, competition_id=43, season_id=106, build_id=build_id)
    if build is None or any(build.get(field) != value for field, value in context.items()):
        raise GoldIntegrityError("No matching registered Gold build.")
    if build_id is not None and build["build_id"] != build_id:
        raise GoldIntegrityError("Exact Gold lookup returned a different build.")
    for field in ("build_id", "input_fingerprint", "schema_sha256"):
        require_sha256(build[field])
    if (build["transform_version"] != spec.transform_version
            or any(type(build.get(field)) is not int or build[field] <= 0 for field in ("row_count", "file_count"))
            or build["s3_bucket"] != os.environ.get("S3_BUCKET")
            or build["s3_prefix"] != gold_prefix({**build, "layer": "gold"}, build["build_id"])):
        raise GoldIntegrityError("Gold catalog version/counts/location mismatch.")
    selectel_virtual_url(build["s3_prefix"])
    return build


def verify_gold_manifest(client, build):
    bucket, prefix = build["s3_bucket"], build["s3_prefix"]
    actual = read_manifest(client, bucket=bucket, prefix=prefix, build_id=build["build_id"])
    if actual is None:
        raise GoldIntegrityError("Registered Gold build has no manifest.")
    files = inspect_output(client, bucket=bucket, prefix=prefix)
    if files is None or len(files) != build["file_count"]:
        raise GoldIntegrityError("Gold output inventory/count mismatch.")
    specification = {field: ("gold" if field == "layer" else build[field]) for field in SPEC_FIELDS}
    try:
        expected = make_manifest(specification, actual["inputs"],
                                 {"row_count": build["row_count"], "match_count": actual.get("match_count")}, files)
        if expected["build_id"] != build["build_id"] or expected["match_count"] > expected["row_count"]:
            raise GoldIntegrityError("Gold build identity or match count mismatch.")
        validate_manifest(actual, expected)
    except (KeyError, TypeError, ValueError):
        raise GoldIntegrityError("Malformed Gold manifest.") from None
    return actual


def parquet_url(build):
    return selectel_virtual_url(build["s3_prefix"]) + "part-*.parquet"
