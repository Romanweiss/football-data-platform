# Stage 9C.2-C/D: UEFA provider verification and real-data readiness

Stage C checked: **2026-10-29**. Stage D authenticated probe: **2026-10-30**.
Baseline HEAD/origin-master:
`8f7728605e8de0c079f7cbb3a77e79463df803bb`, branch `master`.
Stage 9C.2-A/B: READY for synthetic work. Stage 8C: PARTIAL.

**Stage D technical connection/payload probe: SUCCESS (3/3 GET, all HTTP 200).**
**Recommendation: football-data.org PRIMARY technical candidate for a scoped
UCL league-phase read-only proof of concept; not production provider approval.**
**Persistent real-source onboarding: BLOCKED / LEGAL_REVIEW_REQUIRED.**

These are independent gates. Stage C left provider selection UNDECIDED. Stage D
resolves the sampled football-data fixtures/results/standings access uncertainty,
but not persistent storage/publication rights or collection consistency. No
production PRIMARY/FALLBACK is approved. Sections 1-8 retain the Stage C audit;
section 9 records the newer evidence and supersedes its technical UNKNOWNs only
for the inspected provider, season and league-phase scope.

## 1. Scope and evidence levels

This is a documentation-only evaluation. The existing nine A files, seven B
files, StatsBomb pipeline, serving contract and application were not changed.
The local untracked deployment evidence `docs/stage9b2-deployment.md` and unrelated
shortcut were preserved. A/B files are still untracked, not missing work and not
published source. Their successful synthetic tests do not prove live readiness.

Evidence terms:

- **LIVE_VERIFIED:** a completed response observed in the dated C/D evaluation, or an
  explicitly recorded HTTP access failure. An HTTP failure verifies only access,
  never the absent dataset's schema or coverage.
- **DOCUMENTED:** primary documentation or terms observed in the earlier 9C.1
  audit on the same date, referenced in the retained A runbook, or successfully
  reread here. It is not a current-season payload test.
- **UNAVAILABLE:** explicit feature absence from an observed response. The prior
  OpenFoot standings observation is dated/qualified below, not presented as a new
  response in C.
- **UNKNOWN:** not obtained or not established. Read timeouts/403 are not proof
  of absent fixtures or an unavailable season.
- **AUTH_REQUIRED:** an endpoint requires authentication. It does not mean that
  buying a plan would prove coverage or that a personal key is always required
  when a provider also offers an intentional public demo.

Earlier coverage/licensing evidence is retained in the
[A runbook](stage9c2-provider-adapter.md); collection requirements are in the
[B runbook](stage9c2-collection.md). Earlier live observations are not relabelled
as fresh C probes. No 36-team standings payload was obtained in C; D obtained one
as recorded in section 9.

## 2. Stage C: exactly six external HTTP requests

The strict six-request budget included documentation reads, not just API calls.
All were GET over HTTPS with default certificate verification, 15s operation
timeout and at most 1 MiB response-body read. Redirects and automatic retries
were disabled; no browser/token extraction, credentials, registration or paid
access was used. No raw responses were written to disk/Git. Complete bodies were
held temporarily in one Python process, summarized through explicit public-field
allowlists, then cleared before process exit. No demo key was loaded or used.

| # | Provider / official URL | Result | What it establishes |
| --- | --- | --- | --- |
| 1 | [OpenFoot docs](https://openfootapi.com/docs) | HTTP 200 headers; body read TimeoutError | Document body/demo instructions not obtained; not a successful content verification |
| 2 | [football-data terms](https://www.football-data.org/about) | HTTP 200, complete 24645-byte body | Fresh terms/attribution restrictions inspected |
| 3 | [API-Football terms](https://www.api-football.com/terms) | HTTP 403 | Website access denied; all further requests to this provider stopped |
| 4 | [football-data catalogue](https://api.football-data.org/v4/competitions) | HTTP 200, complete 73824-byte body | UCL catalogue/season fields below verified |
| 5 | [OpenFoot terms](https://openfootapi.com/terms) | HTTP 200 headers; body read TimeoutError | Current terms content not obtained; earlier audit remains qualified evidence only |
| 6 | [OpenFoot catalogue](https://openfootapi.com/v1/competitions) | HTTP 401 | Unauthenticated access is AUTH_REQUIRED; all further provider requests stopped |

Request 3 was a terms-page request, NOT an API-Football API request: its 403 does
not prove that an application key caused the failure. No API-Football data probe
was made after that denial. OpenFoot's published demo was not retried or replaced
with an unverified key after the docs body timed out. No seventh request was made.
The timeouts are observed transport limitations, not diagnosed provider outages.

## 3. Stage C verified fields: football-data catalogue only

The returned UCL entry contained:

| JSON field | Observed value | Safe interpretation |
| --- | --- | --- |
| id | 2001 | Provider competition ID, not platform canonical ID |
| name | UEFA Champions League | Display metadata |
| code | CL | Provider-specific code |
| type | CUP | Coarse competition classification, NOT proof that every stage is knockout |
| plan | TIER_ONE | Catalogue entitlement label; not an authenticated plan/field test |
| lastUpdated | 2026-05-31T11:41:29Z | Competition metadata update, not fixture/table freshness |
| currentSeason.id | 2557 | Provider season ID |
| currentSeason.startDate | 2026-09-08 | Catalogue date, not proof of qualifying-round scope |
| currentSeason.endDate | 2027-01-27 | Does not establish coverage through the final/entire season |
| currentSeason.currentMatchday | 4 | Reported catalogue field; not independently checked against played fixtures |

The dates establish a catalogue season spanning 2026/27. They do NOT prove
fixtures/results/standings availability, live score freshness, qualifying or
knockout coverage. No team or fixture IDs were returned in the inspected entry.

## 4. Stage C provider decision matrix (historical)

| Criterion | football-data.org | API-Football | OpenFoot API |
| --- | --- | --- | --- |
| UCL 2026/27 | LIVE_VERIFIED catalogue season | DOCUMENTED coverage candidate; actual season payload UNKNOWN | Prior 9C.1 demo samples verified; fresh C payload AUTH_REQUIRED |
| Fixtures/results/status | DOCUMENTED; current-season payload UNKNOWN, authenticated access required | DOCUMENTED; C API probe not executed | Prior demo fixture/status/null-score samples; C payload UNKNOWN |
| League-phase standings | UNKNOWN; docs/CUP mismatch needs authenticated test | DOCUMENTED endpoint; actual 36-team payload UNKNOWN | UNAVAILABLE in prior 9C.1 feature_not_available response; not re-probed in C |
| Stages/rounds/knockout ties | DOCUMENTED stage/matchday fields; actual 2026/27 structure UNKNOWN | DOCUMENTED rounds; actual tie/bracket relationships UNKNOWN | Prior fixture round label observed; complete stage/tie structure UNKNOWN |
| Match/team IDs | DOCUMENTED schema; current samples UNKNOWN | DOCUMENTED schema; current samples UNKNOWN | IDs observed in prior demo, continuity/stability UNKNOWN |
| Updates and corrections | Match update semantics need payload/history; catalogue lastUpdated is not sufficient | DOCUMENTED update fields; actual availability/history UNKNOWN | Prior updatedAt observed; correction/revision guarantees UNKNOWN |
| Authentication | Catalogue works without key; data endpoints require token according to documentation/prior probe | Application key documented; no key used/requested | Unauthenticated catalogue 401; public demo documented earlier but not used here |
| Completeness/freshness | UNKNOWN beyond catalogue | UNKNOWN for selected season | Preview != full inventory; current content UNKNOWN |
| Architectural fitness | CONDITIONAL: mapping, status/score semantics, table and consistency gates pending | CONDITIONAL: same gates plus actual season/plan verification | NOT ESTABLISHED for MVP requiring standings; licensing/source limitations also unresolved |
| Decision | UNDECIDED | UNDECIDED | UNDECIDED; not eligible for the required MVP on present evidence |

No numeric score is assigned to unknown coverage or unconfirmed rights. There is
no evidence-supported PRIMARY/FALLBACK selection in this stage.

### Documented prices/limits, not newly purchased or plan-verified

The following were observed in the earlier same-date 9C.1 audit. Pricing pages
were not fetched again within C's six-request budget. Reconfirm before choosing
a plan; price/endpoint inclusion is not season/field coverage proof.

- [football-data pricing](https://www.football-data.org/pricing): Free EUR0,
  10 calls/minute and delayed data; live tier EUR12/month; deeper data EUR29/month.
- [API-Football pricing](https://www.api-football.com/pricing): Free 100/day with
  season restrictions; Pro USD19/month, 7500/day. The free tier does not establish
  2026 availability. Per-minute/account limits still need confirmation.
- [OpenFoot pricing](https://openfootapi.com/pricing): Free 5000/month, 60/minute;
  Developer USD14/month, 250000/month, 100/minute. Public demo has a separate
  documented limit and is not a production credential.

No statements about current account quota, payment availability or paid entitlements
are verified. Earlier documentation references:
[football-data competition/standings](https://docs.football-data.org/general/v4/competition.html),
[football-data match](https://docs.football-data.org/general/v4/match.html),
[API-Football documentation](https://www.api-football.com/documentation_v3),
[API-Football coverage](https://www.api-football.com/coverage),
[OpenFoot docs](https://openfootapi.com/docs),
[OpenFoot coverage](https://openfootapi.com/coverage).
Listing a reference is not an extra HTTP link check or a successful current probe.

## 5. License and storage gate

This records technical contract-review findings, not legal advice/clearance.
UNKNOWN is not permission. An API subscription is not automatically an underlying
competition-data licence. Public display and a redistributable raw-data API are
different uses, as are response caching and perpetual raw/backup retention.

| Intended use | football-data.org | API-Football | OpenFoot |
| --- | --- | --- | --- |
| API access | DOCUMENTED account/token conditions; public catalogue verified | DOCUMENTED key/account conditions; C website access denied | DOCUMENTED access/demo/plan conditions; fresh catalogue requires auth |
| Local caching | Scope/limits require clarification | UNKNOWN explicit permission for intended scope | Earlier terms permitted caching; current body not re-obtained |
| Long-term exact raw retention/backups | UNKNOWN explicit broad permission | UNKNOWN explicit broad permission | Earlier terms permitted retention, subject to underlying-source obligations |
| Derived tables | Intended scope/rights need confirmation | Intended scope/rights need confirmation | Earlier permission for normalized fields/aggregates, subject to source rights |
| Public fixtures/results/standings | Attribution/use terms apply; post-cancellation restriction freshly verified | Earlier terms explicitly did not grant publication rights on behalf of rights holders | Provider access does not waive underlying feed restrictions |
| Redistribution through our API | UNKNOWN permission for planned public API | Raw resale prohibited in earlier terms; planned API scope needs explicit approval | Underlying feed redistribution not granted merely by subscription |
| Attribution | Freshly verified mandatory visible credit, section 7.1 | Exact obligations/rights-holder conditions need clarification | Earlier terms require carrying source attribution and licence obligations |

Fresh [football-data terms](https://www.football-data.org/about) sections 7.1 and
9.1 require attribution and restrict continued display of obtained football data
on the customer's site/service after subscription cancellation. Section 9.2
separately reserves logo/photo rights. Section 4.6 describes deletion of the
provider-side account/data; it is not proof of a customer's local raw-file deletion
obligation or a broad permission to retain it. No such inference is made here.

In the earlier audit, [API-Football terms](https://www.api-football.com/terms)
explicitly separated API supply from rights-holder permission to publish and
prohibited direct raw-data resale. C's 403 prevented a fresh content review;
those observations must not be presented as a successful new terms fetch.

Earlier [OpenFoot terms](https://openfootapi.com/terms) expressly permitted long
retention of responses/normalized data but kept third-party source obligations.
The 9C.1 UEFA catalogue marked the FotMob source Unlicensed-Beta. That does not
establish CC0/ODbL coverage or public redistribution rights for these tournaments.
C did not obtain a new authenticated catalogue or completed terms body. Do not
generalize other OpenFoot competitions' open licences to UEFA.

**LEGAL_REVIEW_REQUIRED for every candidate.** Obtain clear permission/terms for
the concrete app, public API response shape, raw history, derived tables, encrypted
backups and post-subscription use before persistent onboarding. No legal request
or external contact was sent automatically.

## 6. Stage C compatibility with A/B: conditional, not a live mapping

| Existing contract | Verified/documented mapping candidate | Remaining gap |
| --- | --- | --- |
| Competition | football-data id/name/code | Canonical registry; club type from reviewed competition config, not CUP-to-knockout inference |
| Season | currentSeason.id and catalogue 2026/27 dates | Actual requested-season payload, format version and phase/full-season scope |
| Stage | Documented stage labels | Actual league-phase/qualifying/knockout representation; no fabricated stage from type=CUP |
| Round | Documented matchday/round | Stable round identity and tie/leg relationship not established |
| Participant | Documented provider team IDs/names | Actual samples and identity continuity; no name-based merging with StatsBomb |
| Fixture | Documented event ID, teams, kickoff, status | Actual payload, UTC precision, reschedules and stable ID behavior |
| Score | Documented nullable result/extra-time/penalty structures | Whether fullTime includes extra time; A requires regulation plus ADDITIONAL extra-time goals |
| FixtureStatus | Basic scheduled/live/finished/postponed/cancelled concepts | Paused/suspended/abandoned/awarded cases and retained scores need actual semantics |
| StandingsEntry | Documented table counters | Real 36-entry table, deductions and official tie-break criteria; not a points/GD-only substitute |
| Snapshot | Namespace/context/freshness/partial fields exist | Actual capabilities, truthful coverage, per-resource timestamps and collection consistency |

No real provider response was passed to A's parser: it accepts the neutral schema,
not arbitrary vendor JSON. No source IDs were assigned as platform IDs. External
numeric IDs would be explicitly represented as strings, with internal identity
allocated independently. Existing StatsBomb IDs and canonical routes stay intact.

Important unresolved semantic risks, NOT reasons to change the models blindly:

1. A's cancelled/unknown/postponed states require null scores. A suspended or
   abandoned real fixture may retain a score. Dropping it or coercing it to zero
   would lose semantics; inspect a real example and review an explicit extension.
2. `lastUpdated` is not a monotonic provider revision. Revision counters cannot
   be invented as though supplied by a vendor. Future mapping needs content-aware
   revision allocation against prior state and actual update semantics.
3. B's source_revision fence spans fixtures/standings and metadata. No candidate
   has been proved to expose such a global snapshot token. Per-response ETags or
   per-fixture timestamps do not establish it. Hashing a response locally also
   does not create an atomic upstream version. Approve a weaker observed-window
   consistency design if necessary; do not fabricate a fence to pass the collector.
4. Catalogue freshness cannot be copied to every fixture or standings resource.
   Distinguish fetched/checked times from a provider's genuine last update.
5. A catalogue season ending in January must not silently claim coverage through
   qualification and the final. Phase coverage must be explicitly verified.

No defect requiring a change to the synthetic A/B code was established. Real-data
requirements remain unverified extensions/mapping decisions, not implemented fixes.
Existing one-build-per-context serving guards remain unchanged.

## 7. Stage C proposed proof of concept (completed by Stage D below)

No live adapter or UI is implemented in C. A future diagnostic proof of concept
should keep responses in process memory only and display a sanitized summary:

- Requested UCL season and explicit observed coverage/stage set.
- Fixtures and results (nullable future scores), provider IDs and UTC kickoff.
- A real league-phase table with 36 participant entries, or a precise unavailable
  result. Never label a locally guessed points/GD ranking as the official table.
- Per-resource provider update fields, fetched time and coverage/freshness flags.
- Schema/status/score differences and the source's consistency guarantees.

**Next smallest step:** operator-authorized authenticated diagnostic probe of one
candidate. football-data is a reasonable first *verification target* because its
catalogue and terms were readable, not an approved PRIMARY or a promise that its
standings work. Suggested separately approved budget: at most three GET requests
(competition/season metadata, season fixtures including results, standings), no
retries or redirects; stop provider requests on 401/403/429. This is a NEW future
budget, not permission to exceed C's exhausted six-request cap.

Before that probe, the operator must choose a candidate, confirm account/plan
access and authorize the diagnostic. A personal key is necessary only if that
provider's documented personal-auth route is chosen; OpenFoot also documents a
public demo that would need explicit verification and its own future request
budget. No account or subscription should be created automatically.

For a personal-auth route, use a masked operator prompt or another explicitly
approved process-memory mechanism. Never request the key in chat, read unknown
credential files, place it in CLI arguments/URLs, persist it in Git/plaintext,
dump headers, or reuse S3/runtime credentials. Clear temporary references on exit;
do not claim guaranteed zeroization of Python strings. No key is requested now.

If authenticated UCL standings returns unsupported/404, record that evidence and
revisit the candidate rather than bypassing it with an unverified derived table.
Full pagination and source consistency would require another explicitly bounded
test; one metadata/fixtures/table sample is not season-completeness proof.

Even successful technical probes do not authorize S3/DB persistence: approve the
license/storage gate and serving publication design separately before onboarding.

## 8. Stage C local checks and final boundary

Local checks: 119 A+B provider tests PASS on Windows CPython 3.12.10; 40 existing
CI contracts PASS; repository/security contracts PASS. The new document receives
an explicit secret-signature/URL/relative-link/whitespace audit. No external link
fetches are performed by that audit, to preserve the six-GET cap.

No staging, commit/push, live ingestion, migrations, S3 writes, production update,
database/volume operations, backup/restore/key access or Bitwarden access occurred.
Raw HTTP bodies remained in process memory and were discarded. Only this document
was added by C; the pre-existing local A/B work remains unstaged and preserved.

**Provider selection: BLOCKED (UNDECIDED).**
**Persistent real-source onboarding: BLOCKED (LEGAL_REVIEW_REQUIRED).**
That was the Stage C stopping boundary. The separately authorized Stage D probe
below is not permission for a live adapter or Current Competitions UI. Stage 8C
remains PARTIAL.

## 9. Stage D: authenticated read-only probe, 2026-10-30

### Authorization, secret handling and HTTP budget

The inherited process environment did not contain the authorized token. After
explicit operator agreement, a separate masked local GUI accepted the operator's
football-data.org token into process memory. This fallback was authorized; no
credential files, browser storage, Bitwarden, logs or other stores were searched.
The token was not placed in command arguments, environment variables, URLs or
files. The entry was cleared after submission; request headers/references were
cleared on completion and the process exited. Python string zeroization is not
guaranteed. Only allowlisted derived summaries escaped the process; raw response
bodies were discarded, not saved to Git or persistent storage.

Exactly **three HTTPS GET exchanges** were made, with automatic redirects and
retries disabled, default TLS certificate validation, a 20-second request timeout,
1 MiB maximum response size and at least 6.1 seconds between request starts.
No additional documentation, pagination, corrective or diagnostic HTTP requests
were made in D. C's six requests and D's separately authorized three are distinct
budgets; D's budget is now exhausted.

| # | Documented endpoint | HTTP | Response bytes | Result |
| --- | --- | --- | --- | --- |
| 1 | [Competition metadata](https://api.football-data.org/v4/competitions/2001) | 200 | 6157 | Competition 2001, current season 2557 |
| 2 | [Season fixtures/results](https://api.football-data.org/v4/competitions/2001/matches?season=2026) | 200 | 141389 | 144 fixtures, all competition 2001 / season 2557 |
| 3 | [Season standings](https://api.football-data.org/v4/competitions/2001/standings?season=2026) | 200 | 28420 | League-stage TOTAL/HOME/AWAY tables, 36 rows each |

The documented query uses the season's starting year `season=2026`, not the
provider's internal season ID `2557`. The latter was checked in the responses.
These are LIVE_VERIFIED observations for this token and scope, not confirmation
of account plan, remaining quota, contractual entitlement or continued access.

### Competition and season

- Competition ID `2001`, type `CUP`; current season ID `2557`, also present in
  the season history list. Dates: `2026-09-08` through `2027-01-27`.
- Competition `lastUpdated=2026-05-31T11:41:29Z`. It is metadata freshness only,
  not a fixture or table update timestamp.
- Root schema keys: `area`, `code`, `currentSeason`, `emblem`, `id`, `lastUpdated`,
  `name`, `seasons`, `type`.
- Season keys: `currentMatchday`, `endDate`, `id`, `startDate`, `winner`.

### Fixtures/results and coverage

| Observation | LIVE_VERIFIED value |
| --- | --- |
| Fixtures / populated IDs / unique fixture IDs | 144 / 144 / 144 |
| Populated home/away team ID slots | 288 |
| Distinct fixture team IDs | 36 |
| Status counts | FINISHED 54; TIMED 90; IN_PLAY/PAUSED 0 |
| Stage values | LEAGUE_STAGE only |
| Minimum / maximum kickoff UTC | 2026-09-08T16:45:00Z / 2027-01-27T20:00:00Z |
| Missing/invalid utcDate | 0 |
| resultSet.count / resultSet.played | 144 / 54 |
| Valid lastUpdated fields | 144/144 |
| Minimum / maximum fixture lastUpdated | Both 2026-10-30T00:20:29Z |
| Numeric fullTime home/away pairs / both-null pairs | 54 / 90 |
| score.duration values | REGULAR only |

Fixture schema keys observed: `area`, `awayTeam`, `competition`, `group`,
`homeTeam`, `id`, `lastUpdated`, `matchday`, `odds`, `referees`, `score`, `season`,
`stage`, `status`, `utcDate`. Presence is not field-value or usability verification
for odds, referees or other uninspected nested data.

`score.winner`, `duration`, `fullTime` and `halfTime` were present in all 144
fixtures. `regularTime`, `extraTime` and `penalties` were **absent in all 144**,
not present with null values. No extra-time/shootout fixture was observed. This
does not establish that those fields are unavailable in other phases or plans.
No suspended, abandoned, postponed, awarded or live fixture example was observed;
their status/score semantics remain UNKNOWN.

The returned fixture array agrees with its declared result count, and 144 equals
the expected league-phase arithmetic `36 * 8 / 2`. That is not an independent
full-season completeness proof. The probe did not check eight fixtures per team,
four home/four away, round/opponent uniqueness, qualification or knockout scope,
reschedules, fixture-ID continuity or historical corrections. The date range and
single observed stage must not be labelled complete UCL 2026/27 coverage.

### League-phase standings

Three tables were returned, each with `stage=LEAGUE_STAGE`, `group=null` and 36
rows with populated, distinct team IDs: `TOTAL`, `HOME`, `AWAY`. This means
**36 teams in the primary TOTAL table**, not 108 teams. Each entry exposes
`draw`, `form`, `goalDifference`, `goalsAgainst`, `goalsFor`, `lost`, `playedGames`,
`points`, `position`, `team`, `won`.

The authenticated HTTP 200 response resolves the earlier documentation/CUP
standings ambiguity for this competition/season. It does not establish standings
support for every CUP or every account scope. Fixture/table team-set equality,
W/D/L/goals/points reconciliation and official UEFA tie-break/rank verification
were **not performed**. Counts and schema alone are not the B DQ acceptance gate.

### Pagination, revisions and consistency

No `Link` or `ETag` response header, pagination keys, or root
`revision`/`version`/`snapshotId` fields were observed in any of the three
responses. Fixture `revision`/`version` fields were absent. All fixture
`lastUpdated` timestamps were equal; this does not establish genuine per-fixture
revision granularity, a monotonic correction counter or a shared atomic snapshot.
The inspected responses provide **no verified global source revision** across
fixtures, standings and metadata.

There is no evidence of a visible page continuation in this sample, but no
independent full-inventory test or follow-up request was performed. Do not invent
a source revision from local hashes/timestamps or claim an atomic snapshot to
satisfy B's existing collection fence. Future collection needs an explicitly
reviewed consistency contract and a new bounded verification budget.

### A/B compatibility after the probe

| Contract | Mapping supported by observed schema | Remaining acceptance gate |
| --- | --- | --- |
| Competition/Season | Provider IDs 2001/2557 and season dates | Independent canonical identity registry and explicit league-phase coverage |
| Stage/Round | LEAGUE_STAGE to league_phase; matchday field present | Round values/identity DQ, qualification/knockout/ties not verified |
| Participant/Fixture | Team IDs and 144 unique fixture IDs; UTC dates | Identity continuity, canonical allocation and complete reference validation |
| Status | FINISHED to finished; TIMED to scheduled | Other statuses, suspended/abandoned retained-score behavior untested |
| Score | REGULAR fullTime numeric pairs; future both-null pairs | Explicit regulation mapping; inclusive extra-time/penalty semantics untested |
| StandingsEntry | TOTAL table counters; draw to drawn, position to rank | All existing arithmetic/reference DQ; official order, adjustments and tie-breaks |
| HOME/AWAY views | Distinct table types observed | Do not import as duplicate TOTAL entries into the same stage/participant key |
| Freshness/Revision | Per-fixture lastUpdated; independent collection times | Not a monotonic revision; define correction handling without fabricating vendor versions |
| Collection fences | No global revision verified | Existing shared source_revision requirement is not fulfilled by these responses |
| Capabilities | Fixtures/results and league-phase standings observed | No inspected xG, event-coordinate, pressure, lineup or player-stat capability |

No raw vendor response was passed as a neutral A snapshot, and no model, adapter,
status enum, validation rule, serving identity or application was changed. A/B
remain synthetic-ready contracts, **not a verified production collector**. Basic
mapping is feasible; persistence remains blocked by licensing and the unresolved
consistency contract, even though authenticated connectivity now passes.

### Licensing and provider recommendation

Stage D made no new terms requests. Section 5's 2026-10-29 terms evidence remains
the basis, with its UNKNOWNs unchanged. The operator-authorized transient,
in-memory probe succeeded technically; this is not a broad legal clearance for
local caching, exact raw storage, indefinite retention, encrypted backups,
derived tables, public display or redistribution through Django. Attribution and
post-cancellation display restrictions remain applicable; logos/photos require
separate rights. Obtain scope-specific clarification before persistent onboarding.

- **Technical connection/payload compatibility probe: SUCCESS.**
- **Recommendation: PRIMARY technical candidate, football-data.org**, limited to
  a read-only UCL league-phase proof of concept. No production approval follows.
- **Production provider approval: UNDECIDED.** Other candidates were not probed
  in D; no verified FALLBACK has been selected.
- **Persistent onboarding/publication: BLOCKED / LEGAL_REVIEW_REQUIRED**, plus
  collection-consistency and full reconciliation acceptance work.

### Checks, next smallest task and stop boundary

The next minimal implementation task, requiring separate authorization, is an
offline football-data-specific mapping spike with **artificial fixtures matching
the observed schema**, explicit TOTAL selection, status/score mapping and tests
for missing ET fields and unrecognized states. Design the observed-window
consistency alternative separately; do not weaken B's fence silently. No real
payload persistence, live collector or public serving is authorized by this probe.

Stage D local checks: **119 A/B provider tests PASS** on Windows CPython 3.12.10;
**40 CI contracts PASS**; repository/security contracts PASS. The untracked
evaluation document also passed an explicit secret-signature, HTTPS URL allowlist,
local Markdown link/anchor and whitespace audit, without network access. Tracked
and staged diff checks passed; the document's no-index whitespace check passed.
The existing deployment-evidence document's SHA-256 remained unchanged.

The temporary diagnostic source and its now-empty directory were removed after
the GUI process exited. No token or raw-payload file had been created there.
Only this evaluation document was modified in D; existing untracked A/B files
and the unrelated shortcut remain untouched. Nothing was staged. No commit/push,
ingestion, migrations, S3 or database operations, production update,
backup/key/Bitwarden access or application changes occurred in this stage.
Stop after this report. Stage 8C remains PARTIAL.
