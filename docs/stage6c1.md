# Stage 6C-1 — Airflow orchestration foundation

## Inspection and execution map (before implementation)

Inspected Compose, both existing runtime Dockerfiles, requirements/environment
injection, Stage 6B-1 A–M runbook and 6B-2 evidence, all publishing CLI wrappers,
source/Bronze/API validators, PostgreSQL catalog queries, Silver/Gold identity,
publisher recovery paths and both ClickHouse loader state machines.

`C` below means explicit `--competition-id C --season-id S`; `B` adds exact
`--parent-sha256 H --bronze-max-id N`. IDs are positive UInt32. There is no CLI
default context. Existing python-tools uses Python 3.12; the proven Spark image
uses Python 3.10.12, Java 21, Spark 4.2.0, Hadoop 3.5.0 and local[2].

| Step | Existing command | Runtime / exact input | Output / mutation / retry semantics |
| --- | --- | --- | --- |
| Source preflight | check_statsbomb_source.py C | Python; public HTTPS catalog/matches + child HEAD | JSON parent/catalog SHAs, coverage; no writes; bounded transport retry |
| Parent ingestion | ingest_statsbomb_bronze.py C | Python; S3/PG + source | Shared catalog + context parent; conditional immutable PUT and independent registration; existing versions verified |
| Child ingestion | ingest_statsbomb_match_data.py C --parent-sha256 H | Python; exact catalog parent, S3/PG/source | Events/lineups; existing cataloged children fully GET/hash verified and reused; missing children published |
| Freeze input | inspect_context_catalog.py C | Python; PG SELECT | Parent IDs/SHA, Bronze max ID, registered build references; no writes |
| Bronze gate | check_statsbomb_bronze.py B | Python; exact parent and frozen catalog boundary | Parent GET SHA, child membership/HEAD; failure stops downstream |
| Silver event_core | publish_silver_event_core.py B [--check-only] | Spark/S3A | Independent of other Silver outputs; deterministic build + DQ, then immutable publication/catalog |
| Silver passes/shots | publish_silver_event_domains.py --dataset passes\|shots B [--check-only] | Spark/S3A | Both read Bronze events directly, not event_core output |
| Silver teams/players/squads | publish_silver_lineup_domains.py --dataset teams\|players\|match-squads B [--check-only] | Spark/S3A | Independent reads of same Bronze lineups and existing DQ; no sibling-build dependency |
| Silver matches | publish_silver_matches.py C --parent-sha256 H --teams-build-id T [--check-only] | Spark; exact parent + published teams build for referential DQ | Existing identity is parent/schema based; teams reference does not redefine identity |
| Silver gate | load_clickhouse_silver.py C --dataset D --build-id H --check-only | Python; exact PG/S3 manifest + CH reader | Verify source/schema/counts/target state; no INSERT |
| Gold v2 stats | build_gold_match_stats.py C --dataset team-match-stats\|player-match-stats --transform-version DATASET_v2 --silver-build D=H ... [--check-only] | Spark; exact event_core, match_squads, pass_events, shot_events | Full read/DQ before publish; deterministic IDs; no latest lookup |
| Gold results | build_gold_match_stats.py C --dataset match-results --transform-version match_results_v1 --silver-build D=H ... [--check-only] | Spark; exact event_core, matches, shot_events | Same existing immutable publisher; no formula changes |
| Gold gate | load_clickhouse_gold.py C --dataset D --transform-version v2\|v1 --build-id H [four stats pins] --check-only | Python; exact PG/S3/CH references | Manifest, lineage, source casts and target-state validation |
| Load | same Silver/Gold loader commands without --check-only | Python; existing global cooperative PG writer lock | Conditional INSERT; complete target reused; partial/conflicting target fails; catalog recovery supported |
| Serving gates | check_clickhouse_model.py C --transform-version v2; check_clickhouse_gold_model.py C --transform-version v2; check_clickhouse_match_results.py C --bi | Python; SELECT only | Actual context grains, references, source/Gold values, results |
| Application gate | check_application_api.py C --base-url http://football-api:8000 | Python stdlib HTTP; existing API service | Discoverability + existing section/composite checks; no Django installation or second API |

## Architecture decision

Use LocalExecutor with one custom image **derived from the existing project Spark
runtime**. Keep its exact system Python, Java, Spark, Hadoop/S3A JARs and CA setup.
Install pinned Airflow 3.2.2 and its PostgreSQL/standard providers into a separate
venv with official Python 3.10 constraints verified by SHA-256. Airflow tasks
invoke the existing project CLIs as subprocesses under `/usr/bin/python3` or the
existing `spark-submit`; project dependencies never enter the Airflow venv.
The older Spark image predates `clickhouse-connect`; the custom image installs
the three existing `requirements/tools.txt` pins without upgrading satisfied
Spark dependencies. A no-network runtime import test covers all three clients.

This is option A with interpreter isolation. Copying Spark into an official
Python 3.12 Airflow image would change the proven Spark Python runtime; avoid
that unnecessary variation. DockerOperator/Compose subprocesses would require
Docker socket/root-equivalent host access and Windows bind-path translation.
A new runner/SSH service would add an execution protocol without a current need.
Kubernetes/Celery/Redis are unnecessary for one local[2] Spark job at a time.

Airflow 3 requires separate API, scheduler and DAG processor processes. Add those
three services, a dedicated PostgreSQL 17 metadata service, plus one-shot secret
bootstrap and non-destructive metadata-init services. No triggerer is required
because no tasks defer. Airflow's database/volumes belong only to Airflow; platform
and Superset metadata remain separate. Only the UI binds to a loopback host port.
Repository code is baked into the image; persistent state uses Docker named
volumes, avoiding Windows UID/bind-mount permission dependencies.

Design evidence: [Airflow prerequisites](https://airflow.apache.org/docs/apache-airflow/3.2.2/installation/prerequisites.html),
[LocalExecutor](https://airflow.apache.org/docs/apache-airflow/3.2.2/core-concepts/executor/local.html),
[development SimpleAuthManager](https://airflow.apache.org/docs/apache-airflow/3.2.2/core-concepts/auth-manager/simple/index.html).

## Parameter, graph and state contracts

`statsbomb_context_pipeline`: required positive UInt32 integer `competition_id`
and `season_id`, no defaults, manual schedule, no catchup. Missing/bool/string/
float/out-of-range values fail before data IO. Run ID never enters build identity.

The 60 tasks are explicit, not dynamically mapped: seven heterogeneous Silver
and three Gold jobs have different pins; named dependencies make these clear.

```text
validate_context -> source.preflight
  -> bronze.parent_ingest -> children_ingest -> freeze_snapshot -> validate
  -> silver.{teams,players,match_squads,event_core,pass_events,shot_events}
       each: check -> publish -> validate
       teams.validate -> silver.matches: check -> publish -> validate
  -> gold.team_match_stats and gold.player_match_stats
       each: check -> publish -> validate
       require event_core + match_squads + pass_events + shot_events
  -> gold.match_results: check -> publish -> validate
       requires event_core + matches + shot_events
  -> [all ten artifact validation gates]
  -> clickhouse.silver_teams: preflight -> load
  -> silver_players -> silver_match_squads -> silver_event_core
  -> silver_pass_events -> silver_shot_events -> silver_matches
  -> gold_team_match_stats -> gold_player_match_stats -> gold_match_results
       every load has its own immediately preceding preflight
  -> validation.{serving_model,gold_model,match_results}
  -> validation.application_api
```

Source preflight resolves the exact parent SHA and existing dataset/version build
IDs. Changed parent/shared catalog fails closed: deliberate source upgrades need
separate review. Bronze uses existing immutable ingestion, then freezes catalog
max ID. All builds receive exact pins, never arbitrary latest. A check-only ID
must match the existing build before publish becomes eligible. Publish/loader
results must match the exact registered PostgreSQL row.

XCom holds context IDs, parent/catalog SHAs, frozen Bronze ID, ten expected build
IDs, dataset/layer, statuses and aggregate counters only. No rows/files/credentials.
Airflow is not a second catalog. The subprocess adapter captures raw logs privately
and emits allowlisted metadata. Failure exposes script/exit/exception class only.
Project subprocesses receive no `AIRFLOW*` variables, including task JWTs.

Artifact validation invokes existing loaders with `--check-only`: source manifest,
schema/counts and target checks without INSERT. The immediate pre-load gate repeats
that check after all publication gates. Extra reads are intentional safety gates.

## Concurrency, retries and resume

`max_active_runs=1` prevents all overlapping DAG runs. Parallelism/active tasks=2;
pool `spark_local` has one slot for a single local[2] Spark job. CH loads serialize
because the existing loader uses a global cooperative writer lock. Stop separate
manual publishers/loaders before a DAG run.

Airflow retries=0: current CLI exit codes do not distinguish permanent and transient
failures. Existing bounded HTTP/boto/S3A retries remain unchanged. Reported
`transport_retries` counts public-source retry diagnostics only, not opaque
boto/S3A internal retries. No automatic retry of DQ, SHA, certificate or context
errors is introduced.

| Failure boundary | Resume |
| --- | --- |
| Source | No ingestion eligible; fix cause, rerun |
| Partial Bronze | Existing immutable objects/catalog entries verified and reused; missing work resumes |
| Silver | Check/DQ gates publish; deterministic artifacts/catalog govern reuse |
| Gold | Same, with exact validated Silver pins |
| Some CH loads | Same-build complete targets reused; existing catalog recovery supported; partial/conflicting targets stop |
| Serving/API | No cleanup; diagnose then rerun validation or whole DAG |

Prefer a fresh manual run after fixing the cause. Clearing failed tasks is valid
only while their pinned inputs remain valid. Never mark failed validators successful
to bypass a gate. No cleanup DAG, DELETE/TRUNCATE/DROP or force-overwrite escape.

## Security and initialization

Dedicated Airflow PostgreSQL and three named volumes; no DB host port. UI binds
loopback `18080` (optional `AIRFLOW_HOST_PORT`). SimpleAuthManager is development
authentication, not production RBAC. Only scheduler receives existing project
S3/PG/CH variables; API/DAG processor have only Airflow config. No Docker socket,
embedded `.env`, host credentials mount, committed passwords or Airflow Variables.

Bootstrap generates missing credentials once in `football_airflow_secrets` and
preserves existing files. UI password is pre-generated to avoid Airflow logging
auto-generated passwords. API alone mounts the secret volume writable because
SimpleAuthManager locks its password file with `a+`. Other services mount it read-only.
Init runs non-destructive `airflow db migrate` against only Airflow metadata and
idempotently defines the one-slot pool. Normal startup never resets metadata.

## Exact local operations (PowerShell, repository root)

Airflow derives from the **existing** approved Spark image ID, preserving Python
3.10.12, Java 21.0.12, Spark 4.2.0/Hadoop 3.5.0. If absent on another host, restore
that image or deliberately rebuild/test the project runtime first; no silent
replacement with a floating base. Airflow dependencies use pinned official
constraints checked by SHA-256.

```powershell
docker image inspect football-data-platform-football-spark:latest --format '{{.Id}}'
docker tag sha256:0b540b6bee67dc6eca53e2bbfa80bc5feffe387d542db6355a963473df86d74b football-spark-runtime:6c1-0b540b6bee67
docker compose config -q
docker compose --profile airflow build football-airflow-api
# Bootstrap and migration are dependencies. Platform services are not restarted.
docker compose --profile airflow up -d football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow ps --all football-airflow-bootstrap football-airflow-db football-airflow-init football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow exec -T football-airflow-scheduler airflow db check
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-import-errors
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags unpause statsbomb_context_pipeline
# User airflow; retrieve to clipboard locally, never paste into logs/chat:
docker compose --profile airflow exec -T football-airflow-api /usr/bin/python3 /opt/airflow/config/bootstrap.py ui-password | Set-Clipboard
# Open http://127.0.0.1:18080; supply both IDs in Trigger DAG.

# Equivalent CLI trigger. Use a unique run ID for each replay.
@'
import json, subprocess
subprocess.run(['airflow','dags','trigger','statsbomb_context_pipeline',
                '--run-id','manual__9_281_operator_replay',
                '--conf',json.dumps({'competition_id':9,'season_id':281})],check=True)
'@ | docker compose --profile airflow exec -T football-airflow-scheduler python -

docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-runs statsbomb_context_pipeline
docker compose --profile airflow exec -T football-airflow-scheduler airflow tasks states-for-dag-run statsbomb_context_pipeline manual__9_281_operator_replay
# SELECT-only evidence: capture before/after and compare JSON structurally.
docker compose run --rm --no-deps football-python-tools python scripts/check_orchestration_snapshot.py
# Stop only Airflow, after tasks finish; keep all volumes:
docker compose --profile airflow stop football-airflow-scheduler football-airflow-dag-processor football-airflow-api football-airflow-db
```

Code is baked into the image. Rebuild and `up -d` between runs, or pause the DAG
and wait until no tasks are running/queued before an explicit recovery upgrade.
UI task logs contain allowlisted summaries. Never print resolved Compose config
or Airflow connection/secret config commands.

## Checks and evidence

Before replay: 479 offline/unit tests, no-network DAG parse, and eight Spark
synthetic suites (97 tests) passed. Synthetic tests use no network/project secrets.
Final checks additionally cover shared-catalog drift and retry-counter propagation:
481 offline/unit tests, two Airflow parse/runtime tests.
All eight Spark suites were then rerun on the final image: **97/97 passed**.
`docker compose config -q`, `git diff --check`, new-file whitespace checks,
Airflow DB health and live DAG import-error checks passed. All four long-running
Airflow services are healthy; zero active/queued runs remain. The final image
is deployed, and both historical DAG runs/evidence are preserved.

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker run --rm --network none football-airflow:3.2.2 python /app/tests/airflow/test_dag.py
docker run --rm --network none --hostname localhost -e SPARK_LOCAL_IP=127.0.0.1 football-airflow:3.2.2 /opt/spark/bin/spark-submit tests/spark/test_context.py
# Also: test_event_core.py, test_s3a_event_core.py, test_event_domains.py,
# test_lineup_domains.py, test_matches.py, test_gold_match_stats.py, test_match_results.py
docker compose config -q
git diff --check
```

[Pre-run snapshot](stage6c1-baseline.json): 9/281 has 69 scoped Bronze artifacts,
7 Silver and 3 Gold builds, 34 API matches. WC has 129 scoped artifacts (parent
and 128 children), 64 API matches. Global 199 rows also include the one shared
competitions file. Snapshot records exact IDs, all serving counts/builds, load
catalog fingerprints and all-match API hashes. Its normalization is defined in
the script; compare within this method, not older differently wrapped hashes.

### Live Airflow replay and recovery

Run `manual__stage6c1_9_281_20261004` finished **success**, all **60/60** tasks
successful. Start/end: 2026-10-04 23:11:54–23:26:40 Europe/Moscow
(20:11:54–20:26:40 UTC), elapsed **886.186 s / 14m46s**, including the pause for
runtime repair. Exact task durations, attempts and results:
[stage6c1-runs.json](stage6c1-runs.json).

The first `event_core.validate` and `shot_events.validate` attempts failed because
the inherited older Spark image lacked `clickhouse-connect`. The DAG was paused,
active work drained, and a SELECT/API snapshot reconfirmed no data changes. The
custom image gained the already-approved client pin; no analytical code changed.
Failed/upstream-failed task states were cleared via Airflow's CLI and the same
pinned run resumed. Those two validators finished on attempt 2; every other task
finished on attempt 1. **No automatic Airflow retries** were configured or used.
No serving load ran before all artifact gates passed. This is real recovery
evidence, not a claim that the first deployment ran without any failures.

Source preflight recorded **5 bounded public HTTP retry events**. The original
freeze XCom inherited that counter from the source snapshot: it represents the
same five events, not five additional requests. A diagnostics-only follow-up now
sets the freeze task's counter to zero, with an offline regression test; the
raw historical evidence is intentionally retained unchanged. Botocore/S3A
internal retry counts are not exposed by the existing CLIs.

| Layer | Observed replay result |
| --- | --- |
| Bronze parent/shared catalog | 2 downloaded for comparison, 2 reused, 0 uploaded, 0 registered |
| Bronze children | 68 reused, 0 downloaded/uploaded/registered |
| Seven Silver + three Gold publishes | All `UNCHANGED / ALREADY_BUILT`, `ALREADY_REGISTERED` |
| Ten ClickHouse loads | All `UNCHANGED / ALREADY_LOADED`, `ALREADY_REGISTERED` |
| Three serving validators + API validator | All successful |

[After snapshot](stage6c1-after.json) is identical to the baseline. Exact IDs,
all row counts, global/scoped Bronze checksums and both load catalogs unchanged.

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

All 34 new-context API analyses retain SHA-256
`63bfc1fe1d54124dad60ba04e6a977e52c5ae1f4d6b97652d98e8f45d240ac4a`.
All 64 WC analyses retain
`b8e15494beecb1a709e3380fa83c2420c09a0aa6cba3993659f67f7056f3408d`.
No third context, platform migrations or Superset changes were performed.

### Safe failure-path proof

Run `manual__stage6c1_invalid_context_20261005`, context `9/4294967295`, failed
in **6.953 s** on 2026-10-05 11:25:13–11:25:20 Europe/Moscow. IDs pass the range
contract, but that season is absent from the source catalog. `validate_context`
succeeded, `source.preflight` failed with the safe summary:
`CLI failed: script=check_statsbomb_source.py exit=1 exception=SourceContextError`.
The remaining 58 tasks were `upstream_failed`, attempt 0: **no Bronze ingestion**
and no downstream work. The snapshot was recaptured after this run and still
matched baseline exactly. This is a failed preflight, not onboarding a third context.

The 64 task log files from both runs were scanned without printing their contents:
zero credential-assignment, signed-URL or auto-generated-password patterns found.
Offline tests separately exercise secret-bearing synthetic raw output and verify
it is absent from the adapter's public metadata/errors. Real secret values were
not read for comparison. `.env` and `keys.txt` remain ignored; no commit/push.

### Files in this stage

- `compose.yaml`, `.env.example`, `README.md`.
- `docker/airflow/Dockerfile`, `requirements/airflow.txt`.
- `infrastructure/airflow/bootstrap.py`, `dags/statsbomb_context_pipeline.py`.
- `src/orchestration/{__init__,commands,runtime}.py`.
- `scripts/airflow_pipeline_step.py`, `scripts/check_orchestration_snapshot.py`.
- `tests/test_orchestration.py`, `tests/airflow/test_dag.py`.
- This document and `stage6c1-{baseline,after,runs}.json` evidence.

## Limitations and Stage 6C-2

Local development only, not HA. No schedule, distributed executor, notifications,
cleanup, automatic source upgrade or third-context onboarding policy. Repeated
check/publish reads are intentional. Raw driver logs are suppressed for security.
Local staging is ephemeral; authoritative state stays in S3/PostgreSQL/ClickHouse.
Do not recreate scheduler while task processes are active. Approved local Spark image must be
available to build on another machine.

Next: operator-approved source/context upgrade policy; structured safe CLI result/
error contracts with transient classification; CI replay acceptance; runtime-image
distribution/retention; then scheduling and alerting requirements. No demonstrated
need for Celery/Kubernetes.
