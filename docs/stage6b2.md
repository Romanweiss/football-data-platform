# Stage 6B-2 — Second-context onboarding attempt

Attempt date: 2026-10-04 (Europe/Moscow).
Status: **Real Stage 6B-2 onboarding complete and verified; Superset safety follow-up required.**
43/106 and 9/281 coexist, loads are idempotent and WC data/API regression is
unchanged. Superset is unmodified and its World Cup dashboard can mix contexts.
Earlier STOP/partial checkpoints below are historical, not the final state.

The Stage 6B-1 runbook was read before execution. The target supplied by the task
is competition `9`, season `281`: the previously inspected Bundesliga 2023/2024
subset of 34 Bayer Leverkusen matches. The original attempt used prior expectations
from [Stage 6B-1](stage6b1.md); the follow-up below reconfirms the authoritative
identity and complete available source inventory from the pipeline container.

## Original source preflight failure

The exact documented command ran inside the intended Python pipeline container:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_statsbomb_source.py --competition-id 9 --season-id 281
```

Exit code: `1`.
Safe diagnostic:

```text
Public source preflight failed: exception=URLError
```

`URLError` is the reported source-access failure class. The formatter does not
expose its nested cause, so this run does not establish whether the cause was
TLS, DNS, a connection failure or another URL transport error. No raw exception
text or credentials were printed. TLS verification was not changed or bypassed.

The original task required immediate STOP if this preflight failed. That attempt
stopped without retries, source substitution or later onboarding steps. The next
task explicitly authorized diagnosis and a bounded preflight transport fix.

## Connectivity diagnosis

All diagnostics used the same `football-python-tools` service/image as ingestion,
with verified TLS and without persistent source downloads or database/S3 clients.

The actual script uses Python standard-library `urllib.request.urlopen`:
GET catalog/matches goes through `src/common/http.py:download_bytes`, while child
availability uses HEAD in `scripts/check_statsbomb_source.py`. Both use a 30-second
socket-operation timeout, not an overall preflight deadline. urllib's standard
redirect handling remains enabled. HEAD checks run with four worker threads.
The canonical URL is already `hudl/open-data`; no source URL/identity changed.

The historical log cannot establish the exact failed URL retrospectively. An
instrumented reproduction exposed these concrete failures:

| Method | Exact failing URL | Hostname | Safe reason |
| --- | --- | --- | --- |
| HEAD | `https://raw.githubusercontent.com/hudl/open-data/master/data/events/3895292.json` | `raw.githubusercontent.com` | `URLError.reason=SSLEOFError`, `UNEXPECTED_EOF_WHILE_READING` |
| HEAD | `https://raw.githubusercontent.com/hudl/open-data/master/data/events/3895134.json` | `raw.githubusercontent.com` | `URLError.reason=SSLEOFError`, `UNEXPECTED_EOF_WHILE_READING` |

The observed failure is an intermittent premature TLS connection close on the
container's outbound source requests. It is not an observed certificate-validation
or DNS error. The evidence does not identify which upstream peer/network component
closes the connection, so attributing it specifically to GitHub, Docker or a VPN
would be unsupported. No global DNS/network/proxy settings were changed.

Host/container comparison:

- Windows GET to the exact catalog and matches URLs: HTTP 200, respectively 34887
  and 63079 response bytes. Windows HEAD to both reproduced child URLs: HTTP 200.
- Container Python GET to the same catalog/matches URLs: HTTP 200; 256-byte samples
  read in memory; no redirect for either request. Both simple HTTPS probes pass,
  while the original full project preflight fails intermittently on child HEAD.
- Container `socket.getaddrinfo` succeeds for `raw.githubusercontent.com`
  (185.199.108.133 through 185.199.111.133) and `github.com` (140.82.121.3).
  No DNS failure warranted changing Docker DNS or reading unrelated network config.
- Container OpenSSL: `OpenSSL 3.0.20 7 Apr 2026`; default Python context has
  `CERT_REQUIRED` and `check_hostname=True`. Default CA paths are
  `/usr/lib/ssl/cert.pem` and `/usr/lib/ssl/certs`; the OS bundle
  `/etc/ssl/certs/ca-certificates.crt` exists. certifi is installed at
  `/usr/local/lib/python3.12/site-packages/certifi/cacert.pem`; urllib uses its
  normal Python/OpenSSL trust configuration, not a newly selected certifi override.
- The existing `python:3.12.14-slim-bookworm` Dockerfile installs OS
  `ca-certificates` and GlobalSign Root R6. No image rebuild or CA change was needed.
- HTTP_PROXY/HTTPS_PROXY/NO_PROXY and lowercase counterparts are all unset on host
  and container. Container `urllib.request.getproxies()` is empty; host Python's
  urllib discovers `ftp/http/https` proxy entries despite those environment variables
  being unset. Thus host urllib has OS-level proxy discovery absent in the container;
  identical routing cannot be assumed. Proxy values/credentials were not printed
  or copied into Docker. This difference alone does not prove the cause of TLS EOF.

## Targeted fix and strictness

Only `scripts/check_statsbomb_source.py` changed at runtime:

- GET and HEAD preflight requests now have at most three attempts with 1s/2s
  exponential backoff, each retaining the original 30-second timeout/default TLS.
- Retries apply to TLS EOF, timeout/reset/aborted/broken connections, incomplete
  responses, temporary DNS (`EAI_AGAIN`), and HTTP 429/500/502/503/504.
- Certificate verification failures, other TLS protocol errors, permanent DNS,
  HTTP 404/other permanent status, invalid content and catalog/context mismatches
  are not retried. Source parsing/identity checks still run outside the retry loop.
- Failure/retry output includes method, public URL/hostname, exception/reason
  classes, safe category and attempt count. URL userinfo/query/fragment and
  arbitrary exception text are excluded. Wrapped downloader causes are unwrapped.
- The catalog, matches membership and every required events/lineups HEAD check
  remain mandatory. Exhausted failures still produce a nonzero exit code.

This is preflight-only transport handling. Bronze downloader behavior, source
identities, existing WC2022 lineage, data architecture and Docker configuration
remain unchanged.

## Successful original-command rerun

The exact command from the original runbook was rerun after the fix:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_statsbomb_source.py --competition-id 9 --season-id 281
```

Exit code: **0**. Actual authoritative output:

```text
competition_id: 9
season_id: 281
competition_name: 1. Bundesliga
season_name: 2023/2024
match_count: 34
team_count: 18
events_available: 34
lineups_available: 34
catalog_sha256: e6cd42f5d8956d6aa30fb917ce8d4c3b3df1879a93f02f8feba820930a6971fa
matches_sha256: 13dff90f126d9f73da410ae3292b2773744657d3ba968a2b7a9c02135033581c
```

The hashes agree with the prior inspected source evidence. Four child HEADs
(`lineups/3895320.json`, `events/3895340.json`, `events/3895134.json`,
`events/3895258.json`) reported TLS EOF on attempt 1 and succeeded on attempt 2.
All 68 required child checks completed; no failure was ignored or substituted.
TLS certificate and hostname verification remained enabled throughout.

## Focused verification

New `tests/test_statsbomb_source_preflight.py`: 10 focused tests passed, covering
retry classification/backoff/exhaustion, certificate/404/content/context rejection,
safe diagnostics, complete child inventory and unchanged default-TLS HEAD behavior.
The existing inexpensive offline suite also passed: **438 tests**. No Spark,
serving load or expensive pipeline run was needed for this transport-only fix.

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_statsbomb_source_preflight.py'
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose run --rm --no-deps football-python-tools python -m compileall -q scripts/check_statsbomb_source.py tests/test_statsbomb_source_preflight.py
docker compose config -q
git diff --check
```

All listed checks passed. Changed files: the preflight script, its focused tests
and this report. README remains unchanged because live data state did not change.

## Original attempts: execution and partial state before onboarding

- No S3 publication or object mutation was attempted.
- No PostgreSQL registration or ClickHouse load/DDL was attempted.
- WC2022 baseline capture, Bronze ingestion/validation, Silver and Gold builds,
  load preflights, real loads and idempotency reruns were not started.
- No new Silver/Gold build IDs, row counts or metric totals were produced.
- Two-context serving, WC before/after comparisons, API/frontend acceptance and
  the Superset dashboard semantic audit remain unexecuted.
- The original STOP attempt did not run the broader test suite. The authorized
  connectivity follow-up ran only the tests/static checks listed above.
- No secrets files were opened; no commit, push, destructive database operation
  or Docker cleanup was performed.

There are no new ingestion/build/load artifacts from this attempt. Existing
remote data state was not inspected after the stop; no claim is made about
artifacts potentially created by other runs. README is unchanged because this
attempt did not change the platform's live data state.

## Resume point

The container source preflight now passes. At the user's requested boundary,
execution stops before ingestion and returns control. No architectural/source
identity change was required. Intermittent transport errors remain possible;
bounded retries improve tolerance but do not guarantee future network availability.

When Stage 6B-2 is resumed, begin with the same exact preflight command above to
establish current source availability. After its PASS, the next read-only baseline
command is:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
```

Capture WC catalog/served build IDs and API baseline as specified in Stage 6B-1
before continuing A–M with exact pins. No ingestion command was executed by this
connectivity follow-up.

## Real onboarding continuation (2026-10-04)

Fresh original-command source preflight: exit 0, 34 matches, 18 teams, all 34
events and 34 lineups available. Catalog/matches hashes remain the values recorded
above. Ten runbook mutation/build/load CLI interfaces passed `--help` checks.
Before publication, context 9/281 has no registered Bronze parent, Silver or Gold
builds; global Bronze max ID is 144.

### WC2022 baseline before the first write

`check_clickhouse_match_visuals.py` passed its chained Stage 4C/4D/4E checks.
The canonical API was read for all 64 WC matches. Baseline values:

| Measure | 43/106 before onboarding |
| --- | --- |
| Matches | 64 |
| Team-match v2 rows | 128 |
| Player-match v2 rows | 3244 |
| Normal shots | 1453 |
| Shootout shots / matches | 41 / 5 |
| Extra-time shots | 45 |
| Normal xG | 155.8985419302 |
| Event rows, including period 5 | 234637 |
| Pass rows | 68515 |
| Shot rows, including period 5 | 1494 |
| API competition catalog | 43 only |
| API season catalog for 43 | 106 only |

Registered WC Gold v2 IDs (also verified by current-serving validators):

- team_match_stats_v2: `b9a786b952f976d1ce320d37757fea83fe390ad552439c5f0feef8d79d98d7b4`
- player_match_stats_v2: `65f1a3c4e2e69b602c14c2254668b1a500e5e2c0cb3a67f46a87776aa145fe9e`
- match_results: `e64306623d34074950ff541e4a5c4cdd79f764723e63d478cef0595343746360`

Response hashes use UTF-8, `ensure_ascii=False`, sorted JSON keys and compact
separators; the all-match hash wraps each complete canonical analysis body with
its match ID and orders matches ascending. These normalization rules must remain
identical for the after-state comparison:

- All 64 WC analysis responses: `50de5240d2b300f7fd64073b95b04ab0df2d10cfdc353b7ef651013c12c04260`
- Argentina–France canonical analysis: `f9b3b3db4b8c5ec1feb523b37f639061a9eb58708b2184beeb6cdce160724307`

No second-context publication was started before these baseline checks passed.

The 130 existing Bronze catalog rows at `id <= 144` have a baseline canonical
tuple-list SHA-256 of `a31300efab48f2816e40e19563ea6c20169cd34610d8c343210bceb09781c290`
(fields: id/source/dataset/source_url/bucket/key/SHA/size; ordered by id).
All ten required serving tables initially contain 43/106 only, with one build per
dataset/context. Both API WC golden validation and the installed-view checks pass.

### A. Bronze checkpoint: matches parent published

Executed:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/ingest_statsbomb_bronze.py --competition-id 9 --season-id 281
```

Exit 0. Shared competitions artifact: `UNCHANGED / ALREADY_REGISTERED`, 34887
bytes, catalog SHA above. New matches parent: `UPLOADED / REGISTERED`, 63079 bytes,
SHA `13dff90f126d9f73da410ae3292b2773744657d3ba968a2b7a9c02135033581c`.
Exact immutable key:

```text
football/bronze/statsbomb/matches/competition_id=9/season_id=281/sha256=13dff90f126d9f73da410ae3292b2773744657d3ba968a2b7a9c02135033581c/matches.json
```

Child fan-out starts with that exact parent SHA, without a limit. No Silver/Gold
or ClickHouse second-context load has started at this checkpoint.

Fan-out attempt 1 stopped with exit 1 on source GET
`events/3895286.json` (`DownloadError`, underlying `URLError`). Both events and
lineups for 3895292, 3895320, 3895158, 3895107 and 3895340 were already uploaded
and registered: 10 child artifacts. This is a partial Bronze checkpoint, not a
completed onboarding. The exact immutable-ingestion command is resumed unchanged;
existing objects must report `UNCHANGED / ALREADY_REGISTERED`, not be overwritten.

Attempt 2 confirmed those statuses for existing artifacts and progressed through
`events/3895202.json`, then stopped on GET `lineups/3895202.json` with the same
safe `DownloadError / URLError` diagnostic. Exact-command attempt 3 resumes the
append-only checkpoint. No frozen Bronze boundary is selected before full success.

### A. Final partial checkpoint and transport limitation

Five operator attempts used exactly the same unmodified full fan-out command:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/ingest_statsbomb_match_data.py --competition-id 9 --season-id 281 --parent-sha256 13dff90f126d9f73da410ae3292b2773744657d3ba968a2b7a9c02135033581c
```

| Attempt | Failing source GET | Exit |
| --- | --- | --- |
| 1 | events/3895286.json | 1 |
| 2 | lineups/3895202.json | 1 |
| 3 | events/3895292.json | 1 |
| 4 | events/3895086.json | 1 |
| 5 | lineups/3895107.json | 1 |

Every failure was `DownloadError` wrapping `URLError`. The current ingestion
formatter does not expose the nested reason; this attempt therefore cannot prove
that each GET failure is TLS EOF rather than another URL transport failure. A
subsequent read-only probe made 15 full GETs to the three reproduced source paths
3895292/events, 3895107/lineups and 3895202/lineups: all passed. Intermittent source
transport failure is still an operational blocker to completing one entire fan-out.
No HTTP, preflight, proxy, DNS, CA, TLS or source identity code/config was changed.

The bounded retry policy from the connectivity follow-up is **preflight-only**.
`src/common/http.py:download_bytes`, used by Bronze ingestion, still makes one
GET attempt. Passing HEAD preflight does not guarantee 68 subsequent full GETs.
After five failed whole-command attempts, no further writes were attempted.

SELECT-only inventory and S3 HEAD + full GET/SHA checks confirmed:

| Artifact | Registered and byte-verified | Required |
| --- | --- | --- |
| Context matches parent | 1 (catalog id 146, 63079 bytes) | 1 |
| Events | 25 | 34 |
| Lineups | 24 | 34 |
| New context artifacts total | 50 | 69 |

Each of the 50 artifacts passed catalog SHA versus downloaded bytes, byte size,
immutable-key SHA and HEAD SHA metadata checks. Child source URL/path match IDs
agree and all belong to the exact 34-match parent, with no duplicate identities.
Every child key contains `competition_id=9/season_id=281`; SHA changes were not
observed on replayed files. Existing objects reported
`UNCHANGED / ALREADY_REGISTERED`; no overwrite or deletion was performed.

The complete partial inventory, including source URLs, immutable object keys,
SHA-256 values, sizes and catalog IDs, is recorded in
[stage6b2-bronze-checkpoint.csv](stage6b2-bronze-checkpoint.csv).
Observed global Bronze max ID is **205**, **not a frozen Silver input boundary**:
ingestion is incomplete, so select a boundary only after full successful fan-out.

Missing events match IDs:
`3895052, 3895060, 3895067, 3895095, 3895113, 3895153, 3895167, 3895182, 3895194`.
Missing lineups: the same nine IDs plus `3895202`.

Exact context catalog inspection shows one parent, `silver=[]`, `gold=[]`.
No Silver/Gold build IDs, file counts, DQ result or new-context analytical metric
totals exist from this attempt. B (complete Bronze validation) and C-M have not
been executed: do not treat partial byte integrity as complete membership/DQ.
No ClickHouse INSERT, load registration or idempotency load rerun was attempted.
9/281 is not yet served or discoverable through the API/frontend.

### Read-only WC2022 after-state

The same baseline queries and the full `check_clickhouse_match_visuals.py`
regression were repeated after the partial Bronze writes. All Stage 4C/4D/4E
checks pass; WC row counts, normal/shootout/extra-time metrics and all ten serving
build IDs match the recorded baseline. All serving tables still contain only
43/106. The API competition/season catalogs remain 43/106 only.

The original 130 Bronze catalog rows at id <= 144 retain the exact baseline
tuple-list SHA `a31300efab48f2816e40e19563ea6c20169cd34610d8c343210bceb09781c290`.
Re-reading all 64 canonical WC analysis responses with identical normalization:

- All-match response SHA: `50de5240d2b300f7fd64073b95b04ab0df2d10cfdc353b7ef651013c12c04260` (unchanged).
- Argentina-France response SHA: `f9b3b3db4b8c5ec1feb523b37f639061a9eb58708b2184beeb6cdce160724307` (unchanged).

### Superset read-only semantic audit

The existing Superset metastore was inspected in a read-only PostgreSQL
transaction, selecting only dashboard/chart/dataset filter configuration and RLS
associations. No app initialization, dashboard save or Superset mutation occurred.

**Immediate follow-up blocker before claiming multi-context dashboard safety:**
`World Cup 2022 Overview` (dashboard 1) has **no fixed competition_id=43 /
season_id=106 restriction in any of its eight charts**. Datasets are physical
`football.bi_team_match_stats` (id 2) and `football.bi_player_match_stats` (id 3),
without virtual SQL constraints or associated RLS. Chart filters only set
`match_date: No filter`. Dashboard native filters are Stage, Match Date and Team,
all without defaults and none enforcing the context pair.

Affected charts: Total Matches (1), Team Total xG (2), Team Total Shots (3), Team
Pass Attempts (4), Shots vs xG by Team (5), Top Players by xG (6), Top Players by
Shots (7), Match Table (8). They currently read WC only because serving has not
received 9/281 yet; after onboarding they can mix both contexts. No claim of
World Cup dashboard correctness after future coexistence is made.

`Match Analysis` (dashboard 2) has eight charts (9-16). Native Match uses
`match_label`, single selection, scope ROOT with no exclusions, but no default,
`enableEmptyFilter=false`, `defaultToFirstItem=false`, `creatable=true`. There are
no fixed context filters or associated dataset RLS. Shots correctly retains
`is_shootout=0`; Shootout Summary retains `result_method='PENALTIES'`; these are
analytical restrictions, not context guards. A correctly selected unique match
label can scope the charts, but an empty/unselected Match filter does not
guarantee one context/match. Native-filter behavior and label uniqueness across
both live contexts still require validation after successful onboarding; this
dashboard is not certified multi-context-safe by the metastore inspection alone.
Superset configuration is intentionally unchanged; manual hardening needs a
separate authorized follow-up.

### Checks at the partial stop and next task

438 offline Python tests passed. Read-only installed Stage 4C/4D/4E validators
passed, including exact v2 affected-key checks and normal-shot/xG/series checks.
The full WC API response before/after comparison passed for all 64 matches.
Spark synthetic, broader API unit/integration, frontend/build/Playwright and real
9/281 API/frontend acceptance were not rerun: the requested post-onboarding gate
has not been reached. They remain required before declaring Stage 6B complete.

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
docker compose config -q
git diff --check
```

Recommended next task: authorize a targeted ingestion GET transport-hardening
patch (or restore reliable container outbound connectivity), without changing
source identities, TLS verification, immutable S3 semantics or DQ. If retries
are added, bound them and explicitly reject certificate-validation, HTTP 404
and content/context failures; test offline. Do not redesign Stage 6B-1 or alter
its successful preflight. Then rerun the exact original source preflight; if it
passes, resume the fan-out command above with the same parent SHA, freeze the
new successful Bronze max ID and continue B-M from Stage 6B-1. Do not delete the
50 verified artifacts to restart. Superset context hardening remains a separate
immediate follow-up before multi-context dashboard correctness is claimed.

Changed files in this onboarding attempt: this report and the partial Bronze
checkpoint CSV. README is unchanged because real second-context serving did not
complete. No secrets files were opened, no destructive commands/cleanup were
run, and no commit or push was performed.

## Authorized downloader hardening and continuation

Production path: `ingest_statsbomb_match_data.py` calls
`src.common.http.download_bytes` (urllib `urlopen`, 30-second timeout). It reads
the entire response into memory before returning; no source-to-S3 streaming
exists. A failed read raises before SHA, immutable PUT and PostgreSQL registration.
Previously it had only one attempt, unlike source preflight. Historical ingestion
logs exposed only wrapped URLError, so their exact nested cause is unknown;
verified preflight reproductions establish intermittent TLS EOF on the same host.

The minimal patch shares the existing classifier/safe diagnostics/backoff in
`src/common/source_transport.py`. Production GET now has three total attempts,
1s/2s delays, default certificate/hostname verification and the same URL/bytes.
Preflight GET delegates once to that downloader: **no nested 3x3 retry**. HEAD
continues using the shared wrapper. Transient EOF/reset/timeout/incomplete read,
temporary DNS and HTTP 429/500/502/503/504 qualify; certificate/hostname failures,
other TLS errors, permanent DNS, other 4xx and content/context errors do not.

Each response is closed on every attempt. Content-Length, when present, is
checked against fully read bytes; incomplete bytes are discarded and never
returned for publication. Fan-out validates JSON array framing outside the GET
retry before hashing/PUT, without reserialization or altering Silver DQ.

Resume now resolves existing children from the authoritative context catalog,
not the CSV. Exact parent membership/source URL/key/bucket, HEAD SHA metadata,
full S3 GET SHA and byte size are checked before reuse; existing children need
no source GET or new registration. Missing/unregistered children retain the old
conditional PUT/recovery path. No overwrites/deletes or analytical changes.

Offline suite: **451 tests passed**, including 13 new production retry/resume
tests. Coverage includes first-attempt success, one/two transient failures then
success, exhaustion at three, nonretryable cert/404/content errors, short-body
discard, one final publication/registration per child after successful retry,
zero writes after exhausted partial reads, safe logs/default TLS, verified reuse
without remote download/registration and corruption rejection.

### Bronze resume checkpoint: ingestion complete

Fresh original source preflight passed with the unchanged catalog/parent hashes,
34 matches, 18 teams and all 68 children available. Before writes, WC serving
counts/builds and both canonical response hashes were reconfirmed unchanged.
Four additional offline tests cover no nested preflight GET retry, partial-catalog
fetching of only missing children, foreign-context exclusion and source/key
mismatch rejection: **455 tests pass** in total.

The exact full fan-out command above then finished with exit 0:

- Parent reused and SHA-verified: 1.
- Existing children fully verified/reused: 49; no source GET or registration.
- Source GETs completed: 19; new immutable publications: 19; new registrations: 19.
- Transport retries observed during ingestion: **2** (GET lineups/3895153.json
  and events/3895060.json, SSLEOFError/TLS_EOF on attempt 1, success on attempt 2).
- Full context catalog: 1 parent + 34 events + 34 lineups = **69 artifacts**.
- Source identity/parent SHA unchanged; no WC data mutation.

Successful ingestion boundary frozen at **bronze_max_id=267**. Use that exact
boundary for every child-based Silver check/publish; never advance it mid-run.
Final Bronze metadata/membership and full byte-validation checkpoints follow.

Final Bronze validator: exit 0, events 34/34, lineups 34/34, exact parent SHA
verified. Supplementary full S3 GET checks passed SHA/size/JSON-array validation
for all 69 objects and exact parent context/membership; no missing children.
Final catalog evidence: [stage6b2-bronze-complete.csv](stage6b2-bronze-complete.csv).
The original 50-artifact CSV is retained as the historical partial checkpoint.
Silver teams full check-only started only after both Bronze checks passed.

### Silver publication checkpoints

All jobs below use 9/281, the exact parent SHA above and frozen Bronze max ID 267.
Each full check-only passes before publication; check-only and published build IDs
must agree. Initial completed checkpoint:

| Dataset | Build ID | Rows | Files | DQ | Publication/catalog |
| --- | --- | --- | --- | --- | --- |
| teams | `65225ec0d725e42e77af05c83a986595889629a4e10b13e5cd37db3afb65de63` | 18 | 1 | PASS | CREATED / REGISTERED |
| players | `6812dabdc3df85171cc4e4947620c97e5477c35ffaa8f3454a8daba1d3aa9dd7` | 460 | 2 | PASS | CREATED / REGISTERED |
| match_squads | `5f20bf72ef8a2ec7be7fa9f51b60092b086f270725d011175743c86b0ea64418` | 1353 | 2 | PASS | CREATED / REGISTERED |
| event_core | `6da4cacc187df6a6bdf1d9f1687396bd4f94c5abf742a3310fa6dc67efc55288` | 137765 | 4 | PASS | CREATED / REGISTERED |
| pass_events | `dc16623c4307c6ab7f278aeafd08a6f89d940ae9a94857ac1d9d14e5b7405118` | 39214 | 4 | PASS | CREATED / REGISTERED |
| shot_events | `032e806d47ecc5f761a749ef724fc866020204dbb601de646e958a8374556676` | 916 | 4 | PASS | CREATED / REGISTERED |
| matches | `0559f5effc14d3387d47f774e6a3ec0e727b7915400ed140e7e30a6d4d1a0abb` | 34 | 1 | PASS | CREATED / REGISTERED |

Players check-only/publish follows the same pinned Bronze snapshot. Gold and
ClickHouse loads have not started at this checkpoint.

All seven Silver builds now registered, each with the same check-only/published
ID. Matches explicitly pins this run's teams build. Seven exact-build Silver
loader check-only invocations passed source inventory/schema/casts/row-count/DQ
and context-scoped target checks; WC rows are not a global conflict. No INSERT or
load registration has occurred yet. Gold begins with the explicit Silver IDs above.

### Gold checkpoints

Stats v2 pins event_core, match_squads, pass_events and shot_events from the
completed Silver table above; match_results_v1 pins event_core, matches and
shot_events from that same table. No implicit latest selection or WC pins.
Full check-only precedes each publish with identical resulting build ID.

| Dataset/version | Build ID | Rows | Files | DQ | Publication/catalog |
| --- | --- | --- | --- | --- | --- |
| team_match_stats_v2 | `4860842745a367e641a4a36c976ed6172ae00f97133cf3cdbe69699565134077` | 68 | 1 | PASS | CREATED / REGISTERED |
| player_match_stats_v2 | `a901e32250b595ccb69278f68b7ba6deb61a918d239dea87c77e8dad9343a480` | 1353 | 2 | PASS | CREATED / REGISTERED |
| match_results_v1 | `a99c1fd9f20b54cc0a18b75dfaf41cd1cc1c8e9238bf25083d66aad193a5f284` | 34 | 1 | PASS | CREATED / REGISTERED |

All three exact-build Gold loader check-onlys passed: source rows 68/1353/34,
requested 9/281 target rows zero, no global conflict from WC2022. Results DQ:
28 regulation wins, 6 draws, zero extra-time/penalty results. No analytical
formula/version/schema changed. Real loads follow only after these preflights.

Before the first ClickHouse load, WC load catalogs have 7 Silver / 5 Gold rows,
with tuple SHA-256 `2617efd3158123a7fe6f343bb5e30358de1e2c53dcfdd615d9a92fb924db0aed`
and `eea0778549482ef3173dd067f153757dc4c2b763ba601dee73d5434111d5c8d5`
respectively (id/context/table/build/row_count, ordered by id). 9/281 has no load
registrations yet. These existing WC records must remain unchanged.

### First real ClickHouse loads

All ten 9/281 loaders finished `LOADED / REGISTERED`, each preceded immediately
by its exact check-only command. Silver targets: event_core, pass_events,
shot_events, teams, players, match_squads, matches. Gold targets:
team_match_stats_v2, player_match_stats_v2, match_results. Target names derive
only from the existing allowlist; no DDL, replacement, delete or truncation.
Source/target rows equal the build counts in the two tables above.

Both contexts now coexist physically; WC Bronze catalog hash, serving row
counts/build IDs and existing load catalog hashes remain unchanged. New context
load registrations: 7 Silver and 3 Gold, one for each exact build. The next
checkpoint repeats all ten load commands with identical pins, again preceded
by check-only, and compares row/catalog state before and after.

## Final acceptance: real coexistence

### Idempotency and serving

All ten exact same-build reruns, each preceded by check-only, returned
`UNCHANGED / ALREADY_LOADED` and `ALREADY_REGISTERED`. Full grouped
row/build state and all selected load catalog tuples before/after rerun compare
identically. Registrations remain 7 Silver / 3 Gold for 9/281, and 7 / 5 for WC.
No duplicate registration or row growth. WC load catalog hashes remain the
before-load values above. [Serving checkpoint](stage6b2-serving-checkpoint.csv)
records both contexts' row counts and exact single build IDs in all ten targets.

Generic Silver/model, Gold v2/model and match-results BI validators pass for both
contexts. Every reported hard/info orphan count is zero; full-key grains,
home/away coverage, source-versus-Gold counts, lineage and xG totals pass. There
are no cross-context orphan keys or leaked joins in these checks.

### Actual observed context totals

These are measured values, not WC-derived expectations. 9/281 is the supplied
34-match Bayer Leverkusen subset, not all 306 league fixtures.

| Measure | 9/281 | WC2022 43/106 after |
| --- | --- | --- |
| Matches | 34 | 64 |
| Teams | 18 | 32 |
| Players (dimension) | 460 | 829 |
| Event rows including period 5 | 137765 | 234637 |
| Passes | 39214 | 68515 |
| Shots including period 5 | 916 | 1494 |
| Normal shots | 916 | 1453 |
| Normal shot goals | 110 | 169 |
| Normal shot xG | 100.5025969706 | 155.8985419302 |
| Team-match v2 rows | 68 | 128 |
| Player-match v2 rows | 1353 | 3244 |
| Extra-time matches / shots | 0 / 0 | 5 / 45 |
| Shootout matches / shots | 0 / 0 | 5 / 41 |

Gold 9/281 xG sum is 100.50259697060001; source/API sum is 100.5025969706,
within the existing 1e-9 tolerance. Team event/pass/shot totals equal
137765/39214/916; player event/pass/shot totals equal 137257/39214/916.
Normal shot goals exclude own goals and are not a replacement for official
match scores. Existing period-5 exclusion and periods-3/4 retention are unchanged.

### WC2022 unchanged

Installed Stage 4C/4D/4E checks pass after onboarding, including exact affected
keys, v2 cutover schema/all values, 1453 normal shots, 41 shootout shots,
2906 long-form race states and 155.8985419302 normal xG. All original serving
build IDs and the 130 original Bronze catalog-row hash remain unchanged.
The canonical body hash for **all 64** WC analysis responses remains
`50de5240d2b300f7fd64073b95b04ab0df2d10cfdc353b7ef651013c12c04260`;
Argentina-France remains
`f9b3b3db4b8c5ec1feb523b37f639061a9eb58708b2184beeb6cdce160724307`.
No golden test was weakened or data replaced.

### API and React

Canonical API catalogs expose competitions 9 and 43, with seasons 281 and 106
respectively; match lists contain 34 and 64 rows. Existing
`check_application_api.py` passes for 9/281 (all section endpoints for four
matches: 3895052, 3895060, 3895067, 3895074) and WC with named golden regression.
A supplementary read of **all 34** new-context analysis bodies verifies 1353
player rows, 916 normal shots, zero shootout attempts, xG 100.5025969706,
two race states per event_order with one home/one away, monotonic cumulative xG
and team final xG equal to team stats. No API/runtime frontend patch was needed.

Real browser acceptance on Chromium-based Edge at **1440x900 and 390x844**
passes: both data-driven context selectors, match switching, canonical deep link,
refresh, back/forward, match header, team comparison, race, shot map, player
table/full squad and race-map-details selection. No page-level horizontal
overflow or fake carry-forward markers; ShootoutPanel is absent for 9/281.
Screenshots inspected: `frontend/test-results/stage6b2-1440.png` and
`stage6b2-390.png` (ignored test outputs, not published assets).

Two real-context Playwright acceptance tests were added; the existing root
smoke now explicitly selects WC before its unchanged WC golden checks, since
root correctly chooses the first available catalog context (9). No frontend
runtime hardcoding was added. All existing WC browser assertions remain intact.

### Superset after coexistence: confirmed immediate follow-up

Fresh read-only metastore audit matches the pre-onboarding configuration
identically; Superset was not saved/initialized/changed. All eight World Cup
Overview charts still lack fixed `competition_id=43 AND season_id=106` filters,
virtual dataset constraints or associated RLS. Their physical views now expose:

- bi_team_match_stats: 9/281 = 68 rows / 34 matches; 43/106 = 128 / 64.
- bi_player_match_stats: 9/281 = 1353 rows; 43/106 = 3244.
- bi_match_overview: 34 + 64 = 98 matches.
- Unfiltered Overview aggregate: **98 matches, xG 256.4011389008**, not WC-only.

Thus those charts **can mix contexts**; cached visual values are not proof of
semantic safety. World Cup dashboard correctness is not certified. Match
Analysis's native Match filter has no required default/selection guard. Current
overview labels are unique (98 rows / 98 distinct labels), so selecting a valid
single label can scope one match; empty selection remains unsafe. Immediate next
authorized task: harden World Cup Overview context restrictions and Match
Analysis's selected-match guard in Superset, then validate both contexts read-only.
Do not "fix" this by narrowing generalized serving views or deleting 9/281.

### Final tests and commands

All passed after onboarding:

| Check | Result |
| --- | --- |
| Offline Python | 455 tests |
| Spark synthetic, eight suites | 97 tests (16+9+21+25+8+10+6+2) |
| API offline unit | 26 tests |
| API read-only live integration | 3 tests |
| Existing frontend unit | 50 tests |
| Playwright smoke | 15 tests, including two new real-context viewport tests |
| Frontend typecheck/production build | PASS |
| Both-context serving/API, WC 4C/4D/4E and before/after hashes | PASS |
| docker compose config -q / git diff --check | PASS |

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
foreach ($suite in @('test_event_core.py','test_s3a_event_core.py','test_event_domains.py','test_lineup_domains.py','test_matches.py','test_gold_match_stats.py','test_match_results.py','test_context.py')) {
  docker compose run --rm --no-deps football-spark spark-submit "tests/spark/$suite"
  if ($LASTEXITCODE -ne 0) { throw "Failed: $suite" }
}
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'test_*.py'
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p integration_api.py
foreach ($pair in @(@(9,281),@(43,106))) {
  docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_model.py --competition-id $pair[0] --season-id $pair[1] --transform-version v2
  docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_gold_model.py --competition-id $pair[0] --season-id $pair[1] --transform-version v2
  docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_results.py --competition-id $pair[0] --season-id $pair[1] --bi
}
docker compose run --rm --no-deps football-api python scripts/check_application_api.py --competition-id 9 --season-id 281
docker compose run --rm --no-deps football-api python scripts/check_application_api.py --competition-id 43 --season-id 106 --wc2022-regression
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
Push-Location frontend
npm.cmd test
npm.cmd run build
npm.cmd run test:smoke
Pop-Location
docker compose config -q
git diff --check
```

Exact ingestion/build/load commands are the A-M runbook in Stage 6B-1 with the
parent SHA, frozen boundary 267 and complete Silver/Gold pin tables recorded
above. No second real ingestion is needed to verify this completed onboarding.

Changed runtime files: `src/common/http.py`, new `src/common/source_transport.py`,
`scripts/check_statsbomb_source.py`, `scripts/ingest_statsbomb_match_data.py`.
Tests: `tests/test_http.py`, new `tests/test_http_retry.py`,
`tests/test_ingest_statsbomb_match_data.py`, `frontend/tests/smoke/live.spec.ts`,
new `frontend/tests/smoke/coexistence.spec.ts`. Evidence/docs: README, this report,
historical partial Bronze CSV, complete Bronze CSV and serving checkpoint CSV.

No incomplete new-context builds/loads remain. Data-pipeline and application
onboarding acceptance is complete; Superset safety is the outstanding separate
follow-up above. No secrets opened/printed, no DeleteObject/destructive command,
schema/formula/version change, Docker cleanup, commit or push was performed.
