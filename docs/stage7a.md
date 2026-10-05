# Stage 7A — Data quality contracts and observability foundation

## Outcome and inventory

The platform now records context-aware, append-only DQ executions in its existing
PostgreSQL metadata database. Existing validator functions remain the authority
for analytical rules. Airflow consumes the same contract; no external DQ service,
Grafana installation, new context, formula or immutable build identity was added.

The [pre-integration inventory](stage7a-inventory.md) covers Bronze, all Silver/Gold
datasets, loader preflights, serving references/reconciliation, Stage 4C/4D/4E,
WC golden fixtures, API/multi-context checks, Superset checks, Airflow and tests.
It records inputs/context, rules/severity, execution/output and prior persistence.
Superset dashboard configuration and its existing checks were inspected, not changed.

## Taxonomy, identity and statuses

| Category | Meaning / examples |
| --- | --- |
| `source_integrity` | Exact catalog/build identity, parent SHA, membership, manifest lineage/files |
| `structural` | Schema/types, required fields, grain and domain aggregates |
| `referential` | Match/team/player references, complete match-team coverage |
| `semantic` | Source scores, extra time, winner and shootout evidence |
| `reconciliation` | Bronze membership vs Silver; Silver performance totals vs Gold; registered Gold vs serving; API membership vs serving |
| `regression` | Explicit WC2022 golden fixtures, never generic fixed counts |
| `operational` | Dependency execution, query availability, row-volume observations, successful build/load timestamps |

Rule IDs are stable code-owned identifiers such as `bronze.source_hash_valid`,
`silver.event_core.structure_domain_counts`, `serving.gold.team_shot_xg`,
`api.catalog_serving_membership`. Display messages are not identities. Dataset
names and query check names come from existing internal specifications, not user
data. Preserve IDs across reruns; material changes of rule meaning require an
explicit versioned rule ID/contract change. One execution contains at most 1,000
unique rule IDs. IDs are unique *within* an execution, not across execution history.

| Severity | Behavior |
| --- | --- |
| ERROR | Failed check is FAIL and makes the command/task fail |
| WARNING | Failed concern is WARN; recorded but nonblocking |
| INFO | Observations; no new thresholds or blocking behavior |

PASS means an executed check passed or an informational measurement was recorded.
FAIL is reserved for an ERROR check. WARN is a nonblocking concern. SKIP means
not evaluated (explicitly inapplicable fixture or failed prerequisite), never a
claim of successful validation. A skipped prerequisite has a separate blocking
failure. Existing informational orphan counts remain INFO observations even when
nonzero. No thresholds were introduced for optional NULLs, spelling variants or
volumes. The synthetic tests exercise WARNING; current live checks found no WARN.

Known integrity/quality failures and invalid validator conditions are attributed
to their rule. A transport/dependency failure skips the analytical rule and emits
an ERROR under `operational.*`, distinguishing unavailable evidence from a data
invariant failure. Arbitrary exception text and legacy console logs are discarded.

## Normalized result and storage

`src/dq/model.py` defines contract version 1. A completed report contains:

- random UUID `execution_id`, context IDs, exact `suite`, start/finish UTC timestamps;
- explicit overall status, computed status counts and layer summaries;
- optional `airflow` linkage (`dag_id`, `run_id`, `task_id`), never required manually;
- results: stable `rule_id`, timestamp, context, category, layer/dataset,
  nullable immutable `build_id`, status/severity, observed/expected and safe message.

Observed/expected values are bounded finite numeric/boolean scalars or null.
No event JSON, lists, query result sets, source/object URLs, credentials or exception
strings are accepted as measurements. Messages are code-owned descriptions plus
fixed reasons. Exact build IDs are SHA-256 values, not paths. Multi-input reference
and model rules intentionally have null `build_id`; the full report also records
the ten exact registered input builds individually. Single-artifact executions
carry their exact build ID on every artifact rule.

Additive migration
[`006_create_dq_history.sql`](../infrastructure/postgres/migrations/006_create_dq_history.sql)
was applied live on 2026-10-05. Previous migrations were not edited.

- `metadata.dq_executions`: completed execution header, context/scope and optional Airflow IDs.
- `metadata.dq_results`: rule observations, keyed by execution UUID and rule ID.
- `metadata.dq_latest_executions`: latest completed execution per context and exact scope,
  including failures. Latest PASS is never substituted for latest state.

The writer only INSERTs, atomically committing the complete header/results.
Rerunning the same immutable build creates a new execution UUID; no UPSERT or
replacement of an earlier FAIL. Foreign keys, status/severity checks, scalar JSON
constraints and indexes protect the contract. Application append-only behavior is
not a tamper-proof audit against a database owner; future monitoring credentials
must be read-only. Existing build/load tables remain authoritative and unchanged.

Results are persisted after checks, using a separate connection so a failed
validator transaction cannot suppress its failure history. If storage is unavailable,
the report says `persisted=false`, includes a fixed persistence error and exits 2.
It never claims the failure was stored. A killed process before completion has no
completed execution; Airflow owns that task/process failure. No incomplete execution
is presented as PASS.

## Thin adapters and blocking gates

`src/dq/bronze.py`, `artifacts.py`, `serving.py` and `api.py` wrap existing primitives.
The coordinator does not contain dataset transformation logic. Optional observer
callbacks in the existing reference/Gold metric loops emit their already-computed
values, without changing SQL, tolerances, predicates, exception behavior or formulas.
Legacy validators remain callable with their existing signatures/default behavior.

`check_platform_dq.py` is the common human/JSON entry point. Structured output is
created from rule results, not parsed from console prose. Composite legacy checks
(e.g. result/BI and WC visual contracts) initially retain a stable composite rule;
granular migration of every inner assertion is deliberately incremental.

| Gate | Blocking behavior |
| --- | --- |
| Source/Bronze integrity | Existing source preflight remains; normalized Bronze ERROR blocks Silver |
| Silver build/validation | Existing Spark structural/referential DQ remains; normalized exact artifact validation blocks Gold |
| Gold build/validation | Existing Spark semantic DQ remains; manifest/lineage/preflight ERROR blocks ClickHouse loading |
| Serving reconciliation | Failure after load fails the pipeline and preserves data plus evidence |
| API validation | Failure fails final pipeline acceptance |

The 60-task DAG graph, manual schedule, retries=0, max_active_runs=1 and one-slot
Spark pool are retained. Fifteen validation tasks (Bronze, seven Silver, three Gold,
three serving, one API) now run the normalized, persistent contract. Build and
load commands keep their existing behavior and recovery logic. XCom holds only
execution UUID/status/counts and up to ten failed rule IDs alongside existing small
build metadata; full results live in platform PostgreSQL, never Airflow metadata.
The private adapter exits nonzero after persisting failures; DAG dependencies enforce
the gates. A standalone full DQ scan may continue independent read-only checks to
collect evidence, but it never publishes or loads anything.

After a post-load failure, investigate the specific execution/rule/context/build,
then rerun validation or use the established idempotent retry/resume workflow.
Do not bypass a failing gate, mark tasks successful, delete rows, truncate tables,
or delete immutable artifacts. A later PASS is an additional history entry.

Airflow still owns task/run state, durations, attempts and logs. Platform DQ owns
data correctness, reconciliations and build evidence. No duplicate copy of every
Airflow metric is made. The image was rebuilt and idle Airflow API/processor/
scheduler updated normally. DAG parsing and the real callable metadata bridge were
tested offline. A read-only API validation through `orchestration.runtime.invoke`
inside the Airflow scheduler persisted four passing rules; this was a manual adapter
smoke check, not a new DagRun. No 60-task ETL replay was needed to test DQ.

## Reconciliations, observations and limits

- Verified Bronze parent membership equals exact Silver matches in serving:
  row count, distinct match count and outside-parent count, scoped by context/build.
- Existing Silver/Gold artifact checks verify catalog/manifests/file inventory and
  server-side Parquet aggregates; existing loader preflights remain check-only.
- Registered serving builds must match exact Silver/Gold catalogs and load records,
  row counts, target schema and context. Source/target structural checks are reused.
- Existing hard squad/event/match references remain blocking; optional references
  remain informational. Named reference counts are persisted.
- Gold team/player grain and event/pass/normal-shot totals reconcile with currently
  served Silver; period 5 handling and xG tolerance 1e-9 are unchanged.
- Match results retain source-score, extra-time, shootout and enriched BI checks.
- API match membership equals ClickHouse membership, and existing analysis/JSON/
  ordering/shot/race/shootout validation remains in place.
- Full scans verify that serving build IDs and counts remain unchanged during checks.

Counts/aggregates are computed in ClickHouse; Parquet/event datasets are not collected
into Python. Bronze parent IDs and API catalog IDs are small membership lists.
Existing WC golden validators retain their bounded WC dimension/BI row comparisons.
The full artifact adapter reads aggregate source metrics and also runs the original
loader preflight, which repeats that aggregate scan; it does not run Spark transforms.
This preserves the old preflight contract and is a future measured optimization,
not a second ETL. No Parquet byte-level checksum claim is made by metadata-only
checks; Bronze child HEAD likewise does not imply full child SHA verification.

Full reports record useful row/distinct-grain/orphan counts, Gold/Silver totals and
xG, plus successful registered build/load timestamps as Unix seconds. This is a
manual pipeline: no daily freshness SLA, arbitrary percentage anomaly thresholds
or new volume alarms. These executions establish monitoring baselines.

Generic rules assume neither 64/32 nor 34/18. WC2022 `golden.*` rules alone retain
the strongest pinned counts, shootout semantics and known xG. For 9/281 those two
fixture checks are explicitly SKIP. No duplicate Bundesliga golden suite was added.
API analytical validation samples four matches as the existing validator does;
separate before/after evidence covers response hashes for all 98 available matches.

## Live acceptance

Final results (2026-10-05):

| Context | DQ execution | PASS | FAIL | WARN | SKIP |
| --- | --- | ---: | ---: | ---: | ---: |
| 43/106 | `032c29ff-5704-43a4-8b7e-37cc24a0d5af` | 170 | 0 | 0 | 0 |
| 9/281 | `0e218908-9398-4dec-97f0-a68a6cc9ca87` | 166 | 0 | 0 | 2 |

Bronze/Silver/Gold/Serving/API all PASS. Complete normalized evidence:
[43/106](stage7a-dq-43-106.json), [9/281](stage7a-dq-9-281.json).
The compact [acceptance record](stage7a-acceptance.json) records test results,
final execution durations, state comparison and the manual Airflow adapter smoke.
Each context was checked twice against the same immutable builds. The first
executions remain in PostgreSQL. Final reporting omits eight inapplicable no-op
team-coverage entries; `--summary` exposes those removed rule IDs and reports no
change in retained observations/status/build IDs. It also detects added rules and
changed expectations, rather than silently treating different rule sets as identical.

The [before](stage7a-before.json) and [after](stage7a-after.json) platform snapshots
are structurally identical: 199 global Bronze artifacts, same Silver/Gold build IDs,
load-catalog fingerprints and all ten ClickHouse table counts for both contexts.
API hashes for all matches remain:

- WC2022, 64: `b8e15494beecb1a709e3380fa83c2420c09a0aa6cba3993659f67f7056f3408d`.
- Bundesliga subset, 34: `63bfc1fe1d54124dad60ba04e6a977e52c5ae1f4d6b97652d98e8f45d240ac4a`.

Only the new DQ schema/history was written; datasets were not rebuilt or loaded.
No secrets/environment files were read for auditing. Synthetic exception/log secret
tests prove raw text is not forwarded into normalized output. Stored metrics reject
strings/objects/arrays and nonfinite numbers. Credentials continue to be consumed
privately by the existing client helpers, never logged as DQ observations.

## Grafana contract and framework decision

Grafana was absent from the repository/Compose on inspection. Stage 7B should use
a dedicated read-only PostgreSQL datasource restricted to DQ and selected platform
catalog tables/views. [dq_observability.sql](../scripts/dq_observability.sql) provides
four verified SELECT-only queries: latest scope/layer states including FAIL,
numeric history, preserved failures with optional Airflow links, and build timestamps.
No Airflow internal DB queries or service are needed for data correctness dashboards.
Do not combine unrelated partial scopes into an unqualified whole-platform PASS.
Keep context, exact scope, rule and build filters visible in future panels.

External frameworks were considered, not installed:

| Option | Benefit | Decision for this project |
| --- | --- | --- |
| Great Expectations | Reusable expectation suites, checkpoints and validation stores | Would add another configuration/result abstraction alongside mature custom lineage/football validators; defer |
| Soda | Declarative metrics/checks, useful SQL-facing authoring | Potential future analyst workflow; current need is shared evidence/history, already met without another dependency |
| Deequ/PyDeequ | Spark-native data verification and metrics | Useful for broader Spark profiling, but current stage does not need new Spark/JVM compatibility work or rewritten rules |
| Existing code | Preserves tested semantics and runtime; easy unit failure injection and Airflow reuse | Selected; explicit contract plus small layer adapters and PostgreSQL history |

Primary references: [GX stores](https://docs.greatexpectations.io/docs/core/configure_project_settings/configure_metadata_stores/),
[Soda metrics/checks](https://docs.soda.io/soda-documentation/soda-v3/sodacl-reference/metrics-and-checks),
[Deequ](https://github.com/awslabs/deequ). The maintenance/fit judgment is project-specific;
no unsupported claim of Spark 4.2 compatibility is made. Learning value now comes
from explicit contracts/gates/evidence; revisit a framework when profiling scale or
non-developer rule authoring creates a concrete requirement.

## Exact operations (PowerShell, repository root)

Migration 006 is already applied live. On another existing installation, apply it
before deploying the DQ-aware Airflow image. The trailing semicolon in the here-string
keeps Windows CRLF out of the migration path passed to Linux `sh`.

```powershell
@'
exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/006_create_dq_history.sql;
'@ | docker compose exec -T football-postgres sh

# Full read-only data checks; write only append-only DQ history:
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_dq.py --competition-id 43 --season-id 106
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_dq.py --competition-id 9 --season-id 281 --output-json

# No data/source checks: inspect latest full execution and previous successful one:
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_dq.py --competition-id 9 --season-id 281 --summary
docker compose run --rm --no-deps football-python-tools python scripts/check_platform_dq.py --competition-id 43 --season-id 106 --summary --output-json

# Deploy between runs; retain all volumes/history:
docker compose --profile airflow build football-airflow-api
docker compose --profile airflow up -d --no-deps football-airflow-api football-airflow-dag-processor football-airflow-scheduler
docker compose --profile airflow exec -T football-airflow-scheduler airflow dags list-import-errors

# Verification:
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose run --rm --no-deps football-python-tools python tests/integration/test_dq_postgres.py
docker run --rm --network none football-airflow:3.2.2 python /app/tests/airflow/test_dag.py
docker compose config -q
git diff --check
```

Other `--suite` choices: `bronze`, `artifact`, `references`, `gold`, `results`, `api`,
`golden`. `artifact` requires `--layer`, `--dataset` and exact `--build-id`.
Gold stats artifact checks additionally require the four exact `--silver-build DATASET=SHA`
pins (event_core, match_squads, pass_events, shot_events). Bronze accepts exact
`--parent-sha256` / `--bronze-max-id`; absent explicit parent is allowed only when
the catalog has one unambiguous parent hash. Full checks resolve already-served
registered build IDs, never arbitrary latest builds.

`--summary --suite artifact --layer silver --dataset event_core` selects that scope;
adding `--build-id SHA` restricts history to executions that checked that exact build.
Manual validations need no Airflow IDs. The optional three `--airflow-*-id` arguments
must be supplied together and reference actual orchestration, not fabricated runs.
`--no-persist` is explicit diagnostic mode only; Airflow always persists.

Exit codes: 0 for PASS/WARN/explicit SKIP, 1 for ERROR/FAIL, 2 for invalid configuration,
unavailable summary or failed persistence. JSON uses stable field names and sorted keys;
timestamps/execution UUIDs intentionally differ. Human output prints rule/status/severity,
safe reason, numeric observations/expectations and exact build when applicable.

## Tests, changed files and remaining work

499 offline Python tests pass, including 18 DQ tests for PASS/FAIL/WARN/SKIP,
multi-context isolation, repeat build checks, manual/Airflow linkage, secret and
payload rejection, runtime-vs-integrity distinction, observer semantics, JSON/CLI,
read-only preflight, post-load failure and persistence failure blocking.
The PostgreSQL integration test passes: duplicate execution rejection, multiple
contexts/builds, FAIL history, previous-success comparison, added/removed rules,
exact-build filtering, constraints, atomic rollback and Airflow linkage. Synthetic
rows are rolled back, not left in production history. Both Airflow runtime/parse
tests pass with networking disabled, including the real task callable's safe linkage.
All four observability queries pass in a read-only PostgreSQL transaction.
Compose and diff checks pass. Spark transformations/validators, frontend and API
product code were untouched, so expensive unrelated suites were not repeated.

Changed files: the new `src/dq` package, common CLI and observability SQL, additive
PG migration, optional reporters in three analytics modules, orchestration runtime/
bridge and DAG metadata linkage/doc, DQ/offline/PG/Airflow tests, README, this runbook,
inventory and five JSON evidence files. No commit/push, new services, dashboard
changes, build-identity changes or destructive commands.

Limits: some legacy checks are composite; optional metrics and Spark build-time
inner rules are not all individually persisted yet. Operational Airflow failures
before/without completed DQ remain in Airflow. No tamper-proof audit, alerting,
retention automation, daily SLA or concurrent-writer snapshot isolation is claimed.
Coordinate independent writers; full checks detect serving ID/count changes but do
not hold a platform-wide lock. Post-load aggregate reconciliation is not a byte-for-byte
comparison of every Gold/ClickHouse field. Superset's independent semantic validator
remains in its own runtime and inventory, without automatic dashboard interaction.

Stage 7B recommendation: provision the read-only Grafana datasource and panels for
context/scope status, failures by rule/build, count trends and build/load timestamps.
Link execution UUIDs to CLI summaries and real Airflow tasks where available. Agree
alerting/freshness/retention policy from observed history before setting thresholds.
