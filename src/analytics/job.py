"""Safe CLI orchestration for Stage 3A; no raw exception messages."""

import argparse
import sys
from contextlib import ExitStack, closing, nullcontext
from dataclasses import dataclass

from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import clickhouse_load_lock, create_postgres_connection
from src.common.s3 import create_s3_client
from src.silver.build_identity import require_sha256
from src.silver.manifest import SilverIntegrityError
from src.analytics.event_core import (
    ClickHouseIntegrityError, load_event_core, source_metrics, validate_metrics, verify_named_collection,
)
from src.analytics.silver_input import parquet_url, resolve_silver_build, verify_silver_manifest


@dataclass
class LoadDiagnostics:
    stage: str = "configuration"
    operation: str = "initialize"

    def set(self, stage: str, operation: str) -> None:
        self.stage, self.operation = stage, operation

    def failure(self, error: Exception) -> str:
        category = "integrity" if isinstance(error, (ClickHouseIntegrityError, SilverIntegrityError)) else "runtime"
        return (
            f"ClickHouse job failed: stage={self.stage}; operation={self.operation}; "
            f"exception={type(error).__name__}; category={category}. "
            "No automatic delete/reload. After an INSERT error, wait for the server query to finish "
            "before rerunning; the next run validates target rows first."
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Load one verified event_core Silver build into ClickHouse.")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--build-id")
    args = parser.parse_args(argv)
    if args.build_id is not None:
        try:
            require_sha256(args.build_id)
        except ValueError:
            parser.error("--build-id must be 64 lowercase hexadecimal characters")
    return args


def run_job(*, check_only=False, build_id=None, smoke=False) -> int:
    diagnostics = LoadDiagnostics()
    try:
        with ExitStack() as stack:
            connection = stack.enter_context(closing(create_postgres_connection()))
            diagnostics.set("Silver catalog", "resolve_silver_build")
            build = resolve_silver_build(connection, build_id)
            diagnostics.set("manifest", "verify_silver_manifest")
            s3 = stack.enter_context(closing(create_s3_client()))
            manifest = verify_silver_manifest(s3, build)
            url = parquet_url(build)
            diagnostics.set("ClickHouse configuration", "create_client")
            client = stack.enter_context(closing(create_clickhouse_client()))
            diagnostics.set("named collection", "verify_named_collection")
            verify_named_collection(client)
            if smoke:
                diagnostics.set("ClickHouse S3 read", "source_metrics")
                metrics = source_metrics(client, url)
                validate_metrics(metrics, manifest)
                print(f"ClickHouse version: {client.server_version}")
                print(f"Silver build_id: {build['build_id']}")
                print(f"Silver prefix: {build['s3_prefix']}")
                print(f"Parquet file count: {manifest['file_count']}")
                print(f"Rows via ClickHouse s3(): {metrics[0]}")
                print(f"Matches via ClickHouse s3(): {metrics[1]}")
                print("CLICKHOUSE S3 CHECK PASSED")
            else:
                diagnostics.set("writer lock", "pg_try_advisory_lock")
                with nullcontext() if check_only else clickhouse_load_lock(connection):
                    load_event_core(
                        client, connection, build, manifest, url,
                        check_only=check_only, diagnostics=diagnostics,
                    )
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1
