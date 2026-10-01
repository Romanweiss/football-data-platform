"""Resolve once from PostgreSQL, verify Silver metadata, then read exact parts via Spark."""

import os

from src.common.postgres import find_latest_silver_build, find_silver_build
from src.common.s3_paths import s3a_uri
from src.gold.build_identity import REQUIRED_INPUTS
from src.gold.manifest import GoldIntegrityError
from src.silver.build_identity import calculate_build_id, input_fingerprint, require_sha256, silver_prefix
from src.silver.manifest import inspect_silver_output, read_manifest


def resolve_inputs(connection, client, *, competition_id, season_id, diagnostics,
                   required=REQUIRED_INPUTS, build_ids=None):
    if build_ids is not None and set(build_ids) != set(required):
        raise GoldIntegrityError("Provide exactly one pinned Silver build for every required input.")
    selected, manifests = [], {}
    for dataset in required:
        diagnostics.set("Silver catalog", "find_latest_silver_build", dataset=dataset)
        context = dict(source="statsbomb", dataset=dataset, competition_id=competition_id, season_id=season_id)
        if build_ids is None:
            build = find_latest_silver_build(connection, **context)
        else:
            require_sha256(build_ids[dataset])
            diagnostics.set("Silver catalog", "find_silver_build", dataset=dataset)
            build = find_silver_build(connection, dataset=dataset, competition_id=competition_id,
                                      season_id=season_id, build_id=build_ids[dataset])
            if build is not None and build["build_id"] != build_ids[dataset]:
                raise GoldIntegrityError("Exact Silver lookup returned another build.")
        if build is None or any(build.get(key) != value for key, value in context.items()):
            raise GoldIntegrityError("Missing or mismatched registered Silver build.")
        for field in ("build_id", "input_fingerprint", "schema_sha256"):
            require_sha256(build[field])
        if (build["transform_version"] != dataset + "_v1" or build["s3_bucket"] != os.environ.get("S3_BUCKET")
                or build["s3_prefix"] != silver_prefix(build, build["build_id"])
                or any(type(build.get(field)) is not int or build[field] <= 0 for field in ("row_count", "file_count"))):
            raise GoldIntegrityError("Silver catalog version/location/counts mismatch.")
        diagnostics.set("Silver manifest", "verify_manifest", dataset=dataset)
        manifest = read_manifest(client, bucket=build["s3_bucket"], prefix=build["s3_prefix"], build_id=build["build_id"])
        fields = (*context, "transform_version", "input_fingerprint", "schema_sha256", "build_id", "row_count", "file_count")
        if manifest is None or any(manifest.get(field) != build[field] for field in fields):
            raise GoldIntegrityError("Silver manifest differs from registered build.")
        if manifest.get("layer") != "silver" or calculate_build_id(manifest) != build["build_id"]:
            raise GoldIntegrityError("Silver manifest identity mismatch.")
        kind = "matches" if dataset == "matches" else "lineups" if dataset == "match_squads" else "events"
        try:
            fingerprint = input_fingerprint(manifest["inputs"], artifact_kind=kind)
        except (KeyError, TypeError, ValueError):
            raise GoldIntegrityError("Malformed Silver input lineage.") from None
        if fingerprint != build["input_fingerprint"]:
            raise GoldIntegrityError("Silver manifest lineage mismatch.")
        if (type(manifest.get("match_count")) is not int or manifest["match_count"] <= 0
                or manifest["match_count"] != (build["row_count"] if dataset == "matches" else len(manifest["inputs"]))):
            raise GoldIntegrityError("Silver match count mismatch.")
        diagnostics.set("Silver completeness", "inventory/_SUCCESS", dataset=dataset)
        files = inspect_silver_output(client, bucket=build["s3_bucket"], prefix=build["s3_prefix"])
        if files is None or len(files) != build["file_count"] or files != manifest.get("files"):
            raise GoldIntegrityError("Silver part inventory mismatch.")
        selected.append(build)
        manifests[dataset] = manifest
    # Gold combines one tournament snapshot, not incompatible match selections.
    memberships = [{item["match_id"] for item in manifest["inputs"]}
                   for name, manifest in manifests.items() if name != "matches"]
    if any(ids != memberships[0] for ids in memberships[1:]):
        raise GoldIntegrityError("Selected Silver builds cover different matches.")
    if build_ids is not None:
        for name in ("shot_events", "pass_events"):
            if name in manifests and manifests[name]["inputs"] != manifests["event_core"]["inputs"]:
                raise GoldIntegrityError("Pinned event domains must share exact Bronze event lineage.")
    return selected, manifests


def read_inputs(spark, builds, manifests, *, diagnostics):
    from pyspark.sql import functions as F

    frames = {}
    try:
        for build in builds:
            dataset = build["dataset"]
            diagnostics.set("Spark Silver read", "read_exact_parts/validate_counts", dataset=dataset)
            paths = [s3a_uri(build["s3_bucket"], item["object_key"]) for item in manifests[dataset]["files"]]
            frame = spark.read.option("recursiveFileLookup", "true").parquet(*paths).cache()
            frames[dataset] = frame
            row = frame.agg(F.count("*").alias("rows"), F.countDistinct("match_id").alias("matches"),
                            F.count(F.when(F.col("match_id").isNull()
                                | F.col("competition_id").isNull() | F.col("season_id").isNull()
                                | (F.col("competition_id") != build["competition_id"])
                                | (F.col("season_id") != build["season_id"]), 1)).alias("invalid")).first()
            if (row.rows != build["row_count"] or row.matches != manifests[dataset]["match_count"] or row.invalid):
                raise GoldIntegrityError("Silver Parquet row/match/context mismatch.")
        if "matches" in frames:
            parent = frames["matches"].select("match_id").distinct()
            for name, frame in frames.items():
                keys = frame.select("match_id").distinct()
                if (keys.join(parent, "match_id", "left_anti").limit(1).count()
                        or parent.join(keys, "match_id", "left_anti").limit(1).count()):
                    raise GoldIntegrityError("Pinned Silver inputs do not cover the same match identities.")
        return frames
    except Exception:
        for frame in frames.values():
            frame.unpersist()
        raise
