"""Build the Stage 2A local preview; reads Bronze but never writes remote data."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze import BronzeIntegrityError
from src.common.postgres import create_postgres_connection, find_latest_ingestion_objects, find_matches_parent
from src.common.s3 import create_s3_client
from src.silver.staging import select_event_artifacts, stage_event_artifact
from src.statsbomb.events import EventArtifactError
from src.common.bronze_reader import read_bronze_object
from src.statsbomb.context import add_bronze_arguments, context_from_args, matches_context
from src.silver.statsbomb.membership import select_parent_event_artifacts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGING_DIR = PROJECT_ROOT / "data/work/bronze_events"
OUTPUT_DIR = PROJECT_ROOT / "data/work/silver/event_core"


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0")
    return result


def build_local_preview(paths: list[Path], *, competition_id, season_id) -> dict:
    # Lazy imports keep catalog/staging and ordinary unit tests Spark-independent.
    from pyspark.sql import SparkSession
    from src.silver.statsbomb.events import (
        OUTPUT_PARTITIONS, EventCoreQualityError, read_staged_events,
        transform_event_core, validate_event_core, write_event_core,
    )

    spark = (
        SparkSession.builder.appName("football-silver-event-core")
        .master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", str(OUTPUT_PARTITIONS))
        .getOrCreate()
    )
    event_core = None
    try:
        # FAILFAST parser/executor stack traces can contain raw JSON. The CLI
        # reports safe phase/error-type messages and our own aggregate DQ counts.
        spark.sparkContext.setLogLevel("OFF")
        raw = read_staged_events(spark, paths)
        event_core = transform_event_core(
            raw, competition_id=competition_id, season_id=season_id,
        ).cache()
        counts = validate_event_core(event_core)
        if counts["match_count"] != len(paths):
            raise EventCoreQualityError(
                f"DQ: matches_with_events={counts['match_count']}, selected_artifacts={len(paths)}."
            )
        event_core.printSchema()
        write_event_core(event_core, OUTPUT_DIR / f"competition_id={competition_id}" / f"season_id={season_id}")
        return {**counts, "spark_version": spark.version, "output_partitions": OUTPUT_PARTITIONS}
    except EventCoreQualityError as error:
        # Only aggregate counts are included; no event payloads or credentials.
        raise EventArtifactError(str(error)) from None
    finally:
        if event_core is not None:
            event_core.unpersist()
        spark.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=positive_int, metavar="N", help="select the first N latest artifacts")
    add_bronze_arguments(parser, children=True)
    args = parser.parse_args(argv)
    context = context_from_args(args)
    phase = "catalog lookup"
    try:
        with create_postgres_connection() as connection:
            parent = find_matches_parent(connection, **context, sha256=args.parent_sha256)
            artifacts = find_latest_ingestion_objects(
                connection, source="statsbomb", dataset="match_events", max_id=args.bronze_max_id, **context,
            )
        select_event_artifacts(artifacts)  # Validate catalog URLs before remote IO.
        phase = "verified Bronze staging"
        with closing(create_s3_client()) as client:
            raw = read_bronze_object(client, bucket=parent["s3_bucket"], key=parent["object_key"], checksum=parent["sha256"])
            selected = select_parent_event_artifacts(matches_context(raw, **context), artifacts)[:args.limit]
            paths = [
                stage_event_artifact(client, artifact, staging_dir=STAGING_DIR / f"competition_id={args.competition_id}" / f"season_id={args.season_id}")
                for artifact in selected
            ]
        phase = "Spark transformation / DQ / local Parquet write"
        result = build_local_preview(paths, **context)
    except (EventArtifactError, BronzeIntegrityError) as error:
        print(f"Silver preview failed ({phase}): {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # Remote client and Spark exceptions can contain credentials or raw data.
        print(f"Silver preview failed ({phase}, {type(error).__name__}).", file=sys.stderr)
        return 1

    # A successful summary is emitted only after the Parquet write has finished.
    print("Silver event_core build complete")
    print(f"Bronze artifacts selected: {len(selected)}")
    print(f"Matches processed: {result['match_count']}")
    print(f"Events read: {result['row_count']}")
    print(f"Events written: {result['row_count']}")
    print(f"Output partitions: {result['output_partitions']}")
    print(f"Output: data/work/silver/event_core/competition_id={args.competition_id}/season_id={args.season_id}")
    print(f"Spark version: {result['spark_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
