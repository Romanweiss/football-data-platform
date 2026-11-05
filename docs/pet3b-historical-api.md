# PET-3B: Historical UEFA results-only Django API

Scope: OpenFootball UCL 2024/25, isolated serving only, **not deployed**.
Stage 8C: PARTIAL. No frontend integration or production persistent onboarding.

## Routes and existing API compatibility

The existing API uses `/api/v1`, no trailing slash, and `APPEND_SLASH=False`.
The historical namespace follows that convention, rather than introducing
unversioned `/api/competitions/historical/` aliases:

```text
GET /api/v1/competitions/historical
GET /api/v1/competitions/historical/uefa-champions-league/2024
GET /api/v1/competitions/historical/uefa-champions-league/2024/fixtures
GET /api/v1/competitions/historical/uefa-champions-league/2024/participants
GET /api/v1/competitions/historical/uefa-champions-league/2024/coverage
GET /api/v1/competitions/historical/uefa-champions-league/2024/quality
```

These are additive; existing StatsBomb competition/season/match URLs, Match Lab
analysis, Pass Map, Smooth/Grid heatmap, shots, xG race, shootout and player APIs
are unchanged. The current synthetic UCL 2026/27 frontend source is not replaced
or mixed with historical OpenFootball. Unknown season/competition gets 404;
invalid queries get 400, non-GET gets 405. Unsupported standings/events routes
remain 404, not fabricated datasets.

## Serving and provenance

The four real PET-3A serving views and types were inspected before SQL was written:
`historical_fixtures`, `competition_participants`, `stage_round_coverage`,
`source_quality`. Date is native ClickHouse Date; canonical scores and UTC kickoff
are nullable, and standings eligibility is false.

Source: `openfootball/football.json@e6744429ee395bc86f247348c6184bb08d4eb361`,
`2024-25/uefa.cl.json`, CC0-1.0.

Source SHA-256:
`12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6`.

Accepted batch:
`ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc`.

`DatasetContract` contains public counts and logical fingerprints already
verified in [PET-3A](pet3-openfootball-etl.md). Counts are not embedded in Django
views: summary and pagination totals derive from the serving rows. Every request
validates all four datasets against that pinned content contract. A partial,
different or mixed generation is NOT_READY/503, not a silently accepted update.

For this tiny fixed season, the reader performs four bounded SELECTs per request
and filters/paginates their validated in-memory result. It does not query S3 or
Parquet per request, normalize providers again, infer results, or cache a hidden
synthetic fallback. SQL has explicit projections/order, typed database Identifier,
batch/source String parameters and UInt32 row bound (4097 guard rows). It reuses
`FootballRepository._query`, `readonly=1`, native serialization, driver exception
sanitization and existing HTTP middleware/error envelopes.

The maximum supported dataset is 4096 rows/view, maximum verified bundle 2 MiB,
maximum JSON response 1 MiB. No silent truncation/sampling occurs. This design is
not a scalable multi-season query engine or a claim of cross-query/global ACID:
content fingerprints fence the single approved immutable bundle. A changed
source/batch requires an explicitly reviewed new metadata contract.

## Pagination and filters

Paginated collections accept `limit=1..100` (default 50) and `offset=0..10000`
(default 0). Response `pagination` contains `limit`, `offset`, `total`, `returned`
and nullable `next_offset`. Past-end pages are empty with the true total retained.

| Collection | Filters | Stable order |
| --- | --- | --- |
| fixtures | team_id, stage_id, round_id | match_date, fixture_id |
| participants | team_id | participant_id |
| coverage | stage_id, round_id | date_min, stage_id, round_id |
| quality | team_id, stage_id, round_id | fixture_id, code |

Filters use exact canonical `uefa:participant:<64 lowercase hex>`,
`uefa:stage:<64 lowercase hex>` and `uefa:round:<64 lowercase hex>` identities.
They are validated before opening a connection and never interpolated into SQL.
Repeated, unsupported, malformed or injection-like parameters get 400. A valid
unknown identity or impossible filter combination returns an empty 200 page.
Quality filters select the matching fixture IDs, preserving every diagnostic;
its `diagnostic_counts` covers the full filtered set, not merely the current page.
Index and overview do not accept filters/pagination parameters.

## DTO and score semantics

TypedDict contracts distinguish known source observations, unknown values and
unsupported derived metrics. Competition/season/participant/stage/round IDs are
source-scoped canonical identities, not StatsBomb numbers. Fixture DTOs include
provenance and the adapter's explicit `status_origin` (not a live official-status
feed); collection/overview envelopes provide provenance, capabilities,
coverage and freshness for their entire scope.

Examples below are response projections, not full payload dumps. The source's
final remains unknown even though its actual outcome could be known elsewhere:

```json
{
  "match_date": "2025-05-31",
  "home": {"state": "known", "name": "Paris Saint-Germain FC (FRA)"},
  "away": {"state": "known", "name": "FC Internazionale Milano (ITA)"},
  "status": "unknown",
  "result_availability": "MISSING",
  "kickoff_utc": {"state": "unknown", "value": null},
  "source_reported_score": {
    "ht": {"state": "unknown", "value": null},
    "ft": {"state": "unknown", "value": null},
    "et": {"state": "unknown", "value": null},
    "p": {"state": "unknown", "value": null}
  },
  "canonical_regulation_score": {"state": "unsupported", "value": null},
  "score_semantics": {"scope": "source_reported_only", "ft_period_verified": false, "quality": "MISSING_RESULT", "source_score_state": "EMPTY"}
}
```

`known` on an ht/ft/et/p pair means only that those raw source numbers exist.
It does **not** verify the represented period, regulation score, ET inclusivity,
penalty resolution, result/winner, points or official standings. Unknown is null,
never 0:0; an actual source zero is retained. There are no winner/points/standings
data fields. Capability flags explicitly mark standings, verified regulation
scores and event analytics unsupported; upstream capability declarations are
retained separately and are not promoted to verified coverage.

Verified summary from the real isolated dataset:

```json
{
  "fixture_records": 189,
  "participant_records": 36,
  "source_stages": 3,
  "coverage_records": 14,
  "non_fatal_limitations": 394,
  "source_reported_ft": 188,
  "unknown_results": 1,
  "ambiguous_components": 2
}
```

Source coverage remains UNKNOWN; results remain INCOMPLETE. All 394 NON_FATAL
limitations remain available. Git source revision is distinguished from an
unsupported global provider revision. Gold has no reliable observation timestamp:
freshness is `pinned_historical`, `last_observed_at` unknown, not the HTTP clock.

## Configuration, NOT_READY and isolation

The new API is disabled by default. Only its dedicated host process reads:

```text
HISTORICAL_API_ENABLED=true
HISTORICAL_CLICKHOUSE_HOST=pet3-openfootball-ch-<12..32 hex>
HISTORICAL_CLICKHOUSE_DATABASE=pet3_openfootball_api_<12..32 hex>
HISTORICAL_CLICKHOUSE_PASSWORD=<temporary isolated reader password>
```

The role is fixed to `historical_reader`; timeouts are bounded and retries off.
The factory never reads existing `CLICKHOUSE_*`, S3/PostgreSQL credentials or
environment files. Production host/database names are rejected. This is an
isolated prototype configuration, not instructions to connect a deployed API
container to Docker or production data. HTTP/8123 is used only inside the private
internal network of disposable tests; production TLS/configuration needs a
separate future review.

Disabled/missing configuration, unavailable source, absent tables/data, wrong
source/batch/fingerprint, duplicates or size/integrity violations return:

```json
{"error":{"code":"historical_not_ready","message":"Historical serving dataset is NOT_READY"}}
```

Status is 503, no-store. No SQL, native driver error, connection value, token or
fallback synthetic data is returned. Existing HTTP error/log sanitization is
preserved. Availability of the tmpfs server is not production readiness.

## Reproducible integration and tests

```text
python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python scripts/check_historical_api.py --gold-store data/work/pet3-openfootball-isolated --confirm-isolated-tests
```

On a fresh environment, build the existing CI image first (no production image
or service is involved):

```text
docker build --build-arg PYTHON_VERSION=3.12.14 -f ci/Dockerfile -t football-ci-checks:8a .
```

The runner defaults to this repository-buildable image and never pulls at test
runtime. `--checks-image` also accepts the already verified local Python 3.10/3.12
check-image aliases used for this task's two-runtime evidence; those aliases are
not a prerequisite for a fresh checkout. Dependencies stay pinned by the existing
requirements and CI Dockerfile; no host installation is needed.

The integration runner loads the already verified Gold into a **fresh** owned
networkless tmpfs ClickHouse using the existing attested loader. It creates a
SELECT-only reader with readonly=1, then moves only this new server from `none`
onto a new private internal network with a disposable Django test client image.
The client mounts only application, source code and application tests, not the
project root, raw JSON, Parquet, receipts, environment files or local venv.
No Docker socket or host ports are exposed. The original PET-3A tmpfs server stays networkless;
production services/networks/volumes are not changed. Cleanup stops/removes only
the two newly captured test container IDs and removes only its newly created
network ID, including after a test failure/timeout. No broad prune/down is used.
No Bronze/Silver/Gold pipeline or production ingestion is executed by this check.

The runner uses installed pinned Python 3.10.12 / 3.12.14 checks images, not a
local venv or production API process. The real dataset is an explicit local
integration input, not a CI dependency or committed fixture. Automatic offline
tests use artificial data and injected test-only contracts; the runtime factory
cannot select a synthetic contract via HTTP/environment. No real account
credentials are required; the test-only reader identity is disposable.

Tests cover all routes, counts, 189 unique fixtures, unknown final, ambiguous raw
components, date-only fidelity, quality membership, stable pages/filters, query
parameter safety, strict configuration gates, source absence/503, actual readonly
profile, bounded outputs, no secret leakage and existing API regression.

Local verification (2026-11-05):

| Suite | Result |
| --- | --- |
| Linux Python 3.10.12 / 3.12.14 application | 76 PASS per version, including 15 new historical tests |
| Real-Gold isolated ClickHouse + Django integration | six PASS per version: all routes/counts, semantics, pages/filters, errors, absent dataset/503, actual readonly profile |
| Offline root regression | 1089 cases per version, OK with nine Windows-only skips |
| CI/security/documentation contracts | 73 PASS per version |
| Ruff / compileall / repository / Markdown links / diff checks | PASS |

An initial fixture setup attempt exposed Docker's refusal to join an internal
network while the new container was still attached to `none`. The runner now
explicitly disconnects only its own new ID before attachment. No production
network or original PET-3A container was changed; all disposable test resources
are cleaned up. The successful runs validate the real 189/36/14/394 serving
records, not synthetic HTTP results. Offline cases separately use synthetic
fixtures, and never claim to validate the real season.

HEAD remains `5ddab063208daba2d3927edbcee4860b556eece0`; no staging/commit/push.
The licensing index remains `0483341376f8c0ec7040451d30f6793d41552140` with both
original licensing blob IDs. Planning documents, shortcut and ignored PET-2/PET-3A
datasets/receipts/helpers are preserved. The historical API files are local only.

## PET-3B publication review

Publication unit: the original nine PET-3B files plus
`tests/integration/test_historical_api.py` and a minimal change to the existing
database job in `.github/workflows/ci-integration.yml` (11 files total). No new
workflow, infrastructure service, dependency, API feature or canonical Match Lab
route is introduced. The application implementation did not need a functional
fix during review; source-only contracts and query boundaries remain unchanged.

### Fingerprints, partial publication and TOCTOU

Each SELECT binds the same reviewed batch and source SHA. Its exact returned
rows are converted to private request-local Python/JSON objects, verified against
the corresponding immutable logical fingerprint, and then used for the response.
The service does not fetch again after validation or retain references to live
backend buffers. Synthetic regressions prove both boundaries:

- A changed generation between SELECTs, missing rows or foreign-batch DQ rows
  fail closed with 503 and expose no partial fixture list.
- Changing the backend after `load()` cannot change the already validated DTO
  result, and rendering performs no additional data SELECT.
- Restoring exact approved data restores availability; no fallback or source
  correction is performed by the API.

This establishes content consistency of the pinned historical bundle, not a
global ACID transaction, latest-source guarantee or an atomic wall-clock snapshot
of arbitrary mutable tables. Rows from other batches are not merged into it.

### Performance and limits

Initial review measurement, Python 3.12.14, fresh SDK client per HTTP request,
local Docker internal network, 189/36/14/394 rows, page `fixtures?limit=100`:

| Measurement | Observed |
| --- | --- |
| Timed samples (without allocation tracing) | 5 |
| Median / maximum request latency | 55.200 / 63.690 ms |
| Data SELECTs / SDK HTTP exchanges per request | 4 / 7 (three SDK bootstrap exchanges) |
| Response bytes | 193594 |
| Separate tracemalloc peak | 6210283 bytes; Python allocations, not process RSS |
| EXPLAIN | MergeTree PrimaryKey, Parts 1/1, Granules 1/1 |

An empty past-end page also performs four SELECTs. Pagination does not reduce the
full pinned-season validation cost: all 633 logical serving rows are read and
hashed per request, and filters/offsets are applied in memory. There is no per-row
N+1, unbounded page size or request-global cache, but this is intentionally not a
large multi-season/high-concurrency serving design. One current tiny part/granule
is scanned; do not infer index selectivity or bounded scanned bytes for arbitrary
future tables merely from LIMIT. No premature cache/optimization was added.

Connection timeout is 3 s, SDK send/receive timeout 15 s, no query retries. These
are per-operation limits, not a whole-request deadline. The isolated reader role
also has max_execution_time=10 and max_result_bytes=2097152. Application checks
bound rows/serialized bundle/response, but its post-read 2 MiB check is **not** a
hard Python heap cap against a malicious/misconfigured server; preserve reviewed
server profile/resource limits before any future persistent deployment. No load,
concurrency, RSS or RPO/RTO/SLA guarantee is claimed by these measurements.

### Existing CI integration and clean snapshot

CI fast already discovers the historical offline application and completeness/
security contracts on pinned Python 3.10.12 and 3.12.14. The existing ephemeral
PostgreSQL/ClickHouse job now additionally executes
`tests/integration/test_historical_api.py` against its own CI ClickHouse.
It checks the exact existing CI host/user/database/ephemeral flag before creating
fresh private synthetic Memory tables and four views. A test-only injected
contract validates artificial Gold through the real SDK and Django routes;
partial/foreign-batch publication and SQL-injection attempts are covered.
There is no runtime option to select that synthetic contract. No real Gold,
source JSON, credentials or ignored artifacts become CI inputs. Missing/wrong CI
configuration fails rather than skipping. No existing check is disabled.

Real-Gold integration remains a separate opt-in local check: its fresh server is
seeded from the existing verified local Gold, never by ingestion or a new Spark
build. For clean-source verification this input stays outside the Git snapshot;
neither HTTP client nor snapshot contains the raw JSON, Gold, receipts, venv or
temporary helpers. The host test runner alone verifies and loads that explicit
Gold input into its disposable server.

Review suites: application 79 (18 historical + 61 existing), CI/security/contracts
74 per Python version; real-Gold integration seven per version, including the
performance/EXPLAIN probe; database-backed synthetic CI integration three per
version. Root offline regression retains 1089 cases with nine Windows-only
skips. Skips are not counted as Windows ACL execution. Ruff, compileall,
documentation links, repository, actionlint and diff checks are separate gates.
These are local review results, not remote GitHub CI or deployment acceptance.

The proposed tree uses a separate temporary index; the main licensing index and
both original staged blobs remain unchanged. Planning/shortcut/ignored runtime
artifacts are not publication files. No commit/push or production SQL is part of
this review. Production container identity checks do not imply fresh SQL/hash
reconciliation of all production datasets.

## Limitations and PET-3C

No React changes, ingestion, production migrations, deployment, live source API,
verified 90-minute scores or official standings. No production ClickHouse
connection is made by the new API/tests. Existing production integrity is
protected by separate target configuration and unchanged deployed containers;
offline application regressions cover the existing API contracts. This is not
a claim of rerunning every production analysis hash during PET-3B.

PET-3C can add a results-only historical React source behind explicit source and
coverage badges, consume `next_offset` and exact canonical filters, show null
scores honestly and suppress Match Lab event controls. That is a separate task;
no frontend source switching or production configuration is authorized here.
