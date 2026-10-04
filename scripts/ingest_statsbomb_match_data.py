"""Fan out a cataloged StatsBomb matches artifact into events and lineups."""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

# Support direct execution with `python scripts/ingest_statsbomb_match_data.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze import BronzeIntegrityError, build_versioned_key, put_immutable_object
from src.common.bronze_reader import read_bronze_object, verify_bronze_object_metadata
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError, download_bytes
from src.common.postgres import (
    IngestionObjectNotFoundError,
    create_postgres_connection,
    find_matches_parent,
    find_latest_ingestion_objects,
    register_ingestion_object,
)
from src.common.s3 import create_s3_client
from src.statsbomb.matches import MatchDataError
from src.statsbomb.events import extract_match_id_from_events_url
from src.statsbomb.lineups import extract_match_id_from_lineups_url
from src.statsbomb.context import add_bronze_arguments, context_from_args, matches_context, child_prefix, SourceContextError

SOURCE_BASE_URL = "https://raw.githubusercontent.com/hudl/open-data/master/data"
CHILD_DATASETS = (("events", "match_events"), ("lineups", "match_lineups"))


def validate_child_bytes(data):
    """Validate JSON framing only; keep raw bytes and Silver's DQ semantics."""
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise MatchDataError("Invalid child JSON; nothing published.") from None
    if not isinstance(value, list):
        raise MatchDataError("Child JSON must be an array; nothing published.")


def cataloged_children(connection, context, match_ids):
    """Use the catalog, not a local checkpoint; never reuse a foreign context."""
    existing = {}
    for kind, dataset in CHILD_DATASETS:
        prefix = child_prefix(kind, match_ids[0], **context).rsplit("/match_id=", 1)[0] + "/"
        extract_id = extract_match_id_from_events_url if kind == "events" else extract_match_id_from_lineups_url
        for artifact in find_latest_ingestion_objects(connection, source="statsbomb", dataset=dataset, **context):
            if not artifact["object_key"].startswith(prefix):
                continue  # Historical flat WC rows are not this context's checkpoint.
            match_id = extract_id(artifact["source_url"])
            expected = build_versioned_key(child_prefix(kind, match_id, **context), f"{kind}.json", artifact["sha256"])
            if match_id not in match_ids or artifact["object_key"] != expected:
                raise BronzeIntegrityError("Cataloged child source/path is outside the exact parent identity.")
            existing[artifact["source_url"]] = artifact
    return existing


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("--limit must be an integer > 0")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=positive_int, metavar="N",
        help="ingest events and lineups for only the first N unique matches (writes data)",
    )
    add_bronze_arguments(parser)
    args = parser.parse_args(argv)
    context = context_from_args(args)
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        print("S3 configuration error: S3_BUCKET is required.", file=sys.stderr)
        return 2

    discovered = downloaded = uploaded = unchanged = 0
    registered = already_registered = 0
    current = "parent catalog lookup"
    try:
        with create_postgres_connection() as connection:
            parent = find_matches_parent(connection, **context, sha256=args.parent_sha256)
            client = create_s3_client()
            current = "parent S3 read"
            raw = read_bronze_object(
                client, bucket=parent["s3_bucket"], key=parent["object_key"],
                checksum=parent["sha256"],
            )
            match_ids = matches_context(raw, **context)
            discovered = len(match_ids)
            print(f"Parent bucket: {parent['s3_bucket']}")
            print(f"Parent key: {parent['object_key']}")
            print(f"Parent SHA256: {parent['sha256']}")
            print(f"Discovered matches: {discovered}")
            existing = cataloged_children(connection, context, match_ids)
            if args.limit is not None:
                match_ids = match_ids[:args.limit]

            for match_id in match_ids:
                for kind, dataset in CHILD_DATASETS:
                    current = f"{kind.upper()} match_id={match_id}"
                    source_url = f"{SOURCE_BASE_URL}/{kind}/{match_id}.json"
                    artifact = existing.get(source_url)
                    if artifact is not None:
                        if artifact["s3_bucket"] != bucket:
                            raise BronzeIntegrityError("Cataloged child bucket does not match the target bucket.")
                        verify_bronze_object_metadata(client, artifact)
                        data = read_bronze_object(client, bucket=bucket, key=artifact["object_key"], checksum=artifact["sha256"])
                        if len(data) != artifact["size_bytes"]:
                            raise BronzeIntegrityError("Cataloged child byte size mismatch.")
                        validate_child_bytes(data)
                        unchanged += 1
                        already_registered += 1
                        print(f"{kind.upper()} UNCHANGED: match_id={match_id}")
                        print(f"ALREADY_REGISTERED: {artifact['object_key']}")
                        continue
                    data = download_bytes(source_url)
                    validate_child_bytes(data)
                    downloaded += 1
                    checksum = sha256_bytes(data)
                    key = build_versioned_key(
                        child_prefix(kind, match_id, **context),
                        f"{kind}.json", checksum,
                    )
                    if put_immutable_object(
                        client, bucket=bucket, key=key, data=data, checksum=checksum,
                        metadata={
                            "source": "statsbomb",
                            "layer": "bronze",
                            "dataset": dataset,
                            "match_id": str(match_id),
                            **{name: str(value) for name, value in context.items()},
                            "sha256": checksum,
                            "source_url": source_url,
                        },
                    ):
                        uploaded += 1
                        print(f"{kind.upper()} UPLOADED: match_id={match_id}")
                    else:
                        unchanged += 1
                        print(f"{kind.upper()} UNCHANGED: match_id={match_id}")
                    print(f"Key: {key}")
                    print(f"Bytes: {len(data)}")
                    print(f"SHA256: {checksum}")

                    if register_ingestion_object(
                        connection, source="statsbomb", dataset=dataset,
                        source_url=source_url, s3_bucket=bucket, object_key=key,
                        sha256=checksum, size_bytes=len(data),
                    ):
                        registered += 1
                        print(f"REGISTERED: {key}")
                    else:
                        already_registered += 1
                        print(f"ALREADY_REGISTERED: {key}")
    except (IngestionObjectNotFoundError, BronzeIntegrityError, MatchDataError, DownloadError, SourceContextError) as error:
        print(f"StatsBomb match ingestion failed ({current}): {error}", file=sys.stderr)
        return 1
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "unknown")
        code = error.response.get("Error", {}).get("Code", "unknown")
        print(f"S3 request failed ({current}): HTTP {status}, code {code}.", file=sys.stderr)
        return 1
    except psycopg.Error as error:
        print(
            f"PostgreSQL error ({current}, {type(error).__name__}, "
            f"SQLSTATE {error.sqlstate or 'unknown'}). "
            "Previously saved S3 objects and committed catalog rows were kept.",
            file=sys.stderr,
        )
        return 1
    except ValueError:
        print(
            "Configuration error: check S3_* and POSTGRES_* environment variables "
            "and AWS_CA_BUNDLE.", file=sys.stderr,
        )
        return 2
    except BotoCoreError as error:
        print(
            f"S3 request failed ({current}, {type(error).__name__}); "
            "check connectivity and TLS/CA configuration.", file=sys.stderr,
        )
        return 1
    except Exception as error:
        # Avoid exception details that might contain credentials or source data.
        print(
            f"StatsBomb match ingestion failed ({current}, {type(error).__name__}).",
            file=sys.stderr,
        )
        return 1

    print("StatsBomb match fan-out ingestion complete")
    print(f"Matches discovered: {discovered}")
    print(f"Objects downloaded: {downloaded}")
    print(f"Objects uploaded: {uploaded}")
    print(f"Objects unchanged: {unchanged}")
    print(f"Objects registered: {registered}")
    print(f"Objects already registered: {already_registered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
