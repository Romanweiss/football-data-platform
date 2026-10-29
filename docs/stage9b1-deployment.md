# Stage 9B.1-D — production-like deployment acceptance

**SUCCESS — Stage 9B.1-D: ACCEPTED.** Verified on 2026-10-29 (Europe/Moscow).
This records a local, explicitly authorized application deployment, not a public
service, data refresh or new recovery exercise.

## Source and scope

- Branch: `master`.
- Local HEAD, `origin/master` and remote master:
  `353a80d739e4ac85dbee61361b367d56a9b3e40a`.
- Exact published source tree: `59f3db7ea10ccb7439933350be1736bc17a88f9d`.
- [CI fast](https://github.com/Romanweiss/football-data-platform/actions/runs/40776122479):
  SUCCESS, attempt 2 after the operator's manual rerun.
- [CI integration](https://github.com/Romanweiss/football-data-platform/actions/runs/40776122480):
  SUCCESS, attempt 1.
- Origin: <http://127.0.0.1:18090>.
- Only `football-api-prod` and `football-web-prod` were recreated, under Compose
  project `football-data-platform`, profile `app-prod`, existing `compose.yaml`.
  Production API/web have no repository or persistent-volume mounts.

The published READMEs and [Stage 9B.1 report](stage9b1.md) describe the earlier
pre-deployment checkpoint. This later, uncommitted acceptance report records the
new local runtime state; it does not retroactively change that Git snapshot.

## Baseline and rollback readiness

Before mutation, both health endpoints, the static origin and read-only API
contracts passed for WC2022 `43/106` (64 matches) and Bundesliga `9/281`
(34 matches). The old production passes endpoint returned 404, as expected for
the version being replaced. All 98 canonical analysis responses were hashed.

ClickHouse was queried through the existing `superset_reader`; `currentUser()`
and `getSetting('readonly')` confirmed that identity and `readonly=1`.
Configuration labels, network membership, mounts, container IDs/start times and
safe content fingerprints were recorded before deployment. Resolved runtime
environment mappings were compared in memory before and after recreation; no
secret values or resolved configuration were printed or written to evidence.
Environment list ordering changed for API, but the name/value mappings did not.

| Service | Running image before deployment | Running image after deployment |
| --- | --- | --- |
| API | `sha256:154eae261b7b1705ed66dee7f092e692b17cb44b6e8f33d22c5fee9675edccbd` | `sha256:4febf020861fd52f09ad7b62bf0f29087b685f7bbe5d66f7e464a30304c8f63a` |
| Web | `sha256:8d3241af92ceddf9126d777a0ead612a02debedc9d479ee8dcf0c61e30c64eab` | `sha256:113c69b523e2e47e9c60c89ec58d8e0a6a4af63eb4bbbd6613f1725a3fbd2d3a` |

New tags are `football-api:9b1d-353a80d` and `football-web:9b1d-353a80d`;
both carry the full source SHA in `org.opencontainers.image.revision`.

Rollback tags were reserved before recreating either service:

- `football-api:9b1d-rollback-353a80d` retains the exact previous API image.
- `football-web:9b1d-rollback-353a80d` retains
  `sha256:edc2fe3199a60d55bbff01fb21f21d95f230def0530b12798873dce2778c1753`.
  The old running web image itself was absent from the local image store.
  The retained `football-web:8b` image was verified against the running container:
  SHA-256 matched for every HTML/JS/CSS asset and Nginx configuration file, the
  Nginx binary and installed-package database. It is an equivalent prior
  application runtime, not the same image ID. Its isolated delivery checks passed.

Both rollback and candidate images passed non-root/content/configuration audits
and isolated proxy tests: status/query/header passthrough, SPA routing, caching,
API absence and recovery, safe unavailable-data responses and log boundaries.
Rollback of the real runtime was not needed or exercised. No image prune was run.

## Build and controlled update

An isolated `git archive` of the published HEAD was initialized with an index of
only published paths. Its `git write-tree` matched the source tree above. Build
inputs contained no private environment, keys, CA files, local venv or recovered
data. npm dependencies/test output subsequently created there were excluded by
the existing Docker context rules and were not application runtime inputs.

Both production Docker targets were built from that snapshot, retaining pinned
Python 3.12.14, Node 24.13.0 and Nginx 1.28.2 versions. No source changes were
required. A temporary, non-secret Compose override changed only the two image
references. The existing private `.env` / `.passes` inputs were reused unchanged.

The application-only update used:

```text
docker compose ... --profile app-prod up -d --no-deps --no-build --pull never --wait --wait-timeout 90 football-api-prod football-web-prod
```

Here `...` denotes the explicit existing project directory, private environment
file paths, `compose.yaml` and the temporary image-only override, not new secret
arguments. API then web became healthy. No platform service dependency was
started or recreated. This was not a zero-downtime deployment; a brief local
application interruption was possible.

For a later approved rollback, use the same project/configuration inputs and an
image-only override selecting the two rollback tags above, with the same
`--no-deps --no-build --pull never` restrictions. Do not run a bare Compose update
or rebuild the rollback tags. The temporary overrides are local operator evidence,
not tracked production configuration; the table and tags above allow them to be
reconstructed without secrets. A future ordinary Compose recreation without
the deployment override would select the old `:8b` defaults in `compose.yaml`.

## Acceptance and regression results

| Check | Result |
| --- | --- |
| Python 3.12.14 application contracts | 46 PASS |
| Python 3.12.14 CI/documentation contracts | 28 PASS |
| Repository/security contracts | PASS |
| Ruff; scoped compileall; actionlint | PASS |
| Public-placeholder and private runtime Compose validation | PASS (`config -q`) |
| Frontend unit tests | 62 PASS |
| TypeScript and production asset build | PASS |
| Synthetic preview Chromium checks | 4 PASS |
| Existing production delivery suite | 46 PASS, zero failed/skipped, approximately 1.9 minutes |
| Additional operator browser checks on production | 2 PASS, desktop/mobile |
| Existing dev real-context/pass-map browser smoke | 4 PASS |
| Final `/healthz`, `/api/v1/health`, `/api/v1/health/clickhouse` | HTTP 200 |
| New API/web safe error-log counters | No unexpected errors observed |

The delivery suite contains both real-data cases and explicitly mocked failure/
fixture cases, not 46 different real matches. Published Linux Python matrix and
Windows/recovery gates were already green; no real database restore was repeated.

Real checks covered canonical deep links/reload, competition/season/match
selectors, search, Back/Forward, team comparison, shots/xG interaction and player
table/full squad. The Argentina-France shootout remained eight attempts, while
switching to a non-shootout match removed its panel. EN/RU/ES, keyboard behavior,
whole-page axe checks and no horizontal page overflow passed at 1440x900 and
390x844; the existing suite also exercised intermediate widths.

Additional checks exercised real pass pointer hover/click and keyboard selection,
arrows, team/player reset, period filters, an explicitly browser-delayed loading
state, genuine empty period-5 results,
localization and an explicitly browser-injected 503 followed by successful retry.
No API/backend was changed to simulate failure. No JavaScript page errors were
observed in these cases. Local production screenshots were visually inspected;
they are ignored under `frontend/test-results/stage9b1-d/`, not Git artifacts.

## Pass-map reconciliation

Production example:

```text
GET /api/v1/competitions/9/seasons/281/matches/3895052/passes?team_id=904&player_id=3500&period=1
```

Granit Xhaka: **31 attempts / 31 drawn / 27 completed / 4 failed / 0 unknown /
0 excluded**. An independent parameterized SELECT over `football.pass_events`
matched all 31 event IDs, exact start/end coordinates, outcomes and event order
against the production API. Each SVG line's four coordinates was also checked
against the response. Projection SHA-256:
`1eaa5a109dc4e888299599e576a2103b0d869210c760de19aa7a0b4e74a49bd9`.

The rendered pitch retains the whole 120x80 field inside viewBox
`-4 -4 128 88`, marker-end arrows and distinguishable completed/failed states.
No sampling/truncation was introduced; the existing 5000-row / 4 MiB explicit
error contracts passed. Source coordinates and all analytical formulas remain
unchanged. The UI shows the Bundesliga partial-coverage warning: Bayer
Leverkusen matches only, 34/306. This is an event-based map, not tracking movement.

| Context | Passes | Completed | Failed | Unknown |
| --- | ---: | ---: | ---: | ---: |
| WC2022 43/106 | 68515 | 56346 | 11775 | 394 |
| Bundesliga 9/281 | 39214 | 33332 | 5747 | 135 |
| Total | 107729 | 89678 | 17522 | 529 |

## Data and operational boundaries

Before/after comparisons passed for:

- All 98 canonical analysis JSON SHA-256 values.
- All 12 physical ClickHouse football tables: row counts, sum/XOR row-hash
  aggregates, build/context groups and CREATE TABLE fingerprints.
- PostgreSQL catalog row counts and complete ordered-row SHA-256 values:
  `ingestion_objects=199`, `silver_builds=14`, `gold_builds=8`,
  `clickhouse_loads=14`, `clickhouse_gold_loads=8`.
- All other 15 existing football Compose containers: identity, start time,
  status/health, mounts and network membership unchanged; existing named volume
  bindings retained. Dev containers were not recreated.

These are strong observed before/after invariants, not a global transactional
snapshot or forensic proof against hypothetical concurrent external writers.
Application traffic used only the SELECT-only reader. No ETL, migrations, build,
S3 calls, persistent data/volume changes, Airflow/Superset changes, backup/restore,
recovery-key reads or Bitwarden access were performed. No commit/push was made.
The unrelated untracked shortcut was preserved.

## Remaining limitations and next step

- Local loopback production-like service only: no public hosting, TLS termination,
  HA, authentication or capacity/SLA acceptance is claimed.
- Dense pass lines may overlap; keyboard navigation remains available for every
  returned event. Mobile pitch scale is necessarily smaller; screenshots and
  keyboard/axe checks do not substitute for every assistive-technology workflow.
- Keep candidate/rollback image tags and the reviewed image-only override for
  repeatable local operation. A future publication may update deployment guidance;
  do not assume the original `compose.yaml` image defaults deploy this revision.
- S3 isolated local recovery remains VERIFIED; overall Stage 8C remains PARTIAL.
- Recommended next work is to agree the next small football-analysis feature and
  its data/coverage contract. No Stage 9B.2/9C work was started.
