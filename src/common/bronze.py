"""Content-addressed object keys for immutable Bronze artifacts."""

import re


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
