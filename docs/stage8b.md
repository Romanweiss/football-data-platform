# Stage 8B — production-like local application delivery

## Status and boundary

**Stage 8B local live acceptance completed on 2026-10-20 (Europe/Moscow).**
The real production origin serves both existing contexts: WC2022 `43/106`
(64 matches) and StatsBomb Bundesliga `9/281` (34 available matches, not the full
league). Read-only API, real Chromium UI, desktop/mobile, dev regression and
normal application restart/recovery are verified below. This is local
production-like acceptance, not public-deployment or remote-CI certification.

Historical blocker, now resolved manually by the operator: both APIs held a
placeholder reader password different from ClickHouse's working runtime value,
causing HTTP 403 / Code 516 and safe API 503. The fixed XML principal and
`from_env` mechanism were correct; server-runtime credentials had already passed
`SELECT 1`. The operator subsequently reconciled private `.env` / `.passes` and
configured the Django key. Acceptance did not reopen those files, change any
credentials/key, recreate ClickHouse or modify grants. Current process and
ClickHouse health are both 200/ok through dev and production entrypoints.

`.env`, `.passes` and `keys.txt` remain ignored/untracked and excluded from Docker
build context. They are not frontend build inputs. Do not print these files,
resolved Compose configuration, environment values or raw driver exceptions.

No commit/push, S3 request, ETL, migration, platform data write, public deployment
or modification to Airflow/Superset/Grafana/data services was performed.

## Architecture and development mode

```text
Browser -> 127.0.0.1:18090 -> football-web-prod (Nginx :8080, static React)
                         -> /api/ -> football-api-prod (Gunicorn :8000)
                                     -> football-clickhouse :8123 (SELECT-only)
```

The opt-in `app-prod` profile adds two services to the existing football network.
Only its Nginx publishes a loopback application port; production API has no host
port, repository mount or browser-visible database credentials. Existing DB ports
remain unchanged for developer tooling. There is no CORS requirement.

Development is preserved: `football-web:5b`, Docker target `dev`, Node 24.13.0 /
Vite :5173 -> loopback :15173; `football-api:5a`, target `dev`, Django `runserver`
:8000 -> loopback :18000. Its existing HMR/dev behavior and Vite proxy config are
unchanged. Dev settings still use an ephemeral key fallback and do not trust the
forwarded-proto header. Both old and new settings keep `DEBUG=False`.

## Build, WSGI and environment

Frontend stages: pinned Node 24.13.0 -> `npm ci` -> TypeScript and Vite build ->
pinned Nginx 1.28.2 Alpine. Final runtime copies only `dist`, not source,
node_modules or Node. No frontend build args or server-side environment injection.
API retains Python 3.12.14 / Django 5.2.17 / clickhouse-connect 0.15.0 and adds
Gunicorn 23.0.0. It uses two sync workers, bind :8000, 60s worker timeout and 30s
graceful timeout. The WSGI contract and all analytics remain unchanged.

API production image and Compose explicitly select `API_SERVING_MODE=production`.
Missing/empty or documented placeholder `DJANGO_SECRET_KEY` fails startup rather
than silently generating a key. Provide it at runtime, not in image/build args or
browser JS. `.env.example` contains a non-secret placeholder, not a usable prod
key. A private operator-managed stable key is preferable for repeatable container
recreation; this API has no sessions/authentication/ORM needing persisted state.
Initial packaging checks used an ephemeral process-environment key. The final
live acceptance uses the operator-configured runtime key unchanged. `restart`
preserves the existing container environment; recreation requires the configured
private key to be available again. Do not regenerate it for acceptance/restarts.

Production API receives only this key, mode/hosts and the existing ClickHouse
reader settings. It receives no S3/PostgreSQL writer credentials. Nginx receives
no server secrets. ALLOWED_HOSTS is localhost/127.0.0.1/football-api-prod, with no
wildcard. There are no Django admin/static templates, so collectstatic/WhiteNoise
are unnecessary.

## HTTP contract, health and logging

- `/api` and `/api/...` never fall back to index.html. Full URI/query, Host,
  X-Forwarded-For and X-Forwarded-Proto are forwarded; incoming forwarded headers
  are overwritten by the sole HTTP proxy, not blindly trusted from the browser.
- Real upstream statuses/bodies pass through (`proxy_intercept_errors off`),
  including 400/404/503/500. API DNS is resolved at request time through Docker
  DNS so an API recreation does not require restarting Nginx. Upstream absence
  produces 502, not SPA HTML. Proxy connect/read timeouts are 5s/65s.
- Frontend routes fall back to index.html. Canonical competition/season/match
  URLs and legacy frontend routing are unchanged. Missing `/assets/` files are
  genuine 404s. Fingerprinted JS/CSS cache for one year; HTML is no-cache. Gzip
  is enabled for CSS/JS/JSON/SVG.
- `/healthz` is Nginx liveness, `/api/v1/health` is WSGI/API liveness and
  `/api/v1/health/clickhouse` is dependency readiness. A healthy container does
  **not** prove data readiness. BI/Airflow/Grafana are not health dependencies.
  `depends_on: service_healthy` helps initial API startup only. Runtime dependency
  failures still propagate safely and frontend retry remains available.
- nosniff, strict-origin-when-cross-origin and DENY frame headers apply to the
  app entrypoint. No speculative CSP, TLS, DNS or public hosting is added.
- Both runtime processes are non-root (`api` UID 10001, `nginx`). Nginx uses
  :8080 and /tmp for PID/temp paths instead of writable privileged directories.
- Logs remain separate on stdout/stderr. Safe access formats omit query strings,
  cookies, authorization headers and credentials. Nginx error log uses `crit`:
  ordinary upstream error logs otherwise include raw request/query text, so
  upstream failures are diagnosed by safe access status/duration and health.
  Django retains bounded class/code-only failure logs.

Trust boundary: local loopback HTTP and the existing trusted Docker network.
Other containers on that network are not isolated by a new application security
network in this stage. There is no public-service authentication, TLS, rate-limit
or HA claim. Shared ClickHouse helper retains its existing 10s connect / 300s
receive configuration; Gunicorn's shorter worker/proxy timeouts bound HTTP
serving without changing analytical/client semantics. A timed-out worker may be
restarted by Gunicorn; production capacity tuning is future work.

## PowerShell operations

Run from `F:\Learning_projects\football-data-platform`. Existing ClickHouse/data
must already be available; these commands target only application containers.
Do not use resolved `compose config` without `-q`, print env or inspect Config.Env.

```powershell
Set-Location F:\Learning_projects\football-data-platform
# Preconditions: operator-managed private files contain the working existing
# reader configuration and Django key. Do not print/regenerate those values.

docker compose --env-file .env.example --profile app-prod config -q
docker compose -p football-data-platform --env-file .env --env-file .passes --profile app-prod build football-api-prod football-web-prod
docker compose -p football-data-platform --env-file .env --env-file .passes --profile app-prod up -d --wait --wait-timeout 90 football-api-prod football-web-prod

Invoke-RestMethod http://127.0.0.1:18090/api/v1/health
Invoke-RestMethod http://127.0.0.1:18090/api/v1/health/clickhouse
Invoke-RestMethod http://127.0.0.1:18090/api/v1/competitions
Start-Process 'http://127.0.0.1:18090'

docker compose --profile app-prod ps football-api-prod football-web-prod
docker compose --profile app-prod logs --tail 100 football-web-prod
docker compose --profile app-prod logs --tail 100 football-api-prod
docker compose -p football-data-platform --profile app-prod restart --no-deps football-api-prod football-web-prod

# Operator stop/start: app containers only; no volumes or data are deleted.
docker compose --profile app-prod stop football-web-prod football-api-prod
docker compose --profile app-prod start --wait --wait-timeout 90 football-api-prod football-web-prod
```

Build/app-only startup were verified during implementation; health, actual UI,
status and production restart were verified again at final live acceptance.
Nginx/Gunicorn process and dependency health recovered in approximately 1422ms
including the restart command. Both canonical documents returned 200; all four
sample analysis hashes remained identical. Container IDs/creation timestamps
were retained, confirming restart rather than recreation. ClickHouse/PostgreSQL
IDs and start times, and dev container IDs/start times, were unchanged. No
data/state rebuild, ingestion or volume operation was needed.

The separate stop/start pair is an operator command, **not claimed as tested**:
an earlier automated shell policy rejected the stop invocation before execution.
Final acceptance exercised the requested normal restart/recovery instead.
Application containers remain running and healthy.

Dev mode operations (build/up previously exercised; full live smoke now passed):

```powershell
docker compose build football-api football-web
docker compose -p football-data-platform --env-file .env --env-file .passes up -d --wait --wait-timeout 90 football-api football-web
# Browser http://127.0.0.1:15173 ; direct API http://127.0.0.1:18000/api/v1/health
```

## Verification evidence

Passed locally:

- 525 root offline tests (Python 3.12.14), 30 API tests and 14 CI/boundary tests;
  relevant API/boundary tests also run on 3.10.12. No Spark/ETL suites were run.
- 50 frontend unit tests; TypeScript + build; two isolated CI fixture browser
  tests. Full dev smoke: 15 passed, 5 skipped because they are deliberately
  production-only assertions (two added live-context checks plus three original
  delivery checks); no unexpected skips or failed dev tests.
- Final full production browser suite after restart: **40 passed, 0 failed,
  0 skipped**, approximately 1.6 minutes, Chromium, both desktop/mobile projects.
  This includes real-data regressions, four new per-context/per-viewport live
  checks, fixture coverage and intentional failure/HTTP-contract checks.
- Actual built Nginx served six production fixture browser checks in Chromium at
  1440x900 and 390x844: navigation/search/history/reload, EN/RU/ES, xG/shot
  synchronization, shot details, full roster and shootout, no page overflow;
  safe 502/503 UI fallback. Screenshots inspected locally under ignored
  `frontend/test-results/delivery/`. These are **synthetic**, not real-context
  acceptance. These earlier fixture checks are now supplemented by the complete
  real-data browser acceptance below. Product frontend source/data/API contracts
  were not changed.
- `python ci/check_delivery.py`: actual production images in a uniquely named
  temporary bridge network, no platform membership/mounts/credentials/datasets.
  Tests GET, repeated query passthrough, forwarded headers, 400/404/503/500
  response bodies, deep-link HTML, missing asset 404, gzip/fingerprint cache,
  API absence -> 502, actual Gunicorn with synthetic unavailable CH -> JSON 503,
  static survival, DNS recovery after API replacement and secret/query-free logs.
  The script removes only its own named disposable containers/network.
- Actual image audit: non-root users, Nginx config syntax, Gunicorn config load,
  no Node/npm/node_modules in web runtime, no .env/.passes/keys.txt/.git/data/tests/caches
  in API project content; explicit-copy boundaries ensure no test datasets or
  developer credentials are shipped. Web image ~92.8 MB, API ~299.1 MB (Docker
  reported local sizes, not compressed transfer size). This is a content/boundary
  audit, not a full vulnerability or historical-layer forensic scan.
- Compose default and app-prod/airflow/grafana config -q, Ruff, actionlint and
  git diff --check. The CI API/web matrix now builds/loads production targets and
  runs per-image offline audits; fast config gate includes app-prod. No duplicate
  application build job, CD or image publication. Remote execution of these
  uncommitted workflow edits is not claimed; Stage 8A-R remote baseline remains.

### Real API and latency observations

All calls below went through Nginx at `http://127.0.0.1:18090`, without browser
credentials or direct database access. Catalog returns competition IDs 9 and 43;
season and match lists return the correct 64/34 matches. Each sample has two
teams and exactly twice as many xG state rows as normal shots. Four normalized
JSON SHA-256 fingerprints match the dev-origin responses and remain unchanged
after application restart. This demonstrates response stability, not a new DQ
rule, transformation or rewrite of stored data.

Three sequential HTTP analysis measurements per match (milliseconds, including
response transfer and JSON decoding on this local machine):

| Context / match | Shots / squad players / shootout attempts | Before restart (3 calls) | After restart (1 call) |
| --- | --- | --- | --- |
| 43/106, 3869685 (Argentina–France) | 30 / 50 / 8 | 83.87, 87.13, 94.20 | 104.13 |
| 43/106, 3857265 | 17 / 52 / 0 | 98.09, 108.24, 137.44 | 80.92 |
| 9/281, 3895052 | 25 / 40 / 0 | 119.54, 113.28, 91.90 | 83.76 |
| 9/281, 3895348 | 30 / 39 / 0 | 96.79, 85.47, 85.18 | 83.51 |

The initial 12 calls ranged from 83.87 to 137.44ms. These are small, local,
non-isolated observations with normal cache effects, not a cold-start benchmark,
load test, capacity promise or SLA. Previous static-build sanity observations
were HTML 592 B / ~1.6ms, JS 266627 B / ~2.3ms, CSS 11720 B / ~1.5ms
(uncompressed); delivery tests also verify gzip/cache/header behavior.

### Real browser acceptance

Chromium, actual Nginx-built React, desktop 1440x900 and mobile 390x844:

- Direct canonical load and refresh for WC final
  `/competitions/43/seasons/106/matches/3869685` and Bundesliga
  `/competitions/9/seasons/281/matches/3895052` render actual analysis.
- Competition/season/match selectors, scoped search, Back/Forward, legacy URL
  resolution and language persistence work. Each context is explicitly exercised
  in EN/RU/ES, with reload at each locale and no page-level horizontal overflow.
- Comparison, shot map, xG race, real-shot-only markers, synchronized selection /
  ShotDetails, active/full squad controls and real player rows remain intact.
  WC final has 30 normal-shot markers and eight separate shootout attempts;
  Bundesliga has no shootout. No analytics are recalculated in the browser.
- Existing keyboard/touch/accessibility tests run against live data, including
  additional 1024x768 / 768x1024 widths. Browser page-error assertions pass.
  API requests retain the same origin. The expanded full production suite is
  also run after restart, not just against the pre-restart process.
- Production live-context screenshots use Playwright's per-test output paths
  under ignored `frontend/test-results/delivery/`. Fixture screenshots are named
  separately and are not presented as real football acceptance evidence. Real
  WC/Bundesliga desktop and mobile screenshots were also visually inspected.

No product/runtime failures were found during final acceptance. Expected negative
tests deliberately exercise API 400/404 and synthetic 502/503/500; these are not
live infrastructure outages. The first expanded test run had two failures
(WC desktop/mobile) due to a new test's incorrect assumption that selecting a
season retains the current match. Existing UI intentionally navigates to that
season's first available match. The test now verifies that actual contract and
then reopens the target canonical URL; no product behavior was changed or
assertion skipped. Non-blocking tool warnings concern Node's
NO_COLOR/FORCE_COLOR interaction and Git's Windows LF/CRLF normalization.

### Repeat live acceptance without changing credentials

For an already running stack, do not recreate services or regenerate the key:

```powershell
Set-Location F:\Learning_projects\football-data-platform
Invoke-RestMethod http://127.0.0.1:18090/api/v1/health/clickhouse
Invoke-RestMethod http://127.0.0.1:18090/api/v1/competitions
Invoke-RestMethod http://127.0.0.1:18090/api/v1/competitions/43/seasons/106/matches/3869685/analysis

Set-Location frontend
$env:PLAYWRIGHT_CHANNEL = 'chromium'
npm test
npm run build
npm run test:ci-browser
npm run test:smoke
npm run test:delivery
Set-Location ..
python ci/check_delivery.py
git diff --check
```

`test:delivery` starts no services: it targets :18090 (optional WEB_BASE_URL), runs
existing live/synthetic smoke plus delivery contracts in desktop/mobile projects.
`test:smoke` retains :15173 and the existing dev configuration. Do not replace the
full suites with filtered fixture checks for final acceptance.

## Next stage

The local Stage 8B live gate passes. Recommended Stage 8C scope:
review application-specific read-only principal, secret lifecycle and operational
readiness/capacity; public hosting/TLS/authentication needs a separate explicit
design and authorization. It is not implicit CD or cloud deployment.

## Changed files

Final acceptance continuation changed only `frontend/tests/smoke/delivery.spec.ts`
(explicit real-context locale/history/selector regressions), `docs/stage8b.md`
(results, measurements, recovery and current operations) and `README.md`
(completed local acceptance status). The remaining entries below were existing
uncommitted Stage 8B implementation changes, preserved during acceptance.

- Packaging/configuration: `.gitignore`, `.dockerignore`, `.env.example`, `compose.yaml`,
  `requirements/api.txt`, `application/settings.py`, `docker/api/Dockerfile`,
  `docker/api/gunicorn.conf.py`, `docker/web/Dockerfile`, `docker/web/nginx.conf`.
- Verification/CI: `ci/check_delivery.py`, `ci/check_repository.py`, `.github/workflows/ci-fast.yml`,
  `.github/workflows/ci-integration.yml`, `tests/application/test_delivery.py`,
  `tests/ci/test_delivery.py`, `frontend/package.json`,
  `frontend/playwright.delivery.config.ts`, `frontend/tests/smoke/delivery.spec.ts`.
- Documentation: `README.md`, `docs/stage8b.md`.

No frontend product component, API URL/controller/service/repository, analytical
table/view, transformation, migration or data-pipeline file was changed.
