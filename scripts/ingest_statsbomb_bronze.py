"""Download two StatsBomb source files and preserve their raw bytes in S3 Bronze."""

import os
import sys
from pathlib import Path

from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

# Support direct execution with `python scripts/ingest_statsbomb_bronze.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.checksum import sha256_bytes
from src.common.http import DownloadError, download_bytes
from src.common.s3 import create_s3_client

SOURCES = (
    (
        "https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json",
        "football/bronze/statsbomb/competitions/competitions.json",
    ),
    (
        "https://raw.githubusercontent.com/hudl/open-data/master/data/matches/43/106.json",
        "football/bronze/statsbomb/matches/competition_id=43/season_id=106/matches.json",
    ),
)


def upload_if_changed(
    client: BaseClient,
    *,
    bucket: str,
    key: str,
    data: bytes,
    checksum: str,
    source_url: str,
) -> bool:
    """Upload raw bytes if absent or changed; return whether an upload occurred."""
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
        if existing.get("Metadata", {}).get("sha256") == checksum:
            return False

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
        },
    )
    return True


def main() -> int:
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        print("S3 configuration error: S3_BUCKET is required.", file=sys.stderr)
        return 2

    downloaded = uploaded = unchanged = 0
    current_key = "(client initialization)"
    try:
        client = create_s3_client()
        for source_url, key in SOURCES:
            current_key = key
            data = download_bytes(source_url)
            downloaded += 1
            checksum = sha256_bytes(data)
            if upload_if_changed(
                client,
                bucket=bucket,
                key=key,
                data=data,
                checksum=checksum,
                source_url=source_url,
            ):
                uploaded += 1
                print(f"UPLOADED: {key}")
            else:
                unchanged += 1
                print(f"UNCHANGED: {key}")
            print(f"Bytes: {len(data)}")
            print(f"SHA256: {checksum}")
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
            "S3 configuration error: check S3_ENDPOINT, S3_REGION, "
            "S3_ACCESS_KEY, S3_SECRET_KEY and AWS_CA_BUNDLE.",
            file=sys.stderr,
        )
        return 2
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
