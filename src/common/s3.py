"""Shared S3 client configured exclusively through environment variables."""

import os

import boto3
from botocore.client import BaseClient
from botocore.config import Config


def create_s3_client() -> BaseClient:
    """Use SigV4, virtual addressing and the configured AWS CA bundle."""
    names = ("S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY", "S3_SECRET_KEY")
    settings = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=settings["S3_ENDPOINT"],
        region_name=settings["S3_REGION"],
        aws_access_key_id=settings["S3_ACCESS_KEY"],
        aws_secret_access_key=settings["S3_SECRET_KEY"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
        ),
    )
