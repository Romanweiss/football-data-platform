# Stage 7B — Grafana Data Quality + operational observability

## Inspection and deployment

No existing Grafana compose service, image, provisioning, datasource, dashboard
or volume was found. Stage 7A only anticipated Grafana in documentation and
`scripts/dq_observability.sql`. Platform PostgreSQL already contained persistent
DQ executions/results, `metadata.dq_latest_executions`, build/load catalogs and
both real contexts. No appropriate reader role existed. Airflow and Superset
each retain their separate metadata databases and UI responsibilities.

Added optional Compose profile `grafana`:

- `football-grafana`: official pinned `grafana/grafana:13.0.1`, UID 472, local-only
  `127.0.0.1:13000:3000`; no custom Grafana build or third-party plugin.
- `football-grafana-bootstrap`: one-off existing Python-tools image, private
  credential initialization and approved PostgreSQL grants; not a new ETL engine.
- `football_grafana_data`: Grafana SQLite/internal state.
- `football_grafana_secrets`: generated reader/admin passwords outside the repo.
- Healthcheck: local `/api/health`, expected `database=ok` and container healthy.

Official image/provisioning references:
[Docker configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/),
[provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/),
[PostgreSQL datasource](https://grafana.com/docs/grafana/latest/datasources/postgres/configure/).
Actual pulled digest: `sha256:0f86bada30d65ef9d0183b90c1e2682ac92d53d95da8bed322b984ea78a4a73a`.
Runtime health independently confirmed version `13.0.1`, commit `a100054f`.

## Source and security

The only datasource is platform PostgreSQL (`football-postgres:5432`), UID
`football-metadata-dq`. Neither Airflow DB nor ClickHouse is a Grafana datasource.
The existing local PostgreSQL deployment has no server TLS configuration; the
datasource uses its internal Docker-network connection with `sslmode: disable`.
This is a local development trust boundary, not a production TLS deployment.
No S3 TLS settings are changed.

`grafana_reader` has CONNECT on the platform database, USAGE on `observability`,
SELECT on four explicit views, no underlying metadata table permissions, no
ownership/memberships, no superuser/CREATEDB/CREATEROLE/replication/BYPASSRLS.
Ordinary owner-mediated views intentionally avoid broad table grants. No function
executes validators or writes data. Query statement timeout is 10 seconds and
idle-in-transaction timeout 15 seconds; read-only is the connection default.

PostgreSQL initially granted TEMP through PUBLIC. A user cannot be denied an
inherited PUBLIC privilege individually. Bootstrap preserves effective TEMP
access for existing login roles with explicit grants, then revokes PUBLIC TEMP
**only in the platform database**. Thus the new reader cannot create even temporary
tables. Existing roles retain their effective access; future login roles need
explicit TEMP permission. Airflow/Superset databases are untouched. Public schema
already disallowed CREATE for PUBLIC. Database/role administration requires the
existing platform owner's privileges and is confined to the one-off bootstrap.

Runtime passwords are generated once with `secrets.token_urlsafe(40)`, file mode
0640, directory 0750, owner 472:0. Existing nonempty secrets are preserved on
restart/bootstrap. Existing unsafe reader roles or missing reader secrets stop
bootstrap for operator review rather than silently rotating/resetting them.
Secret-bearing role DDL suppresses routine PostgreSQL statement/error-statement
logging in its bootstrap transaction. Runtime errors print exception class only.

Grafana admin password uses supported `GF_SECURITY_ADMIN_PASSWORD__FILE`.
Datasource YAML contains only `$GRAFANA_READER_PASSWORD`; a small non-tracing
entrypoint privately exports it from the read-only runtime volume. Grafana stores
it as encrypted secureJsonData, never in dashboard JSON, URLs or Git. Normal
authentication stays enabled; anonymous auth and self-signup are disabled.
The bootstrap has writer credentials; **Grafana never receives that writer
password or S3 credentials**. The acceptance helper privately consumes the generated
admin credential for authenticated API checks and outputs only safe IDs/counts.
It never runs the operator password retrieval action.

No `.env`, `keys.txt`, existing credentials, browser cookies or login fields were
opened/printed by the agent. Log pattern audit returned zero suspicious credential
assignments/connection URLs; it emitted counts, not log bodies. Reader and admin
credentials must still be treated as local secrets by operators.

## SQL contract and latest versus history

Additive migration `007_create_dq_observability_views.sql` leaves migration 006,
DQ tables/rules/validators and build/load/analytical semantics unchanged:

| View | Meaning |
| --- | --- |
| `dq_execution_history` | One completed execution with actual P/F/W/S counts, all scopes |
| `dq_current_executions` | Latest **full** execution per context, including FAIL; reuses Stage 7A latest view |
| `dq_rule_history` | Persisted results with safe message, scalar observed/expected, numeric observation only when truly numeric |
| `dq_current_results` | Results of the current full execution |

All are in schema `observability`. No DQ rules are duplicated in SQL.
A later partial `api` PASS cannot mask a full FAIL. Current summaries ignore the
history time range and secondary filters, so selecting a narrow historical range
does not turn current health into missing/green data. If a context has never run
the full suite, it is not claimed healthy or listed by full-context selectors.
History is append-only and includes partial scopes with their explicit suite.

Default history range: **90 days**, UTC, no automatic refresh by default. This
supports occasional manual executions without inventing daily cadence or a stale
SLA. Historical queries use time bounds and row limits (100/200/500/2000). Current
queries touch only small metadata/DQ tables, never raw football events.
One live `EXPLAIN ANALYZE` of current health returned two rows in **0.497 ms**;
this is a measurement, not a latency guarantee or anomaly threshold.

## Dashboard as code

Name: **Football Data Platform — Data Quality**, UID `football-platform-dq`,
folder `Football Data Platform`. Datasource/provider YAML and dashboard JSON are
read-only bind mounts and version-controlled. Datasource/UI dashboard editing is
disabled; make reproducible changes in code. Normal restarts preserve internal
state and provisioning. A fresh Grafana volume receives the same dashboard from
the repository after migration/bootstrap. Actual destructive fresh-volume testing
was deliberately not performed.

Variables: Competition → Season, Layer, Dataset, Severity, Status, Rule ID.
Contexts/options come from PostgreSQL, not hardcoded 43/106 and 9/281. IDs are the
available authoritative context labels; no guessed competition/season names are
introduced. Secondary selectors use an explicit SQL-quoted `All` sentinel and
native query-variable interpolation, not unsafe raw SQL fragments. Rule ID also
has a link from the recent non-PASS table into filtered rule history.

The 15 focused panels are:

1. Current full DQ status.
2. Current full PASS count.
3. Current full FAIL count (red only when nonzero).
4. Current full WARN count (orange only when nonzero).
5. Current full SKIP count (blue, not failed).
6. Last full DQ execution timestamp.
7. Current full quality by persisted layer (all rules, not secondary filters).
8. All-context latest-full health (independent of selected context/time range).
9. Recent non-PASS history with safe message/context/suite/rule/status/severity.
10. Rule history with real observed/expected scalar values and execution/build IDs.
11. Current full dataset/build quality counts (secondary filters apply).
12. DQ execution history, including partial scopes and actual Airflow IDs when present.
13. Actual persisted row/match/shot/event/xG observations over time; no thresholds.
14. Successful build/load timestamps observed by Stage 7A; no invented freshness policy.
15. Last successful full DQ timestamp, explicitly separate from latest health.

PASS/FAIL/WARN/SKIP always have text labels as well as colors; SKIP is not FAIL.
An execution can be PASS with intentional SKIPs; the separate SKIP count exposes
that fact. Qualitative boolean/null checks do not become fake numeric graph points.
Mixed units in the observation panel are informational: select a Rule ID for a
single metric. Nothing in this dashboard becomes a new analytical calculation.

Superset continues football BI (xG/team/player analysis). Airflow continues task
logs/state/DAG scheduling. Grafana adds no task controls, log viewer, alerts,
Prometheus, infrastructure scraping, publication or new real context.

## Verified PowerShell operations

Run from `F:\Learning_projects\football-data-platform`. Existing platform
PostgreSQL must be running. Apply migration 006 first on a fresh platform; it is
already applied here. Apply only the new additive migration for this stage:

```powershell
@'
exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/007_create_dq_observability_views.sql;
'@ | docker compose exec -T football-postgres sh

docker compose --profile grafana config -q
docker compose --profile grafana pull football-grafana
# Reuse the existing Python-tools image. Only if it is absent:
# docker compose build football-python-tools
docker compose --profile grafana up -d football-grafana
docker compose --profile grafana ps football-grafana
Invoke-RestMethod http://127.0.0.1:13000/api/health
Start-Process http://127.0.0.1:13000
```

Login user is `admin`. **Operator only**, copy password directly to the clipboard,
never print it in a terminal or ask the agent to retrieve it:

```powershell
docker compose --profile grafana run --rm --no-deps -T football-grafana-bootstrap python infrastructure/grafana/bootstrap.py ui-password | Set-Clipboard
# Paste into Grafana login. Then clear clipboard:
Set-Clipboard -Value ''
```

Open `Dashboards → Football Data Platform → Football Data Platform — Data Quality`
or direct `http://127.0.0.1:13000/d/football-platform-dq`.

Authenticated automated datasource/dashboard/query checks consume credentials
only inside the private runtime and report no secret values:

```powershell
docker compose --profile grafana run --rm --no-deps football-grafana-bootstrap python infrastructure/grafana/verify.py
docker compose --profile grafana restart football-grafana
docker compose --profile grafana run --rm --no-deps football-grafana-bootstrap python infrastructure/grafana/verify.py
docker compose --profile grafana stop football-grafana
# Start again without deleting state; bootstrap preserves its existing secrets:
docker compose --profile grafana start football-grafana
```

No Grafana image build is necessary. Do not use `down -v`, prune, delete secret
volumes or reset the Grafana database to repair login. Normal password rotation
is an explicit operator action outside this stage.

## Live acceptance, restart and independence

Migration 007 was applied; private bootstrap and Grafana provisioning succeeded.
The real reader authenticated. Grafana HTTP datasource health returned OK.
Before and after normal restart/start, API verification found the same datasource
UID/internal ID `football-metadata-dq` / `1` and dashboard UID/internal ID
`football-platform-dq` / `3935199175688192`. It compared provisioned targets/variables
against source and executed **46 real datasource queries**: seven variables,
15 panels and a filtered rule query for each context, including the real time-series
format. These are actual Grafana PostgreSQL queries, not mocked responses.

| Latest full context | Status | PASS | FAIL | WARN | SKIP |
| --- | --- | ---: | ---: | ---: | ---: |
| 43 / 106 | PASS | 170 | 0 | 0 | 0 |
| 9 / 281 | PASS | 166 | 0 | 0 | 2 |

The two SKIPs are the persisted WC-specific golden checks. PostgreSQL and Grafana
reconcile. History contains two full executions per context and, after the
independence probe, two partial API executions for 9/281. Those are history, not
summed current health. No stale-count forcing or fake production FAIL was used.

Grafana was stopped temporarily. Inside the existing healthy Airflow scheduler
container, the exact `src.dq.orchestration.validate` adapter ran a small real API
validation and persisted **4 PASS**, execution
`381f8507-bd76-4bd2-89b1-cdb060c290c4`. This was a manual adapter invocation, not a
fabricated DagRun/task linkage. No full ETL replay or S3 request was made. Grafana
was started again and re-verified; latest full context counts stayed unchanged.

Reproducible small independence probe (creates only a real partial DQ execution):

```powershell
docker compose --profile grafana stop football-grafana
@'
import json
from src.dq.orchestration import validate
result = validate({'context': {'competition_id': 9, 'season_id': 281}}, 'api')
assert result['dq_persisted'] and result['dq_status'] == 'PASS'
print(json.dumps(result))
'@ | docker compose --profile airflow exec -T football-airflow-scheduler /usr/bin/python3 -
docker compose --profile grafana start football-grafana
```

The container health and HTTP `/api/health` are healthy after restart. Automated
query/provisioning verification and actual operator-authenticated **Edge/Chromium
visual validation** both passed. All 15 panels were loaded by scrolling the
dashboard, with no query-error UI. Competition dropdown changed 9 → 43 and Season
automatically changed 281 → 106. The UI showed 170 PASS / 0 SKIP for WC2022,
then 166 PASS / 2 SKIP after restoring 9/281. Rule ID `api.match_count` reduced
rule history to its actual rows/observed values (64), while current full health
remained 170 checks. Context health showed both rows and all P/F/W/S columns.
Build/load timestamps, execution history and the volume chart were inspected.

Visual verification caught a presentation-only Grafana Stat issue: its default
reduction selected numeric fields and showed `No data` for the string status.
The status panel now explicitly selects `/^status$/`, with offline regression
coverage. Zero FAIL/WARN counts are green; actual nonzero counts become red/orange.
Readable table widths preserve P/F/W/S visibility. No analytical/DQ values changed.
Screenshots were saved locally under ignored `.tmp/stage7b-{bundesliga,world-cup,history}.png`,
not committed. The agent did not inspect login fields/cookies or retrieve passwords.
The isolated browser/debug helper was closed after verification; the healthy
Grafana service remains running. Other browser windows/services were not stopped.

## Tests and safety evidence

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose --profile grafana run --rm --no-deps football-grafana-bootstrap python -m unittest discover -s tests/integration -p 'test_*postgres.py'
docker compose --profile grafana run --rm --no-deps football-grafana-bootstrap python infrastructure/grafana/verify.py
docker compose config -q
docker compose --profile grafana config -q
git diff --check
```

Offline coverage includes JSON/provisioned identities, dynamic chained variables,
required panels, latest/history separation, bounded history, explicit status
colors/text, rule drilldown, no embedded credentials, local auth/health/persistence,
minimal view migration, numeric/null behavior, SQL quoting and bootstrap
preservation/no secret output. No new Python dependencies were added.

Verified results on 2026-10-05: **509 offline Python tests**, **4 PostgreSQL
integration tests**, **2 existing Airflow runtime/parse tests** passed. Grafana
provisioning and its 46 datasource queries, Compose config checks and
`git diff --check` passed. Git may print the existing Windows LF/CRLF warning;
that is not a whitespace validation failure.

PostgreSQL tests include the existing Stage 7A schema test plus three new tests:

- Safely rolled-back synthetic full PASS → full FAIL/WARN/SKIP → partial API PASS;
  dashboard queries still show the full FAIL, recent non-PASS has all three states,
  qualitative numeric_observed stays NULL and all fixture rows vanish on rollback.
- Real runtime reader: no ownership/membership/schema CREATE/database CREATE/TEMP,
  no metadata table SELECT/DML; INSERT/UPDATE/DELETE, public/observability/temp DDL
  all fail with InsufficientPrivilege, even after disabling the default read-only
  flag. Write probes are zero-row statements inside rollback transactions.
- Both live latest-full snapshots reconcile and differ from all-history counts.

All test fixture data is isolated by synthetic context and force-rollback. Failure
representation is proved by real SQL plus dashboard red/text mapping assertions,
not a fake production failure screenshot. Frontend/API/Superset/ETL product code
is unchanged; unrelated frontend/Spark tests are not needed here.

## Changed files and remaining scope

`compose.yaml`, README, this runbook, PostgreSQL migration 007,
`infrastructure/grafana/{bootstrap.py,entrypoint.sh,verify.py}`, datasource/provider
YAML, dashboard JSON, `tests/test_grafana.py`,
`tests/integration/test_grafana_postgres.py`.
No commit/push, credential file edits, destructive commands, ingestion or publication.

Limits: local-only development deployment; no HA/production network TLS, migration
automation, role/password rotation workflow, retention/alerts/anomaly detection or
guessed daily SLA. Full-context status does not incorporate later partial failures
as a new full execution; those remain explicitly visible in history. Contexts with
only partial executions have no claimed full health. Grafana serves stored DQ truth,
not proof that every optional legacy inner rule is separately persisted. The 7A
append-only model and concurrency/legacy-composite limitations still apply.

Stage 7C: first agree notification recipients, applicability/scope, deduplication,
intentional-SKIP handling and on-demand versus scheduled execution policy. Use this
verified current/history contract; do not alert on every historical failure, SKIP,
time gap or invent a freshness SLA. No alert rules were created in Stage 7B.
