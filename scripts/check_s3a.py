"""Read one cataloged event artifact directly with S3A; no remote writes."""

import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze_reader import verify_bronze_object_metadata
from src.common.postgres import create_postgres_connection, find_latest_ingestion_objects
from src.common.s3 import create_s3_client
from src.common.spark_s3a import configure_s3a, runtime_versions
from src.silver.statsbomb.membership import event_artifact_s3a_path


def main() -> int:
    from pyspark.sql import SparkSession
    from src.silver.statsbomb.events import read_s3a_events

    spark = None
    try:
        spark = (
            SparkSession.builder.appName("football-s3a-smoke").master("local[2]")
            .config("spark.ui.enabled", "false").getOrCreate()
        )
        spark.sparkContext.setLogLevel("OFF")
        configure_s3a(spark)
        for name, value in runtime_versions(spark).items():
            print(f"{name}: {value}")
        with create_postgres_connection() as connection:
            artifacts = find_latest_ingestion_objects(connection, source="statsbomb", dataset="match_events")
        if not artifacts:
            raise ValueError("No cataloged match_events artifact.")
        artifact = artifacts[0]
        path = event_artifact_s3a_path(artifact)
        with closing(create_s3_client()) as client:
            verify_bronze_object_metadata(client, artifact)
        count = read_s3a_events(spark, [path]).count()
        print("S3A direct read successful")
        print(f"Object key: {artifact['object_key']}")
        print(f"Rows: {count}")
        return 0
    except Exception as error:
        print(f"S3A check failed ({type(error).__name__}); no writes were requested.", file=sys.stderr)
        return 1
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    raise SystemExit(main())
