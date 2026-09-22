"""Stage 2B: direct S3A event reads and immutable full-parent Silver publication."""

import argparse
import os
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze import BronzeIntegrityError
from src.common.bronze_reader import read_bronze_object, verify_bronze_object_metadata
from src.common.checksum import sha256_bytes
from src.common.postgres import (
    create_postgres_connection, find_latest_ingestion_object, find_latest_ingestion_objects,
)
from src.common.s3 import create_s3_client
from src.common.s3_paths import s3a_uri
from src.common.spark_s3a import configure_s3a, runtime_versions
from src.silver.build_identity import (
    TRANSFORM_VERSION, build_specification, calculate_build_id, input_fingerprint,
)
from src.silver.diagnostics import PublishDiagnostics
from src.silver.manifest import SilverIntegrityError
from src.silver.publish import publish_build
from src.silver.statsbomb.membership import event_artifact_s3a_path, select_parent_event_artifacts
from src.statsbomb.events import EventArtifactError
from src.statsbomb.matches import extract_match_ids

COMPETITION_ID = 43
SEASON_ID = 106


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0")
    return result


def create_spark_session():
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.appName("football-silver-event-core-publish").master("local[2]")
        .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    # Raw FAILFAST records and client exception details must not enter console logs.
    spark.sparkContext.setLogLevel("OFF")
    return spark


def build_event_frame(spark, paths: list[str]):
    from src.silver.statsbomb.events import (
        EventCoreQualityError, read_s3a_events, transform_event_core, validate_event_core,
    )

    frame = transform_event_core(
        read_s3a_events(spark, paths), competition_id=COMPETITION_ID, season_id=SEASON_ID,
    ).cache()
    try:
        counts = validate_event_core(frame)
        if counts["match_count"] != len(paths):
            raise EventArtifactError(
                f"DQ: selected_artifacts={len(paths)}, matches_with_events={counts['match_count']}."
            )
        return frame, counts
    except EventCoreQualityError as error:
        frame.unpersist()
        raise EventArtifactError(str(error)) from None
    except Exception:
        frame.unpersist()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="read/transform/DQ only; no publication")
    parser.add_argument("--limit", type=positive_int, metavar="N", help="only permitted with --check-only")
    args = parser.parse_args(argv)
    if args.limit is not None and not args.check_only:
        parser.error("--limit is allowed only with --check-only; partial publication is forbidden")
    spark = frame = None
    diagnostics = PublishDiagnostics()
    exit_code = 0
    try:
        bucket = os.environ.get("S3_BUCKET", "")
        if not args.check_only:
            s3a_uri(bucket, "football/silver/")  # Validate destination before any remote IO.
        with create_postgres_connection() as connection, closing(create_s3_client()) as client:
            diagnostics.set("parent catalog", "find_latest_ingestion_object")
            parent = find_latest_ingestion_object(
                connection, source="statsbomb", dataset="world_cup_2022_matches",
            )
            print("Parent catalog artifact found", flush=True)
            diagnostics.set("parent GET/integrity", "GetObject/verify_sha256", key=parent["object_key"])
            parent_raw = read_bronze_object(
                client, bucket=parent["s3_bucket"], key=parent["object_key"], checksum=parent["sha256"],
            )
            print("Parent Bronze verified", flush=True)
            diagnostics.set("membership", "extract_match_ids", key=parent["object_key"])
            parent_ids = extract_match_ids(parent_raw)
            print(f"Parent matches discovered: {len(parent_ids)}", flush=True)
            diagnostics.set("membership", "find_latest_ingestion_objects")
            artifacts = find_latest_ingestion_objects(connection, source="statsbomb", dataset="match_events")
            diagnostics.set("membership", "select_parent_event_artifacts")
            selected = select_parent_event_artifacts(parent_ids, artifacts)
            selected = selected[:args.limit]
            print(f"Event artifacts selected: {len(selected)}", flush=True)
            paths = []
            for artifact in selected:
                diagnostics.set("membership", "event_artifact_s3a_path",
                                match_id=artifact["match_id"], key=artifact["object_key"])
                paths.append(event_artifact_s3a_path(artifact))
            for index, artifact in enumerate(selected, start=1):
                diagnostics.set("child HEAD preflight", "HeadObject/verify_metadata",
                                match_id=artifact["match_id"], key=artifact["object_key"])
                print(f"Bronze metadata preflight: {index}/{len(selected)}, match_id={artifact['match_id']}", flush=True)
                verify_bronze_object_metadata(client, artifact)
            diagnostics.set("Spark S3A read", "create_spark_session")
            spark = create_spark_session()
            diagnostics.set("Spark S3A read", "configure_s3a")
            configure_s3a(spark)
            for name, value in runtime_versions(spark).items():
                print(f"{name}: {value}")
            # A batch Spark exception cannot safely identify one child without parsing raw details.
            diagnostics.set("Spark S3A read", "read_transform_dq",
                            match_id=selected[0]["match_id"] if len(selected) == 1 else None,
                            key=selected[0]["object_key"] if len(selected) == 1 else None)
            frame, counts = build_event_frame(spark, paths)
            diagnostics.set("build identity", "build_specification")
            specification = build_specification(
                input_fingerprint=input_fingerprint(selected),
                schema_sha256=sha256_bytes(frame.schema.json().encode("utf-8")),
                transform_version=TRANSFORM_VERSION, competition_id=COMPETITION_ID, season_id=SEASON_ID,
            )
            print(f"Parent matches: {len(parent_ids)}")
            print(f"Bronze artifacts selected: {len(selected)}")
            print(f"Matches processed: {counts['match_count']}")
            print(f"Events read: {counts['row_count']}")
            print(f"Transform version: {TRANSFORM_VERSION}")
            print(f"Input fingerprint: {specification['input_fingerprint']}")
            print(f"Schema SHA256: {specification['schema_sha256']}")
            print(f"Calculated build_id: {calculate_build_id(specification)}")
            if args.check_only:
                print("CHECK ONLY - nothing published")
            else:
                diagnostics.set("Silver output validation", "publish_build")
                result = publish_build(
                    spark=spark, frame=frame, counts=counts, inputs=selected,
                    specification=specification, bucket=bucket, client=client, connection=connection,
                    diagnostics=diagnostics,
                )
                print("Silver event_core publish complete")
                print(f"Events written: {counts['row_count']}")
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


if __name__ == "__main__":
    raise SystemExit(main())
