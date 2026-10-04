"""Read-only exact Bronze parent integrity and complete child metadata preflight."""
import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze_reader import read_bronze_object, verify_bronze_object_metadata
from src.common.postgres import create_postgres_connection, find_matches_parent, find_latest_ingestion_objects
from src.common.s3 import create_s3_client
from src.silver.diagnostics import PublishDiagnostics
from src.silver.statsbomb.membership import (select_parent_event_artifacts, select_parent_lineup_artifacts,
                                           event_artifact_s3a_path, lineup_artifact_s3a_path)
from src.statsbomb.context import add_bronze_arguments, context_from_args, matches_context


def check_bronze(connection, client, *, context, parent_sha256, bronze_max_id, diagnostics):
    diagnostics.set("parent catalog", "find_matches_parent")
    parent = find_matches_parent(connection, **context, sha256=parent_sha256)
    diagnostics.set("parent GET/integrity", "read_bronze_object", key=parent["object_key"])
    raw = read_bronze_object(client, bucket=parent["s3_bucket"], key=parent["object_key"], checksum=parent["sha256"])
    ids = matches_context(raw, **context)
    for dataset, selector, path in (
        ("match_events", select_parent_event_artifacts, event_artifact_s3a_path),
        ("match_lineups", select_parent_lineup_artifacts, lineup_artifact_s3a_path),
    ):
        diagnostics.set("membership", "select_parent_artifacts")
        selected = selector(ids, find_latest_ingestion_objects(
            connection, source="statsbomb", dataset=dataset, max_id=bronze_max_id, **context))
        for artifact in selected:
            diagnostics.set("child HEAD preflight", "verify_bronze_object_metadata",
                            match_id=artifact["match_id"], key=artifact["object_key"])
            path(artifact)
            verify_bronze_object_metadata(client, artifact)
        print(f"{dataset}: {len(selected)}/{len(ids)} metadata verified")
    print(f"Bronze parent SHA verified; matches={len(ids)}. Child HEAD is not a byte-level SHA verification.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_bronze_arguments(parser, children=True)
    args = parser.parse_args(argv)
    diagnostics = PublishDiagnostics()
    try:
        with create_postgres_connection() as connection, closing(create_s3_client()) as client:
            check_bronze(connection, client, context=context_from_args(args), parent_sha256=args.parent_sha256,
                         bronze_max_id=args.bronze_max_id, diagnostics=diagnostics)
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
