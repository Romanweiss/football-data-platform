"""Read Bronze bytes and verify them against the PostgreSQL catalog checksum."""

from contextlib import closing

from botocore.client import BaseClient

from src.common.bronze import BronzeIntegrityError
from src.common.checksum import sha256_bytes


def read_bronze_object(
    client: BaseClient, *, bucket: str, key: str, checksum: str
) -> bytes:
    """Read and close StreamingBody before returning checksum-verified raw bytes."""
    response = client.get_object(Bucket=bucket, Key=key)
    with closing(response["Body"]) as body:
        raw = body.read()
    if sha256_bytes(raw) != checksum:
        raise BronzeIntegrityError(
            f"Bronze object integrity violation for {key}: "
            "downloaded SHA-256 does not match the catalog checksum."
        )
    return raw
