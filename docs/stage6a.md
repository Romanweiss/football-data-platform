# Stage 6A — Multi-competition / multi-season foundation

## Scope and status

Serving/application contracts now use `(competition_id, season_id, match_id)`.
Only WC2022 (43/106) is currently present and live-verified. Synthetic tests exercise
multiple competitions/seasons, including reused match IDs; this is **not** proof
of end-to-end support for a second real dataset. No ingestion, S3 reads/publishes,
DDL, metric changes, Superset changes or commits were performed in Stage 6A.

## Hardcoded-context audit

Baseline: `1d2480b1224c3ae2c52c99c314658c1ba37ffcc3`.
[Line-level audit](stage6a-context-audit.csv) records 409 matching baseline lines:
A = legitimate fixtures (138), B = WC2022 regression/smoke expectations and
historical examples (221), C = runtime context assumptions (50).
Line numbers refer to the baseline, not the modified working tree. A line can
contain several occurrences; the disposition applies to all of them.

The initial tracked-file search, supplemented by review of callers, schemas,
SQL joins/window partitions, metadata and environment defaults, was:

```powershell
git grep -n -I -i -E '\b43\b|\b106\b|wc[_ -]?2022|world[ _-]cup[ _-]2022|64 matches|386[0-9]{4}|385[0-9]{4}' 1d2480b -- . ':!.env' ':!keys.txt' ':!frontend/package-lock.json'
```

Secrets and ignored runtime artifacts are outside this audit. Tracked Compose
and `.env.example` have no competition/season default to change. Fixture values
and historical validation evidence were not blindly replaced. Frontend generic
fixtures now use synthetic 11/22; explicit live golden tests retain 43/106.

| Area | Classification / disposition |
| --- | --- |
| API repository/view fixed context | C: removed; full bound context |
| Frontend API URL, tournament title/count, HTML description | C: catalog-driven |
| API validator fixed context/count | C: generic CLI plus explicit WC regression |
| Match-results validator SQL and metadata lookup | C: explicit CLI context |
| Model helper defaults | C: helpers accept context; generic CLI passes it explicitly; legacy defaults retained |
| Bronze/Silver/Gold orchestration and loader input resolvers | C: retained, exact 6B blockers below |
| Stage 4 cutover, shot audit, match-analysis/visual checks, pinned stats snapshot | B: deliberately WC2022-specific, not generic platform checks |
| Offline/Spark/SQL fixtures | A: test data, not runtime defaults |
| Live smoke, historical docs and shot-audit snapshot | B: retained golden expectations |

## Authoritative catalog and metadata discovery

Availability comes from `SELECT DISTINCT` over existing
`football.bi_match_overview`, ordered by numeric ID. These are matches actually
available to the application, not merely registered upstream artifacts.
No new table, manual registry or migration was needed.

| Requested field | Current stored/serving support |
| --- | --- |
| competition_id, season_id | Silver matches and context columns across CH serving tables/views and PG build/load catalogs |
| competition_name, season_name | Not projected into current Silver matches or CH serving contracts; no name fields in inspected PG catalogs |
| competition_gender, competition_youth, competition_international | Not exposed in those contracts |
| country_name | Player nationality exists in lineup/player data; it is not competition country metadata |

The Bronze ingestion definition includes upstream `competitions.json`, but its
body was not read from S3 during this task. Adding an authoritative name projection
can be considered in 6B; do not turn UI labels into a parallel metadata registry.
PostgreSQL `silver_builds`, `gold_builds`, `clickhouse_loads` and
`clickhouse_gold_loads` already carry competition/season context;
`ingestion_objects` tracks artifact identity. They remain the lineage/control
catalog, not a second serving availability source. Read-only inspection found
only 43/106 in the current Silver build contexts and 64 serving matches.

The API therefore returns only supported fields:

```json
{"competitions": [{"competition_id": 43}]}
```

```json
{"seasons": [{"season_id": 106}]}
```

UI fallbacks are localized `Competition #43` / `Season #106` equivalents. Source
team/player names are not translated. EN/RU/ES cover selectors, empty states,
loading and safe context errors.

## API and compatibility

```text
/api/v1/competitions
/api/v1/competitions/<c>/seasons
/api/v1/competitions/<c>/seasons/<s>/matches
/api/v1/competitions/<c>/seasons/<s>/matches/<m>
  /teams /players /shots /xg-race /shootout /analysis
```

IDs are validated before opening a repository; competition/season are positive
UInt32. Queries bind full context, including every child projection and optional
player team filter. Query identifiers remain internal allowlisted constants.
There is no fallback to 43/106. Match list ordering remains
`match_date, kick_off, match_id`; catalogs order by numeric ID.

Stage 5 response structures and metrics are unchanged. Successful composite
analysis uses six data SELECTs (overview plus five sections), with one reused
client per request. Driver bootstrap is separate (three requests in the measured
deployment); no per-player queries, joins or analytics were added to the API.

Live inspection found no currently ambiguous IDs, but the stored composite keys
do not guarantee global match-ID uniqueness. Legacy `/api/v1/matches/<m>` and
children first resolve identity across available contexts:

- exactly one match: use its context through the same service logic;
- absent: normal `match_not_found` 404;
- multiple contexts: `ambiguous_match` 409; caller must use canonical URL;
- duplicate stored identity: safe integrity error, never arbitrary selection.

Unknown competition/season produce distinct `competition_not_found` /
`season_not_found` 404 errors; invalid IDs produce 400. ClickHouse unavailability
retains 503. Existing JSON error structure and safe redaction remain; no SQL,
tracebacks or environment values reach the frontend.

## Frontend hierarchy and routing

Canonical URL:
`/competitions/:competitionId/seasons/:seasonId/matches/:matchId`.
Competition/season intermediate URLs support selection and deterministic landing.
Root selection is first numeric competition → first numeric season → first match
in documented chronological API order. Empty catalogs remain empty states, not
fabricated defaults. Unknown explicit contexts show errors, not a fallback.

Changing competition resets season/match; changing season resets match. Automatic
selection uses history replacement so Back/Forward visits meaningful selections.
Legacy `/matches/:matchId` resolves through the API overview and replaces the URL
only when unambiguous. Deep links/reloads and browser history preserve full context.

The existing searchable match combobox filters the loaded context list locally;
typing does not issue requests. Resource keys include the entire context, requests
are aborted on changes and late responses ignored. Analysis/shot interaction state
resets even if another context reuses the same match ID. Language persists in
localStorage without refetching data. Typed Competition/Season/Context and route
unions were added; no `any` shortcut. React still accesses only the API, never CH.

## Validation policy

Generic commands require both `--competition-id` and `--season-id`:

- `check_application_api.py`: catalogs, contextual list, canonical sections and
  composite consistency; up to four available matches, no 64/32-team assumption.
- `check_clickhouse_model.py`: current loaded Silver/Gold references in context.
- `check_clickhouse_gold_model.py`: explicit context plus existing v1/v2 option.
- `check_clickhouse_match_results.py`: context-bound PG references and CH/BI checks.
  Its SQL file is now a bound-parameter template, not a standalone unbound query.

API `--wc2022-regression` explicitly requires 43/106 and checks 64 matches, four
golden matches and alias equivalence. Historical Stage 4 shot-audit/cutover/
match-analysis/match-visuals tools remain WC2022 regressions. Their counts and
coordinate review bounds are **not** universal DQ constraints. Historical stage
docs record those scoped checks; use commands below for the new generic entrypoints.

## Pipeline review and Stage 6B blockers

| Component | Readiness |
| --- | --- |
| CH tables/views, joins and windows | Context columns/keys already present; no routing migration required |
| PG build/load catalogs and lookup helpers | Explicit context supported |
| Build specifications, paths, manifests; low-level loaders | Carry selected build/context; reuse rather than redesign |
| `src/gold/inputs.py`, transformations | Context parameters already supported |
| `src/analytics/{model,gold_model,matches_model}.py` | Partially parameterized: explicit context supported; legacy WC defaults remain, new CLIs never rely on them |
| `src/silver/statsbomb/matches.py` | Context-aware validation, but defaults and wrapper still WC; thread context in 6B |
| `scripts/ingest_statsbomb_bronze.py` | Fixed 43/106 matches URL/prefix and `world_cup_2022_matches` dataset |
| `scripts/ingest_statsbomb_match_data.py` | Fixed parent dataset; child URL helpers accept match IDs |
| `src/silver/job.py`, `scripts/build_silver_event_core.py` | Fixed context and parent selection |
| `src/silver/matches_job.py`, `build_identity.py` | Fixed context/DQ parent selection and accepted 43/106 parent URL contract |
| `src/analytics/{silver_input,gold_input}.py` | Loader input selection fixed to 43/106 |
| `src/gold/job.py`, `stats_snapshot.py` | Fixed orchestration context; v2 enforces four reviewed WC Silver build IDs |

6B must explicitly parameterize parent selection, URLs/prefixes and lineage
resolution through these orchestrators before loading another context. Review the
v2 pinned snapshot contract per dataset/context: do not remove integrity checks or
silently switch to latest builds. Preserve existing WC lineage/build identities,
DQ, output contracts and normal-shot/shootout semantics. Evaluate competition
metadata projection from authoritative source data if human-readable labels are
required. Then onboard one real additional competition/season, exercise both
contexts and legacy ambiguity, and re-run WC regression. Generic serving is ready
for that work; multi-dataset ETL and second-real-context correctness are not yet
proven. No Airflow/Kafka is needed for this foundation.

## Verification evidence

- Offline Python: 418 passed. API offline: 26 passed. Django system check: passed.
- Frontend: 50 unit tests passed; TypeScript/Vite production build passed.
- `docker compose config -q` and `git diff --check`: passed.
- Browser: 13 Playwright tests passed (Chromium-based Edge on Windows), including
  original Stage 5 smoke, synthetic multi-context navigation, canonical legacy
  resolution, responsive EN/RU/ES and accessibility checks.
- Opt-in SELECT-only API integration: 3 passed; all 64 matches, 3244 squad rows,
  1453 normal shots (45 extra-time), 41 shootout attempts; normal xG total
  155.8985419302. Measured composite: 6 data + 3 bootstrap requests.
- Live API WC regression passed. Argentina–France: 30 normal shots, 60 cumulative
  race states, 8 shootout attempts, xG 2.758305926 / 2.2726179490000002.
- Normalized final-analysis JSON SHA-256 before/after canonical routing is identical:
  `41cd75ffe292cecf22a42cbd013e4d332bda3ec64ce7bc5606b8a845642f9cfd`.

Synthetic multi-context tests mock the API/repository, not real catalog writes.
No second dataset was added. Responsive checks cover 390/768/1024/1440 widths;
existing shot synchronization, full-roster option, markers and pitch are unchanged.

## Manual commands (PowerShell, project root)

Build/restart only the two application services if needed:

```powershell
docker compose build football-api football-web
docker compose up -d --no-deps football-api football-web
docker compose config -q
git diff --check
```

API manual read-only checks (current default host ports):

```powershell
curl.exe -fsS http://127.0.0.1:18000/api/v1/competitions
curl.exe -fsS http://127.0.0.1:18000/api/v1/competitions/43/seasons
curl.exe -fsS http://127.0.0.1:18000/api/v1/competitions/43/seasons/106/matches
curl.exe -fsS http://127.0.0.1:18000/api/v1/competitions/43/seasons/106/matches/3869685/analysis
curl.exe -fsS http://127.0.0.1:18000/api/v1/matches/3869685/analysis
docker compose run --rm --no-deps football-api python scripts/check_application_api.py --competition-id 43 --season-id 106
docker compose run --rm --no-deps football-api python scripts/check_application_api.py --competition-id 43 --season-id 106 --wc2022-regression
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_model.py --competition-id 43 --season-id 106
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_gold_model.py --competition-id 43 --season-id 106 --transform-version v2
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_results.py --competition-id 43 --season-id 106 --bi
```

Automated checks (live integration/smoke use only current local serving data):

```powershell
docker compose run --rm --no-deps football-api python manage.py check
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'test_*.py'
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p integration_api.py
Push-Location frontend
npm.cmd test
npm.cmd run build
npm.cmd run test:smoke
Pop-Location
```

Open `http://127.0.0.1:15173/` and the canonical final URL; refresh, use Back/Forward,
switch EN/RU/ES, type in the match search. The real selectors correctly contain
one competition and one season today. Do not invent a second live selector option.

## Changed file groups

- Backend: `application/{repository,services,views,urls}.py`.
- Frontend: `index.html`, `src/{App,api,types,locales,styles}`, new `routes.ts`,
  `useResource.ts`, `components/ContextSelector.tsx`, updated `components/States.tsx`.
- Validators: new `src/analytics/context.py`; `scripts/check_application_api.py`,
  `check_clickhouse_model.py`, `check_clickhouse_gold_model.py`,
  `check_clickhouse_match_results.py/.sql`; WC scope docstring in
  `check_clickhouse_match_visuals.py`.
- Tests: application API/context/validator/integration tests; frontend API/app/
  fixtures/context/smoke tests; context CLI/model/Gold tests and match-results SQL fixture.
- Documentation: README, this report and the baseline line-level audit CSV.
