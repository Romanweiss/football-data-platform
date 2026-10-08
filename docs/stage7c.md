# Stage 7C — conservative scheduling and platform alerts

Stage 7C adds monitoring orchestration and persisted incident state, not another
ETL implementation. PostgreSQL platform metadata remains authoritative. Airflow
invokes platform functions; Grafana displays persisted DQ. No football formula,
DQ rule, immutable build identity, API, frontend or Superset behavior changes.

## Scheduling policy

[StatsBomb Open Data](https://github.com/hudl/open-data) publishes selected JSON
competitions/seasons, matches, events and lineups. It is not a contracted real-time
feed. Weekly cadence is this project's conservative policy, **not** a claim about
the publisher's update frequency or a freshness/availability SLA.

| DAG | Policy | Purpose |
| --- | --- | --- |
| `statsbomb_context_pipeline` | Manual; unchanged 60 tasks | Explicitly approved ingestion/build/load/replay |
| `statsbomb_source_discovery` | Sunday 04:00 UTC / 07:00 Moscow | Small source snapshot and review recommendation |
| `platform_dq_validation` | Sunday 05:00 UTC / 08:00 Moscow | Existing serving/catalog/API validators; no rebuild |

The two new DAGs start from `2026-10-09T00:00:00Z`, use explicit UTC,
`catchup=False`, one active run, one active task, and zero Airflow task retries.
Source discovery has a ten-minute task timeout; DQ has fifteen minutes. Both are
**paused upon creation**. Inspect the Airflow UI for the next actual run time:
cron timetable/data-interval behavior, not host-local time, determines scheduling.
No historical backfill is useful here. Source/DQ schedules are independent;
DQ does not depend on a successful source check. Failed discovery is not a reason
to rerun the full pipeline. Static historical 43/106 and 9/281 do not need weekly
60-task replays just to produce green history.

### Lightweight source discovery

One public catalog GET plus one matches GET per registered context; existing
bounded, transient-only HTTP retries remain responsible for TLS EOF recovery.
No event/lineup scan, S3 access, ingestion, Spark, publication or automatic DAG
trigger. The current inventory requires three successful GETs total.

Persist the raw catalog SHA-256 and canonical per-entry SHA-256; for registered
contexts also persist the raw matches SHA-256. First observations are BASELINE,
then NEW / UNCHANGED / CHANGED; absent prior/registered entries become MISSING.
The first registered matches snapshot is also compared with its catalogued Bronze
parent SHA. Recommendations list up to twenty NEW/CHANGED/MISSING contexts and
require explicit human review. Initial unknown historical entries are a baseline,
not eighty requests to onboard new contexts. No changes are automatically adopted
into existing immutable builds. A source outage aborts snapshot persistence: it
does not turn an incomplete fetch into a false MISSING snapshot.

### Registered contexts and scheduled DQ

Discover StatsBomb contexts from authoritative platform PostgreSQL: complete
load registration for seven Silver and three Gold datasets, plus previously
full-DQ-observed contexts with a registered Silver build. The latter preserves a
known context when a load registration accidentally disappears. Not API guesses,
source catalog availability, hardcoded context IDs or Airflow XCom.

An explicit exclusion is `PLATFORM_DQ_EXCLUDED_CONTEXTS=43/106,9/281` (example
only; default empty). There is no platform active/archive flag yet; this
configuration is the explicit operational exclusion policy. Invalid exclusions
and inventories over 100 contexts fail safely instead of silently truncating.
The public catalog is bounded at 1000 unique contexts.

For each discovered context, execute existing `references`, `gold`, `api` suites
and append their real normalized DQ executions. These checks read catalog,
ClickHouse and API, not Bronze/Silver/Gold S3 objects. They do not run `results`
or WC2022 golden checks, because those include source/deeper snapshot work.
Current coverage is 40 checks/context; it is **not** a replacement for full DQ.
Grafana latest-full health remains separate from partial validation history.

Acquire a session context advisory lock and the existing cooperating ClickHouse
loader lock. A busy lock returns BUSY, creates no fake DQ history, does not clear
an incident, and waits for the next cadence/operator retry. Dynamic mapped tasks
also have `max_active_tis_per_dag=1`. These locks protect cooperating platform
jobs, not arbitrary external SQL writers or an atomic cross-database snapshot.

## Alert policy and precedence

`validator → committed normalized DQ → policy evaluation → committed incident
state → optional transport`.

Default `PLATFORM_ALERTS_ENABLED=false`: ordinary DQ still persists, but automatic
incident evaluation/delivery does not run. Explicit alert CLI evaluation is a
separate operator action and does not require this flag.

| Class | Stable classification |
| --- | --- |
| DATA_QUALITY_FAILURE | Non-operational normalized rule failure |
| SOURCE_ACCESS_FAILURE | Operational Bronze dependency failure, or terminal public-source transport failure |
| SERVING_FAILURE | Operational serving/API dependency failure |
| PIPELINE_FAILURE | Other operational DQ failure, or failed pipeline adapter before DQ evidence |

Only **FAIL + ERROR** opens an incident. WARN is visible in persistent DQ/Grafana
but never notifies in Stage 7C; no repetition/escalation policy is invented.
INFO and intentional SKIP never open or deliver. WARN/SKIP do not falsely resolve
an existing ERROR incident. PASS of the same identity resolves it. A later FAIL
after resolution creates a new episode. Recovery messages are **disabled**.

The private pipeline bridge observes terminal operation failures; it does not
alert on an intermediate HTTP retry. Existing transport exhausts its bounded
retries before SOURCE_ACCESS_FAILURE is observed. A persisted DQ gate failure
owns the alert decision and suppresses an additional PIPELINE_FAILURE for that
gate. A successful operation clears prior same-operation source/pipeline issues.
Direct source-discovery CLI uses the same observer. Intentional operational tests
use `test_mode=True`; intentional persisted negative DQ tests must explicitly
disable automatic alerts or use rollback fixtures/direct policy evaluation.
No inference from arbitrary red task status or raw exception messages is used.

### Deterministic dedup and resolution

Version-1 canonical JSON SHA-256 includes class, competition/season (or a global
operation), scope/suite, layer, dataset, rule ID and optional build ID. Timestamp,
execution UUID, run/task ID and human message text do **not** define identity.
Scope/build isolation is intentional: a partial/API PASS cannot silently resolve
an artifact/full-scope failure, and a new build is not assumed to repair an old
build. Revalidate the original scope/build to resolve that incident.

Per-key PostgreSQL transaction advisory locks plus a unique partial OPEN index
serialize concurrent opens. Repeated FAIL updates last_seen and authoritative DQ
link, not a new notification. A `(finished_at, execution_id)` watermark rejects
late/replayed observations, including an old FAIL replayed after PASS resolution.
One incident episode has at most one automatic delivery claim.

### PostgreSQL schema (migration 008)

- `metadata.alert_rule_state`: current observation watermark/status per dedup key.
- `metadata.alerts`: incident episodes, class/context/scope/layer/dataset/rule/build,
  OPEN/RESOLVED, created/last-seen/resolved timestamps, DQ and optional Airflow refs.
- `metadata.alert_delivery_events`: application-append-only STARTED and SENT/FAILED
  events, provider, attempt ID, bounded attempt count and fixed safe reason.
- `metadata.source_discovery_runs` and `metadata.source_discovery_observations`:
  source snapshots/hash classification, not Bronze publication metadata.

Existing metadata migrations/tables are not rewritten. The writer has existing
platform privileges: application append-only history is not a new database-level
immutability/access-control guarantee. Alert state is neither XCom nor Grafana.

## Transport, failure isolation and secrets

Only **local/log** is shipped: `send(notification)` is the thin provider contract.
The inspected public project configuration has no external provider integration;
the real `.env` was not inspected, so no assertion is made about its contents.
No external credentials are requested or silently used. Unsupported provider
configuration records FAILED with provider `invalid`, not the supplied string.

Messages contain local project/environment, incident/class/context, scope,
layer/dataset/rule/build, fixed short reason, timestamp and validated Airflow refs
when present. Local links point to Grafana port 13000 and Airflow port 18080;
they are not public endpoints. Airflow receives bounded typed safe JSON, not raw
driver/subprocess logs. Standalone LogTransport writes to stderr to preserve CLI
JSON stdout. No secrets, env values, DSNs, raw provider errors or stack traces
are rendered/stored. Existing credentials are consumed privately by connection
helpers, never opened/printed by the agent.

Incident and STARTED claim are committed before provider I/O in normal execution;
SENT/FAILED is a later independent transaction. Notification problems never undo
DQ or build commits, nor change a DQ gate decision. The best-effort observer emits
only a fixed unavailable warning when alert-state persistence itself fails.
Clearly typed transient provider failures get at most three attempts with 1s/2s
backoff. Invalid configuration is attempted zero times; permanent/unclassified
provider rejection once. Local-log SENT means emitted to the local sink, **not**
that a human received/read it. No external delivery guarantee is claimed.

Existing STARTED, SENT or FAILED suppresses automatic resending. A crashed worker
with an uncertain STARTED requires investigation; FAILED/uncertain retry tooling
is intentionally not shipped. This favors avoiding notification storms over
guaranteed delivery. Dispatch processes at most ten eligible incidents/invocation;
larger backlogs require explicit subsequent dispatch.
The Airflow bridge shares a ten-claim budget across all its DQ suites/observers,
so a bounded JSON response never silently drops an already-SENT local message.
Unclaimed excess incidents remain eligible for a subsequent invocation.
Transactional acceptance
tests use only the local/mock transport and roll back: never invoke a future
external provider inside an outer rollback transaction.

Grafana remains unchanged/read-only and has no authoritative Grafana Alerting.
Its existing DQ history shows partial executions; there is no new alert-state
panel. Inspect incident/delivery state with the CLI below.

## Operational commands (PowerShell, project root)

Apply only the additive new platform migration (already applied for acceptance):

```powershell
@'
exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/008_create_alert_and_discovery_state.sql;
'@ | docker compose exec -T football-postgres sh
```

Build and deploy only existing Airflow services while no pipeline run is active:

```powershell
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-runs statsbomb_context_pipeline --state running -o json
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-runs statsbomb_context_pipeline --state queued -o json
docker compose --profile airflow build football-airflow-api
docker compose --profile airflow up -d --no-deps football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list -o json
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-import-errors -o json
```

No bootstrap/database reset is needed. Existing manual DAG stays manual and its
existing pause state is preserved. New scheduled DAGs remain paused. After policy
acceptance, enable each separately (do **not** run these merely for verification):

```powershell
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags unpause statsbomb_source_discovery
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags unpause platform_dq_validation
# Suspend future scheduling without deleting data or running Docker down:
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags pause statsbomb_source_discovery
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags pause platform_dq_validation
```

Source dry-run uses public GETs plus platform SELECTs; no snapshot writes,
incident writes, notification, S3 or ETL. Omit `--dry-run` only when intentionally
recording a source snapshot. A changed recommendation never triggers ingestion.

```powershell
docker compose run --rm --no-deps -e PLATFORM_ALERTS_ENABLED=false football-python-tools python scripts/discover_statsbomb_source.py --dry-run
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_alerts.py
```

Use an actual persisted DQ execution UUID from the validator output/history:

```powershell
$dqExecutionId = 'replace-with-real-persisted-execution-uuid'
# Read-only eligibility check; no incident/watermark writes or delivery:
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_alerts.py --execution-id $dqExecutionId --dry-run --dispatch --provider log
# Explicit opt-in: evaluate that execution and emit eligible incident messages locally:
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_alerts.py --execution-id $dqExecutionId --dispatch --provider log
# Later explicit bounded backlog dispatch (does not re-send failed/uncertain episodes):
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_alerts.py --dispatch --provider log
```

To enable **automatic local/log** observation, explicitly set the non-secret
compose override and recreate the scheduler (not the databases). This is a
separate opt-in from unpausing scheduled DAGs:

```powershell
$env:PLATFORM_ALERTS_ENABLED = 'true'
$env:PLATFORM_ALERT_PROVIDER = 'log'
docker compose --profile airflow up -d --no-deps football-airflow-scheduler
# Disable again by explicit override and recreate the scheduler:
$env:PLATFORM_ALERTS_ENABLED = 'false'
docker compose --profile airflow up -d --no-deps football-airflow-scheduler
```

For persistent policy, an operator can set these non-secret settings in their own
environment. Enabling Python-tools auto-observation uses the same explicit flag;
do not enable it for intentional negative tests. Scheduled DQ can be smoke-checked
without a fabricated DagRun or full replay; it appends real partial DQ history:

```powershell
@'
import json
from src.common.postgres import create_postgres_connection
from src.orchestration.monitoring import registered_contexts, scheduled_dq
with create_postgres_connection() as c:
    contexts = registered_contexts(c)
for ctx in contexts:
    result = scheduled_dq(ctx)
    assert result['dq_persisted'] and result['dq_status'] == 'PASS'
    print(json.dumps(result, sort_keys=True))
'@ | docker compose run --rm --no-deps -T -e PLATFORM_ALERTS_ENABLED=false football-python-tools python -
```

## Tests and safe acceptance

```powershell
docker compose run --rm --no-deps -e PLATFORM_ALERTS_ENABLED=false football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose --profile grafana run --rm --no-deps football-grafana-bootstrap python -m unittest discover -s tests/integration -p 'test_*postgres.py'
docker run --rm --network none football-airflow:3.2.2 python /app/tests/airflow/test_dag.py
docker compose --profile grafana run --rm --no-deps football-grafana-bootstrap python infrastructure/grafana/verify.py
docker compose config -q
docker compose --profile airflow --profile grafana config -q
git diff --check
```

Offline tests cover deterministic identity/context/build/scope, WARN/SKIP/INFO,
message redaction, persisted-DQ precedence, explicit test suppression, default-off
observation, provider selection/retry limits, dry-run source budget, discovered
contexts, existing suite delegation and BUSY behavior. PostgreSQL tests use actual
transactions with force-rollback for synthetic full ERROR failures, repeated FAIL,
separate contexts, local delivery dedup, PASS resolution, late replay, invalid
provider, uncertain STARTED and operational Airflow references. Synthetic records
do not remain in current-health panels. Real latest full 9/281 has exactly two
intentional SKIP results and evaluation opens **zero alerts**.

Read-only live validation of both discovered contexts produced **40 PASS/context**
(six real partial executions), no FAIL/WARN/SKIP and no S3 calls. The deployed
Airflow private bridge also discovered both contexts and validated 9/281 with
40 PASS (three additional real partial executions), without fabricated task refs.
Public discovery
dry-run saw eighty baseline contexts and two registered contexts, with no ETL
recommendations; a transient TLS EOF succeeded after the existing bounded retry.
Grafana verified all 46 datasource queries and retained latest-full 43/106:
170 PASS; 9/281: 166 PASS + 2 SKIP, with zero FAIL/WARN. No fake DagRun was created,
no scheduled DAG unpaused, and no external notification was sent.

Final verification on 2026-10-09 (Moscow): **525 offline Python tests**, **10
PostgreSQL integration tests**, and **2 Airflow dependency/parse/runtime tests**
passed. Compose config (default and Airflow/Grafana profiles) and
`git diff --check` passed. Grafana provisioning was not modified; its live 46-query
verification was rerun as a regression check. Migration 008 was applied and the
existing Airflow image/services updated; all three services were healthy, both
new DAGs were registered paused, and import errors were empty. The existing manual
DAG's unpaused state was preserved; its schedule remains None. No full ETL,
external delivery, onboarding, commit, push or destructive cleanup was performed.

### Changed file inventory

New:

- `dags/platform_dq_validation.py`, `dags/statsbomb_source_discovery.py`.
- `infrastructure/postgres/migrations/008_create_alert_and_discovery_state.sql`.
- `src/alerts/__init__.py`, `policy.py`, `store.py`, `transport.py`, `operations.py`.
- `src/orchestration/monitoring.py`, `src/statsbomb/discovery.py`.
- `scripts/check_platform_alerts.py`, `scripts/discover_statsbomb_source.py`.
- `tests/test_alerts.py`, `tests/integration/test_alerts_postgres.py`.
- `docs/stage7c.md`.

Updated:

- `.env.example`, `compose.yaml`, `README.md`.
- `src/dq/cli.py`, `src/orchestration/runtime.py`, `scripts/airflow_pipeline_step.py`.
- `tests/airflow/test_dag.py`.

## Limits and next stage

- Weekly detection latency is intentional; there is no freshness SLA/escalation.
- Catalog/matches discovery cannot detect event/lineup content changes when those
  metadata/matches hashes stay unchanged. Full ingestion upgrades need review.
- Exclusions are config-based, not a new active/archive registry model.
- Read-only DQ is not a full object-integrity scan or a transactionally consistent
  cross-store snapshot. Historical full health and partial history stay distinct.
- Worker/Scheduler hard death outside the private project bridge has no independent
  watchdog; an unparseable/absent bridge response raises a safe Airflow failure,
  but is not invented as persisted DQ evidence. Operational alerting covers failures
  actually observed inside the bridge/source CLI, not every infrastructure outage.
- Scope/build-isolated incidents need same-identity PASS; no automatic obsolete-build
  closure, recovery messages, FAILED/uncertain requeue, retention or escalation.
- Only local/log exists; links assume default local ports and environment `local`.
- If PostgreSQL itself is unavailable, incident truth cannot be fabricated in
  Airflow/Grafana. A fixed warning is emitted; replay authoritative DQ later.

Recommended next stage: agree an actual operational SLA and one external delivery
channel, then implement its thin transport with mounted/private secrets, explicit
opt-in, finite network timeouts and audited operator retry/recovery controls.
Do not add a second alert truth store, aggressive replay, Kafka or Prometheus.
