"""Upload a local sample to S3 Bronze and verify its bytes with SHA-256."""

import hashlib
import os
import sys
from contextlib import closing
from pathlib import Path

from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Support direct execution with `python scripts/test_s3_roundtrip.py`.
sys.path.insert(0, str(PROJECT_ROOT))
from src.common.s3 import create_s3_client

SAMPLE_FILE = PROJECT_ROOT / "data" / "samples" / "sample_match.json"
OBJECT_KEY = "football/bronze/_tests/s3_roundtrip/sample_match.json"


def main() -> int:
    try:
        original_bytes = SAMPLE_FILE.read_bytes()
    except OSError:
        print(
            "S3 roundtrip failed: cannot read data/samples/sample_match.json.",
            file=sys.stderr,
        )
        return 1

    original_hash = hashlib.sha256(original_bytes).hexdigest()
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        print("S3 configuration error: S3_BUCKET is required.", file=sys.stderr)
        return 2

    try:
        client = create_s3_client()
        client.put_object(
            Bucket=bucket,
            Key=OBJECT_KEY,
            Body=original_bytes,
            ContentType="application/json",
            Metadata={"source": "local-sample", "layer": "bronze"},
        )
        response = client.get_object(Bucket=bucket, Key=OBJECT_KEY)
        with closing(response["Body"]) as body:
            downloaded_bytes = body.read()
    except ValueError:
        print(
            "S3 configuration error: check S3_ENDPOINT, S3_REGION, "
            "S3_ACCESS_KEY and S3_SECRET_KEY environment variables.",
            file=sys.stderr,
        )
        return 2
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "unknown")
        print(
            f"S3 roundtrip failed (HTTP {status}): check the bucket, region "
            "and permissions to write and read the test object.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        # Do not print exception details that might contain credentials.
        print(
            f"S3 roundtrip failed ({type(error).__name__}): "
            "check connectivity, TLS certificates and S3 configuration.",
            file=sys.stderr,
        )
        return 1

    downloaded_hash = hashlib.sha256(downloaded_bytes).hexdigest()
    if original_hash != downloaded_hash:
        print(
            "S3 roundtrip failed: SHA-256 mismatch between source and downloaded bytes.",
            file=sys.stderr,
        )
        return 1

    print("S3 roundtrip successful")
    print(f"Bucket: {bucket}")
    print(f"Key: {OBJECT_KEY}")
    print(f"Bytes: {len(original_bytes)}")
    print(f"SHA256: {original_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
