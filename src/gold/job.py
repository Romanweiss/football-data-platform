"""Gold orchestration. Check-only never writes S3 or PostgreSQL."""

import argparse
import json
import os
import sys
from contextlib import closing
from dataclasses import dataclass

from src.common.checksum import sha256_bytes
from src.common.postgres import create_postgres_connection
from src.common.s3 import create_s3_client
from src.common.s3_paths import s3a_uri
from src.common.spark_s3a import configure_s3a
from src.gold.build_identity import DATASETS, build_specification, calculate_build_id, input_fingerprint, required_inputs, require_sha256
from src.gold.inputs import read_inputs, resolve_inputs
from src.gold.manifest import GoldIntegrityError
from src.gold.publish import publish_build
from src.silver.manifest import SilverIntegrityError


@dataclass
class Diagnostics:
    stage: str = "configuration"
    operation: str = "initialize"
    dataset: str | None = None

    def set(self, stage, operation, *, dataset=None):
        self.stage, self.operation, self.dataset = stage, operation, dataset

    def failure(self, error):
        category = "integrity" if isinstance(error, (GoldIntegrityError, SilverIntegrityError)) else "runtime"
        return (f"Gold job failed: stage={json.dumps(self.stage)} operation={json.dumps(self.operation)} "
                f"dataset={json.dumps(self.dataset)} exception={type(error).__name__} category={category}. "
                "No automatic overwrite or cleanup.")


def create_spark_session():
    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.appName("football-gold-match-stats").master("local[2]")
             .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4").getOrCreate())
    spark.sparkContext.setLogLevel("OFF")
    return spark


def build_frame(frames, **context):
    if context["dataset"] == "match_results":
        from src.gold.statsbomb.match_results import build_match_results
        context.pop("dataset")
        context.pop("transform_version", None)
        return build_match_results(frames, **context)
    from src.gold.statsbomb.match_stats import build_match_stats
    return build_match_stats(frames, **context)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build immutable Gold from registered Silver inputs; explicit pins required for results/v2.")
    parser.add_argument("--dataset", required=True, choices=DATASETS)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--transform-version", help="Explicit dataset_v1 or dataset_v2 (stats only). Default preserves v1.")
    parser.add_argument("--silver-build", action="append", default=[], metavar="DATASET=SHA256",
                        help="Pin each required immutable registered Silver input.")
    args = parser.parse_args(argv)
    dataset = DATASETS[args.dataset]
    version = args.transform_version or dataset + "_v1"
    allowed = (dataset + "_v1",) if dataset == "match_results" else (dataset + "_v1", dataset + "_v2")
    if version not in allowed:
        parser.error("Unsupported dataset transform version")
    pinned = {}
    for value in args.silver_build:
        name, separator, build_id = value.partition("=")
        if not separator or name in pinned:
            parser.error("--silver-build requires unique DATASET=SHA256 entries")
        try:
            require_sha256(build_id)
        except ValueError:
            parser.error("Each Silver build ID must be 64 lowercase hexadecimal characters")
        pinned[name] = build_id
    if (dataset == "match_results" or version.endswith("_v2") or pinned) and set(pinned) != set(required_inputs(dataset)):
        parser.error("This build requires all exact --silver-build inputs: " + ", ".join(required_inputs(dataset)))
    diagnostics = Diagnostics(dataset=dataset)
    spark = frame = None
    frames = {}
    status = 0
    try:
        bucket = os.environ.get("S3_BUCKET", "")
        s3a_uri(bucket, "football/gold/")
        with create_postgres_connection() as connection, closing(create_s3_client()) as client:
            options = {"required": required_inputs(dataset), "build_ids": pinned} if pinned else {}
            builds, manifests = resolve_inputs(connection, client, competition_id=43, season_id=106, diagnostics=diagnostics, **options)
            print("Selected Silver inputs:")
            for build in builds:
                print(f"  {build['dataset']}: {build['build_id']}")
            diagnostics.set("Spark setup", "configure_s3a")
            spark = create_spark_session()
            configure_s3a(spark)
            frames = read_inputs(spark, builds, manifests, diagnostics=diagnostics)
            diagnostics.set("Gold transformation/DQ", "build_match_results" if dataset == "match_results" else "build_match_stats", dataset=dataset)
            frame, counts = build_frame(frames, dataset=dataset, competition_id=43, season_id=106, transform_version=version)
            specification = build_specification(dataset=dataset, competition_id=43, season_id=106,
                transform_version=version, input_fingerprint=input_fingerprint(builds),
                schema_sha256=sha256_bytes(frame.schema.json().encode("utf-8")))
            for label, value in (("Dataset", dataset), ("Transform version", specification["transform_version"]),
                                 ("Input fingerprint", specification["input_fingerprint"]),
                                 ("Schema SHA256", specification["schema_sha256"]), ("Build ID", calculate_build_id(specification)),
                                 ("Matches", counts["match_count"]), ("Output rows", counts["row_count"])):
                print(f"{label}: {value}")
            print("DQ: PASSED")
            if args.check_only:
                print("CHECK ONLY - nothing published")
            else:
                result = publish_build(spark=spark, frame=frame, counts=counts, inputs=builds, specification=specification,
                                       bucket=bucket, client=client, connection=connection, diagnostics=diagnostics)
                print(f"Output status: {result['output_status']}")
                print(f"Catalog: {result['catalog']}")
                print(f"Output: {result['output_uri']}")
                print(f"Output files: {result['file_count']}")
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        status = 1
    finally:
        for resource, operation in [(frame, "unpersist"), *[(item, "unpersist") for item in frames.values()], (spark, "stop")]:
            if resource is not None:
                try:
                    getattr(resource, operation)()
                except Exception as error:
                    diagnostics.set("Spark cleanup", operation)
                    print(diagnostics.failure(error), file=sys.stderr)
                    status = 1
    return status
