# Stage 9C.2-A: provider-neutral football contracts

Baseline: `8f7728605e8de0c079f7cbb3a77e79463df803bb`, branch `master`.
Stage 9B.2-F: ACCEPTED. Stage 8C: PARTIAL.

Status: **PROVIDER_UNDECIDED**. Foundation: implemented with synthetic data;
real-source onboarding: BLOCKED. No source is connected to S3, PostgreSQL,
ClickHouse, Airflow, Django or React by this stage.

## Architecture gate: Stage 9C.1 evidence

The read-only audit on 2026-10-29 found the following. Public catalogue presence
is not proof of endpoint completeness, licensing or actual match capabilities.

| Candidate | Observed evidence | Unresolved gate |
| --- | --- | --- |
| football-data.org | Public catalogue lists UCL 2026/27 (`2001`, `CL`); unauthenticated fixtures/standings requests returned 403 | Authenticated season payload and the 36-team table unverified; competition docs say CUP standings return 404 |
| API-Football | All four UEFA tournaments advertised; unauthenticated season probe returned 403 | Actual 2026/27 coverage, standings and publication/storage rights unverified |
| OpenFoot | Public demo returned fixture samples for all four UEFA 2026/27 contexts; future scores were null | Preview is not full inventory; UEFA standings unavailable; underlying source marked Unlicensed-Beta |
| Sportmonks | UEFA fixtures, standings and stage/round structures advertised | No authenticated season payload inspected; exact capabilities and rights need confirmation |

API-Football remains a candidate, not a selected/approved live provider. No user
API key is needed for this stage. The audit used only public/explicitly public
demo access and did not persist provider payloads. The JSON files here contain
invented teams, fixtures and scores, not downloaded API responses.

Primary references, checked during Stage 9C.1:

- [football-data public catalogue](https://api.football-data.org/v4/competitions),
  [standings contract](https://docs.football-data.org/general/v4/competition.html),
  [pricing](https://www.football-data.org/pricing),
  [terms, attribution and post-cancellation display restrictions](https://www.football-data.org/about).
- [API-Football coverage](https://www.api-football.com/coverage),
  [pricing](https://www.api-football.com/pricing),
  [publication-rights caveat](https://www.api-football.com/terms).
- [OpenFoot coverage](https://openfootapi.com/coverage),
  [demo documentation](https://openfootapi.com/docs),
  [retention and underlying-source obligations](https://openfootapi.com/terms).
- [Sportmonks pricing](https://www.sportmonks.com/football-api/plans-pricing/),
  [storage/redistribution conditions](https://www.sportmonks.com/integrity-support/).

Indicative audit pricing: football-data Free 10 calls/minute with delayed data;
API-Football Free 100/day with season restrictions, Pro $19/month 7500/day;
OpenFoot Free 5000/month 60/minute, Developer $14/month; Sportmonks Starter
EUR29/month for five competitions. These are not purchases or coverage guarantees.
Before onboarding, separately confirm attribution, raw-response retention,
encrypted backup, public display and post-subscription use. API access/payment
does not automatically grant all underlying rights. Do not import logos on this
basis. No legal clearance is claimed here.

## Minimal extension point

```text
Synthetic JSON bytes (tests/fixtures, no URL or credential)
  -> src.providers.validation.parse_snapshot
  -> immutable typed Snapshot + referential/semantic DQ
  -> SyntheticAdapter (ProviderAdapter protocol)
  -> normalized bytes / semantic digest / typed read methods

Future, separately approved: provider adapter -> existing Bronze/catalog/DQ
patterns -> new serving snapshot design -> Current Competitions API/UI
```

This is a contract package, not a second ingestion framework. Existing adapters
use stdlib parsing and dataclasses, not Pydantic; no Pydantic dependency was added.
Existing `src.common.source_transport` error classification is reused. No changes
were made to StatsBomb, metadata schemas, Spark, loaders, DAGs or Match Lab.
The one-build-per-context guards remain unchanged: none of these contracts is
permission to overwrite an existing serving build.

## Schema and identity

The frozen dataclasses in [models.py](../src/providers/models.py) are runtime
type-checked, including direct constructors. There is no bool-to-int/string-to-ID
coercion. Parsing rejects unknown fields, duplicate JSON keys and non-finite values.

| Contract | Meaning |
| --- | --- |
| ProviderIdentity | Provider namespace + entity kind + opaque external ID |
| Competition / Season | Stable internal IDs; club/national type; season label distinct from provider season ID; season format version |
| Stage / Round | Qualifying/league-phase/knockout/group; optional division/group; round order scoped to stage |
| Participant | Stable team identity and club/national type |
| Tie | One/two-leg knockout identity and participant references |
| Fixture / FixtureStatus | Explicit season/stage/round, participants, optional UTC kickoff, status, result revision, update time, optional tie/leg |
| Score | Nullable regulation goals, **additional** extra-time goals, separate shootout goals |
| StandingsEntry | Stage/participant, provisional rank, W/D/L/GF/GA/points and explicit points adjustment |
| SourceCapability | Verified/declared/unavailable/restricted/unknown for each named feature |
| DataFreshness | Provider update, fetched, checked and optional published UTC times; caller supplies stale clock/threshold |
| Snapshot | One provider + competition + season; explicit partial coverage/note; schema version 1 |

Internal and external IDs are never inferred from dates or team names. The v1 ID
grammar is `[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}`, provider names use lowercase
letters/digits/underscore/hyphen. External IDs stay strings, even when numeric.
An actual provider needing a broader grammar requires an explicit reviewed change.
Existing StatsBomb IDs/URLs are not remapped. Names support Unicode.

Input timestamps require RFC3339 with seconds and explicit `Z` or numeric offset;
offsets normalize to UTC. Direct model constructors require aware UTC datetime.
Missing kickoff is allowed (e.g. postponement), not replaced by a fabricated date.
Future/unknown/postponed/cancelled results must be null; live scores may be unknown;
finished results require regulation scores. A provider's inclusive 120-minute score
must be explicitly converted to additional extra-time goals by a future adapter.
Each score component is a strict integer in 0..100; live/finished known kickoff
and fixture update timestamps cannot be later than collection time.
Cancelled/abandoned matches with historical scores need a reviewed status/raw
retention extension, not silent dropping or coercion by this contract.

No optional statistics are invented. Capability verification here refers ONLY
to the synthetic contract. Absence of a capability is unknown, not available.
Verified fixtures never imply xG, pass coordinates, tracking or pressure events.
Capabilities are currently snapshot-scoped; fixture-specific evidence belongs
to a later approved extension before heterogeneous real coverage is supported.

## Adapter and errors

[adapter.py](../src/providers/adapter.py) exposes the `ProviderAdapter` protocol:
`get_competition()`, `get_season()`, `get_fixtures()`, `get_results()`,
`get_standings()`. Each instance represents one explicit context, not an arbitrary
query engine. `SyntheticAdapter.from_bytes(payload)` accepts synthetic provider
data only. Results are the finished fixtures, with the same result model.

There is **no network transport**, URL loader, CLI, environment credential reader,
provider registration, persistence or automatic refresh. The live allowlist is
empty and `require_live_provider()` denies every provider. Arbitrary URLs are
not accepted. Do not add an HTTP path until licensing/coverage gates pass.

Future request-policy bounds are expressed/tested but NOT executed by the offline
adapter: timeout 10s (hard cap 30), at most 3 attempts, exponential 1s/2s backoff,
30 requests/minute (cap 60), at most 10 pages and 1 MiB per response. A live adapter
must enforce these using a shared quota budget, overall collection budget,
transient-only retries/Retry-After, TLS verification, fixed HTTPS endpoints,
redirect/SSRF guards and bounded streaming reads. These runtime protections are
not claimed implemented by declaring a policy dataclass.

The parser actually enforces 1 MiB payload and 2000 rows per collection, without
silent truncation. Only fixed error codes escape: contract TYPE/REFERENCE/etc.,
adapter TIMEOUT/TLS/AUTHENTICATION/ACCESS_DENIED/RATE_LIMIT/TRANSIENT/INVALID_PAYLOAD.
Neither payload values, URLs, credentials nor raw exception messages are logged.
There is no logging or retry sleep in the synthetic adapter.

## DQ, replay and corrections

- Canonical IDs and provider-kind-external-ID tuples must be unique.
- All references remain in the explicit competition/season; team types agree.
- Rounds belong to stages; tie legs have distinct numbers and reversed teams.
- Extra time/shootouts are knockout-only; first legs cannot have either.
- A completed shootout needs a tied single match or verified tied aggregate and
  a shootout winner. Incomplete legs cannot establish that aggregate.
- Standings keys are unique; arithmetic includes explicit point adjustments.
  Equal provisional ranks are valid. No local points/GD re-ranking is performed.
- `validate_update(previous, current)` rejects missing old fixtures/entities,
  identity reassignment and regressing collection time. A partial response is not
  a deletion instruction. Rescheduling preserves the same fixture ID.
- Changed fixtures require a greater revision and non-regressing update time.
  Replays are accepted. Finished-result corrections stay finished; an exceptional
  finished-to-scheduled rollback fails closed for later explicit review.
- Allowed ordinary transitions: scheduled -> live/finished/postponed/cancelled;
  postponed -> scheduled/live/finished/cancelled; live -> finished/postponed/cancelled;
  cancelled -> scheduled/postponed on a higher revision. Unknown can resolve to a
  known status. Self-transitions are allowed subject to revision rules.
- Normalized record-set order, timestamps and JSON encoding are deterministic.
  `canonical_bytes` includes freshness; `content_digest` excludes freshness only.
  This is a semantic contract fingerprint, NOT a Silver/Gold build ID or proof
  of an immutable Bronze input. No build/catalog/publication state is written.

The partial JSON has four invented teams and nine scenario fixtures, not a
complete UEFA schedule. A separate generated test covers a 36-entry synthetic
table. Full season-size, fixture/table reconciliation, provider pagination,
clock-skew policy and concurrent refresh/cutover tests belong to 9C.2-B onward.

## Tests and next gate

```powershell
& .venv/s3-recovery/Scripts/python.exe ci/run_unittest.py discover -s tests -p test_provider_contracts.py
```

New tests are automatically discovered by the existing Python 3.10.12/3.12.14
fast-CI matrix; no new workflow/job or secrets are needed. Python 3.10 and Windows
Python 3.12 are supported without new dependencies. Existing application,
recovery, CI/security and pipeline regressions remain mandatory.

Local acceptance on 2026-10-29 (no remote CI run/commit in this stage):

| Runtime / gate | Result |
| --- | --- |
| Windows CPython 3.12.10, new provider tests | 61 PASS |
| Windows CPython 3.12.10, synthetic recovery/network-denied gate | 262 PASS, including real temporary ACL/junction tests |
| Linux CPython 3.10.12 and 3.12.14, each | 848 offline tests OK (9 expected Windows/Spark skips), 36 CI contracts PASS, 61 application tests PASS |
| Both Linux runtimes | Ruff and compileall PASS; containers had networking disabled and source mounted read-only |
| Repository audit | Existing tracked-file security/ignore contracts PASS; explicit scan of all nine new source/doc/fixture files PASS |
| Workflows / files | actionlint, relative runbook links, tracked/staged diff checks and separate new-file whitespace checks PASS |

No frontend code changed; no new browser/deployment acceptance is claimed.
HEAD/origin-master remain at the baseline. Files are not staged or committed;
publication completeness must be rechecked against the eventual staged tree.

Next: 9C.2-B synthetic paginated collection, incomplete/quota/error responses,
revision allocation from provider fields, DQ reporting through the existing
framework and candidate-publication failure tests. Do not wire a live provider
or perform ingestion as part of that synthetic work.

Real-source onboarding remains blocked on authenticated 2026/27 payloads,
36-team official standings, legal/storage approval, approved identity mapping
and a safe versioned-serving publication design. Stage 8C remains PARTIAL.
