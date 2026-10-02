# Stage 5A — local read-only Django API

This is an application foundation for the future React client, **not a production
deployment**. Superset remains the BI layer. Existing ingestion, Spark, Gold,
ClickHouse views, PostgreSQL metadata and Superset are unchanged.

## Inspection and structure

The repository had no Django project, manage.py, application service, DRF or
pyproject. It used pinned requirements, environment-only connection helpers,
one bridge network `football-network`, unittest and explicit opt-in live checks.
The existing `src/common/clickhouse.py` helper is reused unchanged. PostgreSQL's
helper and S3 are deliberately not imported by the application.

Added a minimal plain Django project, with no ORM models/database, migrations,
sessions, admin, authentication or template UI:

```text
GET /api/v1/...
  -> application/views.py + transport.py (HTTP, validation, safe errors)
  -> application/services.py (composition and existence checks)
  -> application/repository.py (fixed parameterized SELECT projections)
  -> existing ClickHouse BI views
  -> application/serialization.py -> JsonResponse
```

`application/settings.py`, `urls.py`, `wsgi.py` and root `manage.py` are the Django
scaffold. `requirements/api.txt` pins Django 5.2.17 and the existing
clickhouse-connect 0.15.0. Django 5.2 is an LTS series; the selected patch was
released before this implementation date (2026-10-02), see the official
[release announcement](https://www.djangoproject.com/weblog/2026/aug/04/security-releases/).
Plain [JsonResponse](https://docs.djangoproject.com/en/5.2/ref/request-response/#jsonresponse-objects)
is sufficient here; no DRF or schema-generation dependency is introduced.

## Endpoints and sources

All routes accept GET, with **no trailing slash**. Other methods return JSON 405.
All match IDs resolve in competition 43, season 106. Another well-formed context
returns 404; malformed numeric context or match IDs return 400.

| Path after `/api/v1` | Response | ClickHouse source | BI SELECT count |
| --- | --- | --- | ---: |
| `/health` | `{"status":"ok"}` | none, no client creation | 0 |
| `/health/clickhouse` | `{"status":"ok"}` | SELECT 1 connectivity check | 1 |
| `/competitions/43/seasons/106/matches` | `{"matches":[...]}` | bi_match_overview | 1 |
| `/matches/<id>` | match object | bi_match_overview | 1 |
| `/matches/<id>/teams` | `{"match_id":id,"teams":[...]}` | overview + bi_match_team_stats | 2 |
| `/matches/<id>/players` | `{"match_id":id,"players":[...]}` | overview + bi_match_player_stats | 2 |
| `/matches/<id>/shots` | `{"match_id":id,"shots":[...]}` | overview + bi_match_shot_map | 2 |
| `/matches/<id>/xg-race` | `{"match_id":id,"xg_race":[...]}` | overview + bi_match_xg_race_series | 2 |
| `/matches/<id>/shootout` | shootout object below | overview + bi_match_shootout | 2 |
| `/matches/<id>/analysis` | composite below | the six views above | 6 |

### Fields and ordering

Match/list: `competition_id`, `season_id`, `match_id`, `match_label`, `match_date`,
`kick_off`, `competition_stage_id/name`, `home_team_id/name`, `away_team_id/name`,
`home_score`, `away_score`, `display_score`, `result_method`, `went_to_extra_time`,
`went_to_penalties`, `winner_team_id/name`. Scores/winner come from overview's
authoritative match_results semantics, not Python calculations.
List order: `(match_date, kick_off, match_id)`.

Teams: `team_id/name`, `opponent_team_id/name`, `is_home`, `goals_for`,
`goals_against`, `goal_difference`, `match_result`, `event_count`, `pass_attempts`,
`shot_count`, `shot_xg`, `shot_goals`, `under_pressure_events`, `counterpress_events`,
`players_with_events`. Exactly two rows; order `(is_home DESC, team_id)`.

Players: `team_id/name`, `player_id/name`, `is_home`, `event_count`, `pass_attempts`,
`shot_count`, `shot_xg`, `shot_goals`, `under_pressure_events`, `counterpress_events`.
Squad grain includes zero-activity players; order `(is_home DESC, team_id, player_id)`.
Only this endpoint accepts `?team_id=<positive UInt32>`. A valid ID with no rows
returns an empty players list. It does not affect `/analysis`.

Shots: `event_id`, `event_index`, `shot_label`, `team_id/name`, `player_id/name`,
`period`, `minute`, `second`, `statsbomb_xg`, `outcome_id/name`, `is_goal`,
`is_extra_time`, `start_x/y`, `end_x/y/z`. Normal-only semantics come directly from
the 015 view: periods 1–4, extra time retained, no period 5. Coordinates and xG
are copied without flips, rounding or replacement. Order is
`(period, minute, second, event_index)`.

xG race: `event_order`, `event_id`, `event_index`, `period`, `minute`, `second`,
`team_id/name`, `is_home`, `cumulative_xg`. Order `(event_order, is_home DESC)`.
No accumulation is performed in Django.

Shootout response:

```json
{"match_id": 3857265, "went_to_penalties": false, "attempts": []}
```

For a shootout, attempts contain `shootout_order`, `team_attempt_number`,
`team_id/name`, `player_id/name`, `outcome_id/name`, `is_goal`,
`home_shootout_goals_after`, `away_shootout_goals_after`, ordered by shootout_order.
The flag is taken from overview; no result or running score is recalculated.
Missing matches return 404 even on child endpoints; existing non-shootout matches
return 200, not 404. Inconsistent team/shootout coverage fails closed with 500.

Composite response keys: `match`, `teams`, `players`, `shots`, `xg_race`, `shootout`.
It uses the same repository and service methods, with **six BI queries**, not one
per player/shot. One request-scoped client is reused across those queries, then
closed; concurrent requests do not share ClickHouse sessions. The current driver
also performs **three initialization SELECTs** (version/timezone, settings,
protocol probe): measured total **nine HTTP database requests** for `/analysis`.
Individual data requests similarly add three bootstrap calls. These internal
results are never included in API responses. There is no cross-query snapshot
transaction; run validation with serving writers idle.

## Serialization and errors

UInts -> JSON numbers; Float64 -> JSON numbers without rounding; boolean flags
(including source UInt8 is_home) -> JSON true/false; Nullable -> null; Date ->
`YYYY-MM-DD`; UUID -> canonical string. Kick-off retains its source clock text.
NaN/infinity and unsupported types fail closed, not invalid JSON or silent
numeric-to-string conversion. Explicit projections exclude build IDs, load
timestamps and internal database metadata. React must account for JavaScript's
integer precision if IDs ever exceed 2^53-1; current WC2022 IDs are below that.

All errors use `{"error":{"code":"...","message":"..."}}`:

| HTTP | code | Meaning |
| --- | --- | --- |
| 400 | invalid_request | malformed/out-of-range ID, repeated/unknown query parameter, bad host |
| 404 | match_not_found | no match in WC2022 context |
| 404 | context_not_found / not_found | other competition/season or unknown route |
| 405 | method_not_allowed | only GET is supported |
| 503 | clickhouse_unavailable | connection/driver failure |
| 500 | server_error | unexpected code, serialization or serving-integrity failure |

No raw exceptions, SQL, environment values or stack traces in responses. Safe
application logs contain only a fixed error code or exception class. DEBUG is
always false. Requests never contain SQL identifiers/fragments: values use typed
ClickHouse placeholders, columns/views/orderings are code-owned constants.

## Docker and security boundary

Only `football-api` was added. The image uses the existing Python base version,
runs as UID 10001, copies only application code/the one shared client helper and
does not mount the repository or `.env`. It receives no S3/PostgreSQL credentials.
The current SELECT-only `superset_reader` profile is reused through existing
SUPERSET_CLICKHOUSE_USER/PASSWORD mappings to the common CLICKHOUSE_* variables.
No credentials were changed, read or printed; no new grants were needed. Superset
itself is untouched. A separately scoped API principal can be reviewed later.

Each application query additionally sets readonly=1. The reader profile forbids
other per-query setting changes, so response limits are enforced by constant
LIMIT 10001 plus a 10000-row guard (never silently truncated). No data writes or
DDL paths exist. The helper retains its existing 10s connect/300s receive timeout
and no query retries; tighter web request deadlines require later review.

Development port: **127.0.0.1:18000 -> container 8000** (`API_HOST_PORT` override).
It was unoccupied during this task. ALLOWED_HOSTS contains only localhost,
127.0.0.1 and football-api. Healthcheck uses the independent health endpoint;
ClickHouse failure does not make process liveness fail. No dependency startup is
required for liveness. Commands below use `--no-deps` to leave existing services
alone; live data checks require the existing ClickHouse to already be running.

No new persistent Django secret is needed for this stateless stage: settings
generate an ephemeral per-process key, optionally accepting DJANGO_SECRET_KEY.
Before adding sessions/signing, provide a stable managed secret explicitly.
No admin/auth/session/cookie functionality is enabled.

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
docker compose build football-api
docker compose run --rm --no-deps football-api python manage.py check

# SELECT-only contract checks, Django in-process: no HTTP server required.
docker compose run --rm --no-deps football-api python scripts/check_application_api.py

# Start only this local development service, after checks pass.
docker compose up -d --no-deps football-api
Invoke-RestMethod http://127.0.0.1:18000/api/v1/health
Invoke-RestMethod http://127.0.0.1:18000/api/v1/matches/3869685/analysis

# Same validator through the actual HTTP transport.
docker compose exec -T football-api python scripts/check_application_api.py --base-url http://127.0.0.1:8000
# Optional stop of only the application service:
docker compose stop football-api
```

Use `python manage.py runserver 127.0.0.1:18000 --noreload` for a host-venv run
after installing requirements/api.txt and securely supplying CLICKHOUSE_* values
for the host-mapped ClickHouse port. The application does not load .env itself.
Do not expose Django runserver publicly or treat it as a production WSGI server.

## Repeatable tests (no external network needed after image build)

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'test_*.py'
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'integration_api.py'
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
docker compose run --rm --no-deps -e PYTHONPYCACHEPREFIX=/tmp/football-api-pycache -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m compileall -q application manage.py scripts/check_application_api.py tests/application
git diff --check
```

API tests are separate from existing python-tools discovery, so Django is not
added to the ingestion tools image. The integration file is deliberately not
named test_*.py; running offline discovery never connects to ClickHouse.

Verified: **416 existing offline tests, 19 API offline tests, 3 live API tests**.
The live suite checks Argentina–France (3869685), Netherlands–Argentina (3869321),
Mexico–Poland (3857265), Croatia–Morocco (3869684), compares individual/composite
responses, validates filtering/types/order, 404/400, normal shots and xG finals.
It also checks all 64 matches: 3244 players including zero-activity rows, 1453
normal shots, 45 extra-time shots, 41 shootout attempts, xG 155.8985419302.
Argentina–France: 30 normal shots, 8 shootout attempts, final cumulative xG
2.758305926 / 2.2726179490000002. Mexico–Poland: no shootout, empty attempts.
Existing Stage 4C/4D/4E installed validators still passed. Django system check,
compose config -q, compilation and whitespace checks are run separately.

### Measured local HTTP latency (not an SLA)

Measured 2026-10-02 from Windows PowerShell Invoke-RestMethod through
127.0.0.1:18000 into a temporary API container, one warm-up then five sequential
requests per endpoint. Includes local HTTP/JSON overhead and client bootstrap;
no concurrent load, no API cache. These numbers are specific to this machine.

| Endpoint after /api/v1 | Median ms | Min–max ms |
| --- | ---: | ---: |
| /health | 1.66 | 1.45–2.79 |
| /competitions/43/seasons/106/matches | 17.66 | 17.13–18.46 |
| /matches/3869685 | 14.21 | 13.79–14.61 |
| /matches/3869685/shots | 26.86 | 26.58–27.48 |
| /matches/3869685/analysis | 80.73 | 78.30–81.84 |

The full validator also passed through real HTTP. The temporary run --rm
container was stopped after measurement and automatically removed; the application
is not left running. No existing Docker service was stopped or recreated.

## Limitations and Stage 5B boundary

WC2022 only, no pagination for the bounded current dataset, no application cache,
no durable shared client, no atomic multi-view snapshot. Direct requirements are
pinned; this is not a complete transitive dependency lock. Image builds need the
package registry, tests do not. This is a local read-only API, not a hardened
public deployment; production WSGI hosting, TLS, stable secrets, request/rate
limits and independently scoped credentials are future deployment work.

No wildcard CORS and no CORS package. Plan same-origin React + /api/v1 reverse
proxy (or a development frontend proxy). If cross-origin becomes necessary,
review an explicit origin allowlist, not '*'. OpenAPI is a later enhancement;
the endpoint/field contracts here are the current reference.

Stage 5B should consume /matches and /analysis for selection, result header,
team/player tables, xG race, shot map and shootout. Keep loading/empty/error states
and typed JSON mapping in React. Pitch/SVG coordinate orientation belongs to an
explicit display transform, never a rewrite of raw fields. The frontend must not
receive ClickHouse credentials, query S3/PostgreSQL, recalculate analytical
metrics or replace Superset. No React/plugin implementation is part of Stage 5A.

Not executed: ClickHouse migrations or writes, S3/Gold publishing, Superset
changes, secret inspection, Docker prune/down, Git commit or push. No Redis,
Celery, GraphQL, Kubernetes or authentication was added.
