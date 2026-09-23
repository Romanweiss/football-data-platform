"""Strict S3A URI construction for application-controlled object keys."""

import os
import re


def s3a_uri(bucket: str, key: str) -> str:
    """Build a URI without userinfo, traversal, URI escapes or ambiguous slashes.

    Accept a deliberately restricted key alphabet; a single trailing slash is
    allowed for dataset prefixes. Inputs are validated, never normalized.
    """
    if (
        not isinstance(bucket, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
        or ".." in bucket or ".-" in bucket or "-." in bucket
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", bucket)
    ):
        raise ValueError("Invalid S3 bucket name.")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_./=-]+", key):
        raise ValueError("Invalid S3 object key.")
    parts = key.removesuffix("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("S3 object key must be relative and contain no empty/traversal segments.")
    return f"s3a://{bucket}/{key}"


def selectel_virtual_url(key: str) -> str:
    """Strict HTTPS vHosted URL. No credentials, arbitrary hosts, or user globs."""
    endpoint = os.environ.get("S3_ENDPOINT", "")
    bucket = os.environ.get("S3_BUCKET", "")
    if not re.fullmatch(r"https://s3\.[a-z0-9]+(?:-[a-z0-9]+)*\.storage\.selcloud\.ru", endpoint):
        raise ValueError("S3_ENDPOINT must be a generic Selectel HTTPS endpoint without a path.")
    s3a_uri(bucket, key)
    # A dotted bucket would require a multi-label wildcard certificate.
    if "." in bucket:
        raise ValueError("Virtual-hosted HTTPS requires a bucket without dots.")
    return f"https://{bucket}.{endpoint.removeprefix('https://')}/{key}"
