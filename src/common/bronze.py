"""Content-addressed object keys for immutable Bronze artifacts."""

import re

from botocore.client import BaseClient
from botocore.exceptions import ClientError


class BronzeIntegrityError(RuntimeError):
    """A Bronze artifact does not match its expected SHA-256."""


def build_versioned_key(base_prefix: str, filename: str, checksum: str) -> str:
    """Build a normalized key using the full lowercase SHA-256 digest."""
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("checksum must contain exactly 64 lowercase hex characters")

    prefix = "/".join(part.strip() for part in base_prefix.split("/") if part.strip())
    name = filename.strip().strip("/").strip()
    if not prefix:
        raise ValueError("base_prefix must not be empty")
    if not name:
        raise ValueError("filename must not be empty")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError("filename must be a single file name")

    return f"{prefix}/sha256={checksum}/{name}"


def verify_object_integrity(existing: dict, key: str, checksum: str) -> None:
    if existing.get("Metadata", {}).get("sha256") != checksum:
        raise BronzeIntegrityError(
            f"Immutable object integrity violation for {key}: "
            "metadata sha256 is missing or mismatched; object was not modified."
        )


def put_immutable_object(
    client: BaseClient,
    *,
    bucket: str,
    key: str,
    data: bytes,
    checksum: str,
    metadata: dict[str, str],
    content_type: str = "application/json",
) -> bool:
    """Create an absent version or verify an existing one; never overwrite it."""
    parts = key.split("/")
    if len(parts) < 3 or parts[-2] != f"sha256={checksum}":
        raise BronzeIntegrityError("Immutable key does not match the source checksum.")
    if metadata.get("sha256") != checksum:
        raise BronzeIntegrityError("Upload metadata sha256 does not match the source checksum.")

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
            ContentType=content_type,
            Metadata=metadata,
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
