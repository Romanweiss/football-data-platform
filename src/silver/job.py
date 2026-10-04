"""Shared context-bound input resolution and immutable Silver job orchestration."""

import argparse
import os
import sys
from contextlib import closing

from src.common.bronze import BronzeIntegrityError
from src.common.bronze_reader import read_bronze_object, verify_bronze_object_metadata
from src.common.checksum import sha256_bytes
from src.common.postgres import (
    create_postgres_connection, find_matches_parent, find_latest_ingestion_objects,
)
from src.common.s3 import create_s3_client
from src.common.s3_paths import s3a_uri
from src.common.spark_s3a import configure_s3a, runtime_versions
from src.silver.build_identity import (
    LINEUP_DATASETS, build_specification, calculate_build_id, input_fingerprint,
)
from src.silver.diagnostics import PublishDiagnostics
from src.silver.manifest import SilverIntegrityError
from src.silver.publish import publish_build
from src.silver.statsbomb.membership import (
    event_artifact_s3a_path, select_parent_event_artifacts,
    lineup_artifact_s3a_path, select_parent_lineup_artifacts,
)
from src.statsbomb.context import add_bronze_arguments, matches_context


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0")
    return result


def create_spark_session(dataset: str = "event_core"):
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.appName(f"football-silver-{dataset.replace('_', '-')}-publish").master("local[2]")
        .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    # Raw FAILFAST records and client exception details must not enter console logs.
    spark.sparkContext.setLogLevel("OFF")
    return spark


def parse_publish_args(parser: argparse.ArgumentParser, argv: list[str] | None):
    parser.add_argument("--check-only", action="store_true", help="read/transform/DQ only; no publication")
    parser.add_argument("--limit", type=positive_int, metavar="N", help="only permitted with --check-only")
    add_bronze_arguments(parser, children=True)
    args = parser.parse_args(argv)
    if args.limit is not None and not args.check_only:
        parser.error("--limit is allowed only with --check-only; partial publication is forbidden")
    return args


def run_publish_job(*, dataset: str, transform_version: str, build_frame, check_only: bool, limit: int | None,
                    competition_id: int, season_id: int, parent_sha256: str, bronze_max_id: int) -> int:
    """A dataset supplies only its read/transform/DQ function, not another publisher."""
    context = {"competition_id": competition_id, "season_id": season_id}
    spark = frame = None
    diagnostics = PublishDiagnostics()
    exit_code = 0
    try:
        is_lineup = dataset in LINEUP_DATASETS
        artifact_kind = "lineups" if is_lineup else "events"
        selector = select_parent_lineup_artifacts if is_lineup else select_parent_event_artifacts
        artifact_path = lineup_artifact_s3a_path if is_lineup else event_artifact_s3a_path
        bucket = os.environ.get("S3_BUCKET", "")
        if not check_only:
            s3a_uri(bucket, "football/silver/")  # Validate destination before any remote IO.
        with create_postgres_connection() as connection, closing(create_s3_client()) as client:
            diagnostics.set("parent catalog", "find_matches_parent")
            parent = find_matches_parent(connection, **context, sha256=parent_sha256)
            print("Parent catalog artifact found", flush=True)
            diagnostics.set("parent GET/integrity", "GetObject/verify_sha256", key=parent["object_key"])
            parent_raw = read_bronze_object(
                client, bucket=parent["s3_bucket"], key=parent["object_key"], checksum=parent["sha256"],
            )
            print("Parent Bronze verified", flush=True)
            diagnostics.set("membership", "extract_match_ids", key=parent["object_key"])
            parent_ids = matches_context(parent_raw, **context)
            print(f"Parent matches discovered: {len(parent_ids)}", flush=True)
            diagnostics.set("membership", "find_latest_ingestion_objects")
            artifacts = find_latest_ingestion_objects(connection, source="statsbomb", dataset=f"match_{artifact_kind}", max_id=bronze_max_id, **context)
            diagnostics.set("membership", "select_parent_lineup_artifacts" if is_lineup else "select_parent_event_artifacts")
            selected = selector(parent_ids, artifacts)
            selected = selected[:limit]
            print(f"{'Lineup' if is_lineup else 'Event'} artifacts selected: {len(selected)}", flush=True)
            paths = []
            for artifact in selected:
                diagnostics.set("membership", "lineup_artifact_s3a_path" if is_lineup else "event_artifact_s3a_path",
                                match_id=artifact["match_id"], key=artifact["object_key"])
                paths.append(artifact_path(artifact))
            for index, artifact in enumerate(selected, start=1):
                diagnostics.set("child HEAD preflight", "HeadObject/verify_metadata",
                                match_id=artifact["match_id"], key=artifact["object_key"])
                print(f"Bronze metadata preflight: {index}/{len(selected)}, match_id={artifact['match_id']}", flush=True)
                verify_bronze_object_metadata(client, artifact)
            diagnostics.set("Spark S3A read", "create_spark_session")
            spark = create_spark_session(dataset)
            diagnostics.set("Spark S3A read", "configure_s3a")
            configure_s3a(spark)
            for name, value in runtime_versions(spark).items():
                print(f"{name}: {value}")
            # A batch Spark exception cannot safely identify one child without parsing raw details.
            diagnostics.set("Spark S3A read", "read_transform_dq",
                            match_id=selected[0]["match_id"] if len(selected) == 1 else None,
                            key=selected[0]["object_key"] if len(selected) == 1 else None)
            frame, counts = build_frame(spark, paths, [artifact["match_id"] for artifact in selected], **context)
            diagnostics.set("build identity", "build_specification")
            specification = build_specification(
                input_fingerprint=input_fingerprint(selected, artifact_kind=artifact_kind),
                schema_sha256=sha256_bytes(frame.schema.json().encode("utf-8")),
                transform_version=transform_version, **context,
                dataset=dataset,
            )
            print(f"Dataset: {dataset}")
            print(f"Parent matches: {len(parent_ids)}")
            print(f"Bronze artifacts selected: {len(selected)}")
            print(f"Matches processed: {counts.get('match_count', counts.get('input_match_count'))}")
            if is_lineup:
                print(f"Raw lineup team rows: {counts['raw_lineup_team_rows']}")
                print(f"Raw lineup player rows: {counts['raw_lineup_player_rows']}")
                print(f"Output rows: {counts['row_count']}")
            else:
                print(f"Events read: {counts['row_count']}")
            if "input_row_count" in counts:
                print(f"Input events: {counts['input_row_count']}")
                print(f"Domain events: {counts['row_count']}")
            print("DQ: PASSED")
            print(f"Transform version: {transform_version}")
            print(f"Input fingerprint: {specification['input_fingerprint']}")
            print(f"Schema SHA256: {specification['schema_sha256']}")
            print(f"Calculated build_id: {calculate_build_id(specification)}")
            print(f"Build ID: {calculate_build_id(specification)}")
            if check_only:
                print("CHECK ONLY - nothing published")
            else:
                diagnostics.set("Silver output validation", "publish_build")
                result = publish_build(
                    spark=spark, frame=frame, counts=counts, inputs=selected,
                    specification=specification, bucket=bucket, client=client, connection=connection,
                    diagnostics=diagnostics,
                )
                print(f"Silver {dataset} publish complete")
                print(f"{'Rows' if is_lineup else 'Events'} written: {counts['row_count']}")
                print(f"Output files: {result['file_count']}")
                print(f"Build ID: {result['build_id']}")
                print(f"Output: {result['output_uri']}")
                print(f"Output status: {result['output_status']}")
                print(f"Catalog: {result['catalog']}")
    except Exception as error:
        print(diagnostics.failure(error, integrity=isinstance(error, (SilverIntegrityError, BronzeIntegrityError))),
              file=sys.stderr)
        exit_code = 1
    finally:
        for resource, operation in ((frame, "unpersist"), (spark, "stop")):
            if resource is not None:
                try:
                    getattr(resource, operation)()
                except Exception as error:
                    diagnostics.set("Spark cleanup", operation)
                    print(diagnostics.failure(error), file=sys.stderr)
                    exit_code = 1
    return exit_code
