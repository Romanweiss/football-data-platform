"""Independent Gold CLI orchestration; no raw exception text or secret logging."""

import argparse
import sys
from contextlib import ExitStack, closing, nullcontext
from dataclasses import dataclass

from src.analytics.gold_input import parquet_url, resolve_gold_build, verify_gold_manifest
from src.analytics.gold_loader import load_gold
from src.analytics.gold_specs import CLI_DATASETS, serving_spec
from src.analytics.validation import ClickHouseIntegrityError, verify_named_collection
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import clickhouse_load_lock, create_postgres_connection
from src.common.s3 import create_s3_client
from src.gold.manifest import GoldIntegrityError
from src.gold.stats_snapshot import validate_context_snapshot
from src.statsbomb.context import add_context_arguments, context_from_args
from src.silver.build_identity import require_sha256


@dataclass
class GoldDiagnostics:
    stage: str = "configuration"
    operation: str = "initialize"

    def set(self, stage, operation):
        self.stage, self.operation = stage, operation

    def failure(self, error):
        category = "integrity" if isinstance(error, (GoldIntegrityError, ClickHouseIntegrityError)) else "runtime"
        return (f"Gold ClickHouse job failed: stage={self.stage}; operation={self.operation}; "
                f"exception={type(error).__name__}; category={category}. No automatic delete/reload. "
                "After INSERT timeout wait for the server query to finish before retrying.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Materialize one registered Gold build in ClickHouse.")
    parser.add_argument("--dataset", required=True, choices=CLI_DATASETS)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--build-id", required=True)
    add_context_arguments(parser)
    parser.add_argument("--silver-build", action="append", default=[], metavar="DATASET=SHA256")
    parser.add_argument("--transform-version", choices=("v1", "v2"), default="v1")
    args = parser.parse_args(argv)
    if args.dataset == "match-results" and args.transform_version != "v1":
        parser.error("match-results only supports v1")
    if args.transform_version == "v2" and args.build_id is None:
        parser.error("Shadow v2 loading requires an explicit --build-id; latest is not allowed")
    if args.build_id is not None:
        try:
            require_sha256(args.build_id)
        except ValueError:
            parser.error("--build-id must be 64 lowercase hexadecimal characters")
    from src.gold.build_identity import REQUIRED_INPUTS
    args.expected_inputs = {}
    for value in args.silver_build:
        name, separator, build_id = value.partition("=")
        if not separator or name in args.expected_inputs or name not in REQUIRED_INPUTS:
            parser.error("Provide unique allowlisted DATASET=SHA256 Silver pins")
        try:
            require_sha256(build_id)
        except ValueError:
            parser.error("Invalid Silver build ID")
        args.expected_inputs[name] = build_id
    if args.transform_version == "v2" and set(args.expected_inputs) != set(REQUIRED_INPUTS):
        parser.error("Stats v2 loading requires all four exact --silver-build inputs")
    return args


def main(argv=None):
    args = parse_args(argv)
    spec = serving_spec(CLI_DATASETS[args.dataset], args.transform_version)
    diagnostics = GoldDiagnostics()
    try:
        with ExitStack() as stack:
            connection = stack.enter_context(closing(create_postgres_connection()))
            diagnostics.set("Gold catalog", "resolve_gold_build")
            build = resolve_gold_build(connection, args.build_id, **context_from_args(args), spec=spec)
            diagnostics.set("Gold manifest/completeness", "verify_gold_manifest")
            s3 = stack.enter_context(closing(create_s3_client()))
            manifest = verify_gold_manifest(s3, build)
            if spec.version == "v2":
                validate_context_snapshot(manifest["inputs"], args.expected_inputs, **context_from_args(args))
            url = parquet_url(build)
            # No ClickHouse access before the registered Gold artifact is verified.
            diagnostics.set("ClickHouse configuration", "create_client/named_collection")
            client = stack.enter_context(closing(create_clickhouse_client()))
            verify_named_collection(client)
            diagnostics.set("writer lock", "pg_try_advisory_lock")
            # Reuse the existing cooperative lock without changing Silver semantics.
            with nullcontext() if args.check_only else clickhouse_load_lock(connection):
                load_gold(client, connection, build, manifest, url, spec=spec,
                          check_only=args.check_only, diagnostics=diagnostics)
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1
