"""Preserve StatsBomb raw versions in S3 and register their PostgreSQL metadata."""

import os
import sys
from pathlib import Path

import psycopg
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

# Support direct execution with `python scripts/ingest_statsbomb_bronze.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.bronze import build_versioned_key
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError, download_bytes
from src.common.postgres import create_postgres_connection, register_ingestion_object
from src.common.s3 import create_s3_client

SOURCES = (
    {
        "source_url": "https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json",
        "dataset": "competitions",
        "base_prefix": "football/bronze/statsbomb/competitions",
        "filename": "competitions.json",
    },
    {
        "source_url": "https://raw.githubusercontent.com/hudl/open-data/master/data/matches/43/106.json",
        "dataset": "world_cup_2022_matches",
        "base_prefix": "football/bronze/statsbomb/matches/competition_id=43/season_id=106",
        "filename": "matches.json",
    },
)


class BronzeIntegrityError(RuntimeError):
    """An immutable key and its expected SHA-256 metadata disagree."""


def verify_object_integrity(existing: dict, key: str, checksum: str) -> None:
    if existing.get("Metadata", {}).get("sha256") != checksum:
        raise BronzeIntegrityError(
            f"Immutable object integrity violation for {key}: "
            "metadata sha256 is missing or mismatched; object was not modified."
        )


def upload_immutable_object(
    client: BaseClient,
    *,
    bucket: str,
    key: str,
    data: bytes,
    checksum: str,
    source_url: str,
    dataset: str,
) -> bool:
    """Create an absent version or verify an existing one; never overwrite it."""
    parts = key.split("/")
    if len(parts) < 3 or parts[-2] != f"sha256={checksum}":
        raise BronzeIntegrityError("Immutable key does not match the source checksum.")

    try:
        existing = client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = error.response.get("Error", {}).get("Code")
        object_missing = code in {"404", "NoSuchKey", "NotFound"} or (
            status == 404 and not code
        )
        if not object_missing:
            raise
    else:
        verify_object_integrity(existing, key, checksum)
        return False

    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="application/json",
            Metadata={
                "source": "statsbomb",
                "layer": "bronze",
                "sha256": checksum,
                "source_url": source_url,
                "dataset": dataset,
            },
            IfNoneMatch="*",
        )
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = error.response.get("Error", {}).get("Code")
        if status != 412 and code != "PreconditionFailed":
            raise
        # Another writer created this version after HEAD; verify, never overwrite.
        existing = client.head_object(Bucket=bucket, Key=key)
        verify_object_integrity(existing, key, checksum)
        return False
    return True


def main() -> int:
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
            for source in SOURCES:
                current_key = source["base_prefix"]
                data = download_bytes(source["source_url"])
                downloaded += 1
                checksum = sha256_bytes(data)
                key = build_versioned_key(source["base_prefix"], source["filename"], checksum)
                current_key = key
                if upload_immutable_object(
                    client,
                    bucket=bucket,
                    key=key,
                    data=data,
                    checksum=checksum,
                    source_url=source["source_url"],
                    dataset=source["dataset"],
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
    except BronzeIntegrityError as error:
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
