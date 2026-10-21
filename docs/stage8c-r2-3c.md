# Stage 8C-R2.3-C: real read-only adapters and live dry-run

This document records stage C live evidence, not a new audit of Selectel today.
See the [publication audit](stage8c-r2-3-publication.md) for the combined A/B/C/D source status.

Acceptance date: **2026-10-21**. R2.3-C read-only acceptance: **PASS**.
First full encrypted live S3 backup: **BLOCKED / not enabled** (see boundaries below).
Overall Stage 8C disaster recovery remains **PARTIAL**. No independent copy, recovery
key, bucket, cloud write, database write, ETL run, commit or push was created here.
Pending R2.3-A/B sources are preserved; database backup v1 and archive schema 2 are unchanged.

## Adapters and reuse

- `src/recovery/s3_readonly.py`: injected boto3 client, full-root paginated LIST,
  HEAD, streaming GET with native HEAD `IfMatch`, one-byte Range probes, optional
  versioning/lock/version-list/owner observation. No PUT, delete, create-bucket or
  destination API. SDK calls use the existing shared client configuration:
  SigV4, virtual addressing, standard retries, timeouts and CA/TLS verification.
- `src/recovery/s3_metadata.py`: existing Docker/runtime `pg_snapshot` and `registry`
  helpers read all five catalog/receipt tables in an exported repeatable-read,
  read-only PostgreSQL transaction. ClickHouse reads only table descriptions,
  build/context/count groups and duplicate-key aggregates, not full serving rows.
  SELECT aggregates specify `readonly=2`; descriptions are intrinsically read-only.
- `src/recovery/s3_dry_run.py`: inventory, small-document lineage checks, conditional
  probes and a second inventory. No writer or archive creation is invoked.
- `scripts/check_s3_recovery_dry_run.py`: host orchestration, initial/final metadata
  fence, only a safe JSON summary. Current Python sources and detached catalog DTOs
  enter the existing scheduler through stdin and an in-memory importer. Credentials
  stay in that runtime; environment/credential files are never opened by the script.
  No rebuild, container recreation or source-file copy is necessary.

The existing scheduler image separates SDK dependencies (`/usr/bin/python3`) and
crypto dependencies (the same-version `/opt/airflow-venv`). The launcher appends
that already-installed venv's library directory for this process only. Initial
import-only attempts exposed this dependency split and performed no S3 reads;
no packages or runtime configuration were installed/changed.

`inventory(..., allow_live_read=True)` enables enumeration only. The independent
synthetic-only backup and restore identity guards remain mandatory. The full
`validate_lineage()` still requires measured byte SHA-256 for all Bronze payloads.
The separate `validate_metadata_lineage()` checks only the explicitly downloaded
documents by byte SHA, reports remaining coverage as unverified and never substitutes
an ETag or catalog/metadata SHA claim for a measured payload hash.

## Source identity and aliases

| Field | Observation |
| --- | --- |
| Endpoint | `https://s3.ru-3.storage.selcloud.ru` |
| Bucket | `football-data-platform-dev-v1` |
| Addressing | `virtual` |
| Resource identity | `endpoint-bucket:803a3353cf52681fca79ff5444db60e6cedfdd8f57b8341a73db8b07315ef4de` |
| Path-form alias | `https://s3.ru-3.storage.selcloud.ru/football-data-platform-dev-v1` |
| Virtual-host alias | `https://football-data-platform-dev-v1.s3.ru-3.storage.selcloud.ru` |
| Account/project | Unknown; an additional `LIST MaxKeys=1, FetchOwner=True` succeeded but exposed no canonical owner ID |

Endpoint case, a trailing slash and default port 443 normalize to the same identity.
Userinfo, non-HTTPS, query/fragment or endpoint path components are refused. The
path alias is an identity token only, not a change to SDK virtual addressing.
An exposed canonical owner would be recorded only as a SHA-256 fingerprint, not
assumed to identify a Selectel project. Other regional endpoints, custom DNS and
administrative ownership aliases cannot be exhaustively resolved from these reads.
Identity is **endpoint-bound**, not proof of global resource ownership. No live
destination adapter exists; unresolved destination identity cannot enable restore.
Production source credentials are never supplied to any destination.

## Actual inventory and registered coverage

| Layer | Current objects | Bytes |
| --- | ---: | ---: |
| Bronze | 202 | 321,473,523 |
| Silver | 78 | 34,559,914 |
| Gold | 35 | 349,972 |
| Total | **315** | **356,383,409** |

Formats: 224 JSON, 47 Parquet, 22 zero-byte directory markers and 22 extensionless
`_SUCCESS` artifacts. `_SUCCESS` artifacts are not assumed empty.
The current count/size agrees with the R2.1 baseline; no change needs explaining.
Counts are observations, not hardcoded acceptance thresholds.

Registered classification: **312**; two unversioned legacy Bronze JSON objects and
one Bronze test object remain outside the registry. They are not excluded from
future backup scope and are not declared disposable. No source object was deleted.

### Bounded reads and conditional behavior

- Two complete root LIST traversals and **630 HEAD** requests succeeded. The extra
  owner-observation request was a separate one-row LIST, not another full audit.
- **22 build manifests + 2 Bronze matches-parent JSON** were fully read for existing
  deterministic-ID, input/membership and checksum validation. Parent JSON is necessary
  to verify the 64/34 context match memberships, not a general Bronze payload download.
- Three additional GET probes read **one byte each**: Bronze, Silver Parquet, Gold
  Parquet. Total body bytes read: **455,754**, not 356 MB.
- There were **30 GetObject requests**: 24 documents and 6 conditional probes.
  Each correct HEAD validator succeeded; every deliberately wrong validator returned
  **HTTP 412**. All returned streams were closed; failed conditions returned no body.
- **47 LIST/HEAD ETag mismatches** remain. Both sampled Parquet objects exhibit the
  discrepancy, and their native HEAD validators work. LIST ETag is used only against
  the existing manifest's LIST observation, never as a byte checksum or GET validator.
  The provider-specific reason for the discrepancy is still unknown.
- Final LIST/HEAD observations matched initial observations exactly. This is a
  detection fence, **not a globally atomic snapshot** or proof of no transient ABA change.

Defaults: full-object GET limited to **256 KiB per document**, **2 MiB aggregate**;
strict positive reads at most **64 KiB**. Configurable dry-run bounds are capped at
1 MiB/object and 8 MiB total. Oversized full GET is rejected before a request; Range
must return the expected HTTP 206, length and Content-Range. Truncation, stream
exceptions and state/header changes fail closed. Early caller termination closes
the stream but is not reported as full-byte verification. Use sequential consumers.

24/315 objects have measured whole-object SHA-256 in this audit; **291 do not**.
No claim about all payload checksums, Parquet contents or independent recovery is made.

### Capabilities observed

| Capability | Result |
| --- | --- |
| ListBucket / ListObjectsV2 | ALLOWED, full current root listing |
| HeadObject | ALLOWED, all 315 objects twice |
| GetObject | ALLOWED for selected documents and ranged samples |
| Conditional GET | PASS: correct validator accepted, wrong validator HTTP 412, all three layers sampled |
| GetBucketVersioning | HTTP 403, state **UNKNOWN** |
| GetObjectLockConfiguration | HTTP 403, state **UNKNOWN** |
| ListObjectVersions | HTTP 403, historical versions **UNKNOWN / NOT BACKED UP** |
| Canonical owner via FetchOwner | Request allowed, owner not exposed |

403 does not mean disabled. Adapter operation restrictions are not a proof that
the runtime credential's IAM policy is read-only; no IAM inspection/change occurred.
Server behavior is sampled, not exhaustively proven for all objects/future requests.
Any future conditional probe failure blocks live backup; no unconditional fallback exists.

## PostgreSQL / manifest / ClickHouse reconciliation

Catalog: **199 ingestion objects, 14 Silver builds, 8 Gold builds, 14 Silver load
receipts and 8 Gold load receipts**. All 22 published/loaded deterministic identities
and source locations resolve. Exact manifest file sets/sizes/LIST ETags, schema hashes,
input fingerprints, Bronze references, selected match memberships and receipt fields
agree. Published status means presence in the immutable build registry, not a new
status column. No latest-build selection or identifier rewriting is performed.

ClickHouse: **12 MergeTree serving tables**, **496,838 rows**, zero duplicate
business keys; all observed build/context/count groups match their registered receipts.
Views are not read as duplicate serving datasets. No full serving-table payload export.

| Context | Competition/season | Matches |
| --- | --- | ---: |
| World Cup 2022 | 43/106 | 64 |
| Bundesliga selected subset | 9/281 | 34 |

Initial/final detached metadata digests matched. PostgreSQL's transaction is internally
consistent; ClickHouse's sequential aggregate reads and S3's two scans have no shared
transaction. Equal fences cannot establish an atomic S3/PostgreSQL/ClickHouse snapshot.

Safe audit digests (not secrets):

- Inventory: `1507a7676eed78b676ac8d82177fc451a4ca9a081f2aab5e5c6888abb2d931b6`.
- Catalog/serving: `adfe233f2477f5b8e39bb1d1681c908d255750d58104b3caa6ce0c907371b410`.

## Schema 2 compatibility and tests

Real user metadata remains a string-to-string map. Selected standard HTTP headers
are preserved as string-valued `s3:<HeaderName>` entries, including content type,
encoding/disposition/cache attributes, version/encryption fields when returned.
Timestamps normalize to UTC ISO-8601. Reserved-name collision, non-string user
metadata or the existing 64 KiB/index metadata limit causes refusal, not silent loss.
All 315 actual HEAD maps passed the existing archive metadata validator. Original
object keys remain index data, never local paths. No archive format or cipher change.

Offline fake-transport tests cover pagination/cycles/malformed replies, safe provider
403/404/412 and unexpected errors, bounded/partial/truncated/failed streams, wrong
validators/ignored conditions, changed metadata/ignored Range, empty objects,
normalization/collisions, identity aliases, owner exposure, no-write surface and
read-only catalog/serving snapshot acquisition. Existing A/B and database suites
remain required.

| Final local check | Result |
| --- | --- |
| Python 3.10.12, network disabled | 649 root + 30 application + 16 CI tests PASS |
| Python 3.12.14, network disabled | 649 root + 30 application + 16 CI tests PASS |
| New adapter suite on Windows | 30 tests PASS |
| Archive A / workflow B / database recovery v1 | Existing suites green in both root matrix runs |
| Ruff, both matrix environments | PASS |
| compileall, both matrix environments | PASS |
| Repository/workflow/publication contracts | PASS |
| Git whitespace and explicit new-source secret-signature checks | PASS |
| `.env`, `.passes`, `keys.txt` exclusion | Git ignored and Docker build context excluded |

One early test selected a matches manifest instead of its Bronze parent due to
unordered set iteration; the test now explicitly selects the Bronze prefix. Both
matrix runs passed after correction. No production analytical behavior changed.
No new remote CI run is claimed: commit/push was not performed.

## Exact R2.3-C changed files

New files:

- `src/recovery/s3_readonly.py`
- `src/recovery/s3_metadata.py`
- `src/recovery/s3_dry_run.py`
- `scripts/check_s3_recovery_dry_run.py`
- `tests/test_s3_readonly.py`
- `docs/stage8c-r2-3c.md`

Updated:

- `src/recovery/s3_lineage.py`: separate metadata-only coverage mode; full-byte mode stays strict.
- `src/recovery/s3_workflow.py`: explicit read-only inventory opt-in, without relaxing backup/restore guards.
- `docs/stage8c.md`: link and scope/status summary.

Already-pending A/B archive/storage/workflow/lineage sources, their tests and
`docs/stage8c-r2-3a.md` / `docs/stage8c-r2-3b.md` remain uncommitted. Their unrelated
content was not replaced; `archive.py`, `operations.py`, `runtime.py`, database
requirements and `scripts/backup.py` are unchanged. Git staging remains empty.

## PowerShell verification (no secrets in arguments)

Run the explicitly read-only command using existing containers/dependencies:

```powershell
Set-Location F:\Learning_projects\football-data-platform
.\.venv\recovery\Scripts\python.exe -B scripts/check_s3_recovery_dry_run.py
```

It neither opens `.env`/`.passes` nor transfers their contents. The existing runtime
resolves its configured SDK environment. Provider/SDK messages, payloads and metadata
values are suppressed; only fixed error codes and the safe summary are printed.

Offline checks with the already available CI image (repeat with `py310` for matrix):

```powershell
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python ci/run_unittest.py discover -s tests -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 ruff check --no-cache .
docker run --rm --network none -e PYTHONPYCACHEPREFIX=/tmp/pycache --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python -m compileall -q src application scripts infrastructure dags tests ci
python ci/check_repository.py
git diff --check
git check-ignore .env .passes keys.txt
```

## Boundaries before a first full encrypted backup

The transport/metadata dry-run is ready, but **executing the first full encrypted
live backup remains BLOCKED**: A/B intentionally permit only synthetic archive scope
and synthetic backup workflow. C does not remove those guards or introduce a live
backup writer entry point. A separately authorized next implementation must bind
this verified read adapter to full streaming/hash/archive/evidence handling with
an explicit live scope and suitable full-backup limits, preserving v1/v2 compatibility.

Before execution also confirm an independent physical medium/provider, exclusive
archive placement/capacity, separately recoverable encryption key/escrow and a quiet
collection window. None was created or tested by this task. Later restore needs a
provably isolated destination identity, separate credentials, proven conditional
create/no-overwrite and full post-restore SHA-256 checks. An unknown identity stays blocked.

Historical versions remain unobservable under current rights. Independent S3 bytes,
remote restore, secret recovery and complete machine-loss recovery remain **NOT VERIFIED**.
No real database backup/restore drill was repeated. Stop after R2.3-C; do not infer
authorization for a live archive, new credentials, destination writes or publication.
