"""Immutable Gold publication and recovery. No remote delete or overwrite."""

from src.common.postgres import find_gold_build, register_gold_build
from src.common.s3_paths import s3a_uri
from src.gold.build_identity import OUTPUT_PARTITIONS, calculate_build_id, gold_prefix
from src.gold.manifest import GoldIntegrityError, ensure_manifest, inspect_output, make_manifest, read_manifest, validate_manifest
from src.silver.publish import write_new_silver as write_new_parquet


def validate_catalog(actual, expected):
    if actual is None or any(actual.get(name) != value for name, value in expected.items()):
        raise GoldIntegrityError("Gold catalog conflicts with verified output.")


def validate_readback(spark, frame, *, bucket, files):
    """Small Gold marts: verify exact logical contents, including recovery without manifest."""
    try:
        restored = spark.read.option("recursiveFileLookup", "true").parquet(
            *[s3a_uri(bucket, item["object_key"]) for item in files])
        if restored.schema.toNullable() != frame.schema.toNullable():
            raise GoldIntegrityError("Gold read-back schema mismatch.")
        if restored.exceptAll(frame).limit(1).count() or frame.exceptAll(restored).limit(1).count():
            raise GoldIntegrityError("Gold read-back values differ from deterministic rebuild.")
    except GoldIntegrityError:
        raise
    except Exception:
        raise GoldIntegrityError("Gold Parquet read-back failed.") from None


def publish_build(*, spark, frame, counts, inputs, specification, bucket, client, connection, diagnostics):
    build_id = calculate_build_id(specification)
    prefix = gold_prefix(specification, build_id)
    uri = s3a_uri(bucket, prefix)
    identity = {field: specification[field] for field in ("dataset", "competition_id", "season_id")}
    identity["build_id"] = build_id
    diagnostics.set("Gold catalog", "find_gold_build")
    existing = find_gold_build(connection, **identity)
    diagnostics.set("Gold output", "inspect_output")
    files = inspect_output(client, bucket=bucket, prefix=prefix)
    unchanged = files is not None
    if files is None:
        if existing is not None:
            raise GoldIntegrityError("Registered Gold output is missing; refusing recreation.")
        diagnostics.set("Gold write", "write_new_parquet")
        write_new_parquet(frame, uri, partitions=OUTPUT_PARTITIONS[specification["dataset"]])
        diagnostics.set("Gold output", "inspect_output")
        files = inspect_output(client, bucket=bucket, prefix=prefix)
        if files is None:
            raise GoldIntegrityError("No Gold output after Spark write.")
    diagnostics.set("Gold manifest", "validate_manifest")
    expected = make_manifest(specification, inputs, counts, files)
    manifest = read_manifest(client, bucket=bucket, prefix=prefix, build_id=build_id)
    if manifest is not None:
        validate_manifest(manifest, expected)
    elif existing is not None:
        raise GoldIntegrityError("Registered Gold build is missing its manifest.")
    record = {field: specification[field] for field in (
        "source", "dataset", "competition_id", "season_id", "transform_version", "input_fingerprint", "schema_sha256")}
    record.update(build_id=build_id, s3_bucket=bucket, s3_prefix=prefix, row_count=counts["row_count"], file_count=len(files))
    if existing is not None:
        validate_catalog(existing, record)
    diagnostics.set("Gold read-back", "validate_readback")
    validate_readback(spark, frame, bucket=bucket, files=files)
    diagnostics.set("Gold manifest", "ensure_manifest")
    ensure_manifest(client, bucket=bucket, prefix=prefix, manifest=expected)
    registered = False
    if existing is None:
        diagnostics.set("PostgreSQL registration", "register_gold_build")
        registered = register_gold_build(connection, **record)
        validate_catalog(find_gold_build(connection, **identity), record)
    return dict(build_id=build_id, output_uri=uri, file_count=len(files),
                output_status="UNCHANGED / ALREADY_BUILT" if unchanged else "CREATED",
                catalog="REGISTERED" if registered else "ALREADY_REGISTERED")
