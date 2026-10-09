# Stage 8A — CI architecture and automated quality gates

The repository now has secret-free GitHub Actions definitions, tested locally.
**No workflow has been pushed or run on GitHub. Remote CI success is not claimed.**
There is no deployment, image publication, cloud provisioning or release step.

## Inspection and workflow boundaries

The existing branch convention is `master`. Before Stage 8A there were no GitHub
workflows, pre-commit configuration, Python linter, Python type-checker or coverage
configuration. Tests use standard-library **unittest**, not pytest. Frontend uses
Vitest, strict TypeScript and Playwright, with `npm run build` already including
`tsc --noEmit`. Those runners and runtime contracts are preserved.

Two workflows keep quick feedback separate from larger runtime/service checks:

- `.github/workflows/ci-fast.yml`: independent Python/API/BI contracts, workflow/
  Compose validation, and frontend unit/type/build/fixture-browser jobs.
- `.github/workflows/ci-integration.yml`: ephemeral database migrations/tests,
  Spark synthetic + Airflow image/parse checks, API/web Docker build matrix.
  Actual Superset-image rendering tests are an optional `workflow_dispatch` input.

Both run on `pull_request`, push to **master**, and `workflow_dispatch`. No
`pull_request_target`. No deployment triggers or remote repository mutations.
Concurrency is scoped by workflow and PR/ref; a newer PR commit cancels its
superseded run, while unrelated PRs and master pushes are not cancelled.
Job timeouts are 10–15 minutes for fast jobs, 20 minutes for databases/application
images, 45 minutes for Spark/Airflow, and 25 minutes for optional Superset.

Path filtering is deliberately deferred: cross-cutting fixtures, contracts,
migrations and shared helpers make an incomplete filter dangerous. Every PR runs
the selected deterministic gates; live acceptance and large optional Superset
image tests are excluded. This is not a blanket execution of every repository
command. Cold image builds are cached; change-based optimization can follow real
GitHub timing evidence.

## Check inventory

Times are approximate local/cold-run budgets, not an SLA. “Setup” network means
package/image/browser/CA/Maven downloads, **not** StatsBomb or Selectel. “CI only”
credentials are public disposable strings or privately generated ephemeral
reader credentials; never developer `.env` or project GitHub Secrets.

| Class / check | Command / selection | Runtime and dependencies | Approximate cost | Network | DB | Docker | Secrets | Writes | Normal CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FAST Python compile | `python -m compileall -q src application scripts infrastructure dags tests ci` | Python 3.12.14 | seconds | none | none | optional locally | none | bytecode only | yes |
| FAST Python lint | `ruff check .` | Ruff 0.14.14 | <1s | setup only | none | optional | none | optional tool cache | yes |
| FAST pipeline/DQ/alerts | `python -m unittest discover -s tests -p 'test_*.py'` | tools requirements, unittest; 525 tests | seconds | mocked/offline | fake clients | optional | synthetic | temp fixtures only | yes |
| FAST Grafana config | `test_grafana.py` within previous command | stdlib/fakes; JSON and provisioning YAML contracts | seconds | none | fake | optional | none | temp fixtures | yes |
| FAST Superset safety | `test_superset_foundation.py`, `test_superset_safety.py` within offline discovery | pure helpers/fakes; WC guard, full match identity | seconds | none | fake | optional | synthetic | temp fixtures | yes |
| FAST Django/API | `python -m unittest discover -s tests/application -p 'test_*.py'` | Django 5.2.17, ClickHouse driver; 26 tests | seconds | mocked/offline | none | optional | none | no platform writes | yes |
| FAST CI contracts | `python -m unittest discover -s tests/ci -p 'test_*.py'` | PyYAML 6.0.3, CI helpers | seconds | none | none | optional | none | none | yes |
| FAST repository policy | `python ci/check_repository.py` | Python, PyYAML, Git | seconds | none | none | no | never reads ignored secrets | none | yes |
| FAST workflows | actionlint 1.7.11 | pinned Docker image | seconds after pull | setup; execution network none | none | yes | none | none | yes |
| FAST Compose | `docker compose --env-file .env.example ... config -q`; CI file with `ci/empty.env` | Compose v2 | seconds | none | none | CLI only | public placeholders | none | yes |
| STANDARD frontend unit | `npm ci`; `npm test` | Node 24.13.0, npm lockfile, Vitest; 50 tests | seconds–minutes | npm setup only | none | optional | none | node_modules/test temp | yes |
| STANDARD frontend type/build | `npm run build` (includes typecheck) | TypeScript 7.0.2, Vite 8.3.2 | seconds | setup only | none | optional | none | dist | yes |
| STANDARD fixture browser | `npm run test:ci-browser` | Playwright 1.63.0 Chromium, built frontend | seconds after browser install | local preview only; API mocked | none | no | none | failure screenshots | yes |
| INTEGRATION Spark | eight `spark-submit tests/spark/test_*.py` entrypoints listed below | Spark 4.2.0, Hadoop 3.5.0, Python 3.10, Java 21; 97 tests | minutes, 45m job budget includes builds | setup; test network none | none | yes | synthetic only | tmpfs Parquet/work files | yes |
| INTEGRATION PostgreSQL | `python ci/databases.py postgres` | PostgreSQL 17.6, tools; existing 10 tests | seconds after build | private CI network | ephemeral PG | yes | CI only | migrations, tiny fixtures, rolled-back tests | yes |
| INTEGRATION ClickHouse | `python ci/databases.py clickhouse` | ClickHouse 25.8.23.13, driver; existing 32 tests | seconds after build | private CI network | ephemeral CH | yes | CI only | empty-schema DDL and synthetic temporary tables | yes |
| INTEGRATION Airflow | `python /app/tests/airflow/test_dag.py` in image | Airflow 3.2.2, constraints-3.10; 2 tests | seconds after build | test network none | none | yes | none | image/container temp | yes |
| INTEGRATION Docker | existing API/web/Spark/Airflow Dockerfiles; CI runner Dockerfile | existing pinned bases and requirements | cache-dependent, minutes cold | registries/package repositories | none | yes | none | local build cache/images | yes |
| INTEGRATION optional Superset | `tests/superset/test_image.py`, `test_semantic_safety.py` | Superset 6.0.0 image/digest; 8 tests | seconds after large build | test network none | none | yes | synthetic | no metadata writes | dispatch opt-in |
| LIVE serving regressions | `tests/integration/test_match_analysis.py`, `test_match_visuals.py`, `test_stats_cutover.py`; `scripts/check_clickhouse_*.py` | actual audited contexts and installed views | data-dependent | local serving, sometimes source/S3 depending validator | real CH / PG | existing platform | operator env | generally SELECT; inspect exact command | no |
| LIVE API/browser | `tests/application/integration_api.py`; `npm run test:smoke` | real serving/API/web; WC2022 and 9/281 data | minutes | live local platform | real serving | existing platform | operator env | browser artifacts only | no |
| LIVE source/object checks | `check_statsbomb_source.py`, `check_statsbomb_bronze.py`, `check_s3.py`, `check_s3a.py`, discovery | public StatsBomb / Selectel / metadata | transport/data-dependent | public source and/or real S3 | sometimes PG | existing platform | S3 where applicable | discovery can persist; roundtrip writes object | no |
| LIVE full pipeline / DQ | manual 60-task DAG, ingestion/publish/load scripts, full `check_platform_dq.py` | existing whole platform and real contexts | expensive | real source/S3/services | real PG/CH | existing platform | real operator env | pipeline writes; DQ appends history | no |
| LIVE BI acceptance | Grafana `infrastructure/grafana/verify.py`, Superset semantic validation CLI/UI | configured dashboards, roles and live metadata | seconds–minutes | live local BI | real metadata/serving | existing platform | private runtime helpers | verification read-only; apply/init modes mutate | no |

The root unittest discovery intentionally does not recurse into non-package
integration/Spark/application directories. Each gate selects its own explicit
test boundary. ClickHouse integration entrypoints run in separate interpreters:
root and integration tests reuse module names and their fixture imports alter
`sys.path`; one shared discovery process would import the wrong file.

## Runtime and dependency choices

- Python fast/API/CI runner: **3.12.14**, matching python-tools/API Dockerfiles.
- Spark/Airflow: the existing **Spark 4.2.0** image's Python **3.10** and Java **21**;
  local validated image reports Python 3.10.12 and Java 21.0.12. Hadoop remains
  **3.5.0**. The existing six S3A/cloud dependency JAR pins remain intact.
- Airflow **3.2.2** and providers retain `requirements/airflow.txt` and the existing
  SHA-verified `constraints-3.10.txt`; no full Airflow services start in CI.
- Node **24.13.0**, matching the frontend Dockerfile and package engine range.
  `npm ci` installs the existing lockfile; npm install is not used in workflows.
- PostgreSQL **17.6-alpine3.22**, ClickHouse **25.8.23.13-alpine**, Superset **6.0.0**
  with the existing digest. No arbitrary application-runtime upgrade.
- `requirements/ci.txt` includes current tools/API pins plus **PyYAML 6.0.3** and
  **Ruff 0.14.14**. Runtime application requirements remain unchanged.

Ruff is the one new Python quality tool. The narrow E9/F63/F7/F821/F822/F823 rule
set catches syntax/runtime-name issues without import-order/style rewrites.
[Ruff documents undefined-name detection](https://docs.astral.sh/ruff/rules/undefined-name/)
as a runtime correctness check. Existing code passes without reformatting.
Strict Python typing and a coverage threshold are deferred: neither was previously
configured and a new percentage target would not establish meaningful coverage.
Existing strict frontend TypeScript stays mandatory.

## Ephemeral services and migrations

`ci/compose.yaml` is an independent project, `football-ci-stage8a`. It has a private
**internal** network, no published ports, no shared/external volumes, no env_file,
and database storage in tmpfs. Its runner has only synthetic endpoint credentials.
The normal project `compose.yaml` is never used to run CI integration tests.
An explicit `--env-file ci/empty.env` prevents implicit developer `.env` loading.

The harness checks the CI marker and exact `ci-postgres` / `ci-clickhouse` host,
database/user contract, and refuses nonempty initial state. It cannot be pointed
at `football-postgres`/`football-clickhouse` by silently inheriting the local env.
No real Selectel keys or live football payloads are provided. Stop/recreate only
these explicitly named ephemeral services to run the clean initialization again.

PostgreSQL applies **init + 001–008 in order**, then repeats the same sequence to
prove the current idempotent initialization contract. Migration 001 depends on
the init-created metadata schema; CI honors that existing dependency. It creates
two tiny synthetic context/history fixtures solely because existing integration
assertions expect 43/106 and 9/281. They are explicitly `ci.fixture` data, not live
WC2022/Bundesliga validation. Two artificial SKIP rules exercise the same policy.
The real Grafana bootstrap creates a reader role and private credentials inside
runner tmpfs; permission tests reuse it without running Grafana or reading the
developer's secret volume. All additional negative DQ/alert fixtures roll back.

ClickHouse applies **001–010, 012–015** twice against empty CI tables. **011 is an
explicit rollback**, so it is tested separately, followed by 010 restoring v2.
CI asserts the v1/v2 backing-view switch, required Float64 columns, and resolves
every final view with `SELECT ... LIMIT 0`. Existing synthetic SQL tests exercise
casts, nulls, overflow, dedup, keys, BI joins and match results. No WC dataset is
loaded, no S3 table function is executed, and no live DDL is applied. The simple
SQL splitter is limited to the current DDL files (no procedural/semicolon-string
bodies); extend it deliberately if migration syntax evolves.

## Spark, Airflow and Docker strategy

Build the **existing** Spark Dockerfile once, cache its layers including the large
AWS SDK JAR, and run all eight synthetic suites with `--network none`, loopback
hostname and `SPARK_LOCAL_IP=127.0.0.1`. Repository mount is read-only, with only
`/app/data/work` backed by writable disposable tmpfs. No `--packages`, live
downloads, S3 credentials or platform database connection occurs during tests.

Airflow is built using that job's locally loaded Spark image as the
`project_spark` named build context. The workflow does not assume the developer's
`football-spark-runtime:6c1-0b540b6bee67` tag exists on a GitHub runner. A Docker
29.7.2 daemon with containerd image store and Docker Buildx driver enables both
local-image reuse and the GitHub cache backend. This follows Docker's documented
[daemon configuration](https://github.com/docker/setup-docker-action) and
[GHA cache requirements](https://docs.docker.com/build/cache/backends/gha/).

Airflow tests validate all three DAG IDs, the manual 60-task graph/params/pools,
scheduled cron/UTC/start/paused/catchup/concurrency, project dependencies and a
real decorated callable's metadata bridge. Socket connections during DAG parsing
are forbidden by the existing test. No scheduler, Airflow DB or source access.

API and web images build independently with cache; they are not deployed or
published. Python-tools/Superset Dockerfile configuration contracts remain in
offline tests. Actual Superset image build/Jinja/dialect tests are dispatch-only
because of their large runtime; no Superset app or metadata database boots.

## Frontend and Playwright boundary

Keep `npm run test:smoke` as live acceptance. Its existing `context.spec.ts` mixes
one fully mocked synthetic test with one live catalog test; the other smoke files
also require real data. New `playwright.ci.config.ts` explicitly selects only the
synthetic test, twice: **1440×900** and **390×844**. All API responses are intercepted
by the existing fixture. A fresh production-preview server uses port **15174**;
`reuseExistingServer=false` prevents accidental reuse of developer port 15173.
No React/API architecture or interaction semantics change. Browser failure
screenshots/results are the only uploaded artifacts, retained seven days.

## Cache, permissions and secret model

Actions use maintained stable major pins: checkout v4, setup-python/setup-node v6,
build-push v6, setup-buildx v3, setup-docker v4, upload-artifact v4; actionlint is
fixed at 1.7.11. Stronger action SHA pinning is a future supply-chain improvement.
Python pip cache keys include `requirements/*.txt`; npm cache keys include
`frontend/package-lock.json`. No node_modules, test outputs or database state are
cached. BuildKit cache scopes separate CI, Spark, Airflow, API, web and Superset.
Tests still execute on each run; a cached image does not cache passing test results.

Permissions are only **contents: read**. Checkout does not persist credentials.
No workflow expression reads project Secrets, no registry login/push or PR write
is requested. Fork CI needs only public dependencies and disposable service
credentials. Standard Actions/cache/artifact platform tokens are used by official
actions, not project S3/DB secrets. No self-hosted runner is configured.

`ci/check_repository.py` checks required Compose variable **names** against public
`.env.example` (excluding escaped container variables), workflow security, and
Git-tracked high-confidence private-key/AWS/GitHub token signatures. Findings print
only file/line/category. `.env` and `keys.txt` are rejected if tracked and are never
opened; `git check-ignore` verifies both paths remain excluded. This limited scan
is not an entropy scanner, a full-history audit or proof that no possible secret
exists. Do not upload `.env`, logs from live services, database volumes or datasets.

## Local PowerShell equivalents

Run from `F:\Learning_projects\football-data-platform`. Native Python commands
below require a Python **3.12.14** environment; do not silently use another global
interpreter. Docker equivalents provide the pinned runtime when needed.

```powershell
python -m pip install -r requirements/ci.txt
python -m compileall -q src application scripts infrastructure dags tests ci
ruff check .
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s tests/application -p 'test_*.py'
python -m unittest discover -s tests/ci -p 'test_*.py'
python ci/check_repository.py
docker run --rm --network none --mount "type=bind,source=${PWD},target=/repo,readonly" -w /repo rhysd/actionlint:1.7.11 -color
docker compose --env-file .env.example config -q
docker compose --env-file .env.example --profile airflow --profile grafana config -q
docker compose --env-file ci/empty.env -f ci/compose.yaml config -q
git diff --check
```

Pinned Python/Django test alternative (read-only mount, no container network):

```powershell
docker build -f ci/Dockerfile -t football-ci-checks:8a .
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" football-ci-checks:8a python -m unittest discover -s tests -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" football-ci-checks:8a python -m unittest discover -s tests/application -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" football-ci-checks:8a python -m unittest discover -s tests/ci -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" football-ci-checks:8a ruff check --no-cache .
```

The repository-policy script additionally requires Git; run it on the host. The
CI image intentionally does not copy Git metadata or the ignored `.gitignore`;
the read-only mount supplies that public file for existing offline assertions.

```powershell
Push-Location frontend
npm.cmd ci --no-audit --no-fund
npm.cmd test
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:ci-browser
Pop-Location
```

Ephemeral database acceptance (the harness deliberately refuses a second run
against already-initialized databases):

```powershell
docker build -f ci/Dockerfile -t football-ci-checks:8a .
docker compose --env-file ci/empty.env -f ci/compose.yaml up -d --wait ci-postgres ci-clickhouse
docker compose --env-file ci/empty.env -f ci/compose.yaml run --rm --no-deps checks python ci/databases.py postgres
docker compose --env-file ci/empty.env -f ci/compose.yaml run --rm --no-deps checks python ci/databases.py clickhouse
docker compose --env-file ci/empty.env -f ci/compose.yaml stop
# For a new clean test cycle, recreate ONLY the disposable CI databases:
docker compose --env-file ci/empty.env -f ci/compose.yaml up -d --wait --force-recreate ci-postgres ci-clickhouse
```

Docker build and Spark/Airflow parity (no registry publication):

```powershell
docker build -f docker/api/Dockerfile -t football-ci-api:8a .
docker build -f docker/web/Dockerfile -t football-ci-web:8a .
docker build -f docker/spark/Dockerfile -t football-ci-spark:8a .
foreach ($ciSuite in @('test_event_core','test_s3a_event_core','test_event_domains','test_lineup_domains','test_matches','test_gold_match_stats','test_match_results','test_context')) {
  docker run --rm --network none --hostname localhost -e SPARK_LOCAL_IP=127.0.0.1 --mount "type=bind,source=${PWD},target=/app,readonly" --tmpfs /app/data/work:mode=1777 football-ci-spark:8a spark-submit "tests/spark/$ciSuite.py"
  if ($LASTEXITCODE -ne 0) { throw "Spark suite failed: $ciSuite" }
}
docker build -f docker/airflow/Dockerfile --build-context project_spark=docker-image://football-ci-spark:8a -t football-ci-airflow:8a .
docker run --rm --network none football-ci-airflow:8a python /app/tests/airflow/test_dag.py
```

Optional Superset-image parity:

```powershell
docker build -f docker/superset/Dockerfile -t football-ci-superset:8a .
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" --entrypoint python football-ci-superset:8a /workspace/tests/superset/test_image.py
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" --entrypoint python football-ci-superset:8a /workspace/tests/superset/test_semantic_safety.py
```

Live acceptance commands remain in the Stage 6/7 runbooks and are deliberately
not called by either workflow. They require explicit operator configuration and
prove actual platform/data health, which synthetic CI cannot establish.

## Local evidence and first-remote-run limits

Local checks on 2026-10-09: 525 offline Python tests, 26 API tests, 5 CI-contract
tests, 10 ephemeral PostgreSQL tests, 32 ephemeral ClickHouse tests, 50 frontend
unit tests, TypeScript/build and two fixture Chromium viewport tests passed.
All 97 synthetic Spark tests passed across eight entrypoints
(16 + 9 + 21 + 25 + 8 + 10 + 6 + 2), with test-time networking disabled. The last suite was also
rerun with an explicit Docker exit-code check: **0**. In Windows PowerShell,
redirected native stderr can affect the shell's final status; check
`$LASTEXITCODE` rather than treating Spark's ordinary stderr logging as a failure.
Ruff, compile, actionlint, public-template Compose parsing and tracked-secret
signature checks passed. Airflow's two image/parse tests passed. Superset's eight
actual image/Jinja tests passed using the existing pinned local image.

API, web, CI runner and Airflow images built successfully locally. A cold rebuild
of the existing Spark Dockerfile hit repeated HTTP 502 responses from Ubuntu's
public apt mirror. No TLS/signature checking was weakened or runtime Dockerfile
rewritten to mask that external failure. Local synthetic Spark verification uses
the already validated `football-spark-runtime:6c1-0b540b6bee67` image, tagged locally
as `football-ci-spark:8a`; Airflow was built against that same existing image.
This is not evidence of a successful fresh Spark download/build on GitHub.

The first actual GitHub run must still prove hosted-runner runtime downloads,
cold Spark/S3A asset availability, Docker local named-context/cache compatibility,
cache read/write permissions and quotas on forks, browser Linux dependencies,
job timeouts/resources and artifact behavior. No remote SUCCESS badge/status or
branch-protection configuration is claimed. Exact image tags and top-level Python
pins are intentional, but Python transitive dependencies/base-image tags and
hosted-runner patch releases are not a complete immutable lock.

Recommended Stage 8B: run the workflows remotely through the normal reviewed
Git process, tune budgets from measured runs, add required-check policy, strengthen
action SHA/dependency locking and secret scanning, and consider non-blocking
coverage reporting. Deployment/CD requires its own design and authorization.

## Changed files

Added `.github/workflows/ci-fast.yml`, `.github/workflows/ci-integration.yml`,
`ci/Dockerfile`, `ci/compose.yaml`, `ci/empty.env`, `ci/check_repository.py`,
`ci/databases.py`, `requirements/ci.txt`, `ruff.toml`, `tests/ci/test_contract.py`,
`frontend/playwright.ci.config.ts` and this runbook. Updated only `README.md`,
`frontend/package.json` and `frontend/tsconfig.json` among pre-existing files.
The CI runner defaults to its five self-contained contract tests; the full
offline suite's local Docker command mounts the repository read-only so existing
tests can also inspect Git-ignored-from-build configuration such as `.gitignore`.
Application code, analytical/DQ semantics, runtime Dockerfiles and migrations
remain unchanged.
