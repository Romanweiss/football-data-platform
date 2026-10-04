"""Preserve StatsBomb raw versions in S3 and register their PostgreSQL metadata."""

import argparse
import os
import sys
from pathlib import Path

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

# Support direct execution with `python scripts/ingest_statsbomb_bronze.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze import BronzeIntegrityError, build_versioned_key, put_immutable_object
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError, download_bytes
from src.common.postgres import create_postgres_connection, register_ingestion_object
from src.common.s3 import create_s3_client

from src.statsbomb.context import (add_context_arguments, context_from_args, CATALOG_URL,
                                   catalog_context, matches_context, matches_url, matches_prefix, SourceContextError)


def sources(context):
    return (
        {"source_url": CATALOG_URL, "dataset": "competitions",
         "base_prefix": "football/bronze/statsbomb/competitions", "filename": "competitions.json"},
        {"source_url": matches_url(**context), "dataset": "matches",
         "base_prefix": matches_prefix(**context), "filename": "matches.json"},
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_context_arguments(parser)
    args = parser.parse_args(argv)
    context = context_from_args(args)
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        print("S3 configuration error: S3_BUCKET is required.", file=sys.stderr)
        return 2

    downloaded = uploaded = unchanged = 0
    registered = already_registered = 0
    current_key = "(client initialization)"
    try:
        client = create_s3_client()
        with create_postgres_connection() as connection:
            for source in sources(context):
                current_key = source["base_prefix"]
                data = download_bytes(source["source_url"])
                downloaded += 1
                if source["dataset"] == "competitions":
                    catalog_context(data, **context)
                else:
                    matches_context(data, **context)
                checksum = sha256_bytes(data)
                key = build_versioned_key(source["base_prefix"], source["filename"], checksum)
                current_key = key
                if put_immutable_object(
                    client,
                    bucket=bucket,
                    key=key,
                    data=data,
                    checksum=checksum,
                    metadata={
                        "source": "statsbomb",
                        "layer": "bronze",
                        "dataset": source["dataset"],
                        "sha256": checksum,
                        "source_url": source["source_url"],
                    },
                ):
                    uploaded += 1
                    print(f"UPLOADED: {key}")
                else:
                    unchanged += 1
                    print(f"UNCHANGED: {key}")
                print(f"Bytes: {len(data)}")
                print(f"SHA256: {checksum}")

                if register_ingestion_object(
                    connection,
                    source="statsbomb",
                    dataset=source["dataset"],
                    source_url=source["source_url"],
                    s3_bucket=bucket,
                    object_key=key,
                    sha256=checksum,
                    size_bytes=len(data),
                ):
                    registered += 1
                    print(f"REGISTERED: {key}")
                else:
                    already_registered += 1
                    print(f"ALREADY_REGISTERED: {key}")
    except (BronzeIntegrityError, SourceContextError) as error:
        print(f"StatsBomb ingestion failed: {error}", file=sys.stderr)
        return 1
    except DownloadError as error:
        print(f"StatsBomb ingestion failed: {error}", file=sys.stderr)
        return 1
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "unknown")
        code = error.response.get("Error", {}).get("Code", "unknown")
        print(
            f"S3 request failed for {current_key}: HTTP {status}, code {code}.",
            file=sys.stderr,
        )
        return 1
    except ValueError:
        print(
            "Configuration error: check S3_* and POSTGRES_* environment variables "
            "(including POSTGRES_PORT), and AWS_CA_BUNDLE.",
            file=sys.stderr,
        )
        return 2
    except psycopg.Error as error:
        print(
            f"PostgreSQL error for {current_key} ({type(error).__name__}, "
            f"SQLSTATE {error.sqlstate or 'unknown'}). S3 objects were kept; "
            "check the connection and apply the catalog migration before retrying.",
            file=sys.stderr,
        )
        return 1
    except BotoCoreError as error:
        print(
            f"S3 request failed for {current_key} ({type(error).__name__}); "
            "check connectivity and TLS/CA configuration.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        # Avoid printing raw exception details that might contain credentials.
        print(
            f"StatsBomb ingestion failed for {current_key} ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1

    print("StatsBomb Bronze ingestion complete")
    print(f"Downloaded: {downloaded}")
    print(f"Uploaded: {uploaded}")
    print(f"Unchanged: {unchanged}")
    print(f"Registered: {registered}")
    print(f"Already registered: {already_registered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
