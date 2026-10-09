# Stage 8A — CI architecture and automated quality gates

Stage 8A added secret-free GitHub Actions definitions and local verification.
Stage 8A-R's actual hosted-run evidence and acceptance status are recorded below.
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
New-Item -ItemType Directory -Force -Path data/work | Out-Null
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

At the end of local Stage 8A, hosted downloads, cold Spark/S3A assets, Docker
named-context/cache compatibility, Linux browsers, budgets and artifact behavior
were unproven. Stage 8A-R's evidence below supersedes those first-run assumptions
for same-repository push runs; fork execution/cache quotas remain untested.
Branch protection is still a recommendation, not an applied setting.
Exact image tags and top-level Python
pins are intentional, but Python transitive dependencies/base-image tags and
hosted-runner patch releases are not a complete immutable lock.

Recommended Stage 8B: adopt the proven required-check policy through the normal
reviewed Git process, tune budgets from measured runs, strengthen
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

## Stage 8A-R — remote acceptance

Inspection on 2026-10-09 started from committed Stage 8A:
`ee29e6cf17bb6947b348a94c8077d16fc11f78da` (`ci: add automated quality gates`),
branch `master`, initially clean working tree. The initial preflight stopped
because no Git remote was configured. The user subsequently created the empty
public repository `Romanweiss/football-data-platform` and explicitly authorized
the first push and remote validation. Its owner/name, empty refs, and push access
were verified; `origin` now points to
`https://github.com/Romanweiss/football-data-platform.git` for both fetch and push.
The existing `master` convention is retained, consistent with workflow triggers;
the GitHub example's `main` rename is not needed for this existing project.
GitHub CLI is not installed; Actions are inspected through the API.

### Actual runtime parity

Version commands were executed in the existing images with `--network none`,
without developer environment injection, mounts or service connections:

| Existing image / interpreter | Observed version | Current CI coverage |
| --- | --- | --- |
| `football-python-tools:3.12` / `python` | Python 3.12.14 | fast Python job and CI runner |
| `football-api:5a` / `python` | Python 3.12.14 | fast API tests and API Docker build |
| `football-spark-runtime:6c1-0b540b6bee67` / `/usr/bin/python3` | Python 3.10.12 | synthetic Spark job uses this runtime family |
| `football-airflow:3.2.2` / `/usr/bin/python3` | Python 3.10.12 | Airflow project runtime and DAG integration |
| `football-web:5b` / `node` | Node 24.13.0 | frontend job pins 24.13.0 |

Stage 6C's Python 3.10.12 project interpreter is still authoritative for Airflow
project subprocesses and Spark. The 3.12.14 tools/API runtime is also intentional;
there is no single Python version shared by all deployed components.

**Parity decision: option B**, a small Python 3.10.12 / 3.12.14 compatibility
matrix for the fast Python gate, preserving existing Spark/Airflow image tests
and Node 24.13.0. This exercises shared orchestration/loader/DQ code on the actual
project interpreter as well as the tools/API interpreter. It does not change
application runtimes or add a broad OS/runtime matrix. The matrix is implemented
in `ci-fast.yml`, with independent version-labelled jobs and `fail-fast: false`.
Both exact versions have Linux x64 Ubuntu 24.04 entries in the official
[setup-python version manifest](https://github.com/actions/python-versions/blob/main/versions-manifest.json).
`ci/Dockerfile` accepts `--build-arg PYTHON_VERSION=3.10.12` for local reproduction;
its default remains 3.12.14. A CI-contract regression verifies both runtime pins
and that the setup action actually receives the matrix version.

Local matrix verification passed on both Python 3.10.12 and 3.12.14: 525 offline,
26 API and 9 CI-contract tests per interpreter, plus compile checks. Python 3.10
initially exposed test-harness incompatibilities: `TestCase.enterContext` is absent
and argparse exits with code 2 for missing required arguments. `ci/run_unittest.py`
adds only the missing context cleanup method, then invokes standard unittest
discovery. Native implementations are preserved, cleanup after a failing test is
verified, and failures remain failures. The snapshot-argument test accepts each
stdlib's documented error form while checking exit code 2 and all four missing
option names. No application/analytical behavior or test selection changed.

For local matrix reproduction, build `ci/Dockerfile` with `PYTHON_VERSION` set to
each exact version and mount the repository read-only, then run:

```powershell
python ci/run_unittest.py discover -s tests -p 'test_*.py'
python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
```

These are the same stdlib tests as before; the wrapper is needed for Python 3.10.

### Safety and static review

`git check-ignore .env keys.txt`, `python ci/check_repository.py`, and actionlint
1.7.11 passed. Ignored credential files were not opened. The tracked-file scan
reported no supported high-confidence secret signatures; this is the limited
scanner described above, not a full historical or arbitrary-secret audit.
Workflow credentials are only explicit disposable CI database values.

Both workflows retain `contents: read`, public PR execution, no project Secrets,
no persisted checkout credential, and no registry publication. Hosted steps use
bash syntax, repository-relative build paths, an explicit frontend directory,
lockfile/requirements cache paths, and isolated CI service names. Database state
is tmpfs with no developer mounts or published ports. Spark/Airflow tests disable
network access; fixture Chromium uses its own preview port. Artifact upload is
limited to fixture-browser failure results. These are static observations; actual
hosted execution, cache behavior and artifact contents remain unverified.

### Remote execution procedure

The user created the empty repository under `Romanweiss`, without generated files.
After verification, the remote was configured with:

```powershell
git remote add origin https://github.com/Romanweiss/football-data-platform.git
```

The reviewed matrix changes were committed and pushed without force:

```powershell
git push -u origin master
```

Commands use Git Credential Manager; no token belongs in the remote URL or
repository. Actual run IDs, outcomes and timings appear below. The earlier local
Ubuntu apt 502 did not recur in the first hosted cold build. No mirror, package
signature checking, TLS verification or apt retry settings were changed.

The exact check-run names were verified through GitHub's commit checks API:

- `Python 3.10.12, API and BI contracts`
- `Python 3.12.14, API and BI contracts`
- `Workflows and Compose`
- `Frontend unit, TypeScript, build and fixture browser`
- `Ephemeral PostgreSQL and ClickHouse`
- `Pinned Spark synthetic and Airflow DAGs`
- `Application Docker builds (api)`
- `Application Docker builds (web)`

The optional Superset dispatch-only job should not be a required PR check.
Recommended master policy: require a PR, require those proven checks, prevent
force pushes, and optionally require an up-to-date branch. No repository settings
were changed. Remote baseline results will be recorded below after the real
workflow runs; local success alone does not establish remote acceptance.

### First hosted run and targeted fix

First pushed commit: `060f322127396d077e11b6e67c5373a18146ebbd`.
An initial git push was rejected with HTTP 403 because local Credential Manager
selected `romanweizen`; the user completed browser login as `Romanweiss`, then
the non-force push succeeded. A repository-local credential username now selects
the correct account. No token was placed in the remote URL or workflow.

- [First fast run 37951915302](https://github.com/Romanweiss/football-data-platform/actions/runs/37951915302):
  **SUCCESS**, including both exact Python versions, 525 offline + 26 API + 9 CI
  tests per version, frontend unit/type/build and both fixture Chromium viewports.
  Job times: Python 3.10.12 27s, Python 3.12.14 24s, config 18s, frontend 47s.
- [First integration run 37951915062](https://github.com/Romanweiss/football-data-platform/actions/runs/37951915062):
  **FAILURE**, solely at Spark container startup. API build (40s), web build (56s),
  database job (81s), ordered/replayed migrations, 10 PostgreSQL and 32 ClickHouse
  tests passed. Spark **cold build passed in 182s**, without the previous apt 502.
  Spark/Airflow job failed after 210s because the fresh checkout lacked ignored
  `data/work`, and Docker could not create its tmpfs target under `/app:ro`.

The fix creates only the empty runner `data/work` directory before the read-only
repository bind and writable tmpfs mount. A local Git archive reproducing the
clean checkout (no ignored directory) passed all 16 event-core Spark tests after
the same directory initialization, Docker exit code 0. No tests were removed,
disabled, made non-blocking, or changed analytically.

Artifact inspection also revealed build-push-action's default automatic
`.dockerbuild` uploads (four first-run records). Future builds set
`DOCKER_BUILD_RECORD_UPLOAD=false`, retaining job summaries and cache while
restricting artifacts to the explicitly configured fixture-browser failure path.
See the action's [documented artifact control](https://github.com/docker/build-push-action#environment-variables).
The first fast run produced no artifacts. All four first-run build records were
downloaded and checked: only OCI/BuildKit metadata/log/provenance records were
listed, with no supported high-confidence secret signatures. This is the same
limited signature audit, not a claim of detecting every arbitrary secret.

The corrected commit `413d8bc` started
[fast run 37952829774](https://github.com/Romanweiss/football-data-platform/actions/runs/37952829774)
and [integration run 37952829652](https://github.com/Romanweiss/football-data-platform/actions/runs/37952829652).
Both completed with **SUCCESS** for the same commit
`413d8bcfe278980d7bb12d1bbdfe312f05cf9d4c`. API/web/database logs confirm restored pip cache
for both Python versions, npm cache and Docker layer `CACHED` hits. Cached Spark
build took 64s versus the first cold build's 182s. Spark logs confirm all eight
suites (16 + 9 + 21 + 25 + 8 + 10 + 6 + 2 = **97** tests); the actual Airflow
image then built against this run's local Spark image and passed **2** DAG tests.
The same ephemeral migration/test gates passed again, without real platform IO.

### Accepted remote baseline and measured budget

| Check / step | Observed second-run duration |
| --- | --- |
| CI fast workflow (wall, including scheduling/cleanup) | 49s |
| Python 3.10.12 / Python 3.12.14 jobs | 27s / 23s |
| Workflows/Compose job | 14s |
| Frontend unit/type/build/fixture browser job | 45s |
| CI integration workflow (wall) | 519s (8m39s) |
| Ephemeral PostgreSQL/ClickHouse job | 58s |
| API / web Docker jobs | 17s / 17s (build steps 4s each) |
| Spark/Airflow job | 515s (8m35s) |
| Cached Spark build | 64s |
| All Spark synthetic suites | 344s (5m44s) |
| First Airflow build in this CI baseline | 78s |
| Airflow DAG test step | 3s |

Times are timestamps from GitHub run/job/step APIs, rounded to seconds, not an
SLA. Spark synthetic execution dominates; layer caching saves download/build
time but does not skip tests. Current 10–45 minute job limits have headroom; no
resource optimization or test reduction was introduced to get green.

Both accepted run artifact lists are **empty** after disabling automatic Docker
records. Browser failure uploads remain explicitly scoped to synthetic screenshots
and results, with seven-day retention; no failure screenshot/trace was produced
by the passing fixture tests, so an actual failure-artifact contents test remains
unexercised. There are no real credentials, database dumps or full football
datasets in uploaded artifacts for the accepted baseline.

Local post-fix gates passed: actionlint 1.7.11, repository secret-signature/policy
checks, nine CI contracts, the clean-checkout Spark reproduction and
`git diff --check`. The earlier full Python compatibility matrix remains green;
YAML/artifact/documentation edits required no additional application changes.

Stage 8A-R now establishes a remote baseline: both intended workflows passed on
the same corrected commit, with a real cold Spark build and subsequent cache
restore evidence. The optional large Superset image job remains deliberately
dispatch-only; fast Superset safety/config contracts passed on each matrix run.
PR/fork execution, optional dispatch, artifact-on-failure, runner variability and
future upstream availability are remaining acceptance scopes, not claimed as
tested. No failing test was skipped or made non-blocking. No CD, registry push,
real service mutation, branch-protection change or history rewrite occurred.

Stage 8B can proceed from these verified check names and timings: consider the
recommended master policy, exercise normal PR/fork CI, strengthen action/dependency
locking and evaluate non-blocking coverage. Any repository-policy write or CD
still requires explicit scope/authorization.

Stage 8A-R tracked changes: `.github/workflows/ci-fast.yml`,
`.github/workflows/ci-integration.yml`, `ci/Dockerfile`, new `ci/run_unittest.py`,
`tests/ci/test_contract.py`, `tests/test_etl_context.py`, and this runbook.
README's concise CI introduction now points to the proven hosted baseline.
