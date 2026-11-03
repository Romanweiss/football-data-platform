# Stage 9C.4-D — Current Competitions production-like acceptance

Result: **ACCEPTED**. Checked on 2026-11-02 (Europe/Moscow).

Published source: `8af030e4d1108f691f58a366f069776fef3e9125`, branch `master`.
Source tree: `0cdeb95e92c936958ff3fce562a3aaf212ff0791`.
This records the deployment acceptance checkpoint, not a live-data integration.
Documentation publication was reviewed separately on 2026-11-03; no application
source change or additional deployment is part of that review.

## Deployment boundary and provenance

One controlled Compose update recreated **only `football-web-prod`**. The API,
dev API/Web, PostgreSQL, ClickHouse, Airflow, Superset, Grafana, existing networks
and persistent volumes were not recreated or reconfigured. No migration, ETL,
provider request, backup or restore was run. Recovery materials were not accessed.

Current Competitions uses the published local synthetic adapter and needs no new
API endpoint; the existing production API therefore remains on its previous image.

The build context was a separate `git archive` of the exact published HEAD, not
the working directory. The build passed `tsc --noEmit` and Vite production build.
The build-stage image also passed all **96 frontend tests / 13 files**, offline
with `--network none`, using only the archived source and lockfile dependencies.

| Service | Before image ID | After image ID |
| --- | --- | --- |
| Web | `sha256:e975e54603ccc7cb77ce221bb3db49b472b067bd89f12e2e4821dbaec171f498` | `sha256:b2e9855d2477ea20526e200acdb46f466b1e012d13b305c543ce34873225239f` |
| API (unchanged) | `sha256:87192239feefa3221951fbe77faea97140a40925aba669f1f6f4434c675daf40` | `sha256:87192239feefa3221951fbe77faea97140a40925aba669f1f6f4434c675daf40` |

New Web tag: `football-web:9c4d-8af030e`. Its OCI revision label equals the full
published source SHA. Docker's reported image ID above is the local image-index
ID; the build also reported image config digest
`sha256:d3a389eed42974a995e2fb4fcbfaa24c7ea289ba259f136c8c7e916adcdb0a78`.
Runtime user is `nginx`, not root. The candidate and rollback image both passed
the existing `ci/check_delivery.py --audit-image ... --kind web` audit: Nginx
configuration, static assets, no Node/npm/application tree or private runtime
files in shipped application/configuration paths. No private files were in the
Git-only build context.

Initial direct registry resolution failed for `auth.docker.io`. Repeating the
build through the existing loopback Windows system proxy succeeded. Proxy
variables were scoped to that process and restored in `finally`; no DNS, daemon
configuration, trust store or TLS verification setting was changed.

## CI and pre-deployment gates

Both workflows were freshly queried for the exact published SHA:

- [CI fast — SUCCESS](https://github.com/Romanweiss/football-data-platform/actions/runs/41507737586): workflows/Compose, Python 3.10.12, Python 3.12.14, frontend/build/browser.
- [CI integration — SUCCESS](https://github.com/Romanweiss/football-data-platform/actions/runs/41507737373): API and Web Docker builds, Spark/Airflow, ephemeral PostgreSQL/ClickHouse, synthetic database recovery, Windows S3 recovery/ACL. Optional Superset was normally SKIPPED.

Docker Engine `29.8.2`; Compose `v5.6.0`. Before deployment, production Web/API
were healthy and the existing desktop/mobile delivery suite passed **10/10**.
Read-only baseline evidence was captured before the update.

Rollback tag `football-web:9c4d-rollback-8f77286` resolves to the exact before Web
image above. Existing image tags were retained; no prune was performed. The
rollback image passed the same image audit. Rollback was **prepared, not executed**.

Image-only deployment and rollback overrides pin the unchanged API image as well
as the appropriate Web image, avoiding the stale `:8b` Compose defaults. Effective
Compose configuration was resolved only in memory with the existing private
inputs. Environment mappings were compared without printing or persisting values.
Environment mappings, no-volume configuration, existing network and loopback port
bindings matched before deployment, for the candidate, and after deployment.

Local operator evidence was kept outside Git in a temporary directory containing
`deploy.yaml`, `rollback.yaml`, `operator.py`, `before.json`, `post.json`, the public
source archive/snapshot and browser helpers/screenshots. JSON evidence contains
only allowlisted configuration identifiers/hashes and aggregate fingerprints,
never resolved environment values or catalog rows. These local files and images
are not published artifacts and may not survive cleanup or machine loss.

The completed deployment used the standard project Compose command with both
existing private environment inputs, an image-only override, and
`up -d --no-deps --no-build --pull never --wait --wait-timeout 90 football-web-prod`.
No temporary override is needed to reconstruct the rollback instructions below.

### Reconstructible rollback procedure (not executed)

Rollback requires a separate operator decision. First confirm that the project
Compose definition still matches the deployed source and that the existing
private environment inputs remain the validated runtime configuration. If either
has changed, stop for configuration review; do not silently reuse these commands.
From the project root, this read-only check must show no Compose changes:

```powershell
git diff --exit-code 8af030e4d1108f691f58a366f069776fef3e9125 -- compose.yaml
```

The two images must still exist locally with exactly the recorded IDs. The
following checks do not start or update containers:

```powershell
$rollbackWeb = 'football-web:9c4d-rollback-8f77286'
$unchangedApi = 'football-api:9b2f-8f77286'
$webId = docker image inspect --format '{{.Id}}' $rollbackWeb
if ($LASTEXITCODE -ne 0 -or $webId -ne 'sha256:e975e54603ccc7cb77ce221bb3db49b472b067bd89f12e2e4821dbaec171f498') { throw 'Rollback Web image unavailable or changed' }
$apiId = docker image inspect --format '{{.Id}}' $unchangedApi
if ($LASTEXITCODE -ne 0 -or $apiId -ne 'sha256:87192239feefa3221951fbe77faea97140a40925aba669f1f6f4434c675daf40') { throw 'API image unavailable or changed' }
```

For a separately approved rollback, manually save the following non-secret
override as `FootballPlatformOperations\stage9c4\rollback.yaml` under the current
user's `LOCALAPPDATA` directory, outside the repository. Do not overwrite an
existing operational file without reviewing it. The entire override is included
here; it does not depend on the original temporary directory:

```yaml
services:
  football-api-prod:
    image: football-api:9b2f-8f77286
  football-web-prod:
    image: football-web:9c4d-rollback-8f77286
```

After confirming the exact image IDs and configuration, the operator can use:

```powershell
$rollback = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'FootballPlatformOperations\stage9c4\rollback.yaml'
if (-not (Test-Path -LiteralPath $rollback -PathType Leaf)) { throw 'Reviewed rollback override is required' }
docker compose -p football-data-platform --project-directory . --env-file .env --env-file .passes -f compose.yaml -f $rollback --profile app-prod config -q
if ($LASTEXITCODE -ne 0) { throw 'Rollback configuration validation failed' }
# Execute only with separate rollback authorization, after all checks above.
docker compose -p football-data-platform --project-directory . --env-file .env --env-file .passes -f compose.yaml -f $rollback --profile app-prod up -d --no-deps --no-build --pull never --wait --wait-timeout 90 football-web-prod
if ($LASTEXITCODE -ne 0) { throw 'Rollback requires diagnosis; do not retry automatically' }
```

Only Web is targeted; API and persistent services must not be recreated. Follow
with health, historical Match Lab and integrity checks. Never use bare `:8b`
Compose defaults, print resolved environment values or disable security gates.
The override and commands were reviewed, but rollback itself was not exercised.
The images were confirmed present during the publication review. If they are
later lost, this report is **not an image backup or a fresh-machine recovery
procedure**: stop and obtain a separately reviewed rebuild/recovery plan.

## Health and routing

Web became healthy during the controlled update; restart count remained **0**.
The unchanged production API is healthy. Verified HTTP 200:

- `http://127.0.0.1:18090/healthz`
- `http://127.0.0.1:18090/api/v1/health`
- `http://127.0.0.1:18090/api/v1/health/clickhouse`
- `http://127.0.0.1:18090/competitions/current`
- `http://127.0.0.1:18090/competitions/current/uefa-champions-league/2026`

Deep-link reloads, built assets, same-origin API proxy, HTTP error status
preservation and query forwarding passed production delivery browser checks.

## Current Competitions acceptance

Actual production Chromium, **1440×900** and **390×844**, without API mocks in the
main acceptance path:

- 36 invented teams, 144 fixtures, 54 FINISHED, 90 TIMED.
- All fixture statuses, UTC kickoff values, teams and scores matched the published
  deterministic factory. Every standings row was independently recomputed from
  the actual production fixture DOM: P/W/D/L/GF/GA/GD/points, ordering and positions.
- Zones contain 8 / 16 / 12 teams. Ranking is the documented demo ordering,
  **not official UEFA tie-breakers**.
- Team, matchday and date filtering; empty result; reset; invalid URL filters;
  unknown competition route; deep links; Back/Forward and reload: PASS.
- Fixtures/standings tabs work with arrow keys; visible keyboard focus, table
  keyboard scrolling, mobile Points visibility and horizontal scrolling inside
  the table region: PASS. No page-level horizontal overflow.
- Reviewed visible prototype controls meet **44×44 CSS pixels** in both viewports.
- EN/RU/ES selection and reload persistence, demo banner and axe WCAG A/AA checks:
  PASS. The visible provenance labels are `DEMO DATA — SYNTHETIC`,
  `ДЕМО-ДАННЫЕ — СИНТЕТИЧЕСКИЕ` and `DATOS DEMO — SINTÉTICOS`.
  No JavaScript page errors.
- Current-only navigation generated **zero fetch/XHR requests**; all observed
  requests remained on the production origin. No football-data.org request,
  external emblem/image or historical event map was used for synthetic fixtures.
- Transition to the real historical Match Lab and Back/Forward: PASS.

Loading/error/retry were additionally checked in Chromium in six combinations
(two viewports × EN/RU/ES). This was an **explicit browser-only fault fixture**:
the already-resolved typed synthetic league promise was delayed, then rejected,
only inside the test page. No production file, server response or adapter was
modified. Loading and error kept the demo marker; raw fixture error text was not
shown; keyboard retry returned all 144 fixtures; axe passed. These are UI
resilience tests, not evidence of a real provider/backend outage. Corresponding
source-injected loading/error/empty/stale-response unit tests also passed.

Real screenshots were captured outside Git in the local operator evidence:

```text
current-catalog-1440.png       current-catalog-390.png
current-fixtures-1440.png      current-fixtures-390.png
current-standings-1440.png     current-standings-390.png
```

Fixture and standings screenshots for both sizes were visually inspected. They
are full-page captures taken at the stated viewport sizes; fixture screenshots
use matchday 3 for a readable 18-match view. Standings has an intentionally bounded
internal scrolling region, not a missing-row limit; all 36 rows were asserted.

One initial local acceptance assertion used the wrong English unknown-route
wording (`unavailable` instead of published `not available`). Only the TEMP test
helper was corrected and the complete acceptance rerun passed. No UI fix or
deployment retry was required.

## Historical Match Lab regression

After deployment, the existing production browser suites passed **20/20** with
zero skips: delivery, live pass map and live pressure checks across both projects.
This includes 64 WC2022 matches and 34 Bundesliga subset matches; real Shot Map,
xG Race selection synchronization, player table, canonical selection, history,
reload, locales, same-origin API, full-pitch pass coordinate fidelity and axe.

Control case: match `3895052`, team `904`, player `3500`, period `1`:
**31 passes / 27 completed / 4 failed / 0 unknown / 0 excluded**.
Pressure checks retained England 44, Iran 79 and Bayer period-one 63 events,
with both Smooth and Grid modes.

The previous deployment's additional production browser regression helper was
also rerun for both viewport sizes: delayed filter/match responses, loading,
error/retry/empty pressure states, EN/RU/ES axe, and explicit transitions between
shootout and non-shootout matches with Back/Forward/reload all passed.

## Read-only data integrity

Before/after comparisons passed:

- All **98 analysis JSON SHA-256 identities** unchanged (64 + 34).
- All **12 physical ClickHouse tables** unchanged: count, sum and XOR of row
  hashes, schema SHA-256, and all **22 table/context/build groups**.
- All **five PostgreSQL metadata catalogs** unchanged: ordered full-row digest
  and count. Counts: ingestion_objects 199, silver_builds 14, gold_builds 8,
  clickhouse_loads 14, clickhouse_gold_loads 8.
- The API and **all 16 non-Web project containers** retained identity, image,
  start time, status/health, configuration/environment fingerprints, mounts and
  network membership. Only the production Web container was recreated.

| ClickHouse table | Rows, unchanged |
| --- | ---: |
| event_core | 372402 |
| pass_events | 107729 |
| shot_events | 2410 |
| teams | 50 |
| players | 1289 |
| match_squads | 4597 |
| matches | 98 |
| team_match_stats | 128 |
| player_match_stats | 3244 |
| team_match_stats_v2 | 196 |
| player_match_stats_v2 | 4597 |
| match_results | 98 |

SQL collection used the existing read-only ClickHouse identity and a read-only
PostgreSQL connection. Catalog rows and runtime secret values were not logged.

## Repository/security checks and limitations

From the exact Git archive, **55 CI/security contracts passed on each of Linux
Python 3.10.12 and 3.12.14** using existing isolated CI tool images and read-only
snapshot mounts. The tracked-file repository completeness/secret-signature/ignore
audit passed. No API, workflow or dependency source changes were needed.

An initial attempt using the separate host S3-recovery venv could not import
PyYAML. That runtime is not the CI environment and was not modified; the checks
were rerun successfully with the existing CI images. The initial failed import
attempt is not counted as a pass.

The real-reconciliation document retains SHA-256
`bd15d6cde129ee104ff620faf287ff3f324796664aae602fa1be35c55c93b45a`.
At the deployment checkpoint, tracked sources and the Git index were unchanged;
only this local report was added, and no staging, commit or push occurred. The
separate Stage 9C.4-E publication scope is this report alone. The unrelated
shortcut remains untouched. Screenshots, receipts, environment inputs and runtime
files are not part of the publication.

Current Competitions is deployed but **still entirely synthetic**. The fixed
demo clock is not provider freshness. No UEFA persistent onboarding, official
standings methodology, live integration, event data or new tournament is implied.
Persistent onboarding remains **BLOCKED / LEGAL_REVIEW_REQUIRED**. Manual
NVDA/VoiceOver testing was not performed; automated axe/keyboard checks do not
replace it. This is local production-like acceptance, not external hosting/CD.

S3 local recovery remains VERIFIED; **overall Stage 8C remains PARTIAL**.
K: backup, F: plaintext restore and recovery keys were not touched.

**Stage 9C.4-D: ACCEPTED.** No transition to Stage 9C.5 is authorized.
