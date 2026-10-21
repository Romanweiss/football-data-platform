# Stage 8C — backup, restore and disaster recovery

Live backup/drill evidence: **2026-10-20 UTC**; final review completed **2026-10-21**
(Europe/Moscow). Overall status: **PARTIAL**, not full disaster-recovery closure.
Real local database backup/restore acceptance is **PASS**. Independent S3 byte
backup, remote bucket recovery, off-machine key/backup availability and application
secret recovery remain unverified. No schedule, ingestion, migrations, production
restore, password rotation, product changes, commit or push were performed.

Recovery scope remains explicit:

Stage 8C-R2.3-A adds a separate [synthetic encrypted S3 archive profile](stage8c-r2-3a.md).
It does not establish a real independent S3 backup or remote restore; the overall
PARTIAL verdict and database-profile compatibility remain unchanged.

Stage 8C-R2.3-B adds [synthetic storage, consistency fences and lineage](stage8c-r2-3b.md)
over that profile. It likewise provides no live Selectel adapter or remote recovery proof.

Stage 8C-R2.3-C adds [read-only adapters and a bounded live dry-run](stage8c-r2-3c.md).
Inventory/lineage and conditional GET pass; no real encrypted S3 backup or remote
restore has been created. The overall disaster-recovery verdict remains PARTIAL.

Stage 8C-R2.3-D prepares the [operator CLI and live-backup safety gates](stage8c-r2-3d.md),
verified only against synthetic sources. No full real S3 download, archive or key
was created. Execution still requires operator prerequisites and separate approval.

| Check | Status |
| --- | --- |
| Local metadata restore | PASS |
| ClickHouse restore | PASS |
| Grafana SQLite restore | PASS |
| S3 registered-object inventory | PASS |
| R2.3-A/B/D synthetic S3 recovery | PASS |
| R2.3-C live read-only dry-run | PASS |
| Live encrypted S3 backup | NOT EXECUTED |
| Independent S3 byte backup | NOT VERIFIED |
| Remote S3 restore | NOT VERIFIED |
| Complete machine-loss recovery | NOT VERIFIED |
| Secret escrow/restore | NOT VERIFIED |

Publication follow-up: `ci/check_repository.py` now requires the delivery/recovery
sources in the Git index and rejects private backup/key/runtime paths before reading
file contents. A staged source set is not yet a published commit or a new green remote CI.
The full [A/B/C/D publication audit](stage8c-r2-3-publication.md) records the staged
inventory and isolated Git-snapshot checks. HEAD/origin/master is now `8e934a5f65eeb768de1546b03a1a965b91be959a`;
the Stage 8B omission repair and Stage 8C sources were published previously with
fast/integration CI confirmed green. A/B/C/D remain pending publication until approved.

## Git/CI preflight

Branch `master`, origin `https://github.com/Romanweiss/football-data-platform.git`.
Historical audit baseline (before the publication repair below), not current HEAD:
`a1449fd425ee36c74af4d4e8eb2b1572df4bf2b3`
(`feat: add production-like application delivery`). Stage 8B was **partially** committed:
13 previously tracked files are in that commit, while these eight files were untracked
at the start of Stage 8C and were preserved, then published by the subsequent repair:

```text
ci/check_delivery.py
docker/api/gunicorn.conf.py
docker/web/nginx.conf
docs/stage8b.md
frontend/playwright.delivery.config.ts
frontend/tests/smoke/delivery.spec.ts
tests/application/test_delivery.py
tests/ci/test_delivery.py
```

Actual runs for that exact commit:

- [CI fast 39484148220](https://github.com/Romanweiss/football-data-platform/actions/runs/39484148220): success.
- [CI integration 39484148270](https://github.com/Romanweiss/football-data-platform/actions/runs/39484148270): failure in both application Docker-build jobs; database and Spark/Airflow jobs passed. The missing tracked Gunicorn/Nginx files are an independently confirmed publication defect.

Neither the old Stage 8A green runs nor this fast run certify the uncommitted 8C
work. The publication follow-up explicitly stages the audited source files but does
not commit or push without separate approval. `manifest.git_head` identifies Git provenance but cannot
reproduce the entire dirty working tree; retain the pending source changes separately.

## Inventory and recovery dependencies

Verified running Compose project: `football-data-platform`. Named volumes below
are the actual mount names; source containers are resolved by Compose labels,
not by guessing generated container names. Runtime environment values are never
inspected or printed by the backup CLI.

| Component / location | Authority and reproducibility | Backup / dependency / loss consequence |
| --- | --- | --- |
| Platform PostgreSQL 17.6, `football_postgres_data:/var/lib/postgresql/data` | Authoritative append-only Bronze catalog, Silver/Gold build registries, load receipts, DQ history, alert state and source discovery history. Git restores schema, not execution history. | Custom logical dump + roles without password hashes. Loss breaks exact lineage and operational history; do not infer loaded/published status from row existence alone. |
| ClickHouse 25.8.23.13, `football_clickhouse_data:/var/lib/clickhouse` | Derived serving: 12 MergeTree tables and 10 ordinary views. Git has migrations 001–015; current installed schema is authoritative for this snapshot (001 retains historical Float32). | Exact live DDL + Native row exports, including build IDs and `loaded_at`. Silver tables depend on Silver, Gold marts on Gold; **not all serving can be rebuilt from Gold alone**. Loss removes application serving until restored/reloaded. |
| Airflow PostgreSQL 17.6, `football_airflow_db_data` | DAG/task history, XCom, serialized DAG metadata; DAG source is in Git, execution history is not. | Separate consistent DB dump. Fernet/auth keys remain a separate recovery dependency. Do not start a restored scheduler during validation. |
| Superset PostgreSQL 17.6, `football_superset_db_data` | Dashboards, datasets, charts, users, metadata connections and configuration. SQL/views in Git do not recreate all interactive edits. | Separate DB dump. Original Superset secret is required to decrypt saved connections. Restore validation does not start Superset or contact its datasources. |
| Grafana 13.0.1, `football_grafana_data:/var/lib/grafana` | Provisioning YAML/dashboard JSON in Git; users/preferences and non-provisioned state in `grafana.db`. | SQLite Online Backup API, never an unlocked file copy. Original encryption/configuration secrets may be needed for application startup; drill validates SQLite only. |
| `football_airflow_logs:/opt/airflow/logs` | Operational forensic detail, not authoritative published dataset state. | Not in this database backup. Loss loses task log detail, not the DB task history. Propose separate encrypted retention. |
| Selectel S3 `football/bronze/`, `football/silver/`, `football/gold/` | Bronze exact acquired source bytes are authoritative. Silver/Gold are derived immutable artifacts, reproducible only with exact source bytes, code/runtime, configuration and identities. Upstream latest JSON is not a substitute. | Inventory and manifest checks only here; no independent byte backup or restore of real S3. Bucket loss is **not covered** by database copies. |
| Git + local Docker images | Source, migrations, DAGs, provisioning and serving configuration. Images are derived but registry availability is a dependency. | Commit hash + configuration hashes + source image IDs recorded. No Git bundle or image export created; the historical 8B omission is repaired, while new S3 sources require the audited publication below. |
| `.env`, `.passes`, `keys.txt` | Runtime passwords/keys; cannot be reconstructed from Git. | Never opened, copied or printed by this CLI. Separate encrypted operator-managed recovery. |
| `football_airflow_secrets` | `db_password`, Fernet, JWT/API keys, SimpleAuthManager password state. | Not mounted into restore targets. Requires separately protected recovery; losing Fernet can make encrypted metadata unusable. |
| `football_grafana_secrets` | Reader/admin passwords used by provisioning/bootstrap. | Separate protected recovery; do not rerun bootstrap to rotate passwords as a backup substitute. |

Recovered state dependency order is: matching Git/runtime and separately recovered
keys → databases and immutable S3 artifacts → exact catalog/build/load reconciliation
→ serving → read-only API/BI validation → explicitly approved scheduler enablement.
This drill ends before application/scheduler enablement.

## Architecture, encryption and manifest

Host CLI: `scripts/backup.py`, implementation `src/recovery/`. It uses the existing
Docker runtimes and one optional host dependency, `cryptography==50.0.2` in
`requirements/recovery.txt`. Application images/dependencies are unchanged.

Use Python 3.12+ with SQLite `serialize`/`deserialize` support for the host backup
CLI. Python 3.10.12 remains in the general CI matrix, but cannot create a live
backup: preflight rejects it before source IO, key creation or artifact creation.
Both matrix versions test in-memory SQLite integrity/count validation and the
unsupported-runtime guard; Python 3.12.14 also tests actual byte deserialization
and rejects corrupt SQLite bytes. No plaintext temporary-file fallback or skipped
matrix job is used.

`create` resolves existing source services and reads their databases through
`docker exec`. PostgreSQL uses local socket authentication and the container's
existing database/user variables. ClickHouse uses its existing container runtime
credentials; their values never enter host command arguments, reports or manifests.
Child stdout/stderr is captured and never echoed on error. Plain dump/data bytes
exist in process memory, not intermediate unencrypted backup files.

Each session gets a UTC/random ID. Artifacts go to `backups/<id>/`; a random
32-byte AES-256 key goes to `.recovery-keys/<id>.key`, **outside the backup directory**.
POSIX directories are mode 0700/files 0600; on Windows inherited directory ACLs are
removed and access is granted to the current user's SID. Windows administrators
and compromised host processes are outside this protection boundary.

Each artifact has an independent random 96-bit nonce and AES-256-GCM tag. Backup
ID and artifact filename are authenticated additional data. The manifest has a
separate HMAC-SHA256 using the session key. It records:

```text
backup_id, timestamp_utc, schema_version=1, git_head, encryption
artifacts[].path, source_component, backup_method, source_version
artifacts[].file_size, sha256, plaintext_size, plaintext_sha256
contexts, build_ids, consistency_status, verification_status, backup_seconds
authentication
```

Only safe identifiers/counts and hashes appear in the cleartext manifest. Catalog
details, source inventory, schemas and S3 inventory are inside `details.json.enc`.
Metadata databases can contain stored credentials, password hashes and encrypted
connection fields; their dumps are therefore **sensitive encrypted backups**, not
public data. Database role dumps exclude authentication hashes (`--no-role-passwords`).
No `.env`, `.passes`, `keys.txt` or secret-volume file is copied into the backup.

`verify` authenticates the manifest and every artifact, checks sizes/SHA-256, GCM
tags, PostgreSQL `PGDMP` format, required component/table set and supported versions.
All validation happens before restore creates a destination. Paths must be single
safe filenames; path traversal/symlinks and missing components fail closed.
The immutable manifest says `CHECKSUM_VERIFIED_NOT_YET_RESTORED` at creation;
successful drill evidence is a separately authenticated `drill-<target>.json`, bound
to the manifest's SHA-256. `verify` reports authenticated drill results separately.
Failure/partial directories without a sealed manifest are not usable backups.

This local implementation buffers one artifact/table export at a time and refuses
encrypted artifacts over 512 MiB; it is sized for this project, not multi-TB stores.
Authentication verifies integrity, not that the key/backup exists off-machine.

## Consistency and restore method

Each PostgreSQL dump and its control row hashes use the **same exported repeatable-read
snapshot**, held open until both complete. This covers concurrent Airflow metadata
writes without copying the active PostgreSQL data directory. Client and server are
17.6; restore uses the recorded image ID and `pg_restore --create --exit-on-error`.
Roles, memberships, database/table ownership and grants, extensions, logical column
order/types/defaults, constraints and exact sorted row SHA-256 are compared.
ACL entry ordering and holes in internal column numbers left by dropped columns
are normalized; actual permission changes or column reordering are rejected.

ClickHouse uses current `SHOW CREATE TABLE` plus `SELECT * FORMAT Native`, preserving
Float64 values, nulls, build IDs and load timestamps. Restoration inserts each table
once into a **fresh** database; views are installed in dependency order and their
DDL is compared exactly. Full sorted row hashes, counts, schema, per-context/build
groups, duplicate sorting-key groups and selected aggregates are checked. All current
table business keys coincide with their sorting keys; `ORDER BY` itself provides no
uniqueness guarantee. CI explicitly demonstrates that a repeated Native insert can
duplicate rows. Reusing a destination is refused rather than retrying inserts.

Alternative recovery from immutable artifacts must use original Silver/Gold build
identities and manifests, load into a new target, validate exact target contents,
then reconcile receipts. No ETL replay or loader execution was performed here.
The Native export is a logical row backup, not a physical MergeTree part/replica/
deduplication-log backup. Users, named S3 collections, server settings and credentials
are not dumped from ClickHouse system databases. Restore has no S3 credentials.

There is **no distributed atomic snapshot** across PostgreSQL, ClickHouse and S3.
The backup uses a bounded consistency fence: fixed published/loaded registry,
before/after ClickHouse row hashes, no active mutations, and S3 manifest/inventory
checks. Registry fields and ClickHouse counts must agree for all 22 published/loaded
identities; source catalog/serving changes during collection cause failure. DQ/alert
history is the platform snapshot's state. Airflow and Superset have independent
snapshot times. Quiescent published data is required; arbitrary concurrent manual
writers are not made safe by this mechanism.

Grafana uses SQLite's online backup API into memory, including committed WAL state,
and `PRAGMA integrity_check`. Restore deserializes into an in-memory SQLite database
inside a networkless, read-only helper container; integrity and all table counts are
checked. The full snapshot was already SHA-256/GCM verified. No Grafana app is started.

## Isolation and exact PowerShell commands

Run from `F:\Learning_projects\football-data-platform`. This is a host CLI, not a
new production service. It never parses private environment files. Existing source
containers/images must be available; the source project name is intentionally fixed.

```powershell
python -m venv .venv/recovery
.\.venv\recovery\Scripts\python.exe -m pip install -r requirements/recovery.txt

# Read-only source collection; writes NEW local encrypted artifacts/key.
.\.venv\recovery\Scripts\python.exe scripts/backup.py create

# Recorded successful backup, not a placeholder.
$backupId = '20261020T195423Z-b20dc756ab55'
.\.venv\recovery\Scripts\python.exe scripts/backup.py inspect --backup-id $backupId
.\.venv\recovery\Scripts\python.exe scripts/backup.py verify --backup-id $backupId

# Choose a fresh namespace for EVERY new drill.
$drillTarget = 'football-drill-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
.\.venv\recovery\Scripts\python.exe scripts/backup.py plan --backup-id $backupId --target $drillTarget
.\.venv\recovery\Scripts\python.exe scripts/backup.py drill --backup-id $backupId --target $drillTarget --confirm-isolated
```

Exit code 0 means the requested operation passed, 1 is a safely reported runtime/
integrity failure, 2 is invalid CLI arguments. Progress includes fixed stage labels;
the final result is JSON with the backup ID. `inspect` prints only authenticated safe
manifest fields, not decrypted database content. Never use generic dump/inspect
commands to print runtime environment values while troubleshooting.

The isolated environment is created directly through Docker rather than merging
the production Compose file. An explicit `football-drill-<8..24 alphanumeric>` project
namespace is mandatory. Existing containers/volumes/networks with that prefix are
rejected. Containers are labelled with that project, have `--network none`, no host
ports or binds and their own **tmpfs-backed data mounts**. These mounts replace the
images' persistent data volumes; no production volume is reused. Only synthetic DB
credentials are supplied. Restored metadata may retain opaque stored application
connection fields, but no restored app/scheduler is started and no network is available.

Before validation and cleanup, container labels/network/ports/mounts are checked.
Only exact container IDs created by that invocation are removed in `finally`; their
tmpfs copies intentionally disappear. Encrypted backups and keys remain. There is
no `down -v`, volume removal, prune, live DROP/TRUNCATE/DELETE or default-project restore.
Source container IDs/start timestamps must remain unchanged. The CLI deliberately
offers **no in-place restore or resume-into-partial-target mode**.

## Actual local drill results

Final backup: `20261020T195423Z-b20dc756ab55`.
Final target: `football-drill-stage8cfinal1` (disposed after validation).

| Measurement | Result |
| --- | --- |
| Backup collection + encryption | 68.429 s |
| Encrypted artifacts, excluding small cleartext manifest/report | 130,442,398 bytes (about 124.4 MiB) |
| Restore + validation + isolated cleanup | 46.083 s |
| Platform PostgreSQL | 12 tables, 1,078 rows; exact rows, build/catalog/DQ/alert/discovery and schema/ACL/ownership checks passed |
| Airflow metadata | 55 tables, 999 rows; snapshot row hashes and metadata checks passed |
| Superset metadata | 51 tables, 13,081 rows; snapshot row hashes and metadata checks passed |
| ClickHouse | 12 tables, 10 views, 496,838 rows, no duplicate keys; full row hashes and exact DDL matched |
| Grafana SQLite | 86 tables; integrity and table counts passed in isolated helper |
| Published/loaded identities | 22 / 22, unchanged and exactly reconciled |
| World Cup 43/106 | 64 matches |
| Bundesliga subset 9/281 | 34 matches |

Selected restored aggregates matched source baseline (12-decimal display comparison):
Argentina `2.758305926`, France `2.272617949` for match 3869685;
Leverkusen `1.523364167`, Leipzig `1.722110068` for match 3895052.
Full underlying Float64 row hashes also matched. No restored API was started, so
**restored API hashes are not claimed**. The live production application remains
available; its product behavior and runtime secrets were not changed.

Environment: Docker Desktop Linux engine on Windows, 16 Docker CPUs, approximately
15.5 GiB Docker memory, existing images cached. Host CLI used Python 3.14.3 and the
pinned cryptography dependency; tests also run in Python 3.12.14 CI image. These are
local measurements, not cold-machine or public-cloud recovery estimates.

During implementation, early drills correctly failed on ACL ordering, dropped-column
attnum gaps, and readiness races during the database images' temporary initialization
servers. Fixes normalize only non-semantic metadata and wait for final servers (PG
TCP readiness; ClickHouse PID 1 server process). All failures were in disposable
targets. The first interrupted collection `20261020T194307Z-8fa3e53f2e4a` has no sealed
manifest and is not restorable. An earlier complete backup/drill also remains locally;
neither incomplete artifacts nor keys were silently deleted.

## S3 boundary and secret recovery

Read-only validation covered **312 registered objects**: 199 Bronze HEAD checks
(catalog SHA metadata and length), 22 GET manifest SHA-256/identity checks, and 91
other listed output objects checked against build file sets/lengths/ETags. Gold input
build IDs resolve to registered Silver builds. These are not full-byte Bronze/Parquet
checksums; ETags are **not** treated as SHA-256. Unregistered/orphaned S3 objects and
historical versions are outside this inventory. No real object was written/deleted.

Both `GetBucketVersioning` and `GetObjectLockConfiguration` returned HTTP 403 under
the existing credentials. State is **unknown/inaccessible**, not "disabled". No IAM,
bucket policy, retention or permission changes were attempted. Selectel supports
versioning and Object Lock, but that product capability does not establish this
bucket's configuration or an independent recovery copy. Real remote S3 restore
requires a separately approved isolated bucket and suitable credentials. A clearly
synthetic local object-byte restore/checksum/no-overwrite test passes; it does not
prove Selectel disaster recovery.

Secrets procedure for the operator:

1. Keep an independently encrypted, access-controlled vault backup of runtime files
   and secret-volume material. Use secure attachments/export provided by the chosen
   password manager; do not make plaintext staging copies in `backups/` or Git.
2. Protect the new `.recovery-keys/<id>.key` as a separate vault item and verify the
   encrypted vault can be recovered on another machine. Backups plus keys on the
   same workstation do not protect against workstation loss. No vault export was
   performed by this stage.
3. Recover the **original** Superset encryption key, Airflow Fernet/auth material,
   Grafana secret configuration and runtime credentials before application startup.
   Do not rotate/regenerate them to work around missing recovery material. Restore
   into a separate reviewed environment first; verify decryption/identity there.
4. Only after immutable artifact/catalog/load checks and read-only application
   acceptance should an operator explicitly switch endpoints/enable schedulers.

`.env`, `.passes`, `keys.txt`, `backups/` and `.recovery-keys/` are excluded from both
Git and Docker build context. Live backups/keys never enter CI images or artifacts.

## Tests, failure injection and CI

Root offline suite: **554 passed**, including **29 new recovery tests**.
Application suite: **30 passed**; CI contracts: **14 passed**.
Synthetic PostgreSQL/ClickHouse integration passed. Ruff, public-placeholder Compose
configuration, Git whitespace checks and repository safety checks passed. The
repository check requires Git: its first invocation in the minimal CI image could
not run because that image has no Git executable; it then passed on the host.
Failure tests cover missing backup/manifest/component/table, corrupted artifact,
wrong checksum/key, failed GCM tag, unsupported schema/server version, path traversal,
unsafe/default/occupied target, missing explicit confirmation, unsafe mounts/network,
raw exception suppression and forged drill reports. Corruption fails before Docker
target mutation. ACL and logical-order tests reject actual semantic changes.

`ci/check_recovery.py` uses only synthetic values and networkless tmpfs containers.
It tests a concurrent-write exported PostgreSQL snapshot, logical restore, Float64/
NULL Native roundtrip and actual duplicate detection after deliberately repeating a
synthetic insert. The normal offline CI matrix includes archive safety tests via
`requirements/ci.txt`; the integration workflow adds an isolated recovery job with
pinned PG/CH images. No real backups, infrastructure secrets, S3 or artifact uploads.
No CD. These new workflow changes have **not** been published/run on GitHub.

```powershell
docker build -f ci/Dockerfile -t football-ci-checks:8c .
docker run --rm --network none --mount "type=bind,src=$PWD,dst=/workspace,readonly" -w /workspace football-ci-checks:8c python ci/run_unittest.py discover -s tests -p 'test_*.py'
docker run --rm --network none --mount "type=bind,src=$PWD,dst=/workspace,readonly" -w /workspace football-ci-checks:8c python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
docker run --rm --network none --mount "type=bind,src=$PWD,dst=/workspace,readonly" -w /workspace football-ci-checks:8c python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
.\.venv\recovery\Scripts\python.exe ci/check_recovery.py
docker compose --env-file .env.example --profile app-prod --profile airflow --profile grafana config -q
git diff --check
git check-ignore .env .passes keys.txt backups/test.enc .recovery-keys/test.key
```

## RPO/RTO, scheduling and next steps

RPO is the maximum acceptable loss window; RTO is the acceptable restoration time.
No production SLA is established. This manual backup protects the per-component
snapshot times, not subsequent mutations. Observed 46-second local DB restore does
not include obtaining images, secrets, S3 recovery, application startup or operator
response time. Full-platform RTO is therefore **unmeasured**; bucket-loss RPO is not
covered by the inventory.

Proposed starting policy, **not enabled**: metadata backup daily and immediately
before migrations/major loads, checksum/authentication verification every backup,
seven daily and four weekly encrypted generations in independent storage, monthly
isolated restore drill and an additional drill after schema/runtime changes. Delete
old generations only after a newer verified recovery and independent retention check;
no automatic retention deletion was added. Initially target metadata RPO ≤24 h and
local DB recovery ≤15 min as planning goals, not guarantees. S3 and secrets need their
own agreed coverage before calling these full-platform objectives.

Before Stage 8D: repair Stage 8B publication in its own explicitly authorized commit,
confirm actual remote CI for the eventual published code, arrange independent S3
byte/versions protection and separate vault recovery, then drill recovery on another
host with restored API/BI and original encryption-key compatibility. Retain the
explicit PARTIAL verdict until those unverified scenarios are addressed. No claimed
HA, failover, cross-region restore, PITR/WAL recovery or whole-host-loss recovery.

## References

- [PostgreSQL 17 pg_dump: consistent snapshots and custom archive](https://www.postgresql.org/docs/17/app-pgdump.html)
- [ClickHouse Native export/import](https://clickhouse.com/docs/guides/clickhouse/data-formats/binary)
- [SQLite Online Backup API](https://www.sqlite.org/backup.html)
- [Grafana backup scope](https://grafana.com/docs/grafana/latest/administration/back-up-grafana/)
- [Selectel versioning](https://docs.selectel.ru/s3/buckets/versioning/) and [Object Lock](https://docs.selectel.ru/s3/buckets/object-lock/)
- [Authenticated encryption API](https://cryptography.io/en/latest/hazmat/primitives/aead/)
