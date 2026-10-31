# Stage 9B.2-F — production-like deployment acceptance

**SUCCESS — Stage 9B.2-F: ACCEPTED.** Verified 2026-10-29 (Europe/Moscow).
This is a local application-only deployment, not a data refresh, public release
of a hosted service, or recovery exercise. Stage 8C remains PARTIAL.

## Published source and authorization

- Branch `master`; HEAD, `origin/master` and remote master:
  `8f7728605e8de0c079f7cbb3a77e79463df803bb`.
- Published source tree: `71db393557c75919598438c0318061d1aaaf0485`.
- [CI fast](https://github.com/Romanweiss/football-data-platform/actions/runs/40855429202):
  SUCCESS, attempt 1, exact HEAD above.
- [CI integration](https://github.com/Romanweiss/football-data-platform/actions/runs/40855429232):
  SUCCESS, attempt 1, exact HEAD above. All mandatory jobs passed, including
  Windows Python 3.12.10 / 262 synthetic recovery and real ACL/junction tests;
  optional Superset was normally SKIPPED.
- Origin: <http://127.0.0.1:18090>.
- Only `football-api-prod` and `football-web-prod` were recreated, once each.
  Existing project `football-data-platform`, profile `app-prod`, `compose.yaml`,
  existing private environment inputs, and an image-only local override were used.

The published [feature runbook](stage9b2.md) records the earlier pre-publication
and dev checkpoints. This later, uncommitted report records actual production-like
acceptance; it does not alter the earlier Git snapshot or claim a new remote CI run.

## Preflight and rollback

Docker Engine 29.8.2 and Compose 5.6.0 were available. The old origin, Nginx
healthcheck, Django healthcheck and SELECT-only ClickHouse healthcheck returned
HTTP 200. Ten baseline production Chromium checks passed before mutation.
The old Pressure endpoint returned 404, expected for the previous application.

All 98 canonical analysis JSON responses, 12 physical ClickHouse tables and five
PostgreSQL metadata catalogs were fingerprinted before deployment. The existing
ClickHouse identity was `superset_reader`, with `readonly=1`. Container identities,
start times, health, networks, mounts and safe configuration fingerprints were
captured. Resolved environment values were compared only in memory; no resolved
secret or full Compose configuration was printed or written to evidence.

Available space before build: C: 102066446336 bytes, F: 51935211520 bytes;
Docker filesystem reported 869479768064 free bytes. K: and recovery paths were
not accessed.

| Service | Previous image ID | New image ID |
| --- | --- | --- |
| API | `sha256:4febf020861fd52f09ad7b62bf0f29087b685f7bbe5d66f7e464a30304c8f63a` | `sha256:87192239feefa3221951fbe77faea97140a40925aba669f1f6f4434c675daf40` |
| Web | `sha256:113c69b523e2e47e9c60c89ec58d8e0a6a4af63eb4bbbd6613f1725a3fbd2d3a` | `sha256:e975e54603ccc7cb77ce221bb3db49b472b067bd89f12e2e4821dbaec171f498` |

Candidate tags: `football-api:9b2f-8f77286`, `football-web:9b2f-8f77286`.
Both carry the full published SHA in `org.opencontainers.image.revision`.
Exact old images were available and retained under:

- `football-api:9b2f-rollback-353a80d`;
- `football-web:9b2f-rollback-353a80d`.

Unlike the older rollback described in [Stage 9B.1-D](stage9b1-deployment.md),
this deployment did not need a content-equivalent replacement for a missing
Web image: the exact previous API and Web image IDs were retained. Both rollback
images passed their non-root, configuration and shipped-content audits. Current
runtime configuration matched the rollback configuration before mutation.
Candidate environment mappings, network and port bindings were also checked
against the baseline before and after deployment. No mounts were introduced.
Rollback was prepared but not exercised, because deployment succeeded.

## Build provenance and controlled update

Build inputs were extracted with `git archive` from the published HEAD into an
isolated temporary checkout. Its Git index reproduced the exact source tree above.
The snapshot contained no credentials, local environment, CA material, venv,
backup/restore data, keys or unpublished application files. npm dependencies and
test results generated subsequently were excluded from Docker build contexts.

Both production targets were built with pinned Python 3.12.14, Node 24.13.0 and
Nginx 1.28.2. API and Web image audits, Nginx `-t`, 61 API tests, 31 CI/documentation
contracts, repository/security checks, 79 frontend unit tests, TypeScript and the
production frontend build passed. Existing CI had already verified both Linux
Python pins, synthetic Chromium, Windows ACLs, databases, Spark/Airflow and
synthetic recovery. No application source fix was required.

The deployment used only an image override and:

```text
docker compose ... --profile app-prod up -d --no-deps --no-build --pull never --wait --wait-timeout 90 football-api-prod football-web-prod
```

Both services became healthy, with zero restart count. `/`, `/healthz`,
`/api/v1/health` and `/api/v1/health/clickhouse` returned HTTP 200. The API uses
Gunicorn; built assets are served by Nginx, not Vite. Same-origin routing, query
preservation, JSON errors, SPA deep links and asset caching passed.
This was not a zero-downtime deployment; a brief local application interruption
was possible. No dependency was started/recreated and no migration was run.

### Reproducible operator inputs / rollback

Non-secret operator evidence and image-only overrides are currently under:

```powershell
$evidence = Join-Path $env:TEMP 'football-stage9b2-deploy-6ff118804dff4e01b78edea53b552bbd'
```

`deploy.yaml` selects the two candidate tags. `rollback.yaml` selects the two
exact rollback tags listed above. They contain image references only; either
override can be reconstructed from this report without credentials.
For a separately approved rollback, retain the same existing environment inputs:

```powershell
docker compose -p football-data-platform --project-directory F:\Learning_projects\football-data-platform --env-file .env --env-file .passes -f compose.yaml -f "$evidence\rollback.yaml" --profile app-prod up -d --no-deps --no-build --pull never --wait --wait-timeout 90 football-api-prod football-web-prod
```

Run from the project directory. Do not rebuild rollback tags, use a bare `up`,
or prune images. A later ordinary Compose recreation without the reviewed
image-only override would select the older `:8b` defaults in `compose.yaml`.
The source Compose defaults were deliberately not changed in this task.

## Pressure acceptance and analytical reconciliation

Both endpoints were checked through the production Nginx origin:

```text
/api/v1/competitions/{competition}/seasons/{season}/matches/{match}/event-heatmap?type=pressure&team_id={team}&period=1
/api/v1/competitions/{competition}/seasons/{season}/matches/{match}/event-heatmap/coordinates?type=pressure&team_id={team}&period=1
```

| Context / match / team / period | Events | Excluded | Smooth/Grid |
| --- | ---: | ---: | --- |
| WC2022 43/106, 3857271, England 768, period 1 | 44 | 0 | PASS |
| WC2022 43/106, 3857271, Iran 797, period 1 | 79 | 0 | PASS |
| Bundesliga 9/281, 3895052, Bayer Leverkusen 904, period 1 | 63 | 0 | PASS |

A separate read-only query collected original Pressure event identities,
coordinates and order in memory, never persisted the source rows, and compared
them with the production coordinate API for all 98 matches. All 27973 event IDs
were unique, every original coordinate and event ordering matched exactly, every
one of the 96 Grid cells reconciled independently, and exclusions were zero.
WC2022 = 16554, Bundesliga subset = 11419. No sample or silent truncation was used.

The published estimator and production UI preserve the full 120 x 80 source
orientation. Smooth is selected by default after a match loads; fetching remains
explicit via the load button. It uses actual coordinates, Gaussian sigma=6,
120 x 80 samples and per-event boundary correction, not bin smoothing. Frontend
tests verify mass preservation, including corners, and fixed additive density.
The shared logarithmic colour scale is absolute (events per 100 coordinate units
squared, top colour 16+), not selection-max normalization. Pitch markings remain
above the raster. Hover/focus returns exact 10 x 10 area counts, not KDE values.
Pressure density is not tracking movement or normalized pressing effectiveness.

## Chromium evidence and regression

| Check | Result |
| --- | --- |
| Full production delivery suite, both projects | 54 PASS; zero failures/skips; approximately 2.3 minutes |
| Additional production operator browser checks | 2 PASS, desktop 1440x900 / mobile 390x844 |
| Smooth/Grid and team/period filters | PASS |
| Keyboard, hover/focus, selection and whole-page axe | PASS, EN/RU/ES |
| Page overflow and real screenshots | PASS, desktop/mobile |
| Delayed old filter and old context responses | No stale replacement |
| Browser-delayed loading and injected 503/retry | PASS; backend unchanged |
| Real empty period-5 selection | PASS, zero events |
| Canonical links/reload, selectors, Back/Forward | PASS |
| Shootout to non-shootout transition and history | PASS |
| Pass Map, Shot Map, xG Race, Player Table | PASS |
| JavaScript errors in additional operator checks | 0 |
| API traceback / Gunicorn boot failure / Nginx emergency counters | 0 observed |

The full suite contains both real-data and explicitly mocked failure/fixture
cases, not 54 different real matches. A separate operator check held a real
England response while selecting Iran, then held a response across navigation
to Bundesliga; neither replaced the current 79/63-event result. Browser-only
503 injection tested recovery without stopping a service or changing a backend.

Xhaka regression for match 3895052, player 3500, period 1: **31 passes,
27 completed, 4 failed, 0 unknown, 0 excluded**. Existing tests also check all
rendered pass start/end coordinates and shot/xG cross-highlighting. Bundesliga
still displays `Partial coverage: Bayer Leverkusen matches only (34/306)`.

Real production screenshots were visually inspected and kept as ignored local
evidence in `frontend/test-results/stage9b2f/`:

- `{England,Iran}-{smooth,grid}-{desktop,mobile}.png`;
- `Bayer-{smooth,grid}-{1440,390}.png`.

The England/Iran files are exact copies of captures generated by this production
delivery run under its existing Stage C capture paths; they are not older dev
screenshots. Screenshots and temporary operator programs are not Git artifacts.

## Before/after data and infrastructure invariants

All 98 analysis JSON SHA-256 values were identical. For all 12 physical tables,
row count, sum/XOR row-hash aggregates, build/context groups and CREATE TABLE
fingerprints were identical before and after:

| ClickHouse table | Rows |
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

All 22 table/context/build identity groups were unchanged. The event_core builds
remain `6da4cacc187df6a6bdf1d9f1687396bd4f94c5abf742a3310fa6dc67efc55288`
(9/281) and `f62c4943ef505dc56ce02b4c1724fedd69cfc773b23a8f3a1b6cf575bf2f526d`
(43/106).

Complete ordered-row SHA-256 fingerprints and counts were unchanged for
PostgreSQL `metadata.ingestion_objects=199`, `silver_builds=14`, `gold_builds=8`,
`clickhouse_loads=14`, `clickhouse_gold_loads=8`. No new registered ingestion,
build or load receipts were observed. All other 15 project containers retained
their identities, start times, health, environment fingerprints, mounts and
network membership. Dev API/web were not recreated. Production environment
name/value mappings were identical despite possible list-order differences.

No S3 operation was performed and application containers have no S3 write
credentials. There was no ETL, ingestion, schema change, data mutation,
Silver/Gold rebuild, Airflow/Superset recreation, volume operation, backup/restore,
recovery-key read or Bitwarden access. These are observed before/after invariants
and an audited command boundary, not a globally atomic snapshot or proof against
hypothetical external concurrent writers. Independent S3 inventory was not
repeated for this application-only deployment.

## Remaining limits and Git boundary

- Loopback production-like acceptance only: no public hosting/TLS termination,
  authentication, HA, load/SLA or normalized pressing-efficiency claim.
- Source coordinate orientation is preserved, not aligned to a shared physical
  attacking direction. Fixed sigma and edge correction are modelling choices.
- Smooth has an explicit 5000-source-row bound; overflow fails with 422 instead
  of silently dropping events. Grid remains the exact inspection mode.
- Keep candidate and rollback tags plus a reconstructible image-only override.
  A future rollback still requires operator authorization; it was not exercised.
- Screenshots/axe do not substitute for every assistive technology or real device.
- S3 isolated local recovery remains VERIFIED; Stage 8C overall remains PARTIAL.

Only this new report was added to the working tree. No application source,
tracked Compose configuration or published history changed. This report is not
staged, committed or pushed; the unrelated untracked shortcut is preserved.
No Stage 9C work was started.
