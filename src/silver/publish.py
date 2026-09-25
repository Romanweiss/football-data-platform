"""New-destination publication and recovery, without remote overwrite/delete."""

from src.common.postgres import find_silver_build, register_silver_build
from src.common.s3_paths import s3a_uri
from src.silver.build_identity import calculate_build_id, silver_prefix
from src.silver.diagnostics import PublishDiagnostics
from src.silver.manifest import (
    SilverIntegrityError, ensure_manifest, inspect_silver_output,
    make_manifest, read_manifest, validate_manifest,
)

LINEUP_OUTPUT_PARTITIONS = {"teams": 1, "players": 2, "match_squads": 2}


def write_new_silver(frame, output_uri: str, *, partitions: int = 4) -> None:
    """Write a new destination with the existing S3A directory committer."""

    if not output_uri.startswith("s3a://"):
        raise ValueError("Silver publication requires an S3A destination.")
    if type(partitions) is not int or partitions <= 0:
        raise ValueError("Output partitions must be a positive integer.")
    (
        frame.repartition(partitions).write.mode("errorifexists")
        .option("compression", "snappy").parquet(output_uri)
    )


def validate_readback(spark, frame, counts: dict, *, bucket: str, files: list[dict]) -> None:
    from pyspark.sql import functions as F

    paths = [s3a_uri(bucket, item["object_key"]) for item in files]
    try:
        # Read exact parts, without inferring competition/season/build_id path partitions.
        restored = spark.read.option("recursiveFileLookup", "true").parquet(*paths)
        # Parquet readers widen nullability; field names/order/types/metadata must match.
        if restored.schema.toNullable() != frame.schema.toNullable():
            raise SilverIntegrityError("Silver read-back schema mismatch.")
        metrics = [F.count("*").alias("row_count")]
        if "match_count" in counts:
            metrics.append(F.countDistinct("match_id").alias("match_count"))
        actual = restored.agg(*metrics).first().asDict()
        if any(actual[name] != counts[name] for name in actual):
            raise SilverIntegrityError("Silver read-back row_count or match_count mismatch.")
    except SilverIntegrityError:
        raise
    except Exception:
        raise SilverIntegrityError("Silver read-back failed; existing objects were not modified.") from None


def validate_catalog(actual: dict | None, expected: dict) -> None:
    if actual is None or any(actual.get(name) != value for name, value in expected.items()):
        raise SilverIntegrityError("Silver catalog record conflicts with verified output metadata.")


def publish_build(
    *, spark, frame, counts: dict, inputs: list[dict], specification: dict,
    bucket: str, client, connection, diagnostics: PublishDiagnostics | None = None,
) -> dict:
    """Validate complete output on every run; repair only missing manifest/DB row."""
    diagnostics = diagnostics if diagnostics is not None else PublishDiagnostics()
    build_id = calculate_build_id(specification)
    prefix = silver_prefix(specification, build_id)
    output_uri = s3a_uri(bucket, prefix)
    identity = {
        name: value for name, value in specification.items()
        if name in ("dataset", "competition_id", "season_id")
    }
    identity["build_id"] = build_id
    diagnostics.set("PostgreSQL registration", "find_silver_build", key=prefix)
    existing_catalog = find_silver_build(connection, **identity)
    diagnostics.set("Silver output validation", "inspect_silver_output", key=prefix)
    files = inspect_silver_output(client, bucket=bucket, prefix=prefix)
    unchanged = files is not None
    if files is None:
        if existing_catalog is not None:
            raise SilverIntegrityError("Registered Silver output is missing; refusing to recreate it.")
        diagnostics.set("Silver output write", "write_new_silver", key=prefix)
        partitions = {**LINEUP_OUTPUT_PARTITIONS, "matches": 1}
        options = {"partitions": partitions[specification["dataset"]]} if specification["dataset"] in partitions else {}
        write_new_silver(frame, output_uri, **options)
        diagnostics.set("Silver output validation", "inspect_silver_output", key=prefix)
        files = inspect_silver_output(client, bucket=bucket, prefix=prefix)
        if files is None:
            raise SilverIntegrityError("No Silver output found after Spark write.")

    manifest_key = prefix + "_manifest.json"
    diagnostics.set("manifest", "make_manifest", key=manifest_key)
    manifest = make_manifest(specification, inputs, counts, files)
    diagnostics.set("manifest", "read_manifest", key=manifest_key)
    existing_manifest = read_manifest(client, bucket=bucket, prefix=prefix, build_id=build_id)
    if existing_manifest is not None:
        diagnostics.set("manifest", "validate_manifest", key=manifest_key)
        validate_manifest(existing_manifest, manifest)
    elif existing_catalog is not None:
        raise SilverIntegrityError("Registered Silver build is missing its manifest.")

    record = {
        name: specification[name] for name in (
            "source", "dataset", "competition_id", "season_id", "transform_version",
            "input_fingerprint", "schema_sha256",
        )
    }
    record.update(
        build_id=build_id, s3_bucket=bucket, s3_prefix=prefix,
        row_count=counts["row_count"], file_count=len(files),
    )
    if existing_catalog is not None:
        diagnostics.set("PostgreSQL registration", "validate_catalog", key=prefix)
        validate_catalog(existing_catalog, record)
    diagnostics.set("Silver output validation", "validate_readback", key=prefix)
    validate_readback(spark, frame, counts, bucket=bucket, files=files)
    diagnostics.set("manifest", "ensure_manifest", key=manifest_key)
    ensure_manifest(client, bucket=bucket, prefix=prefix, manifest=manifest)
    registered = False
    if existing_catalog is None:
        diagnostics.set("PostgreSQL registration", "register_silver_build", key=prefix)
        registered = register_silver_build(connection, **record)
        # Verify duplicate/racing registration instead of silently accepting different metadata.
        diagnostics.set("PostgreSQL registration", "find_silver_build", key=prefix)
        registered_catalog = find_silver_build(connection, **identity)
        diagnostics.set("PostgreSQL registration", "validate_catalog", key=prefix)
        validate_catalog(registered_catalog, record)
    return {
        "output_uri": output_uri, "file_count": len(files), "build_id": build_id,
        "catalog": "REGISTERED" if registered else "ALREADY_REGISTERED",
        "output_status": "UNCHANGED / ALREADY_BUILT" if unchanged else "CREATED",
    }
