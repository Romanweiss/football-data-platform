"""Checksums of original source bytes."""

import hashlib


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 hexadecimal digest without changing data."""
    return hashlib.sha256(data).hexdigest()
