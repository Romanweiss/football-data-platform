# INFRA-AUDIT-1 — local infrastructure audit, November 2026

Status: **AUDIT READY**, with explicitly unverified UI/ownership items below.
This is an inventory and proposed action plan, **not cleanup authorization**.
No containers were started, stopped, restarted, removed or recreated by this audit.
No images, volumes, networks or existing files were removed. No deployment,
ingestion, migrations, S3 access or football-data.org requests were performed.

## 1. Scope, evidence and preservation

Checked on **2026-11-06**, Windows / Docker Desktop, Docker Engine **29.9.2**.
Docker inventory timestamp: **09:52:45 UTC**; subsequent service and integrity
checks were collected during the same audit. These are observations, not an
atomic snapshot or a continuous monitoring guarantee.

Branch `master`; HEAD and cached `origin/master`:
`d3443f77c24445c3d2fb0978c10d0b57155561e8`.
No publication or remote mutation was requested. PET-3C is published; PET-3D
has not started. Stage 8C remains **PARTIAL**.

The existing index is preserved: only these two licensing documents are staged:

| File | Git blob ID |
| --- | --- |
| `docs/stage9c5-provider-comparison.md` | `fac8b0073dc67bab8f5341b4304036ea78d91e54` |
| `docs/stage9c5-provider-licensing-review.md` | `6fe2394c0dc11ded3199c5e7d75c173d96bc9ddd` |

Existing planning documents and `Learning_projects — ярлык.lnk` are preserved
untracked. The pinned source, Bronze/Silver/Gold files, receipts and index
backups remain local. This report is new and **not staged**.

No `.env`, `.passes`, `keys.txt`, recovery-key material or Bitwarden data was
opened. Neither the USB backup location nor the external plaintext restore
directory was traversed. File sizes for the repository's `backups/` directory
were collected from filesystem metadata only, without opening archives/keys.

### Local evidence appendix (not approved for Git publication)

The ignored directory `.tmp/infra-audit-20261106/` contains:

| File | Evidence |
| --- | --- |
| `docker.json` | Whitelisted metadata for every container, image, volume and network; selected `system df -v` fields; sampled stats |
| `resources-classified.json` | Per-resource classifications, references, reasons and image space estimates |
| `ports.json` | Docker bindings, loopback TCP and bounded HTTP health responses |
| `superset.json` | Safe metadata, configured-engine results, schema checks and semantic validation |
| `airflow.json`, `clients.json` | Read-only DAG/task states and CI activity counts |
| `logs-summary.json` | Error-class/status counts only; no raw logs |
| `files.json` | Metadata-only file counts, bytes and timestamp ranges |
| `artifacts.json` | Public source and sealed ETL artifact hashes; duplicate lockfile hashes |
| `production-fresh.json`, `production-after.json` | Fresh before/after API, ClickHouse and PostgreSQL fingerprints |

The inventory includes full IDs, creation/start timestamps, restart policies,
mounts, networks, exposed/published ports, writable-layer sizes and sampled
CPU/memory. Environment variables, commands, passwords, raw log messages and
complete Docker inspect dumps are not serialized. External host bind paths and
secret mount paths are redacted. The appendix is machine-local operational
metadata; do not automatically publish it, screenshots or diagnostic helpers.

## 2. Docker inventory and classifications

**84 containers: 15 running, 69 exited.** All 15 running containers belong to
football main/CI projects and have healthy checks at observation time.

- Main football project: **17** containers, **13 running + 4 completed init**.
- Isolated football CI project: **2 running** containers.
- Other projects: **65 exited**, all **UNKNOWN / PROTECT**. No authority or
  evidence supports deleting these unrelated resources.

There are no surviving historical preview containers. In particular, no
disposable completed football test container was positively identified for
removal. Completed init/bootstrap containers are retained: deleting their
markers can cause unintended initialization replay in a future Compose run.

In the following table, unqualified service names expand to
`football-data-platform-<service>-1`, except the explicitly named containers.
IDs are shortened display IDs; full immutable IDs are in the local appendix.
CPU and memory are one sample taken during diagnostics, **not idle averages or
capacity commitments**. Exited containers have no live usage sample.

| Container/service | Container ID | Actual image / image ID prefix | State | CPU / MiB | Writable bytes | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| `football-web-prod` | `9e0c8e073664` | `football-web:9c4d-8af030e` / `b2e9855d2477` | healthy | 0.00% / 10.98 | 32768 | KEEP |
| `football-api-prod` | `c62fea7fff11` | `football-api:9b2f-8f77286` / `87192239feef` | healthy | 0.01% / 87.40 | 8192 | KEEP |
| `football-clickhouse` (literal name) | `b41fa7e7438e` | `clickhouse/clickhouse-server:25.8.23.13-alpine` / `b4bcdb3e8014` | healthy | 31.19% / 836.80 | 745005056 | KEEP |
| `football-postgres` (literal name) | `5e3058ff53d2` | `postgres:17.6-alpine3.22` / `ef257d85f76e` | healthy | 0.00% / 20.28 | 36864 | KEEP |
| `football-web` | `14b6cfb720ab` | `football-web:5b` / `9d251986d9c2` | healthy | 0.00% / 174.90 | 2879488 | STOP_CANDIDATE |
| `football-api` | `0a5d42ac4db0` | `football-api:5a` / `08ca59276e88` | healthy | 17.11% / 58.87 | 4096 | STOP_CANDIDATE |
| `football-airflow-scheduler` | `4ed780ef4fc1` | `football-airflow:3.2.2` / `18bc601a1f1d` | healthy | 1.25% / 236.50 | 135168 | STOP_CANDIDATE |
| `football-airflow-dag-processor` | `7fa0f29a0e0b` | same Airflow image | healthy | 0.64% / 146.70 | 135168 | STOP_CANDIDATE |
| `football-airflow-api` | `5b612f9716e6` | same Airflow image | healthy | 0.08% / 259.80 | 135168 | STOP_CANDIDATE |
| `football-airflow-db` | `08efa4f5039e` | `postgres:17.6-alpine3.22` / `ef257d85f76e` | healthy | 0.75% / 32.44 | 24576 | STOP_CANDIDATE |
| `football-superset` (literal name) | `5b38cd98c33b` | `football-superset:6.0.0` / `fe90eca2116e` | healthy | 0.01% / 324.20 | 8192 | STOP_CANDIDATE |
| `football-superset-db` (literal name) | `6e90ea4e7213` | `postgres:17.6-alpine3.22` / `ef257d85f76e` | healthy | 0.00% / 43.82 | 20480 | STOP_CANDIDATE |
| `football-grafana` | `16533a97c3d4` | `grafana/grafana:13.0.1` / `0f86bada30d6` | healthy | 0.60% / 155.10 | 32768 | STOP_CANDIDATE |
| `football-ci-stage8a-ci-postgres-1` (literal name) | `e47d1cf3f904` | `postgres:17.6-alpine3.22` / `ef257d85f76e` | healthy | 2.93% / 72.39 | 20480 | STOP_CANDIDATE |
| `football-ci-stage8a-ci-clickhouse-1` (literal name) | `7d495664f0d4` | `clickhouse/clickhouse-server:25.8.23.13-alpine` / `b4bcdb3e8014` | healthy | 24.31% / 667.00 | 40960 | STOP_CANDIDATE |
| `football-grafana-bootstrap` | `e2e757b57bde` | `football-python-tools:3.12` / `e01feb1501e4` | exited | not applicable | 12288 | KEEP, init marker |
| `football-airflow-init` | `5f2efd89e896` | old Airflow image / `4f800624c32e` | exited | not applicable | 135168 | KEEP, init marker |
| `football-airflow-bootstrap` | `3e316615f00b` | old Airflow image / `4f800624c32e` | exited | not applicable | 24576 | KEEP, init marker |
| `football-superset-init` | `30ff525af1bb` | old Superset image / `66112d1fd7c6` | exited | not applicable | 4096 | KEEP, init marker |

Production and dev Web/API have restart policy `no`. Main database, Airflow
runtime, Superset and Grafana containers use `unless-stopped`. CI and completed
bootstrap containers use `no`. Existing app containers have **no source bind
mounts**, so editing host files does not update their baked-in code.

All running football containers show zero configured CPU/memory limits. They
share the approximately **15.54 GiB** Docker VM budget; this is not a per-service
reservation. Future resource limits need separate workload testing/approval.

Main services share `football-network`. CI uses an internal isolated network
and **tmpfs** databases, not production volumes. No active external CI query
was seen in the sampled PostgreSQL/ClickHouse process counts (both zero).
Stopping CI still discards its synthetic database contents; recheck immediately
before any future action.

### Why both Web/API stacks run

In [compose.yaml](../compose.yaml), dev `football-web` and `football-api` are
unprofiled; prod counterparts belong to additive `app-prod`. Enabling that
profile does **not** exclude unprofiled dev services. Targeted deployments left
both stacks running against the same production serving context. This does not
mean there are two copies of the production data.

The dev images (`5b` / `5a`) are old baked snapshots, not the current Git tree.
Production Web is still `8af030e` and API `8f77286`; PET-3C at current HEAD has
not been deployed. This is expected while PET-3D is not authorized.

Default Compose `8b` image aliases are not the actual deployed image tags.
Do not use a blanket Compose `up` to restore this inspected state: it may select
different tags, include default services or replay init dependencies. Prior
temporary deployment override paths are not durable rollback instructions.

## 3. Ports and local HTTP verification

| Host port | Container port / service | Observation | Required / recommendation |
| --- | --- | --- | --- |
| `127.0.0.1:18090` | Web prod `8080` | `/healthz` and `/api/v1/health` HTTP 200 | KEEP, main UI and same-origin API |
| `127.0.0.1:15173` | dev Web `5173` | `/` and proxied `/api/v1/health` HTTP 200 | optional dev, old baked image |
| `127.0.0.1:18000` | dev Django `8000` | health HTTP 200 | optional dev/direct API |
| `127.0.0.1:18080` | Airflow API `8080` | monitor HTTP 200, DB/scheduler/processor healthy | optional orchestration UI |
| `127.0.0.1:18088` | Superset `8088` | health/login HTTP 200 | optional BI |
| `127.0.0.1:13000` | Grafana `3000` | health HTTP 200, DB ok | optional observability |
| `15436`, all interfaces IPv4/IPv6 | PostgreSQL `5432` | loopback TCP open | keep DB; separately review binding/firewall |
| `18124`, all interfaces IPv4/IPv6 | ClickHouse HTTP `8123` | `/ping` HTTP 200 | keep DB; separately review binding/firewall |
| `19001`, all interfaces IPv4/IPv6 | ClickHouse native `9000` | loopback TCP open | not needed by browser; separate exposure review |
| `15174`, `15175`, `15176`, `18002` | no current Docker binding | loopback TCP closed | former preview/test ports; do not recreate in audit |

Prod API `8000` is internal-only, reached through Web Nginx. Superset/Airflow
metadata databases have no published host ports. CI databases also have no host
ports. Docker metadata and actual TCP/HTTP responses agree for project ports.
Windows listener cmdlets did not enumerate the Docker-forwarded listeners
reliably; their absence in that native snapshot is not evidence of closed ports.
LAN exposure/firewall reachability is **NOT_CHECKED**. All-interface DB binds
are a security-review item, not authorization to recreate containers now.

## 4. Docker storage, volumes, networks and rollback

`docker system df` reports decimal display units, not GiB:

| Resource | Count | Reported size | Reported reclaimable |
| --- | --- | --- | --- |
| Images | 167 unique IDs | 95.5 GB | 25.96 GB, 27% |
| Container writable layers | 84 | 2.502 GB | 1.754 GB, 70% |
| Local volumes | 135 | 19.25 GB | 2.354 GB, 12% |
| Build cache | 1019 records | 64.06 GB | 18.69 GB |

These are **global mixed-project** numbers, not safe football cleanup totals.
Shared image/cache layers must not be double-counted. Deleting Docker objects
does not guarantee immediate equal free space on the Windows host: Desktop
virtual-disk allocation/compaction is separate and was not changed or inspected.

Classification totals from the complete local inventory:

| Kind | KEEP | STOP_CANDIDATE | REMOVE_CANDIDATE_AFTER_APPROVAL | UNKNOWN / PROTECT |
| --- | --- | --- | --- | --- |
| Containers | 8 | 11 | 0 | 65 |
| Images | 24 | 0 | 29 | 114 |
| Volumes | 8 | 0 | 0 | 127 |
| Networks | 5 | 0 | 1 | 30 |

All 1019 global cache records remain **UNKNOWN / PROTECT** pending project/
builder ownership and rebuild-cost review. “Reclaimable” or “dangling” is not a
proof of disposability. Untagged images referenced by stopped initialization
containers are KEEP. Unattributed untagged images remain protected.

### Football persistent volumes: all KEEP

| Volume | Docker-reported size | Role / effect if lost |
| --- | --- | --- |
| `football_clickhouse_data` | 1.536 GB | serving tables/builds; not disposable |
| `football_postgres_data` | 66.44 MB | ingestion/build/load registries and DQ metadata |
| `football_superset_db_data` | 82.4 MB | dashboards, datasets, charts, users and DB configuration |
| `football_airflow_db_data` | 69.05 MB | DAG/run/task metadata |
| `football_airflow_logs` | 16.96 MB | operational evidence |
| `football_grafana_data` | 50.82 MB | Grafana persistent state |
| `football_airflow_secrets` | 273 B aggregate | protected runtime configuration; contents not read |
| `football_grafana_secrets` | 108 B aggregate | protected runtime configuration; contents not read |

All other 127 volumes are UNKNOWN / PROTECT, including anonymous/unattached
volumes. No volume removal is recommended. The ClickHouse writable layer is
about 710.5 MiB; `/var/log/clickhouse-server` reports 733844 KiB (~716.6 MiB).
Different size tools account differently, but logs are the dominant observed
contributor. Do not delete them or change rotation policy without separate
retention approval. A persistent logging/rotation plan can follow this audit.

### Images to retain for rollback and reproducibility

| Reference | Immutable local image ID |
| --- | --- |
| current `football-web:9c4d-8af030e` | `sha256:b2e9855d2477ea20526e200acdb46f466b1e012d13b305c543ce34873225239f` |
| current `football-api:9b2f-8f77286` | `sha256:87192239feefa3221951fbe77faea97140a40925aba669f1f6f4434c675daf40` |
| nearest Web rollback `football-web:9c4d-rollback-8f77286` | `sha256:e975e54603ccc7cb77ce221bb3db49b472b067bd89f12e2e4821dbaec171f498` |
| Web `9b2f-rollback-353a80d` | `sha256:113c69b523e2e47e9c60c89ec58d8e0a6a4af63eb4bbbd6613f1725a3fbd2d3a` |
| API `9b2f-rollback-353a80d` | `sha256:4febf020861fd52f09ad7b62bf0f29087b685f7bbe5d66f7e464a30304c8f63a` |
| API `9b1d-rollback-353a80d` / `8b` | `sha256:154eae261b7b1705ed66dee7f092e692b17cb44b6e8f33d22c5fee9675edccbd` |
| Web `9b1d-rollback-353a80d` / `8b` | `sha256:edc2fe3199a60d55bbff01fb21f21d95f230def0530b12798873dce2778c1753` |

Also retain referenced DB/Airflow/Superset/Grafana images and existing
`football-9c2f-checks:py310-git-edb3bfd`, `py312-git-edb3bfd`, `football-ci-*`
tooling and `football-spark-runtime:6c1-0b540b6bee67`. Their size is not waste by
itself; they support offline reproducibility and checks. An explicit rollback
override must pin **both** inspected Web/API IDs and preserve existing runtime
configuration; generating/replaying that override is outside this audit.

### Conditional image-removal whitelist

These **29** images have named football audit/review/publication/build-stage
provenance, no existing container references and no rollback aliases. They are
candidates only: preserve source/receipts and confirm no future offline
reproduction needs before separate approval. Rebuild is possible in principle,
but exact image-byte reproduction and offline availability are not guaranteed;
there is no verified image export backup.

| Image tag | ID prefix | `df` unique size |
| --- | --- | --- |
| `football-stage9b1-api:audit` | `012b9206c693` | 13.37 kB |
| `football-stage9b1-web:audit` | `01e64466bdd9` | 17.83 kB |
| `football-s3-publication-web:80a84d7c` | `02b2f1348576` | 2.364 kB |
| `football-publication-checks:9cda694200-py312` | `0e002f5abd9c` | 274.8 MB |
| `football-s3-publication-api:80a84d7c` | `10532e2f6351` | 2.215 kB |
| `football-publication-api:9cda694200` | `19e90d8b160f` | 112.9 MB |
| `football-publication-spark:9cda694200` | `23eab65930f4` | 19.75 kB |
| `football-s3-publication-web:9731b8e1` | `34ae9d5b500f` | 2.364 kB |
| `football-web:heatmap-c-review` | `34c9483dab01` | 2.357 kB |
| `football-ci:pressure-review-2946929` | `37f00c9874de` | 5.694 MB |
| `football-publication-checks:9cda694200-py310` | `3daef2c769d4` | 266.3 MB |
| `football-api:heatmap-c-review` | `3e47c49d00c2` | 2.208 kB |
| `football-web:heatmap-d-review` | `42a3867dfd91` | 2.281 kB |
| `football-publication-web:386eaeedc1` | `47a648d2d532` | 416.1 kB |
| `football-web:pressure-review-24946f5` | `4e958fdc630d` | 2.364 kB |
| `football-api:pressure-review-24946f5` | `58157029b4f0` | 2.215 kB |
| `football-publication-airflow:9cda694200` | `5e6097194784` | 383.4 MB |
| `football-web:pressure-review-2946929` | `5e9621fe02de` | 2.364 kB |
| `football-ci:pressure-review-24946f5` | `678fe48768dd` | 5.685 MB |
| `football-publication-web:9cda694200` | `783cc7320ce0` | 433.6 kB |
| `football-publication-api:386eaeedc1` | `8cdee769436e` | 150.6 kB |
| `football-9c2f-audit-web:edb3bfd` | `97eb685aefa6` | 462.9 kB |
| `football-api:heatmap-d-review` | `a958f7ae5578` | 2.132 kB |
| `football-s3-publication-api:9731b8e1` | `afab932f53e4` | 2.215 kB |
| `football-ci:heatmap-c-review` | `e4d38995ffbe` | 15.47 kB |
| `football-9c2f-audit-api:edb3bfd` | `e9fc58b92aee` | 26.21 kB |
| `football-api:pressure-review-2946929` | `f7b3485641c5` | 2.215 kB |
| `football-web-build:9c4d-8af030e` | `f95b5aa0943d` | 542.5 MB |
| `football-stage9b1-ci:py310-audit` | `ff0be30af4f5` | 17.09 kB |

Summed displayed **unique** size is approximately **1.593 GB / 1.48 GiB**.
This is a conditional estimate, not a promised host-space gain; shared layers
and builder retention may retain bytes. Do not add 18.69 GB global cache to it
as if they were independent guaranteed gains.

### Networks

`football-network`: KEEP, 13 running main containers.
`football-ci-stage8a_isolated`: KEEP, internal, two CI databases.
Docker's three default networks: KEEP.
`pet3c-preview-ed3178075abf`: **REMOVE_CANDIDATE_AFTER_APPROVAL**, internal,
zero attached containers, matched to the retained preview receipt. Negligible
disk benefit; recreating network configuration is possible, not restoring its
original identity. Thirty other networks remain UNKNOWN / PROTECT.

## 5. Superset diagnosis: data not lost; UI complaint not reproduced

Both Superset and its PostgreSQL container are healthy. The existing metadata
contains **1 database, 12 datasets, 16 charts and 2 dashboards**:

- ID 1: **World Cup 2022 Overview**, charts 1–8, Stage/Date/Team filters.
- ID 2: **Match Analysis**, charts 9–16, qualified single Match filter.

Both dashboards have `published=false`. This may affect non-admin visibility;
it does not prove deletion or explain an already-visible empty chart.

The **actual configured Superset engine** (`clickhousedb+connect`) connected to
the existing ClickHouse database successfully. Its readonly setting is **1**;
the reader grant is SELECT on `football.*`. DML/CTAS/CVAS are disabled. All
12 physical dataset references and their expected columns exist; no missing
physical columns were found.

| Dataset/reference | Rows |
| --- | --- |
| `matches` | 98 |
| `bi_team_match_stats` | 196 |
| `bi_player_match_stats` | 4597 |
| `match_results` | 98 |
| `bi_match_overview` | 98 |
| `bi_match_team_stats` | 196 |
| `bi_match_player_stats` | 4597 |
| `bi_match_shots` | 2410 |
| `bi_match_xg_race` | 2369 |
| `bi_match_shot_map` | 2369 |
| `bi_match_shootout` | 41 |
| `bi_match_xg_race_series` | 4738 |

The published semantic validator passed against that configured engine:
**8 overview chart cases, 40 match-analysis selection cases, 2 native-option
cases**; contexts include 64 WC and 34 Bundesliga matches. WC overview totals
are 64 matches, 1453 non-shootout shots, 68515 passes and xG 155.8985419302.
Superset metadata inspection used a read-only transaction with rollback;
startup theme synchronization and query audit INSERTs were disabled only in
the diagnostic process. No users, configuration, metadata or charts were
persistently modified.

Important expected behavior, not data corruption:

1. The Overview is deliberately **WC2022-only**, not all competitions.
2. Match Analysis requires exactly one qualified competition/season/match
   identity. Missing/multiple/invalid selections deliberately produce an empty
   result (`0=1` safety); default is Argentina–France final.
3. Bundesliga fixtures have no shootout events. The shootout chart being empty
   there is correct. Non-shootout maps/races exclude 41 shootout shots from the
   2410-shot total, leaving 2369.
4. OpenFootball historical results are not in production ClickHouse or these
   datasets. PET-3D has not deployed their serving path.

| Failure hypothesis | Audit finding |
| --- | --- |
| Missing dashboards/metadata | NOT reproduced: 2 dashboards/16 charts retained |
| Broken database connection | NOT reproduced through actual configured engine |
| Reader permission failure | NOT reproduced; readonly SELECT queries passed |
| Missing tables/columns or semantic SQL mismatch | NOT reproduced in validated cases |
| Filter scope excluding expected data | Plausible; documented intentional gates above |
| Browser rendering, user-role permissions or stale user filters | **NOT_CHECKED**; requires affected chart/browser session |

Logs were summarized in memory with redaction: last 72 hours, maximum 1200
lines per service. Superset sample is dominated by HTTP health 200 responses;
no sampled ClickHouse codes or listed query exception classes were found.
This bounded sample does not prove absence of older/UI-specific errors.
Early diagnostic helper incompatibilities were corrected in the local helper;
they were not reproducible Superset backend faults.

**Root cause of the user's missing-data report remains UNDETERMINED.** Next
diagnostic input: affected dashboard/chart name or URL, selected match/filter
state, user role and a redacted browser error/screenshot. Do not clear caches,
publish dashboards, refresh datasets or rerun init/migrations without evidence
and separate authorization.

## 6. Airflow and Grafana

Airflow API/DB/scheduler/DAG processor health and heartbeats passed. Three
installed DAGs are present:

| DAG | Paused | Schedule / active-work finding |
| --- | --- | --- |
| `platform_dq_validation` | yes | weekly schedule; no active run |
| `statsbomb_source_discovery` | yes | weekly schedule; no active run |
| `statsbomb_context_pipeline` | no | `schedule=None`, manual; no active run |

Queued/running DAG runs: **0**. Historical runs: 2 success, 2 failed; task
instances: 122 success, 2 failed, 116 upstream_failed. Historical failures are
not current activity. Scheduler log sample includes three historical
`OperationalError` occurrences; current health is good, and no corruption
conclusion follows. The OpenFootball DAG is in published source but is not
installed in this older running Airflow image; expected before deployment.

For static UI consumption no scheduler/API/processor is required. They can be
STOP_CANDIDATE when no jobs are running; their database/log/config volumes must
remain. Recheck active runs/tasks and operator intent immediately before a
future stop. Do not change schedules or unpause DAGs as part of startup.

Grafana health: HTTP 200, database ok, version **13.0.1**. Repository provisioning
defines datasource UID `football-metadata-dq` (PostgreSQL reader) and dashboard
UID `football-platform-dq`, version 1, **15 panels**, not editable. The runtime
has the expected read-only provisioning/dashboard mounts. PostgreSQL reports
four SELECT relation grants for `grafana_reader`.

Unauthenticated Grafana dashboard API returns **401**. Actual authenticated
dashboard/datasource inventory is **NOT_CHECKED**: no password file was read,
account created, database copied or diagnostic package installed. Provisioned
source is evidence of intended configuration, not proof that every dashboard
renders for the operator. Grafana is optional for the React product and can be
stopped separately while retaining its volume.

## 7. Project filesystem and candidate provenance

Metadata-only initial scan (new audit evidence increases `.tmp` slightly):

| Path | Bytes / files | Classification and retention |
| --- | --- | --- |
| `.tmp` | 337328616 / 22301 | mixed snapshots, index backups, evidence; **not blanket disposable** |
| `.ruff_cache` | 19902 / 30 | reproducible cache, conditional cleanup; negligible |
| `.venv` | 73326165 / 4557 | KEEP, recovery runtime; rebuild requires pinned dependencies |
| `frontend/node_modules` | 133968161 / 4097 | KEEP for active development; reproducible from lockfile |
| `frontend/test-results` | 1779438 / 12 | preserve unique acceptance evidence pending retention review |
| `frontend/dist` | 386411 / 3 | reproducible build output; conditional cleanup only if no preview uses it |
| `backups` | 388692633 / 62 | PROTECT, three local database backup generations; not duplicate waste |
| `data` | 216743074 / 150 | PROTECT, pinned source and deterministic ETL artifacts |
| `.git` | 7247277 / 2240 | KEEP, source history/index/objects |

Largest `.tmp` groups:

| Group | Bytes | Origin / retention consequence |
| --- | --- | --- |
| `pet3c-review-e5453d273051` | 145760218 | clean-checkout React review; retain evidence/index-related files |
| `pet3c-review-8c548989082c` | 145741849 | earlier React review; same caution |
| `pet3b-review-8effd75d4491` | 12229836 | API review snapshot; do not discard unique receipts blindly |
| `pet3-review-ddd2d53b96f5` | 12098173 | ETL review snapshot |
| `pet3-review-d32c7e8c008d` | 12091049 | ETL review snapshot |
| `stage8ar-checkout-6203cd91f8464d279c63bb2ab4002949` | 6716050 | recovery review evidence; PROTECT until separate retention review |
| `pet3c-publish-27546bd8d529` | 956637 | publication/index backups; **PROTECT** |

Timestamp ranges are in the appendix. Snapshot dependencies include older npm
package timestamps; copied dependency timestamps do not date the review itself.
No file is disposable merely because it is old.

The specific reproducible duplicate candidates are only:

- `.tmp/pet3c-review-e5453d273051/snapshot/frontend/node_modules`
- `.tmp/pet3c-review-8c548989082c/snapshot/frontend/node_modules`

Each has **133968161 bytes**. Combined logical bytes: **267936322 (~255.5 MiB)**.
Their package-lock files and the main lockfile all hash to
`813c4a2c703580188e312e3724de3426fb22a199a6292d954d9af0caf32cb4c9`.
This demonstrates a shared pinned dependency specification, not byte-for-byte
identity of every installed file. Removal would require `npm ci` and package
availability to rerun those snapshots; the main dependency tree is retained,
but no dependency archive backup was verified. Preserve the parent snapshots,
receipts, screenshots and index backups. No deletion has been performed.

Host storage metadata only: C: NTFS Healthy, **82298490880 bytes free**
(~76.65 GiB); F: NTFS Healthy, **48057430016 bytes free** (~44.76 GiB).
No K: query or external restore-directory inspection was made.

### Docker build contexts

[.dockerignore](../.dockerignore) excludes local environment/credential files,
keys/certificates, backups, `.tmp`, `.git`, venvs, dependencies, test outputs and
non-synthetic `data/`. Web copies frontend source/lockfiles; production Web
copies the build stage's `dist`, not host screenshots/node_modules. API copies
application, selected common code and API requirements/scripts. Context size
must not be equated with total workspace size. Exact transmitted context bytes
were **NOT_CHECKED**: no build or tar upload was needed for this audit.

## 8. Fresh data-integrity baseline

Fresh read-only checks were performed before and after the audit and compared
with the retained PET-3A production baseline. All three data sections match
exactly: **98/98 analysis hashes, 12/12 physical ClickHouse tables including
schema/full-row hashes and build groups, and 5/5 PostgreSQL catalogs**.
Production Web/API IDs, start times and health also match within this audit.
Compared with older evidence, start times differ because the environment had
already restarted before the audit; this is not a data fingerprint mismatch.

| Physical ClickHouse table | Rows |
| --- | --- |
| `event_core` | 372402 |
| `pass_events` | 107729 |
| `shot_events` | 2410 |
| `teams` | 50 |
| `players` | 1289 |
| `match_squads` | 4597 |
| `matches` | 98 |
| `team_match_stats` | 128 |
| `player_match_stats` | 3244 |
| `team_match_stats_v2` | 196 |
| `player_match_stats_v2` | 4597 |
| `match_results` | 98 |

There are **22 table/context build groups**. Legacy team/player stats have one
WC group each; other tables have WC2022 and Bundesliga-subset groups. Source
and serving build identities and hashes are preserved in both fresh evidence
files, not substituted with old values.

PostgreSQL catalogs: `ingestion_objects` 199; `silver_builds` 14; `gold_builds` 8;
`clickhouse_loads` 14; `clickhouse_gold_loads` 8. All five hashes match.

### Historical OpenFootball artifacts

The existing public pinned JSON was hashed locally; no redownload:

- 58305 bytes; upstream commit `e6744429ee395bc86f247348c6184bb08d4eb361`.
- Source SHA-256: `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6`.
- Normalized fingerprint: `2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b`.
- Batch ID: `ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc`.
- Existing Bronze/Silver/Gold seals and file hashes: **PASS**, respectively
  3/12/16 manifest-listed files. This ran verification functions, not ETL.

| Gold table | Rows | Row SHA-256 (matches published API pin) |
| --- | --- | --- |
| `historical_fixtures` | 189 | `55d66c3f22b571c28d553469032f446b6f47394167f00daa56fbade0276e4b8a` |
| `competition_participants` | 36 | `a77c6cf8918eb4916786e6f69c469c2a4217825e60149062ace74ec40d48cb5a` |
| `stage_round_coverage` | 14 | `2a2f16af9b794aa7909693251312fb071ab977d81688f554efd5e1c23632f06f` |
| `source_quality` | 394 | `842f201eb009f5e9da1d169be2d22a54a4d32214b8d77edfadb7b631fc98dd89` |

Temporary historical serving containers are absent and preview ports closed.
This is a runtime-availability gap, not evidence of lost Gold files. Keep local
run/load receipts; restoring a temporary serving target would require a
separate authorized operation, not a second source acquisition.

### Stage 8C boundary

Documentary status from the published [recovery closure](stage8c-r2-4a2-4c.md):
S3 current-object backup and isolated local recovery **VERIFIED**, overall
Stage 8C **PARTIAL**. Recorded session
`20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`: 315 objects,
356383409 plaintext bytes, 22 empty objects; archive 319 files / 357278273 bytes.
This audit did **not** reauthenticate the archive, inspect the USB medium,
read any key, revisit plaintext recovery data or prove offsite/fresh-machine
recovery. Prior evidence is explicitly documentary here.

## 9. Proposed operating modes — commands NOT EXECUTED

### A. Minimal running mode

Recommended **4 containers**: main production-like Web/API, ClickHouse and
PostgreSQL. Strict HTTP serving uses three, but retaining the inexpensive
PostgreSQL registry/provenance service is recommended. UI: `18090` only; no dev,
Airflow, Superset or Grafana UI. All eight football volumes and all rollback
images remain. PET-3C historical UI/API availability is not added by this mode.

Observed aggregate memory of these four: **955.46 MiB (~0.93 GiB)**, versus
3127.18 MiB (~3.05 GiB) for all 15. Optional sample difference:
**2171.72 MiB (~2.12 GiB)**. These are sample process memory totals, not guaranteed
host RAM savings; database caches and workload change over time.

Only after separate authorization, fresh active-run/client checks and explicit
loss acceptance for CI tmpfs, the following is a proposed ordered stop list:

```powershell
# PROPOSAL ONLY — not executed by INFRA-AUDIT-1.
docker stop football-data-platform-football-web-1 football-data-platform-football-api-1
docker stop football-ci-stage8a-ci-postgres-1 football-ci-stage8a-ci-clickhouse-1
# Scheduler first; ensure zero running/queued tasks before stopping workers/API.
docker stop football-data-platform-football-airflow-scheduler-1
docker stop football-data-platform-football-airflow-dag-processor-1 football-data-platform-football-airflow-api-1
docker stop football-data-platform-football-airflow-db-1
docker stop football-superset
docker stop football-superset-db
docker stop football-data-platform-football-grafana-1
```

To start the inspected existing core later, do not recreate it:

```powershell
# PROPOSAL ONLY. Verify identity/configuration first; abort on unhealthy status.
docker start football-postgres football-clickhouse
docker inspect --format '{{.State.Health.Status}}' football-postgres football-clickhouse
# Wait for BOTH databases healthy before the next command.
docker start football-data-platform-football-api-prod-1
docker inspect --format '{{.State.Health.Status}}' football-data-platform-football-api-prod-1
# Wait for API healthy before starting Web.
docker start football-data-platform-football-web-prod-1
docker inspect --format '{{.State.Health.Status}}' football-data-platform-football-web-prod-1
```

Starting already-existing containers does not apply new source code. Do not run
init/bootstrap or general Compose workflows as an implicit part of this plan.

### B. Development mode

Core four plus dev Web/API, Airflow four, Superset two and Grafana: **13 running**
containers, approximately **2387.79 MiB** in the observed sample. Optional CI two
bring it back to 15 / 3127.18 MiB only while synthetic tests need them. UIs:
`18090`, `15173`, `18000`, `18080`, `18088`, `13000`. All persistent volumes stay.
Existing dev images remain old until a separately authorized targeted build;
starting them alone does not deploy PET-3C.

Proposed start sequence, after core health checks above:

```powershell
# PROPOSAL ONLY — inspect expected image IDs and active work first.
docker start football-data-platform-football-api-1 football-data-platform-football-web-1
docker start football-superset-db football-data-platform-football-airflow-db-1
docker inspect --format '{{.State.Health.Status}}' football-superset-db football-data-platform-football-airflow-db-1
# Wait for metadata DBs healthy. Scheduler remains off until explicit intent.
docker start football-superset football-data-platform-football-grafana-1
docker start football-data-platform-football-airflow-api-1 football-data-platform-football-airflow-dag-processor-1
docker inspect --format '{{.State.Health.Status}}' football-data-platform-football-airflow-api-1 football-data-platform-football-airflow-dag-processor-1
# Only if orchestration is desired and task/schedule state was reviewed:
docker start football-data-platform-football-airflow-scheduler-1
# Optional synthetic CI: prior tmpfs contents are NOT restored by starting.
docker start football-ci-stage8a-ci-postgres-1 football-ci-stage8a-ci-clickhouse-1
```

Stop optional groups in the sequence listed for Minimal mode. Manual app starts
need fresh health checks; no password reads or CLI secret arguments are required
for the lifecycle commands. Bootstrap state is not an instruction to rerun it.

## 10. Ordered cleanup manifest — separate approval required

| Order / resource | Type / size | Reason | Risk / reversibility | Proposed action |
| --- | --- | --- | --- | --- |
| 1. Completed temporary football tests | container / none positively identified | no surviving eligible disposable container | init replay risk; foreign objects protected | **No removal**; keep four initialization markers |
| 2. Eleven optional containers listed above | runtime / 2171.72 MiB sampled RAM | UI/CI/orchestration not needed for static product use | stop reversible; CI tmpfs contents are lost | approve exact stop list, recheck activity, stop only those names |
| 3. Global cache | builder / 64.06 GB, 18.69 GB reported reclaimable | possible build acceleration leftovers | mixed-project ownership, rebuild time/network, no verified export | **hold**; establish disposable builder/record scope before any prune proposal |
| 4. Image whitelist above | 29 IDs / ~1.593 GB summed unique display bytes | obsolete football review/build intermediates | rebuilding requires source/dependencies; image bytes not backed up | approve immutable-ID whitelist, recheck references/aliases and rollback protection; no blanket dangling removal |
| 5. Empty preview network | network / negligible | retained receipt identifies old preview, zero members | recreation possible, identity changes | remove by exact ID only after fresh emptiness check and approval |
| 6. Two review `node_modules` directories only | files / 267936322 bytes | duplicate locked test dependencies | npm restore required; preserve receipts/index backups/parent snapshots | validate exact absolute paths under workspace and approve targeted removal |
| 7. `.ruff_cache`, unused `frontend/dist` | files / 406313 bytes combined | reproducible cache/output | lint/build rerun; inspect active preview first | optional, negligible benefit |
| Never by default: all volumes, backup generations, source/ETL/evidence/index backups, foreign resources | persistent / protected | provenance, recovery and reproducibility | potentially irreversible | KEEP / UNKNOWN / PROTECT |

No guaranteed Docker host-space recovery amount is established. The clearest
low-risk logical-file estimate is **255.5 MiB** for temporary dependencies,
plus ~0.39 MiB negligible outputs; image space is conditional. Global Docker
reclaimable totals are not an approved cleanup plan. Do not run system/volume
prune, remove all dangling images, delete `.tmp` wholesale or compact the Docker
virtual disk as an unreviewed shortcut. Never start with volume deletion.

## 11. PET-3D entry criteria and unresolved items

1. Separate deployment authorization; preserve current Web/API image IDs,
   volumes and a durable reviewed rollback override (not only a temp path).
2. Reverify published PET-3C image content and current 98/12/5 fingerprints
   immediately before/after future deployment; retain non-secret evidence.
3. Provide historical serving availability through an explicitly isolated,
   controlled Gold-to-serving load/persistence design. Current preview tmpfs
   services are absent; do not point at production CH blindly or bypass
   historical API opt-in/source identity gates. No source reacquisition is needed.
4. Review results-only semantics and 394 DQ limitations; unknown/ambiguous
   scores must not become asserted regulation scores or standings inputs.
5. Recheck zero active Airflow/CI work before any lifecycle change. Keep
   ingestion and production persistent schemas/data outside this audit's scope.
6. Review all-interface DB port exposure separately; LAN/firewall and resource
   limits remain unverified policy items, not silently applied changes.
7. Obtain a concrete affected Superset chart/filter example for browser-level
   diagnosis. Authenticated Grafana inventory also remains NOT_CHECKED.
8. Keep football-data.org persistent onboarding **BLOCKED /
   LEGAL_REVIEW_REQUIRED**. OpenFootball and synthetic/API-observation provenance
   remain separate. Stage 8C remains **PARTIAL**.

## 12. Validation and conclusion

- Fresh before/after production fingerprints: **PASS**, 98 analyses / 12
  physical tables / 5 registries; build groups unchanged, 22 total.
- Pinned source and sealed Bronze/Silver/Gold verification: **PASS**.
- Superset configured reader/schema/semantic checks: **PASS**; operator UI
  symptom/root cause **UNDETERMINED**, not claimed repaired.
- Existing repository/workflow/publication/private-artifact/secret-signature
  contracts: **PASS**, host Python 3.14.3. This is not a Python runtime migration.
- Documentation contracts: **5 tests PASS**. New report additionally checked
  for local link targets and high-confidence secret signatures.
- Working-tree and staged whitespace checks: **PASS**. No source-code changes,
  functional rebuild or full regression run was required for this local audit.

**AUDIT READY** for an operator decision about the exact Minimal-mode stop list
and a separately approved cleanup whitelist. **No cleanup, deployment or
PET-3D execution has been authorized or performed by this report.**
