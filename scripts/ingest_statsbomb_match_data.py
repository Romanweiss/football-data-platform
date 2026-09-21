"""Fan out a cataloged StatsBomb matches artifact into events and lineups."""

import argparse
import os
import sys
from pathlib import Path

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

# Support direct execution with `python scripts/ingest_statsbomb_match_data.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze import BronzeIntegrityError, build_versioned_key, put_immutable_object
from src.common.bronze_reader import read_bronze_object
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError, download_bytes
from src.common.postgres import (
    IngestionObjectNotFoundError,
    create_postgres_connection,
    find_latest_ingestion_object,
    register_ingestion_object,
)
from src.common.s3 import create_s3_client
from src.statsbomb.matches import MatchDataError, extract_match_ids

SOURCE_BASE_URL = "https://raw.githubusercontent.com/hudl/open-data/master/data"
CHILD_DATASETS = (("events", "match_events"), ("lineups", "match_lineups"))


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
    args = parser.parse_args(argv)
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        print("S3 configuration error: S3_BUCKET is required.", file=sys.stderr)
        return 2

    discovered = downloaded = uploaded = unchanged = 0
    registered = already_registered = 0
    current = "parent catalog lookup"
    try:
        with create_postgres_connection() as connection:
            parent = find_latest_ingestion_object(
                connection, source="statsbomb", dataset="world_cup_2022_matches"
            )
            client = create_s3_client()
            current = "parent S3 read"
            raw = read_bronze_object(
                client, bucket=parent["s3_bucket"], key=parent["object_key"],
                checksum=parent["sha256"],
            )
            match_ids = extract_match_ids(raw)
            discovered = len(match_ids)
            print(f"Parent bucket: {parent['s3_bucket']}")
            print(f"Parent key: {parent['object_key']}")
            print(f"Parent SHA256: {parent['sha256']}")
            print(f"Discovered matches: {discovered}")
            if args.limit is not None:
                match_ids = match_ids[:args.limit]

            for match_id in match_ids:
                for kind, dataset in CHILD_DATASETS:
                    current = f"{kind.upper()} match_id={match_id}"
                    source_url = f"{SOURCE_BASE_URL}/{kind}/{match_id}.json"
                    data = download_bytes(source_url)
                    downloaded += 1
                    checksum = sha256_bytes(data)
                    key = build_versioned_key(
                        f"football/bronze/statsbomb/{kind}/match_id={match_id}",
                        f"{kind}.json", checksum,
                    )
                    if put_immutable_object(
                        client, bucket=bucket, key=key, data=data, checksum=checksum,
                        metadata={
                            "source": "statsbomb",
                            "layer": "bronze",
                            "dataset": dataset,
                            "match_id": str(match_id),
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
    except (IngestionObjectNotFoundError, BronzeIntegrityError, MatchDataError, DownloadError) as error:
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
