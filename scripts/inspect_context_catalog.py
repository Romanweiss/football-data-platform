"""SELECT-only context inventory for recording immutable runbook inputs."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.postgres import create_postgres_connection
from src.statsbomb.context import add_context_arguments, context_from_args, matches_url


def inspect_catalog(connection, context):
    url = matches_url(**context)
    result = dict(context)
    with connection.cursor() as cursor:
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM metadata.ingestion_objects")
        result["bronze_max_id"] = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id, sha256, size_bytes FROM metadata.ingestion_objects "
            "WHERE source = %s AND source_url IN (%s, %s) ORDER BY id",
            ("statsbomb", url, url.replace("/hudl/", "/statsbomb/")),
        )
        result["parents"] = [dict(zip(("id", "sha256", "size_bytes"), row)) for row in cursor.fetchall()]
        for layer in ("silver", "gold"):
            # Table identifiers come only from this fixed internal allowlist.
            cursor.execute(
                f"SELECT dataset, transform_version, build_id, row_count, file_count FROM metadata.{layer}_builds "
                "WHERE competition_id = %s AND season_id = %s ORDER BY dataset, build_id",
                (context["competition_id"], context["season_id"]),
            )
            result[layer] = [dict(zip(("dataset", "transform_version", "build_id", "row_count", "file_count"), row))
                             for row in cursor.fetchall()]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_context_arguments(parser)
    args = parser.parse_args(argv)
    try:
        with create_postgres_connection() as connection:
            print(json.dumps(inspect_catalog(connection, context_from_args(args)), indent=2))
        return 0
    except Exception as error:
        print(f"Catalog inspection failed: exception={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
