"""Safely verify read-only access to the configured Selectel S3 bucket."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError

# Support direct execution with `python scripts/check_s3.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.s3 import create_s3_client


REQUIRED_ENVIRONMENT_VARIABLES = (
    "S3_ENDPOINT",
    "S3_REGION",
    "S3_BUCKET",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)


def read_settings() -> dict[str, str]:
    """Read S3 settings from environment variables and reject missing values."""
    settings = {
        variable: os.environ.get(variable, "").strip()
        for variable in REQUIRED_ENVIRONMENT_VARIABLES
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Missing required environment variables: {names}")
    return settings


def main() -> int:
    try:
        settings = read_settings()
    except ValueError as error:
        print(f"S3 configuration error: {error}", file=sys.stderr)
        return 2

    bucket = settings["S3_BUCKET"]
    endpoint = settings["S3_ENDPOINT"]

    try:
        client = create_s3_client()
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        response = error.response
        error_details = response.get("Error", {})
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode", "unknown")
        code = error_details.get("Code", "unknown")
        message = error_details.get("Message", "request rejected")
        print(
            f"S3 connection failed for bucket '{bucket}' "
            f"(HTTP {status}, code {code}): {message}",
            file=sys.stderr,
        )
        return 1
    except (BotoCoreError, ParamValidationError) as error:
        print(
            f"S3 connection failed for bucket '{bucket}' at '{endpoint}': "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:  # Keep credentials out of unexpected error details.
        print(
            f"S3 connection failed for bucket '{bucket}': unexpected "
            f"{type(error).__name__}; verify the endpoint, region and credentials",
            file=sys.stderr,
        )
        return 1

    print("S3 connection successful")
    print(f"Bucket: {bucket}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
