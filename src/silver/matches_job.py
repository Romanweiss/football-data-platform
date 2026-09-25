"""Small verified Bronze parent -> matches; reuse the immutable Silver publisher."""

import os
import sys
from contextlib import closing

from src.analytics.silver_input import resolve_silver_build, verify_silver_manifest
from src.analytics.specs import TEAMS
from src.common.bronze_reader import read_bronze_object, verify_bronze_object_metadata
from src.common.checksum import sha256_bytes
from src.common.postgres import create_postgres_connection, find_latest_ingestion_object
from src.common.s3 import create_s3_client
from src.common.s3_paths import s3a_uri
from src.common.spark_s3a import configure_s3a
from src.silver.build_identity import build_specification, calculate_build_id, canonical_inputs, input_fingerprint
from src.silver.diagnostics import PublishDiagnostics
from src.silver.job import create_spark_session
from src.silver.manifest import SilverIntegrityError
from src.silver.publish import publish_build


def read_teams(spark, build, manifest):
    from pyspark.sql import functions as F
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    paths = [s3a_uri(build["s3_bucket"], item["object_key"]) for item in manifest["files"]]
    frame = spark.read.option("recursiveFileLookup", "true").parquet(*paths).cache()
    try:
        schema = StructType([StructField(name, kind, True) for name, kind in (
            ("competition_id", LongType()), ("season_id", LongType()), ("team_id", LongType()), ("team_name", StringType()))])
        if frame.schema.toNullable() != schema:
            raise SilverIntegrityError("Teams reference schema mismatch.")
        rows, identities, invalid = frame.agg(F.count("*"), F.countDistinct("team_id"),
            F.count(F.when(F.col("team_id").isNull() | F.col("team_name").isNull()
                | F.col("competition_id").isNull() | F.col("season_id").isNull()
                | (F.col("competition_id") != 43) | (F.col("season_id") != 106), 1))).first()
        if rows != build["row_count"] or rows != identities or invalid:
            raise SilverIntegrityError("Teams reference counts/identity/context mismatch.")
        return frame
    except Exception:
        frame.unpersist()
        raise


def run_job(*, check_only=False):
    from src.silver.statsbomb.matches import build_matches

    diagnostics = PublishDiagnostics()
    spark = teams = frame = None
    code = 0
    try:
        bucket = os.environ.get("S3_BUCKET", "")
        s3a_uri(bucket, "football/silver/")
        with create_postgres_connection() as connection, closing(create_s3_client()) as client:
            diagnostics.set("parent catalog", "find_latest_ingestion_object")
            parent = find_latest_ingestion_object(connection, source="statsbomb", dataset="world_cup_2022_matches")
            inputs = canonical_inputs([parent], artifact_kind="matches")
            if parent["s3_bucket"] != bucket:
                raise SilverIntegrityError("Bronze parent bucket differs from configured bucket.")
            print("Parent catalog artifact found")
            diagnostics.set("parent GET/integrity", "verify_metadata/GetObject/sha256", key=parent["object_key"])
            verify_bronze_object_metadata(client, parent)
            raw = read_bronze_object(client, bucket=parent["s3_bucket"], key=parent["object_key"], checksum=parent["sha256"])
            if len(raw) != parent["size_bytes"]:
                raise SilverIntegrityError("Bronze parent size mismatch.")
            print("Parent Bronze verified")
            diagnostics.set("teams reference", "resolve_catalog/verify_manifest")
            team_build = resolve_silver_build(connection, spec=TEAMS)
            team_manifest = verify_silver_manifest(client, team_build, spec=TEAMS)
            print(f"Teams reference build ID: {team_build['build_id']}")
            diagnostics.set("Spark teams read", "read_exact_parts/validate")
            spark = create_spark_session("matches")
            configure_s3a(spark)
            teams = read_teams(spark, team_build, team_manifest)
            diagnostics.set("matches transformation/DQ", "build_matches")
            frame, counts = build_matches(spark, raw, teams)
            specification = build_specification(dataset="matches", transform_version="matches_v1", competition_id=43, season_id=106,
                input_fingerprint=input_fingerprint(inputs, artifact_kind="matches"), schema_sha256=sha256_bytes(frame.schema.json().encode("utf-8")))
            for name, value in (("Dataset", "matches"), ("Transform version", "matches_v1"), ("Rows", counts["row_count"]),
                                ("Input fingerprint", specification["input_fingerprint"]), ("Schema SHA256", specification["schema_sha256"]),
                                ("Build ID", calculate_build_id(specification)), ("DQ", "PASSED")):
                print(f"{name}: {value}")
            if check_only:
                print("CHECK ONLY - nothing published")
            else:
                result = publish_build(spark=spark, frame=frame, counts=counts, inputs=inputs, specification=specification,
                    bucket=bucket, client=client, connection=connection, diagnostics=diagnostics)
                print(f"Output status: {result['output_status']}\nCatalog: {result['catalog']}\nOutput: {result['output_uri']}")
    except Exception as error:
        print(diagnostics.failure(error, integrity=isinstance(error, SilverIntegrityError)), file=sys.stderr)
        code = 1
    finally:
        for resource, operation in ((frame, "unpersist"), (teams, "unpersist"), (spark, "stop")):
            if resource is not None:
                try:
                    getattr(resource, operation)()
                except Exception as error:
                    diagnostics.set("Spark cleanup", operation)
                    print(diagnostics.failure(error), file=sys.stderr)
                    code = 1
    return code
