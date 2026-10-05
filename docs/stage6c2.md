# Stage 6C-2 — Airflow operational hardening and clean replay

## Scope and runtime

Stage 6C-1's architecture is retained: Airflow 3.2.2 LocalExecutor, a dedicated
PostgreSQL 17 database, separate API/scheduler/DAG processor, one-shot bootstrap
and migration. Existing CLIs own ingestion, transforms, DQ, publication and loads.
No Docker socket. No schedule. No new context, platform migration or semantic change.

Inspected `stage6c1.md`, the complete recorded run/task/results evidence, DAG,
command/result adapter, Compose, Dockerfile, bootstrap and offline tests before
this stage. The inherited Spark image already has all necessary additions in its
Dockerfile, including the existing `clickhouse-connect==0.15.0` project pin.

Clean build command: `docker compose --profile airflow build --no-cache football-airflow-api`.
BuildKit reran all custom-image instructions; no running container was patched.
Verified image digest:
`sha256:4f800624c32ebf5fbc44a5c5b9a422cfbb13776dfb131a8622497f5b63fb39d1`.

| Runtime | Verified inside the clean image |
| --- | --- |
| Project Python | 3.10.12, `/usr/bin/python3` |
| Airflow | 3.2.2, isolated `/opt/airflow-venv` |
| Java | Temurin 21.0.12+8 |
| Spark / Scala | 4.2.0 / 2.13.18 |
| Hadoop client + S3A | 3.5.0; AWS SDK bundle 2.35.4 |
| S3 client | boto3 1.40.21 / botocore 1.40.76 |
| PostgreSQL | psycopg + binary 3.3.6 |
| ClickHouse | clickhouse-connect 0.15.0 |
| TLS | Existing system CA bundle present; existing CA/S3 configuration retained |

No-network version/parse tests use `--hostname localhost` and
`SPARK_LOCAL_IP=127.0.0.1` for Spark; this avoids an isolated container hostname
lookup failure without enabling network access. No credentials are needed.

## Restart and health

Updated the services to the clean image, then performed a normal Compose restart
of only Airflow DB/API/DAG processor/scheduler. No volume removal. Before/after
[restart evidence](stage6c2-restart.json) is identical: two historical DagRuns,
120 task records, 61 XCom rows and the one-slot `spark_local` pool persisted.
The DAG was rediscovered unpaused; no import errors. All four services returned
healthy. This restart occurred with no running or queued DAG work.
After the clean replay, the explicit idempotent `run --rm football-airflow-init`
command also passed. A second normal restart preserved the new clean run as well:
four total DagRuns, 240 task records, 122 XCom rows. The new run's states/timestamps
remain unchanged; all four services again became healthy.

The PostgreSQL healthcheck uses `pg_isready`; scheduler and DAG processor use
their Airflow 3 job checks; API uses `/api/v2/monitor/health`. Also verify
`airflow db check`, empty `dags list-import-errors`, and actual recent heartbeats:
an HTTP 200 by itself is not proof every component is healthy.

## Graph, params and concurrency

The original 60 named tasks/dependencies remain intact. TaskGroups keep source,
Bronze, each Silver/Gold dataset, serial ClickHouse preflight/load pairs, and
serving/application validators visible. DAG documentation now explains parameters,
authoritative state, reuse and resume directly in the UI. No dynamic mapping.

Both required params are positive UInt32 integers; there is no context default.
Airflow rejects missing/non-integer params before creating a run. Project context
checks additionally guard every runtime step. Unknown but range-valid IDs stop
in public-source preflight before Bronze.

`max_active_runs=1` applies across **all** contexts: different contexts cannot run
concurrently. Global task parallelism/active-task limit remain 2. All 20 Spark
check/publish tasks use `spark_local`, one slot each; the pool has exactly one
slot. Lightweight validations use the default pool, not the Spark pool. Serial
ClickHouse loads preserve the existing loader's cooperative global writer lock.
Offline DAG tests verify every Spark task's pool and every lightweight task's
absence from it, not just a representative task.

## Retries and operator resume

Automatic Airflow retries remain **0**. Existing CLIs do not reliably classify
transient vs deterministic failures by exit code. Project HTTP transport handles
bounded retries internally; boto/S3A retain their existing policies. Returned
`transport_retries` counts public HTTP retry messages only, not hidden SDK retries.
The freeze task reports zero new transport retries rather than copying the
source task's count. Airflow attempts and HTTP retries are different metrics.

After a failure, inspect the safe script/exit/exception-class summary and fix the
cause. Never skip a failed DQ/integrity validator or mark it successful manually.

- **Fresh run:** preferred when rechecking source/catalog state is appropriate.
  Supply both IDs and a unique run ID. Existing immutable artifacts, deterministic
  builds and catalog/loader recovery decide reuse. No cleanup is required.
- **Retry/clear failed tasks:** suitable when original frozen inputs/build pins
  are still valid. In the UI select the exact run and failed tasks, include
  downstream failed tasks when needed, and review the selection before Clear.
  The same underlying idempotent jobs perform the work. The DAG run ID is never
  a build identity. Do not clear unrelated historical runs.

The Stage 6C-2 proof uses a fresh run exclusively: no clear, manual individual
rerun, skipped task or pipeline execution outside Airflow.

## Exact operations (PowerShell, repository root)

The approved Spark runtime alias from Stage 6C-1 must already exist; the normal
build uses it. Do not silently replace it with another Spark/Python runtime.

```powershell
docker compose config -q
docker compose --profile airflow build --no-cache football-airflow-api
# Explicit idempotent metadata update; bootstrap and dedicated DB are dependencies:
docker compose --profile airflow run --rm football-airflow-init
docker compose --profile airflow up -d football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow ps --all football-airflow-db football-airflow-init football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow exec -T football-airflow-scheduler airflow db check
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-import-errors
docker compose --profile airflow exec -T football-airflow-scheduler airflow pools list
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags unpause statsbomb_context_pipeline

Start-Process 'http://127.0.0.1:18080'
# Existing local user airflow; retrieve password to clipboard only if needed:
docker compose --profile airflow exec -T football-airflow-api /usr/bin/python3 /opt/airflow/config/bootstrap.py ui-password | Set-Clipboard

@'
import json, subprocess
subprocess.run(['airflow','dags','trigger','statsbomb_context_pipeline',
                '--run-id','manual__9_281_operator_clean_replay',
                '--conf',json.dumps({'competition_id':9,'season_id':281})],check=True)
'@ | docker compose --profile airflow exec -T football-airflow-scheduler python -

docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-runs statsbomb_context_pipeline --output json
docker compose --profile airflow exec -T football-airflow-scheduler airflow tasks states-for-dag-run statsbomb_context_pipeline manual__9_281_operator_clean_replay
# Only SELECT against Airflow's own metadata; inspect failed tasks of that exact run:
docker compose --profile airflow exec -T football-airflow-db psql -U airflow -d airflow -c "SELECT task_id,state,try_number FROM task_instance WHERE run_id='manual__9_281_operator_clean_replay' AND state IN ('failed','upstream_failed') ORDER BY task_id;"
# Open that run/task in the UI -> Logs for the safe diagnostic and parsed result.

# Perform restart/stop only after task processes drain. Keep all volumes:
docker compose --profile airflow restart football-airflow-db football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow stop football-airflow-scheduler football-airflow-dag-processor football-airflow-api football-airflow-db
```

Use a new run ID on each trigger. `airflow dags unpause` may print the previous
paused value while applying the update; confirm the current state in UI/metadata.
`restart` retains containers, image, volumes and credentials; source/image changes
require rebuild + `up -d` between runs. The initialization/migration command is
repeatable and never resets database state. Do not print resolved Compose config.

## Verification and parameter failure evidence

481 offline Python tests, two no-network Airflow parse/runtime tests and all eight
Spark synthetic suites (97 tests) passed on the clean image. Extended parse tests
verify missing/non-integer params and all 20 Spark pool assignments. Compose config
and diff whitespace checks pass. No frontend/API code changed, so their unrelated
test suites were not rerun; existing API validation is part of the actual DAG.

Live CLI trigger cases (captured errors, no raw configuration output):

| Case | Result |
| --- | --- |
| Missing competition_id | Rejected, exit 1, no DagRun |
| Missing season_id | Rejected, exit 1, no DagRun |
| competition_id="9" | Rejected, exit 1, no DagRun |
| Context 9/4294967294 | Valid UInt32 range; failed on source preflight; no Bronze/downstream work |

The unknown-context run is `manual__stage6c2_unknown_context_20261005`.
It is a safe absent-source test, not another onboarding. Source preflight only
reads public catalog data. The fresh platform baseline was captured afterwards.

## Clean replay and before/after evidence

[Fresh baseline](stage6c2-baseline.json) records both contexts' exact Silver/Gold
IDs, all ten serving tables, Bronze/load-catalog fingerprints and every match's
canonical API analysis hash. Global Bronze: 199 rows. Context 9/281: 69 artifacts,
7 Silver and 3 Gold builds, 34 matches. WC: 129 context artifacts, 64 matches.
The one shared competitions file is included in the global fingerprint.

Fresh run: `manual__stage6c2_clean_9_281_20261005T0856`.
It completed **60/60 SUCCESS on attempt 1**, with no manual task intervention,
clear/rerun, skipped tasks or pipeline invocation outside Airflow.
Start/end: **2026-10-05 11:54:24.988–12:07:42.158 Europe/Moscow**
(08:54:24.988–09:07:42.158 UTC); duration **797.169 s / 13m17s**.
All per-task start/end/duration/pool/attempt records and safe results are retained
in [stage6c2-runs.json](stage6c2-runs.json). Automatic task retries/failures: **0/0**.
Four bounded public HTTP retry messages were handled inside project transport.

All seven Silver and three Gold publications returned
`UNCHANGED / ALREADY_BUILT` + `ALREADY_REGISTERED`; all ten CH loads returned
`UNCHANGED / ALREADY_LOADED` + `ALREADY_REGISTERED`. Parent/shared catalog:
two reused, zero uploaded/registered; children: 68 reused, zero downloaded/
uploaded/registered. Deterministic build IDs agree with the fresh baseline.

[After snapshot](stage6c2-after.json) is structurally identical to baseline:
global/scoped Bronze counts/fingerprints, every Silver/Gold ID, load-catalog
fingerprints, ten serving counts and both contexts' complete API hashes agree.

| Serving rows | 9/281 before = after | 43/106 before = after |
| --- | ---: | ---: |
| teams | 18 | 32 |
| players | 460 | 829 |
| match_squads | 1353 | 3244 |
| event_core | 137765 | 234637 |
| pass_events | 39214 | 68515 |
| shot_events | 916 | 1494 |
| matches | 34 | 64 |
| team_match_stats_v2 | 68 | 128 |
| player_match_stats_v2 | 1353 | 3244 |
| match_results | 34 | 64 |

All 34 new-context analysis bodies retain
`63bfc1fe1d54124dad60ba04e6a977e52c5ae1f4d6b97652d98e8f45d240ac4a`.
All 64 WC analysis bodies retain
`b8e15494beecb1a709e3380fa83c2420c09a0aa6cba3993659f67f7056f3408d`.
These hashes use the existing snapshot script's wrapper/order, matching the
Stage 6C-1 normalization. WC build IDs/counts and catalog state are unchanged.

Unknown-context test: 8.349 s, `validate_context` success, `source.preflight`
failed, remaining **58 tasks upstream_failed / attempt 0**. No Bronze write,
Silver/Gold build or ClickHouse load. The three schema-invalid trigger attempts
created zero DagRuns.

## XCom and secret audit

[Audit evidence](stage6c2-audit.json) records the result without secret values.
All **60 successful tasks** push one `return_value`; no other XCom keys. Sizes
in PostgreSQL's JSON text representation: **39–1228 bytes**, mean **281.6 bytes**.
`validate_context` returns just two context IDs; source/freeze add exact SHAs,
ten expected build IDs and counters; dataset tasks add layer/dataset/build ID,
status/catalog/row count; validators return context/step/status/counters.

Root fields are restricted to:
`competition_id`, `season_id`, `step`, `status`, `parent_sha256`, `catalog_sha256`,
`match_count`, `expected_builds`, `transport_retries`, `bronze_max_id`, `layer`,
`dataset`, `build_id`, `row_count`, `catalog`, `downloaded`, `uploaded`, `reused`,
`registered`, `already_registered`. The only nested object is the at-most-ten-entry
`expected_builds` SHA map. Audit validates enums, numeric counters, exact SHA
format and field allowlists. No event/match JSON, files, URLs or credentials.

Secret audit: **PASS** for all 60 clean-run task logs plus XCom contract checks.
Scanned logs internally and printed only aggregate counts: zero credential
assignments, unmasked database-password URIs, signed S3 URLs, bearer/JWT tokens
or auto-generated UI password messages. Real credentials and `.env` were not
read to compare values. This is pattern/contract inspection, not proof against
every conceivable unknown secret encoding. No rotation finding was detected.

All **20** completed Spark-heavy task intervals were compared pairwise: **0
overlap pairs**. Each held exactly one `spark_local` slot. This confirms actual
enforcement in addition to the offline DAG graph/pool tests. Lightweight checks
were allowed to overlap a Spark task.

## Actual UI check — PASS

On 2026-10-05 the operator authenticated directly in the isolated Microsoft Edge
(Chromium) window. No password, token, cookie or browser credential storage was
read, printed or persisted. The host helper `node scripts/check_airflow_ui.cjs`
uses the existing Playwright dependency and a temporary loopback control endpoint.
Inspection navigated the actual rendered UI only: no trigger, clear, retry, mark
state, pause or deletion action was performed.

- `statsbomb_context_pipeline` is visible and enabled, with its understandable
  pipeline name and manual/context/StatsBomb tags.
- Grid and Graph show readable `source`, `bronze`, `silver`, `gold`, `clickhouse`
  and `validation` groups, plus `validate_context`. All seven collapsed graph
  nodes show success for the selected clean run; groups remain expandable.
- Latest run `manual__stage6c2_clean_9_281_20261005T0856` is green (Success), with
  start/end 11:54:24 / 12:07:42 and duration 00:13:17 in the UI's +03:00 timezone.
- Run Details explicitly displays `competition_id: 9` and `season_id: 281`.
  Both context and exact run are identifiable without relying on task naming.
- `validation.application_api` opens the actual Logs tab. Its successful task
  result and `Done. Returned value was:` entry are rendered with safe context
  IDs/status, not a log-fetch error. The previously audited log is accessible
  after the service restart.
- The DAG Documentation panel renders required parameters, authoritative state,
  deterministic reuse, manual trigger/resume policy and local concurrency rules.

Evidence: [Graph](stage6c2-ui-graph.png),
[run status and parameters](stage6c2-ui-run-details.png),
[task Logs](stage6c2-ui-task-logs.png), and [audit summary](stage6c2-audit.json).
The overview's two historical failed runs are the deliberate Stage 6C-1/6C-2
negative-context tests, not failures of the latest clean replay. History was not
cleared to make the overview green. The UI requirement is now satisfied and
Stage 6C-2 is complete.

## Files changed

- `dags/statsbomb_context_pipeline.py`: concise operator-facing DAG documentation.
- `tests/airflow/test_dag.py`: required Param and complete Spark pool coverage.
- `scripts/check_airflow_ui.cjs`: isolated interactive UI verification helper.
- `README.md`: Stage 6C-2 runbook link.
- This document and `stage6c2-{baseline,after,restart,runs,audit}.json` evidence.
- `stage6c2-ui-{graph,run-details,task-logs}.png`: authenticated UI evidence.

No Compose, Dockerfile, transform, loader, Django/React or Superset behavior
changes were needed. `.env`/`keys.txt` remain ignored. No commit or push.

## Airflow metadata retention and backup model

Its dedicated database stores DAG serialization/discovery, run and task states,
attempt/timing history, pool settings and XCom orchestration metadata. Task log
files use the separate log volume. Credentials use the separate secret volume.
Deleting the metadata volume would lose Airflow history, pending work and UI
state; deleting logs/secrets would separately remove their contents.

Platform S3 artifacts, platform PostgreSQL catalogs and ClickHouse builds remain
authoritative and are in different systems/volumes. They do not become invalid
just because Airflow history is lost. A newly initialized Airflow can run the same
existing idempotent CLIs, but its earlier operational history cannot be reconstructed
from green/failed tasks. Preserve all three Airflow volumes. No automatic backup
or volume deletion is introduced in this stage; metadata backups contain sensitive
operational data and must be handled privately.

## Remaining limitations and next stage

Local SimpleAuthManager is development authentication, not production RBAC/HA.
All contexts serialize at DAG level; exactly one local[2] Spark task executes.
Manual external writers must be coordinated separately. Raw subprocess output
is intentionally hidden; CLI summaries and exception classes are the safe operator
interface. No automatic source snapshot upgrades, cleanup or scheduling policy.
The approved Spark base is a local image, so another host must restore that image
or deliberately rebuild/test it. No generic task retry can safely infer transient
failures yet.

Next stage: structured safe CLI result/error classification and approved context/
source update policy, then operator alerting/backup requirements and CI replay
acceptance. Define scheduling only after agreeing a data/source cadence.
