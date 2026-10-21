# Stage 8C-R2.3-B: synthetic storage, consistency and lineage

This document records stage B evidence. For the combined A/B/C/D implementation,
current status and publication checks, see the [publication audit](stage8c-r2-3-publication.md).

Implemented: an offline synthetic storage adapter and backup/restore workflow over
the [R2.3-A encrypted archive profile](stage8c-r2-3a.md). Stage 8C remains **PARTIAL**.
Real Selectel reads/writes, database access, independent storage placement and remote
S3 restore are **not implemented or verified**. No production CLI or service changes.

## Storage abstraction

`src/recovery/s3_storage.py` defines detached DTOs and protocols:

- `StorageIdentity(authority, bucket, resource_id, aliases, mode)`: a trusted adapter
  must identify the actual bucket independently of endpoint spelling. Resource IDs
  and alias tokens must be globally unambiguous. `mode=synthetic` is required today.
- `ListEntry(key, size_bytes, last_modified, etag)` and
  `Page(objects, key_count, is_truncated, next_token)` describe full-root listing.
- `Head(size_bytes, last_modified, etag, metadata)`: a detached string-valued metadata
  map, suitable for the encrypted index. Normalize timestamps consistently across
  APIs in the adapter; do not normalize or equate LIST and HEAD ETags.
- `ReadStorage`: `capabilities()`, `list_page(token)`, `head_object(key)`,
  `get_object(key, expected=Head)`. GET returns a closable streaming `ReadResult`.
  Conditional GET must bind to the HEAD observation and fail on state changes.
- `RestoreStorage`: additionally `put_if_absent(key, chunks, size_bytes, metadata)`.
  There is no unconditional PUT or delete operation in the protocol.
- `MetadataSource.snapshot()`: returns `catalog` plus `serving`, without performing
  writes. The catalog contains ingestion_objects, silver_builds, gold_builds,
  clickhouse_loads and clickhouse_gold_loads. Serving DTOs provide groups of
  competition/season/build ID/row count and duplicate-key counts by table.

`SyntheticStorage` is an in-memory fixture with independent LIST/HEAD ETags, opaque
page tokens, conditional GET and lock-protected conditional publication. Its bytes
are synthetic; each destination payload is capped at 8 MiB. It is not a real-world
streaming destination implementation. `StaticMetadata` returns detached copies.

Storage metadata is retained only in encrypted records/evidence. Public workflow
results contain identifiers, counts and digests, not raw provider exceptions,
metadata values or payloads. General provider/IO exceptions become a fixed safe
error. No boto3 adapter or credential discovery is included.

## Consistency fence and workflow

`backup_synthetic(storage, metadata_source, parent, master_key, chunk_size=...)`:

1. Check synthetic identity and required LIST/HEAD/GET/conditional-GET capabilities.
2. Enumerate all pages from the bucket root and HEAD every key.
3. Read the metadata baseline and require registered keys/manifests/_SUCCESS.
4. Stream GET into `S3ArchiveWriter`, computing full-byte hashes. Cache only bounded
   registered build manifests and matches-parent JSON needed for lineage validation.
5. `writer.verify_pending()` re-reads and verifies encrypted source chunks on disk.
6. Repeat full LIST/HEAD, require exact observation equality and stable source identity.
7. Re-read metadata and require its digest to remain unchanged; validate lineage.
8. Append encrypted workflow evidence; seal only after all checks. `seal()` also
   re-verifies the complete on-disk archive including the evidence object.

The inventory records keys, sizes, LastModified, LIST ETag, HEAD ETag and metadata.
LIST sizes/timestamps must agree with HEAD; each API's ETag must remain stable across
passes, but LIST ETag need not equal HEAD/GET ETag. SHA-256 is computed from bytes.

Pagination refuses duplicate keys, repeated tokens, truncated pages without a
continuation token/progress, non-terminal tokens on terminal pages, bad key counts,
invalid observations and provider errors. Catalog coverage catches consistently
missing **known** objects. A provider that consistently omits an unknown unregistered
object from a plausible terminal response cannot be exposed by listing alone.

New, deleted or changed objects/metadata/ETags, truncated GET, inconsistent GET
headers, metadata drift, lineage errors and encrypted-write/readback failures stop
sealing. A failed writer remains unsealed/aborted. No success is returned for partial
data; retry requires a new session. There is no automatic cleanup or resume.

This is **not an atomic S3/PostgreSQL/ClickHouse snapshot**. Transient objects that
appear and disappear between observations and adversarial ABA changes may remain
unobserved. The fence has a finite time interval; it cannot prevent writes after
its final observation. Live acceptance needs a reviewed quiet collection window
or stronger independently verified history/change controls.

## Lineage validation

`src/recovery/s3_lineage.py` provides pure `validate_baseline`, `validate_lineage`
and `snapshot_digest`; no database connections are opened. Row ordering in catalog
tables and serving groups is normalized, while nested ordered values stay ordered.

Checks include:

- Registered Bronze key/size/SHA metadata against catalog and actual byte SHA-256.
- Strict manifest JSON, manifest byte checksum/build metadata and catalog fields.
- Existing Silver/Gold deterministic build-ID and input-fingerprint functions,
  schema hashes, source, dataset, competition/season and canonical build prefixes.
- Exact registered build file sets, positive part sizes and manifest LIST ETags.
- Silver references to exact Bronze source URL/key/SHA; matches-parent URL/context
  and match IDs using the existing pure StatsBomb context parser.
- Gold references to exact registered Silver identities and matching selected
  match memberships. Historical Silver builds are not globally required to share
  the same selection; compatibility is checked for each Gold build's selected inputs.
- Published/loaded/serving reconciliation via the existing pure Stage 8C validator,
  including row counts, receipt fields, duplicate keys and target table identity.
- Duplicate catalog/build/load identities and missing required objects are refused.

Valid published-but-not-yet-loaded builds may be archived: every load must resolve
to a publication and serving group, not every publication must already be loaded.
The report exposes both counts. No fixture assumes exactly 22 builds or 315 objects.

Classifications are `registered`, `test` (the explicit Bronze test prefix), `legacy`
(unversioned StatsBomb Bronze JSON) and `unregistered` (possible orphan/other).
Every listed key is retained. Classification does not authorize deletion or prove
that an unregistered object is disposable.

Fixtures use real manifest contracts but fake JSON/Parquet payloads and tiny row
counts. This stage does not parse Parquet or rerun transformations/DQ to prove that
its rows match serving rows. That remains a separate validation boundary.

## Authenticated evidence without changing archive format A

The archive schema/cipher/reader from A remain compatible. Two small APIs are added:
`S3ArchiveWriter.verify_pending()` and `S3Archive.iter_object_chunks(object_id)`.
The iterator is bounded and checks hashes/GCM; consumers must exhaust it.

The workflow appends exactly one control object with the generated key:
`__recovery_evidence__/<archive-session-id>/snapshot.json`.
It contains source identity, both inventories, the detached metadata baseline,
its digest, lineage result and a hash binding every source object's index record.
It is encrypted/authenticated by the existing profile, not an unauthenticated sidecar.
A collision with a source key fails; nothing is silently excluded.

Consequently **N source objects -> N+1 archive objects**. For example, the R2.1
315-object baseline would occupy 316 archive records; it is not copied by this stage.
The workflow restore writes only the N original keys; its own control record is
verified and excluded explicitly. Source objects whose keys happen to use another
recovery-like prefix are still ordinary source objects. The format-only local
restore from A remains unchanged and restores all archive records.

All A bounds remain: 64 MiB max chunk, 8 MiB index, 10,000 archive records and
20,000 chunks. This workflow supports at most 9,999 source objects plus evidence.
Cached lineage JSON is limited to 1 MiB per document and 8 MiB total; evidence is
also limited to 8 MiB. Limits abort, never silently truncate or drop coverage.

## Synthetic destination safety

`restore_synthetic_storage(directory, key, destination=..., confirmed=True)` first
authenticates the entire archive and recomputes its stored lineage/evidence binding.
Source identity comes from authenticated evidence, not a caller-supplied override.

It requires an explicit synthetic destination, confirmation, all read capabilities
and conditional PUT. Source/destination resource IDs or known aliases must not
overlap; identical bucket names are conservatively rejected even across authorities.
The destination must be empty. Its identity is checked throughout the workflow.

Each original key uses `put_if_absent`; a racing existing key fails without being
overwritten. No fallback unconditional writes exist. The final exact key set,
metadata, sizes and full GET SHA-256 are checked, followed by another inventory
fence. New destination ETags are allowed; original manifests/keys/metadata/bytes
remain unchanged. Extra destination objects cause failure and are never deleted.

Repeated restore into the same destination is refused. Interrupted/failed restores
retain their partial fixture state for inspection. There is no delete API or
automatic rollback. Adapter implementations and their canonical identities are
trusted boundaries; arbitrary malicious adapters cannot be secured by DTO checks.

## Offline example and verification

The fixture builder lives only in the test suite:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import os
from tests.test_s3_workflow import fixture
from src.recovery.s3_storage import SyntheticStorage
from src.recovery.s3_workflow import backup_synthetic, restore_synthetic_storage

with TemporaryDirectory() as tmp:
    key = os.urandom(32)
    source, metadata = fixture(full=True, contexts=((43, 106), (9, 281)))
    report = backup_synthetic(source, metadata, Path(tmp), key)
    destination = SyntheticStorage("fixture-restored")
    restore_synthetic_storage(report["directory"], key,
                              destination=destination, confirmed=True)
```

Run existing CI dependencies, with network disabled:

```powershell
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-ci-checks:8c python ci/run_unittest.py discover -s tests -p 'test_s3_workflow.py'
```

The regular root test discovery includes both A and B. Tests block socket creation
and inject pagination/HEAD/GET/access failures, source bytes/add/delete/metadata
changes, catalog drift, corrupted artifacts, lineage mismatches, destination aliasing,
conditional-PUT absence/collisions, altered restored bytes/metadata, identity drift
and repeated restore. Existing database v1 and production delivery suites remain required.

Local verification on 2026-10-21:

| Check | Result |
| --- | --- |
| Python 3.10.12, network-disabled CI container | 619 root, 30 application, 16 CI tests passed |
| Python 3.12.14, network-disabled CI container | 619 root, 30 application, 16 CI tests passed |
| New B workflow suite on Windows | 32 passed |
| Existing A format and database recovery suites | Included unchanged in the passing root suites |
| Ruff and compileall, both Python matrix versions | PASS |
| Repository contracts, whitespace and new-file secret-signature audit | PASS |
| Executed documentation example | PASS: 22 builds, 97 synthetic source objects, 98 archive records |

These are local synthetic results. No new GitHub run or live S3/database acceptance
was requested or performed.

## Prerequisites for future live integration

Before adding/enabling any real adapter: separately authorize the live scope;
provide canonical account/bucket identity and alias handling; establish dedicated
source read-only credentials; test full pagination and conditional GET against
native HEAD validators; retain TLS/CA/SigV4/virtual-addressing behavior; define safe
metadata/header normalization; provide read-only catalog/serving snapshot adapters;
confirm the quiet collection window, external media and independent key recovery.

Remote restore additionally needs an independently prepared isolated destination,
restricted write/read credentials and proven provider enforcement of conditional
PUT under races. Historical versions/Object Lock remain UNKNOWN where access is
denied; no historical-version backup, runtime pipeline cutover or restored application
acceptance is claimed. No real adapter, cloud writes or database restore runs in B.
