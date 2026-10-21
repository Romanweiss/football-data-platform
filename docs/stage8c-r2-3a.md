# Stage 8C-R2.3-A: synthetic encrypted S3 archive format

This document records stage A evidence. For the combined A/B/C/D implementation,
current status and publication checks, see the [publication audit](stage8c-r2-3-publication.md).

Implemented scope: **local synthetic archive format and local test restore**.
Stage 8C remains **PARTIAL**. Independent backup of real Selectel bytes, remote S3
restore, machine-loss recovery and secret escrow are still **NOT VERIFIED**.
No S3 client, Docker client, environment-file reader or credential discovery is
used by this module. No production CLI commands, services or dependencies change.

## Public Python interface

`src.recovery.s3_archive` provides:

- `S3ArchiveWriter(parent, master_key, expected_objects=N, chunk_size=...)`: creates
  one exclusive new session below an existing directory. Use a context manager.
- `writer.add_object(key, binary_stream, size_bytes=N, metadata={...})`: bounded
  reads; exact byte length is required. Accepts binary and empty objects.
- `writer.seal()`: verifies all stored artifacts before publishing the manifest.
- `verify_archive(directory, master_key)`: authenticates envelope/index, validates
  the exact artifact set, decrypts every chunk and checks chunk/object SHA-256.
  Returns an `S3Archive` with explicit access to its sensitive decrypted `index`.
- `inspect_archive(directory, master_key)`: performs verification and returns only
  the session ID, profile, counts, sizes and explicit false live-backup flags.
- `restore_synthetic(directory, master_key, destination)`: verifies first, then
  writes opaque object files into a **new child of the system temp directory**.
  Existing destinations, including empty directories, are refused.

Minimal executable example, using synthetic objects and an ephemeral key only:

```python
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import os

from src.recovery.s3_archive import (
    S3ArchiveWriter, inspect_archive, restore_synthetic, verify_archive,
)

with TemporaryDirectory(prefix="football-synthetic-") as tmp:
    parent = Path(tmp)
    master_key = os.urandom(32)  # Memory only; not a runtime credential.
    with S3ArchiveWriter(parent, master_key, expected_objects=3) as writer:
        raw = b'{"source":"synthetic"}\n'
        writer.add_object("football/bronze/sample.json", BytesIO(raw),
                          size_bytes=len(raw), metadata={"ContentType": "application/json"})
        writer.add_object("binary/fixture", BytesIO(b"\x00\xff\x01"), size_bytes=3)
        writer.add_object("empty/", BytesIO(b""), size_bytes=0)
        writer.seal()
    archive = verify_archive(writer.directory, master_key)
    print(inspect_archive(writer.directory, master_key))  # No keys/metadata/payload.
    restore_synthetic(writer.directory, master_key, parent / "restored")
```

The restore writes `object-00000001.bin`, etc., and a plaintext test `index.json`
mapping each file to its original key, size, SHA-256 and metadata. Metadata is a
flat string-to-string mapping, preserved exactly. This is a local test representation,
not a filesystem interpretation of S3 keys or an actual S3 restore.

Keys containing Unicode, separators, `..`, Windows reserved names or case-folding
collisions remain index data. They can never choose a local filename. Artifact
references, session paths and restore destinations reject traversal; existing
symlinks, Windows reparse points and hardlinked artifact files are refused.

## Format and authentication chain

```text
<parent>/<UTC timestamp>-<32 UUID hex digits>/
    session.json
    index.json.enc
    object-00000001-chunk-00000001.enc
    object-00000001-chunk-00000002.enc
    ...
    manifest.json                     # Written last, only after verification.
```

An aborted session may contain `aborted.json`. A missing, incomplete or invalid
manifest never represents a successful sealed backup. Unexpected/missing artifacts
are rejected, not silently ignored.

The core in `session.json`, also authenticated inside the final manifest:

```json
{
  "profile": "s3-current-objects",
  "schema_version": 2,
  "scope": "synthetic-local",
  "session_id": "<UTC>-<32 hex digits>",
  "salt": "<32 random bytes encoded as 64 hex digits>",
  "cipher": "AES-256-GCM",
  "kdf": "HKDF-SHA256",
  "chunk_size": 67108864,
  "expected_objects": 3
}
```

`manifest.json` adds `state=SEALED`, `index_size`, `index_sha256` (ciphertext) and
`authentication`: HMAC-SHA256 over the canonical unsigned envelope. The canonical
encoding reuses `src.recovery.runtime.encoded`: sorted keys, UTF-8, compact separators.
Duplicate JSON fields, NaN, unsupported profile/version/crypto suite and invalid
schema/limits are refused.

Encrypted index schema:

```text
objects[]:
    object_id, key, size_bytes, sha256, metadata
    chunks[]:
        file, size_bytes, sha256, ciphertext_size, ciphertext_sha256
```

The HMAC binds the envelope and encrypted-index digest. AES-GCM authenticates the
index. The authenticated index binds each chunk's name, size and ciphertext/plaintext
SHA-256, original key and full-object SHA-256. Chunk AAD additionally binds the core,
role, object ordinal, original key, object size and chunk ordinal. Corruption and
substitution fail before a restore destination is created. Restore decrypts and
checks chunks again, then re-reads the local output files to verify full-object hashes.

## Cryptography and memory bounds

Reuse the pinned `cryptography==50.0.2` dependency, `AESGCM`, shared exclusive file
creation, private-directory permissions, hashing and safe `RecoveryError` codes.
No custom cipher or KDF is introduced. Database `Archive` is not used directly:
its per-artifact whole-buffer API and fixed database manifest are a different profile.

For each session, HKDF-SHA256 derives **96 bytes** from the caller's 32-byte master
key and a fresh **32-byte random salt**. Fixed HKDF info:
`football-data-platform/s3-current-objects/v2`. Split the result into independent
32-byte data-encryption, index-encryption and envelope-HMAC subkeys.

Data nonces are 96-bit values: four zero bytes plus an unsigned 64-bit big-endian
counter, starting at zero, increasing for every data chunk in a session. The index
uses four `ff` bytes plus eight zero bytes, with its separate index subkey. Sessions
never resume; retries create a fresh UUID and random HKDF salt. Never reuse the
data nonce counter with the same derived key. Concurrent use of one writer is unsupported.

Each encrypted file contains eight-byte magic `FDPS302\0`, a 12-byte nonce and the
AES-GCM ciphertext with its 16-byte authentication tag: **36 bytes overhead**.

- Default/max chunk plaintext: **64 MiB**, safely below the database artifact cap
  of 512 MiB, including encryption overhead.
- Payload memory is **O(chunk size)**, including crypto/copy buffers, not O(object
  size). Reads always specify a positive bounded length; short reads are supported.
- Object/index descriptors stay in memory. Encrypted-index plaintext is capped at
  **8 MiB**, metadata at **64 KiB per object**, keys at **1024 UTF-8 bytes**.
- Limits: **10,000 objects**, **20,000 data chunks**. Limit failures leave the
  session unsealed. No compression, deduplication or cross-session dependencies.
- Empty objects have one authenticated zero-byte plaintext chunk and the SHA-256
  of empty bytes. An empty archive is also supported.

Master/subkeys are never written by this API. The caller owns key recovery; this
stage does not add a vault integration or read existing recovery keys. Python/OS
memory is trusted; secure memory erasure and protection against a compromised
host are not claimed.

## Failure and compatibility behavior

All artifacts use exclusive creation. Existing files cannot be overwritten.
Sealing requires the declared object count, exact artifact set and successful
read/decrypt/hash verification of the index and all chunks on disk. An early EOF,
extra bytes, stream error, corruption, missing chunk or write failure aborts the
session. Unsealed context-manager exit also aborts. Partial evidence is retained;
there is no automatic deletion or resume. Reader verification is mandatory after
copying an archive or recovering from a power loss; a filename/status alone is not
proof of durable storage. Hardware power-loss durability is not tested here.

Local synthetic restore rejects existing targets and creates numeric files with
exclusive creation. It never rolls back by deleting a directory. Failed restores
may leave partial plaintext fixtures in their new temp target; another restore
requires a fresh destination. Tests own and dispose their temporary directories.
Filesystem guards assume no malicious concurrent modification by a local administrator.

Database schema version 1, `src/recovery/archive.py`, `operations.py`, `runtime.py`,
`s3_inventory.py` and `scripts/backup.py` remain unchanged. Existing database
manifests keep their fixed components, key paths and validation rules. A separate
compatibility fixture loads an old-style database archive alongside the new tests.

## Verification and next boundary

Local verification completed on 2026-10-21:

| Environment / check | Result |
| --- | --- |
| Python 3.10.12, network-disabled CI container | 587 root, 30 application, 16 CI tests passed |
| Python 3.12.14, network-disabled CI container | 587 root, 30 application, 16 CI tests passed |
| New format suite on Windows | 32 passed |
| Existing database recovery suite in CI container | 30 passed |
| Ruff and compileall on both matrix versions | PASS |
| Repository contracts, new-file secret signatures and whitespace | PASS |

The 32 format tests include short/bounded stream reads, empty/binary/Unicode data,
metadata, filename collisions, envelope/index/chunk tampering, GCM/AAD validation,
missing/truncated files, wrong keys, partial manifest writes, session lifecycle,
hardlinks, traversal, destination refusal and a synthetic database v1 compatibility
fixture. These are local results, not a new remote GitHub run or live S3 acceptance.

Offline checks, using existing dependencies:

```powershell
# The crypto-only recovery venv is sufficient for this new format suite.
.\.venv\recovery\Scripts\python.exe ci/run_unittest.py discover -s tests -p 'test_s3_archive.py'

# The full suite also imports boto3/Django/etc.; use the existing CI requirements.
docker build -f ci/Dockerfile -t football-ci-checks:r23a .
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-ci-checks:r23a python ci/run_unittest.py discover -s tests -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-ci-checks:r23a python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
# Repository safety check needs host Git and requirements/ci.txt dependencies.
python ci/check_repository.py
git diff --check
```

The regular root unittest discovery also includes the new suite. CI containers can
run both Python 3.10.12 and 3.12.14 with `--network none` and a read-only source bind.

Next proposed R2.3-B work: synthetic object-store adapter, inventory-before/after
fences, catalog/build lineage fixtures, provider ETag mismatch fixtures, metadata
mapping and destination guards. Real source reads, independent media placement,
remote writes/restores and live credentials remain a separately authorized live
stage. None are implemented or claimed by this archive-format task.
