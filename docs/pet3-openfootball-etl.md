# PET-3A: isolated historical OpenFootball ETL

Scope: pinned UCL 2024/25, source-only results, **INCOMPLETE** semantics.
Stage 8C: PARTIAL. This task authorizes **no production** ingestion/deployment,
S3/PostgreSQL writes, migrations or production Airflow execution.

## Architecture and boundaries

`verified local JSON → local content-addressed Bronze → Spark Silver → Spark Gold
→ labelled networkless ephemeral ClickHouse → final readback/receipt`.

The existing publisher modules remain StatsBomb/source-gated; they are not
relaxed to admit another source. Local artifacts reuse SHA-256, manifests,
_SUCCESS, explicit schema/input/build identity, staged writes, readback and
verify-on-replay conventions. PostgreSQL is not used as a scratch registry.
All new storage is under an explicit isolated marker and exclusive single-writer
lock. Published v2 normalization runs on the driver (bounded 1 MiB source); Spark
performs typed DataFrame validation, joins/coverage aggregation and Parquet writes.
This is not a claim of distributed raw-JSON parsing or a generic provider engine.

Source SHA-256: `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6`.
Pin: `openfootball/football.json@e6744429ee395bc86f247348c6184bb08d4eb361`,
`2024-25/uefa.cl.json`, 58305 bytes, CC0-1.0. Exact generating Football.TXT
revision remains unknown. No new download. Original acquisition and a separate
actual local observation are preserved in Bronze; neither is a source revision.

Adapter semantic fingerprint:
`2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b`.

## Schemas and expected records

| Layer/dataset | Rows | Contract |
| --- | ---: | --- |
| Bronze | 1 original JSON | bytes, hash, source manifest, acquisition receipt, observation, licence |
| Silver fixtures | 189 | canonical identity/scope, date-only Date, raw local time, nullable HT/FT/ET/p, source quality |
| Silver participants | 36 | exact source-local participant key/name and scope |
| Silver stages | 3 | league, knockout play-offs, knockout finals |
| Silver rounds | 14 | exact source labels, canonical stage/round IDs and order |
| Silver quality | 394 | fixture ID, diagnostic code, NON_FATAL severity |
| Gold historical_fixtures | 189 | Silver source semantics plus team/stage/round display names |
| Gold competition_participants | 36 | verified participant membership, no invented player/club statistics |
| Gold stage_round_coverage | 14 | fixture/reported/unknown/ambiguous counts and date bounds |
| Gold source_quality | 394 | all source limitations with provenance |
| ClickHouse records | 633 | one physical typed generation, four filtered serving views |

Exact column/type contracts are in `src/openfootball_etl/contract.py`, shared by
Spark and ClickHouse. All datasets carry batch ID, repository/pin/path/hash,
licence, normalized schema 2, coverage/result coverage and capability flags.
Date is a Parquet/ClickHouse Date, never midnight UTC. Kickoff and canonical
regulation/ET/penalty scores remain null. Winner/points are null and standings
eligibility false. No official standings, xG, shots, passes or events are built.

## Data Quality

The [v2 semantics](pet2r-score-semantics.md) are unchanged: 188 source-reported FT
pairs, one UNKNOWN final, two explicit ambiguous ET/p fixtures, zero certified
90-minute/ET/penalty results. The source itself is never repaired.

| Code | Rows |
| --- | ---: |
| KICKOFF_UTC_UNKNOWN | 189 |
| REGULATION_SCORE_UNKNOWN | 188 |
| HALF_TIME_SCORE_MISSING | 10 |
| EXTRA_TIME_SEMANTICS_UNKNOWN | 2 |
| PENALTY_SEMANTICS_UNKNOWN | 2 |
| TIED_PENALTY_PAIR | 2 |
| RESULT_MISSING | 1 |

Hash mismatch stops before writes. Fatal adapter/schema/count/integrity errors
fail closed. Expected non-fatal limitations do not disappear or become zeroes.
File presence alone does not prove season completeness; coverage remains UNKNOWN
and result coverage INCOMPLETE. Existing UEFA NOT_ATOMIC policy is unchanged.

## Atomic publication, replay and failure recovery

Each phase writes a fresh owned attempt directory. Only validated Parquet
readback, row digests, schema/count checks and a completed file inventory permit
_manifest/_SUCCESS sealing and a same-filesystem rename into its immutable phase
path. A cooperative exclusive writer lock spans the coordinator; direct worker
calls require its token. External/manual writers to this isolated store are not
supported. Partial attempts are not published or deleted automatically.

Bronze may remain complete after a later failure. Likewise a complete immutable
Silver/Gold artifact is distinct from a completed serving load; only quality_gate
creates the VERIFIED load receipt after fresh destination reconciliation.
There is no cross-filesystem/database global atomic transaction claim.

ClickHouse writes require an exact dedicated container-name pattern, pinned
image, network=none, no published ports, only tmpfs mounts and the ownership
label `pet3.scope=openfootball-etl`. The container ID is pinned after inspection;
existing production targets are rejected before SQL. Database namespace is
separately allowlisted. Only private schema creation, INSERT and one atomic
EXCHANGE TABLES are used; no DROP/TRUNCATE/DELETE is implemented.

All four Gold datasets are inserted into a candidate typed table and checked
against exact exported row digests. One EXCHANGE switches the entire bundle
behind all four views. Partial candidate rows stay invisible to serving; retry
uses another candidate, not append/overwrite. Conflicting existing published
data fails rather than being repaired. Timeout/uncertain EXCHANGE requires a
fresh readback: if the complete generation matches, replay reuses it.

Build identity includes source/semantic content, schema definitions, exact
transform-code hashes and pinned Spark version, not time, host path, run ID,
Parquet filenames or container/database identity. Repeated phases verify existing
file hashes and logical readback; stored first-observation registry/version
snapshots remain immutable. New execution reports are not content versions.
The narrowly scoped `.gitattributes` rule forces LF for these transform files:
their bytes participate in build identity, including on Windows checkouts.

## Operator entrypoint and optional Airflow blueprint

`scripts/openfootball_etl.py` requires explicit source, receipt, store, isolated
container/database and `--confirm-isolated`. `--step` is either all or one of
verify_source → bronze → silver → gold → clickhouse_load → quality_gate.
There are no production defaults or credential parameters. Default confirmation
is denied. Worker scripts are not an alternative publication bypass.

The manual, paused six-task blueprint is intentionally outside production
`dags/`: `src/orchestration/openfootball_historical_dag.py`. It has no import-time
I/O and has required source/receipt/store/container/database params. It is parsed
in an ephemeral Airflow image, **not registered or executed by the running
scheduler**. Deployment to a dedicated executor with Docker access requires
separate review; it is not configured here. Host CLI is the executed control plane.

## Execution and verification evidence

Executed on 2026-11-05, Windows Python 3.12.10 host, existing Spark 4.2.0 image
(`football-ci-spark:8a`, Java 21), dedicated ClickHouse 25.8.23.13-alpine. Spark
containers had network disabled and only the isolated artifact store writable;
the project mount was read-only. The dedicated ClickHouse has no network/ports
and uses tmpfs, not a production volume.

Batch ID (both executions):
`ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc`.

| Execution | Completed UTC | Bronze / Silver / Gold / serving | Final gate |
| --- | --- | --- | --- |
| Initial | 2026-11-05T15:57:24.996691+00:00 | CREATED / CREATED / CREATED / CREATED | VERIFIED |
| Replay | 2026-11-05T15:58:05.005886+00:00 | REUSED / REUSED / REUSED / REUSED | VERIFIED |

Invocation used for these two completed executions (not an instruction to start
an additional run without approval; the named isolated container must first
pass attestation):

```powershell
& 'F:\Soft\Python3.12\python.exe' -I -B scripts/openfootball_etl.py `
  --source data/work/pet2-openfootball/e6744429ee395bc86f247348c6184bb08d4eb361/2024-25/uefa.cl.json `
  --receipt data/work/pet2-openfootball/e6744429ee395bc86f247348c6184bb08d4eb361/acquisition.json `
  --store data/work/pet3-openfootball-isolated `
  --container pet3-openfootball-ch-e5950608cec3 `
  --database pet3_openfootball_real_12a9a227dfce `
  --confirm-isolated
```

All row counts in the schema table above were observed, not extrapolated.
Bronze contains the original 58305-byte JSON and four metadata/completion files.
All 64 files under Bronze/builds/load receipts have identical SHA-256 values
before and after replay, including Parquet, registry and version ledger.
The ledger contains 190 streams / 190 first versions (189 fixtures and the
season metadata observation); replay creates no additional version. The latter
observation is not a standings dataset or permission to compute one.
Two execution receipts are separate from semantic content/version identity.

Gold logical fingerprints (canonical sorted rows, including batch/provenance):

| Dataset | SHA-256 |
| --- | --- |
| historical_fixtures | `55d66c3f22b571c28d553469032f446b6f47394167f00daa56fbade0276e4b8a` |
| competition_participants | `a77c6cf8918eb4916786e6f69c469c2a4217825e60149062ace74ec40d48cb5a` |
| stage_round_coverage | `2a2f16af9b794aa7909693251312fb071ab977d81688f554efd5e1c23632f06f` |
| source_quality | `842f201eb009f5e9da1d169be2d22a54a4d32214b8d77edfadb7b631fc98dd89` |

### Read-only serving reconciliation

Isolated database for this execution: `pet3_openfootball_real_12a9a227dfce`, in
container `pet3-openfootball-ch-e5950608cec3`. Do not replace it with the running
production container/database. The following are read-only example queries;
the loader's fresh readback additionally checks all exported row digests and
each serving view, schema, uniqueness and counts.

```sql
SELECT dataset, count(), uniqExact(record_key)
FROM pet3_openfootball_real_12a9a227dfce.records
GROUP BY dataset ORDER BY dataset;

SELECT count() AS fixtures, uniqExact(fixture_id) AS unique_fixtures,
       countIf(source_ft_home IS NOT NULL) AS reported_ft,
       countIf(source_ft_home IS NULL) AS missing_ft,
       countIf(regulation_home IS NOT NULL) AS verified_regulation,
       countIf(kickoff_utc IS NOT NULL) AS utc_kickoffs,
       countIf(standings_eligible) AS standings_eligible,
       min(match_date), max(match_date)
FROM pet3_openfootball_real_12a9a227dfce.historical_fixtures;

SELECT code, count()
FROM pet3_openfootball_real_12a9a227dfce.source_quality
GROUP BY code ORDER BY code;
```

Observed: 189 / 189 unique fixtures, 188 reported FT, one missing FT, zero
verified regulation scores, zero invented UTC kickoffs, zero standings-eligible
fixtures. Date range 2024-09-17 through 2025-05-31. Coverage totals reconcile to
189 / 188 reported / one missing / two ambiguous. All 394 diagnostic rows and
their exact distribution above were verified in Gold and ClickHouse.

### Production isolation evidence

Read-only API/catalog/table audits before and after both executions matched
exactly: 98 scoped analysis hashes, 12 existing ClickHouse tables (row counts,
full row-hash multisets, schema and serving build groups), five PostgreSQL
catalog counts/content hashes, and production API/web container IDs, images,
start times and healthy states. Combined audit fingerprint both times:
`325281864e6e9c1c62ff3ea8c67cf11c73abeae44d9081ab7fb143c05276ac6c`.

Local artifacts: `data/work/pet3-openfootball-isolated`; execution receipts are
under `runs/`, sealed outputs under `bronze/` and `builds/`, verified load receipt
under `loads/`. Read-only audit helpers/evidence are under `.tmp/pet3a/`. These
are ignored local runtime artifacts, not source files, CI inputs or independent
backups. No source re-download, S3 access/write, production database write,
existing-service recreation, deployment or production Airflow execution occurred.

### Tests and failure evidence

- Windows Python 3.12.10: OpenFootball unit suites, 66 tests PASS (12 new ETL
  tests plus 54 existing adapter/semantics/remediation tests).
- Linux Python 3.10.12 and 3.12.14: each 1089 offline tests, OK with nine
  Windows-only skips; application regression 61 PASS per version. Skips are not
  counted as executed Windows ACL checks.
- Windows Python 3.12.10 recovery venv: explicit network-guarded S3/database
  compatibility and real Windows ACL/junction suites, 262 tests PASS, no skips.
- Final CI/documentation/security contracts: 67 PASS per Linux Python version;
  repository checks, full-repository Ruff and compileall PASS. New-file and
  existing staged diff/whitespace checks PASS. No frontend or production image
  rebuild was needed: application/UI and existing infrastructure are unchanged.
- Actual Spark synthetic ETL integration: PASS. Failure after the first Silver
  Parquet write leaves no sealed Silver; retry succeeds, then Gold and replay
  verify exact data/files and typed Date/null semantics.
- Actual isolated ClickHouse synthetic integration: three tests PASS, including
  half-insert failure (all four serving views remain empty), successful retry,
  replay and conflicting-replay refusal without changing published rows.
- Actual Airflow DagBag import/dependency check: PASS; six manual linear tasks,
  paused schedule, no import-time network. This is not a production DAG run.
- Existing StatsBomb Spark context integration: two tests PASS, including
  unchanged source-scoped projections, Gold results and v2 metrics.
- Wrong SHA and fatal synthetic self-match stop before destination writes;
  foreign directories/production targets, concurrent writers, tampering and
  overwrites are rejected. Failed attempts/candidates remain private evidence,
  never automatically removed or declared complete.

Ruff, compileall, documentation/security/repository contracts are part of the
local handoff checks. Unit and CI suites use no real dataset. The following
publication review connects the extra integration suites to existing jobs;
no remote CI/publication claim is made before a separately authorized push.

Git HEAD remains `ea8964f2aad121f317aece713cbdbaba6919dc8a`. All 16 new PET-3
source/test/document/configuration files remained unstaged at initial handoff. The pre-existing
licensing-only index tree remains
`5325a3b648515ce11a4a5edddf7943fb2f3a8163`, with both original staged blobs.
Planning documents, the unrelated shortcut, source JSON and PET-2 helpers were
preserved. No main-index staging, commit or push was performed.

## PET-3A publication review and CI integration

The minimal proposed publication unit contains the 16 new PET-3A files, plus
changes to `.github/workflows/ci-integration.yml` and `ci/Dockerfile` (18 files).
Licensing/planning documents, source JSON, Bronze/Parquet, receipts and helpers
are not included. A separate temporary Git index is used; the main licensing
index remains untouched. A full binary patch and tree inventory accompany the
local review evidence, outside the publication tree.

No workflows, jobs, services or production DAGs are added. Existing checks and
Python 3.10.12 / 3.12.14 / Windows 3.12.10 pins are retained:

- CI fast already discovers offline ETL tests and security/completeness contracts.
  The new contracts check integration wiring and reproduce the exact accepted
  batch identity from public hash metadata alone, without the real source file.
- Existing `spark-airflow` job additionally executes
  `tests/spark/test_openfootball_etl.py`: failure/retry/replay and two independent
  synthetic builds with identical logical schemas/counts/row digests. New Parquet
  filenames/physical encodings are not promised to be byte-identical across
  independent builds; reuse of one sealed build remains byte-preserving.
- The same job additionally parses the opt-in DAG with
  `tests/airflow/test_openfootball_dag.py`, retaining existing DAG tests. The
  blueprint stays outside production discovery and is not scheduled/executed.
- Existing `recovery` job additionally creates a fresh labelled networkless
  ClickHouse 25.8.23.13-alpine with tmpfs, no ports/volumes/credentials, and runs
  the three synthetic integration tests. It uses the image already pulled by
  that job, waits for readiness, and stops only its newly captured container ID.
  `--require-isolated` makes absent target configuration a failure, not skipped
  tests. Attestation and namespace gates remain unchanged.
- `ci/Dockerfile` now includes `.gitattributes` in its repository metadata COPY.
  Without this addition, the new checkout/identity contracts would work through
  a local bind mount but fail in an image built solely from the checkout.

The attribute rule matches only `src/openfootball_etl/*.py`; no existing provider,
application, frontend, script or data file changes EOL policy. LF is required
because these transform bytes participate in build identity. A native Windows
Git checkout and both Linux Python runtimes must produce the accepted batch ID.

Clean-checkout validation uses the exact proposed tree, independently cloned
Git metadata and a new index/worktree: no local `.venv`, ignored source dataset,
runtime receipts or temporary helpers are carried into the test source tree.
Only artificial fixtures are used by its Spark/ClickHouse tests. Existing
immutable execution receipts are inspected separately read-only to confirm the
189/36/3/14/394/633 counts, 190 versions and accepted source/batch fingerprints;
the real ETL is not executed again during publication review.

Local clean-snapshot review results (2026-11-05):

| Check | Result |
| --- | --- |
| Python 3.10.12 and 3.12.14 offline regression | each 1089 cases, OK; nine Windows-only skips, not counted as executed ACL checks |
| Targeted Windows Python 3.12.10 OpenFootball suites | 66 PASS |
| Application regression | 61 PASS per Linux version |
| CI/security/documentation contracts | 69 PASS per Linux version |
| Spark 4.2.0 synthetic failure/retry/replay and independent rebuild | 2 PASS |
| Synthetic ClickHouse load/failure/replay | 3 PASS, no skips; exact proposed Bash step exercised using Windows Git Bash/Python 3.12.10 |
| Existing and opt-in Airflow parse/graph suites | 2 existing + 1 new PASS in the pinned image |
| Native Windows checkout and Linux accepted batch identity | exact accepted ID on all tested runtimes |
| Ruff, compileall, repository, Markdown links, actionlint and diff checks | PASS |

Linux execution of the new ClickHouse workflow step awaits remote CI after an
authorized push; do not conflate the local Git Bash execution with a GitHub
runner result. No test gate was disabled. `.gitattributes` changes only the new
transform package; existing tracked files retain their checkout policy.

A fresh read-only production audit during this review again matched the prior
98 analysis hashes, 12 tables, five catalogs and production container identities,
with the same combined fingerprint recorded above. Isolated real ETL receipts
remain exactly two, and sealed data/ledger/batch identity are unchanged. The
original PET-3A Windows recovery/ACL result (262 PASS) is previous-stage evidence,
not a claim that the full ACL suite was rerun for documentation/CI-only changes.

Before any future persistent ingestion, separately approve the target catalog,
schema/migrations, licence/provenance policy, correction/identity review, typed
results-only API, retention/replay ownership and service configuration. Keep
UNKNOWN/INCOMPLETE states and prohibit standings/winner/points derivations until
score semantics and coverage have independent supporting evidence. Neither a
local run nor CI success authorizes production publication or persistence.

Reproducible commands for synthetic-only checks (from project root):

```text
python ci/run_unittest.py discover -s tests -p 'test_openfootball*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
spark-submit tests/spark/test_openfootball_etl.py
python tests/integration/test_openfootball_etl.py --require-isolated
python tests/airflow/test_openfootball_dag.py
```

Spark must be the pinned runtime. The Airflow check expects the existing image's
`/app` mount. ClickHouse integration requires an explicit
`PET3_SYNTHETIC_CLICKHOUSE_CONTAINER` pointing to an attested private networkless
container; without it the three tests are SKIPPED, not passed. Never point them
at production. No synthetic failure flag is exposed by the real ETL CLI.

## Remaining limitations / PET-3B

Verdict: **PET-3A READY for isolated historical ETL**, not production onboarding.

No Django/React integration, production catalog registration, persistent serving
migration or live DAG deployment. This ephemeral ClickHouse has no ports/network
and loses its data when removed; local Bronze/Parquet/manifests remain available
for reproducible reload. Local filesystem artifacts are not an independent backup.
The first integration slice can be a separately approved results-only reader
with explicit UNKNOWN results and source labels, never standings or verified
90-minute scores without additional evidence.
