"""Gold manifest contract, reusing schema-agnostic immutable S3 storage helpers."""

from src.silver import manifest as storage
from src.gold.build_identity import (
    REQUIRED_INPUTS, SPEC_FIELDS, calculate_build_id, canonical_inputs, canonical_json, gold_prefix, input_fingerprint,
)


class GoldIntegrityError(RuntimeError):
    """Invalid input/output/catalog; no automatic overwrite or cleanup."""


def _storage_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except storage.SilverIntegrityError:
        raise GoldIntegrityError("Immutable Gold object integrity check failed.") from None


def inspect_output(client, *, bucket, prefix):
    return _storage_call(storage.inspect_silver_output, client, bucket=bucket, prefix=prefix)


def read_manifest(client, *, bucket, prefix, build_id):
    return _storage_call(storage.read_manifest, client, bucket=bucket, prefix=prefix, build_id=build_id)


def ensure_manifest(client, *, bucket, prefix, manifest):
    return _storage_call(storage.ensure_manifest, client, bucket=bucket, prefix=prefix, manifest=manifest)


def make_manifest(specification, inputs, counts, files):
    canonical = canonical_inputs(inputs)
    if tuple(item["dataset"] for item in canonical) != REQUIRED_INPUTS:
        raise GoldIntegrityError("Gold input dataset set differs from the v1 contract.")
    if input_fingerprint(inputs) != specification["input_fingerprint"]:
        raise GoldIntegrityError("Gold input fingerprint differs from selected Silver builds.")
    if any(type(counts.get(name)) is not int or counts[name] <= 0 for name in ("row_count", "match_count")) or not files:
        raise GoldIntegrityError("Gold manifest requires positive validated counts and files.")
    build_id = calculate_build_id(specification)
    prefix = gold_prefix(specification, build_id)
    inventory = [{name: item[name] for name in ("object_key", "size_bytes", "etag")} for item in files]
    if len({item["object_key"] for item in inventory}) != len(inventory):
        raise GoldIntegrityError("Duplicate Gold output part.")
    for item in inventory:
        suffix = item["object_key"].removeprefix(prefix)
        if (not item["object_key"].startswith(prefix) or "/" in suffix or not suffix.startswith("part-")
                or not suffix.endswith(".snappy.parquet") or type(item["size_bytes"]) is not int or item["size_bytes"] <= 0):
            raise GoldIntegrityError("Invalid Gold part inventory.")
    return {**{field: specification[field] for field in SPEC_FIELDS}, "build_id": build_id,
            "row_count": counts["row_count"], "match_count": counts["match_count"], "file_count": len(files),
            "inputs": canonical, "files": sorted(inventory, key=lambda item: item["object_key"])}


def validate_manifest(actual, expected):
    if canonical_json(actual) != canonical_json(expected):
        raise GoldIntegrityError("Gold manifest differs from inputs/schema/counts/inventory.")
