# Development

[Documentation index](README.md) · [Architecture](architecture.md) · [Operations](operations.md)

## Choose the safe path

A fresh checkout contains code, migrations and synthetic fixtures, **not** the
loaded 98-match dataset or production credentials. There is no one-command
data-populating demo. Frontend fixture tests work without lake/database access;
real Match Lab needs an operator-provisioned serving environment.

Run commands from your own checkout root. The existing operator checkout is on
Windows; paths and private files are local configuration, not portable prerequisites.
Do not copy anyone else's `.env`, `.passes`, keys, CA files, backups or venv.

## Runtimes

| Purpose | Repository runtime |
| --- | --- |
| API / Python tools | Python 3.12.14 |
| Spark / Airflow project code | Python 3.10.12; Spark 4.2.0 / Hadoop 3.5.0 |
| Linux CI compatibility | Python 3.10.12 and 3.12.14 |
| Windows recovery-only exception | Python 3.12.10; does not change API/Spark pins |
| Frontend | Node 24.13.0; npm lockfile |

Use Docker runtimes or a suitable separate development environment. A different
host Python version is not evidence of runtime compatibility. Requirements are
split under [requirements/](../requirements/); do not install everything into
the existing recovery venv. Exact CI boundaries are in [Stage 8A](stage8a.md).

## Configuration-only preflight

Requires Git, Docker and Compose v2. No services or real credentials are needed:

```powershell
docker compose --env-file .env.example config -q
docker compose --env-file .env.example --profile app-prod config -q
git diff --check
```

These commands use public placeholders and do not prove live authentication or
data readiness. Never remove `-q` when real secrets may be interpolated.

## Offline frontend checks

From `frontend/`, with Node 24 and no platform services:

```powershell
npm ci --no-audit --no-fund
npm test
npm run build
npx playwright install chromium
npm run test:ci-browser
```

Package/browser installation uses public download services. Tests use synthetic
API responses and a fresh preview server on `127.0.0.1:15174`; no Selectel keys
or real database is needed. They do not prove live football coverage.
Generated `node_modules`, `dist`, test-results and browser artifacts stay ignored.

## Offline Python checks

In a supported, separate Python environment, install the public CI requirements
and run the existing explicit suites (no database/container service startup):

```powershell
python -m pip install -r requirements/ci.txt
python -B ci/run_unittest.py discover -s tests -p 'test_*.py'
python -B ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python -B ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python -B ci/check_repository.py
python -B ci/check_s3_recovery.py
python -B -m ruff check .
```

Recovery here means synthetic tests, with the existing outbound-network guard;
it is not permission to run operator backup/restore commands. Root unittest
discovery does not cover every non-package integration/Spark/application directory.
Use the [CI inventory](stage8a.md#check-inventory) for those separate boundaries.
Documentation contracts are included in `tests/ci` discovery; no extra package is required.

## Already provisioned development application

This is an **operator-only** path: ClickHouse serving rows/views, migrations and
the existing SELECT-only reader must already be available. The schema is not
initialized by starting Django, and empty databases will not show the audited matches.

Keep working runtime values in private ignored configuration. Do not overwrite an
existing `.env` or generate replacement secrets. The published
[delivery runbook](stage8b.md#powershell-operations) documents the operator's
`.env` then `.passes` override order; use it only when those private files have
actually been provisioned. This guide does not create or read them.

For the existing operator's two-file configuration, after verifying those files
are provisioned and obtaining approval to change dev containers:

```powershell
docker compose -p football-data-platform --env-file .env --env-file .passes build football-api football-web
docker compose -p football-data-platform --env-file .env --env-file .passes up -d --no-deps football-api football-web
docker compose -p football-data-platform --env-file .env --env-file .passes ps football-api football-web
```

These are explicit application build/start operations, not commands executed by
the documentation task. They do not publish data or apply database migrations.
If a different installation manages all values in `.env` alone, review that
configuration explicitly rather than creating a dummy `.passes` or copying secrets.
Do not start Superset, Grafana, Airflow or ingestion just to open Match Lab.

| Development entrypoint | Default URL |
| --- | --- |
| Match Lab | `http://127.0.0.1:15173` |
| API process health | `http://127.0.0.1:18000/api/v1/health` |
| ClickHouse dependency health | `http://127.0.0.1:18000/api/v1/health/clickhouse` |

Ports are configurable. Health 200 is not proof that every required serving table
contains the right context/build. Production-like `:18090` is a separate,
explicitly authorized deployment; it has not received the Pass Map update.

## API navigation

Use canonical context scope, GET and no trailing slash:

```text
/api/v1/competitions
/api/v1/competitions/{competition_id}/seasons
/api/v1/competitions/{competition_id}/seasons/{season_id}/matches
/api/v1/competitions/{competition_id}/seasons/{season_id}/matches/{match_id}/analysis
/api/v1/competitions/{competition_id}/seasons/{season_id}/matches/{match_id}/passes
```

Analysis also exposes existing match/teams/players/shots/xg-race/shootout sections;
passes are separately filtered by `team_id`, `player_id`, `period`.
For real dev data, open `/competitions/9/seasons/281/matches/3895052`, choose Xhaka
and period 1, then Load pass map. Expect 31 attempts, 27 completed / 4 failed.
See the [complete pass response contract](stage9b1.md), not an inferred tracking model.

`npm run test:smoke` targets an already running dev origin and real loaded data.
`npm run test:delivery` targets the optional production-like origin. Neither is
an offline fixture test; do not use them as a reason to deploy or rebuild data.
