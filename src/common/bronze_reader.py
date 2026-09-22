"""Read Bronze bytes and verify them against the PostgreSQL catalog checksum."""

from contextlib import closing
import re

from botocore.client import BaseClient
from botocore.exceptions import ClientError

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


def verify_bronze_object_metadata(client: BaseClient, artifact: dict) -> None:
    """HEAD-only preflight; SHA-256 metadata is not a hash of downloaded bytes."""
    checksum = artifact["sha256"]
    key_match = re.search(r"(?:^|/)sha256=([0-9a-f]{64})/[^/]+$", artifact["object_key"])
    if (
        not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
        or key_match is None or key_match[1] != checksum
    ):
        raise BronzeIntegrityError("Bronze immutable key checksum does not match the catalog.")
    try:
        head = client.head_object(Bucket=artifact["s3_bucket"], Key=artifact["object_key"])
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            raise BronzeIntegrityError("Cataloged Bronze object is missing.") from None
        raise
    if head.get("Metadata", {}).get("sha256") != checksum:
        raise BronzeIntegrityError("Bronze metadata sha256 does not match the catalog.")
