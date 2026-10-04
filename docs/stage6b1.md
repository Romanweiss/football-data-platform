# Stage 6B-1 — ETL generalization and second-context preparation

Status: preparation implemented and tested; **not real multi-context proof**.
Only WC2022 (`43/106`) is published and served. No second-context ingestion,
S3 publication, metadata registration, ClickHouse INSERT/DDL or Superset changes
were executed. No commit or push. No credentials files were opened.

## Four blockers: audit and resolution

The pre-edit audit used [Stage 6A](stage6a.md) and its
[line-level context audit](stage6a-context-audit.csv), then followed actual callers,
catalog queries, manifests, transformations, loader state machines and tests.

| Blocker and exact locations | Previous assumption / consequence | Safest change implemented in 6B-1 | Deferred to 6B-2 |
| --- | --- | --- | --- |
| Bronze: `scripts/ingest_statsbomb_bronze.py` source definitions/main; `ingest_statsbomb_match_data.py:main`; `src/common/postgres.py` parent lookup | Fixed WC matches URL/dataset selected the wrong parent for other contexts | Authoritative catalog lookup, explicit IDs, generic matches source, exact context + parent SHA lookup; scoped child keys | Ingest and verify real second-context bytes |
| Silver/Gold orchestration: `src/silver/job.py:run_publish_job`, `matches_job.py:run_job`, `scripts/build_silver_event_core.py`, `src/gold/job.py:main`; publishing wrappers | Wrappers supplied 43/106; implicit input selection could change between runs | Required context; exact parent SHA and frozen Bronze catalog boundary; exact teams build for matches; all Gold upstream builds pinned | Real Spark/S3A builds and DQ |
| Load resolution: `src/analytics/{silver_input,gold_input}.py:resolve_*_build`, `job.py`, `gold_job.py` | Fixed lookup context prevented selecting another context's build | Required CLI context + build ID, exact catalog/manifest validation, existing allowlisted dataset/version mappings | Same physical table coexistence and repeated real load |
| v2 snapshot: `src/gold/stats_snapshot.py`, Gold build/load callers | Universal WC build constants rejected every other input snapshot | Generic explicit-pin/context-prefix validator; old exact WC snapshot still required for 43/106 | Verify chosen context's actual registered lineage |

No formula, output schema, grain, DQ threshold, output committer, Spark/Hadoop/S3A
version, IAM/policy, migration or BI view changed. `matches.py` lost implicit WC
defaults, not validation rules. Lineup path recognition accepts both historical
flat and new context-scoped keys. Generic model functions now require context.

## Source resolution, identity and exact lineage

The [authoritative repository](https://github.com/hudl/open-data) documents:
`competitions.json` → `matches/<competition>/<season>.json` →
`events/<match>.json` and `lineups/<match>.json`. The historical `statsbomb` GitHub
organization redirects to `hudl`; readers still accept historical source URLs.
`src/statsbomb/context.py` centralizes resolution and validates the catalog pair
and every match's nested competition/season before fan-out.

New matches keys:
`football/bronze/statsbomb/matches/competition_id=C/season_id=S/sha256=H/matches.json`.
New child keys:
`football/bronze/statsbomb/{events|lineups}/competition_id=C/season_id=S/match_id=M/sha256=H/{events|lineups}.json`.
The catalog JSON itself remains a shared immutable source artifact. Bronze SHA
is still SHA-256 of exact downloaded bytes; context is not injected into the
content hash. Conditional creation and existing integrity/recovery checks remain.
Existing WC keys/labels/manifests are neither moved nor rewritten.

`--parent-sha256` resolves exactly one registered matches artifact by source URL,
context and SHA. Missing/ambiguous parents fail closed. Child resolution retains
the established latest-per-source rule but requires an explicit `--bronze-max-id`
boundary: only rows at/below that recorded ID are eligible, then exact parent
membership and path/hash/HEAD checks apply. Stop concurrent ingestion before
freezing this boundary and keep it unchanged throughout a run/retry. The catalog
is append-only through project code; a late commit with a previously allocated
lower ID or manual catalog mutation is outside this snapshot guarantee.
Historical flat child keys are accepted for compatibility; source match membership
remains mandatory. Ambiguous old/new URL aliases fail rather than choosing silently.

Silver manifests record the actual selected immutable inputs. Build specifications
already include layer/source/dataset/context/transform version/input fingerprint/
schema SHA. Gold fingerprints already include exact upstream build IDs and paths.
No hash algorithm change was needed, so old WC build identities remain valid.
New contexts have distinct prefixes and build identities, even with reused IDs.
Gold CLI now requires every upstream pin, including v1; low-level legacy lookup
helpers remain available internally but production CLI paths do not use latest.

Seven Silver datasets retain their grains. Matches pins the teams build for DQ;
its output identity continues to depend on the source parent/schema, not redundant
validation-only input. Gold stats require event_core, match_squads, pass_events,
shot_events; results require event_core, matches, shot_events. Event-domain Bronze
lineage and full match membership must agree. Period 5 exclusion applies only to
v2 normal stats; extra time and separate shootout results are unchanged. Result
method derives from actual events/metadata, never from a fixed stage-name list.

## Metadata, physical tables and loader safety

PostgreSQL `ingestion_objects` stores source URL, immutable key, content SHA and
size (no separate context columns). The URL/key carries source context. Existing
`silver_builds`/`gold_builds` explicitly store context, version and lineage, with
unique `(dataset, competition_id, season_id, build_id)` and bucket/prefix identity.
Load catalogs store context, target table and build reference, unique by target
database/table/build ID. Version is validated through the referenced build and
allowlisted specification. No new registry or migration is needed.

Live SELECT inspection confirmed all 12 serving MergeTree tables partition by
`(competition_id, season_id)` and start their sorting keys with that context.
Dimensions, facts, results and v2 tables already coexist correctly by design.
Existing BI joins/windows include full context; installed WC view definitions and
outputs passed the existing regression. No view rewrite or ordering migration.

The existing loader state machine was already context-scoped; it is preserved,
now reachable through explicit resolvers and covered by new coexistence tests.

| Requested load in an allowlisted dataset/version target | Behavior |
| --- | --- |
| Same context/build, complete target and matching catalog | `UNCHANGED / ALREADY_LOADED`, `ALREADY_REGISTERED` |
| Different context, empty requested context | Allowed; other contexts neither count as conflict nor get replaced |
| Same context, different build | Integrity/build-conflict error before INSERT |
| Complete verified target but missing catalog registration | Recover registration without another INSERT |
| Partial/excessive target, wrong context or conflicting catalog | Fail closed, no cleanup or blind INSERT retry |

Dataset/version chooses the target from fixed specifications, not arbitrary CLI
table names. Build hashes include context/version. Full loads keep the shared
cooperative PostgreSQL writer lock, synchronous INSERT and existing dedup token.
Target build totals also detect a build misplaced outside its context. Tests cover
all seven Silver and three relevant Gold targets with two synthetic contexts.

## Validators and WC2022 regression

Generic checks require explicit IDs. `check_clickhouse_model.py --transform-version v2`
checks matches/Silver references against active v2 Gold (no requirement to load v1
for a new context). Gold model reconciles metrics from actual source rows. Result
`--bi` checks use the installed v2 BI source. `validate_context_snapshot` requires
all four supplied IDs, exact manifest input equality and context/build prefixes.
For 43/106 it additionally enforces the unchanged reviewed WC snapshot constants.

Stage 4 shot audit/cutover/match-analysis/match-visuals remain intentionally named
WC regressions, not universal validators. API `--wc2022-regression` likewise stays
explicit. Generic checks contain no 64/32/128/3244 universal requirements.

Read-only live results: WC matches 64; Silver event_core 234637, pass_events 68515,
shot_events 1494, teams 32, players 829, match_squads 3244. Gold v2: team rows 128,
player rows 3244; normal shots 1453, normal xG 155.8985419302; shootout shots 41 in
5 matches, extra-time shots 45. xG race states 1453, long-form states 2906. Stage
4C exact v1/v2 differences (10 team and 53 player grains), Stage 4D and Stage 4E
checks passed. Argentina–France remains covered by the existing golden tests.
Catalog inspection: Bronze max ID 144; seven Silver and five Gold builds for WC.
`football.bi_match_overview` contains only `(43,106,64)` at this stage.

## Candidate comparison and source evidence

Read-only public inspection used repository commit
`4b73468fc5b0f1950f9f66fada70ad3a4f9327cb`, its complete recursive Git tree
(`truncated=false`), the catalog and each matches JSON. All required child paths
were nonempty blobs. Counts below are available source matches, not promised full
competition coverage. Processing costs are relative estimates from match counts,
not measured Spark time or fabricated event counts.

| IDs | Competition / season | Matches / teams | Events / lineups found | Compatibility, diversity, relative cost and risk |
| --- | --- | --- | --- | --- |
| **9 / 281** | **1. Bundesliga / 2023/2024** | **34 / 18** | **34 / 34** | Recommended: club regular-season matches, draws and no expected shootouts; moderate cost, roughly half WC match count. Partial league coverage must be labelled clearly. Full payload DQ remains unproven. |
| 16 / 4 | Champions League / 2018/2019 | 1 / 2 | 1 / 1 | Smallest cost, club final but too narrow for a meaningful season/generalization test; not the whole tournament. |
| 55 / 282 | UEFA Euro / 2024 | 51 / 24 | 51 / 51 | National tournament, similar to WC; more local work and less structural diversity than a league. |

Sources: [catalog at inspected commit](https://raw.githubusercontent.com/hudl/open-data/4b73468fc5b0f1950f9f66fada70ad3a4f9327cb/data/competitions.json),
[Bundesliga matches](https://raw.githubusercontent.com/hudl/open-data/4b73468fc5b0f1950f9f66fada70ad3a4f9327cb/data/matches/9/281.json),
[Champions League matches](https://raw.githubusercontent.com/hudl/open-data/4b73468fc5b0f1950f9f66fada70ad3a4f9327cb/data/matches/16/4.json),
[Euro matches](https://raw.githubusercontent.com/hudl/open-data/4b73468fc5b0f1950f9f66fada70ad3a4f9327cb/data/matches/55/282.json).

Selected 9/281 contains Bayer Leverkusen's 17 home and 17 away matches, **not all
306 Bundesliga fixtures**. All observed stages are Regular Season. No shootouts
is a competition-format expectation, not a substitute for validating events.
These IDs appear only in evidence/runbook, not reusable runtime branches.

The actual container command also passed (GET catalog/matches, HEAD every child):

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_statsbomb_source.py --competition-id 9 --season-id 281
```

Evidence: matches=34, teams=18, events_available=34, lineups_available=34;
catalog SHA `e6cd42f5d8956d6aa30fb917ce8d4c3b3df1879a93f02f8feba820930a6971fa`;
matches SHA `13dff90f126d9f73da410ae3292b2773744657d3ba968a2b7a9c02135033581c`.
Earlier Python attempts had a transient TLS EOF; the repeat passed without any
TLS bypass. Availability is not domain-quality certification. Master is mutable:
repeat preflight before ingestion, record the newly downloaded SHA, and review any
change from this evidence. No child payloads were published or cataloged in 6B-1.

Continuation verification (2026-10-04): the container preflight encountered
`URLError` again. Independent HTTPS inspection from the host reconfirmed the pinned
catalog, 34 matches and all 68 nonempty child blobs in the complete Git tree.
This supports source availability, but is not a successful current container
transport check. **Before the first 6B-2 write, the container preflight must pass
again.** Do not bypass TLS or skip this gate. PostgreSQL SELECT inspection still
finds no 9/281 parent, Silver or Gold builds (global Bronze boundary remains 144).

## Stage 6B-2 manual runbook — NOT executed here

Run from the project root in PowerShell, with existing healthy infrastructure and
previous migrations already applied. No DDL is required. Stop other ingestion/
publish/load processes. Review each checkpoint; do not paste this whole section
as an unattended pipeline. Every data command carries context via `@ctx` (9/281)
or `@wc` (43/106). Wrappers only shorten the verified Docker/CLI invocations.

```powershell
$ErrorActionPreference = 'Stop'
$ctx = @('--competition-id', '9', '--season-id', '281')
$wc = @('--competition-id', '43', '--season-id', '106')
function Tools { docker compose run --rm --no-deps football-python-tools python @args; if ($LASTEXITCODE -ne 0) { throw 'STOP: Python job failed' } }
function Spark { docker compose run --rm --no-deps football-spark spark-submit @args; if ($LASTEXITCODE -ne 0) { throw 'STOP: Spark job failed' } }
function Api { docker compose run --rm --no-deps football-api python @args; if ($LASTEXITCODE -ne 0) { throw 'STOP: API check failed' } }
function Read-Sha([string]$label) { $value = Read-Host $label; if ($value -cnotmatch '^[0-9a-f]{64}$') { throw 'Expected exact lowercase SHA-256' }; return $value }
Tools scripts/inspect_context_catalog.py @wc
Tools scripts/inspect_context_catalog.py @ctx
Api scripts/check_application_api.py @wc --wc2022-regression
```

Record WC catalog output as baseline. New context must have no serving rows before
the first load; already-present artifacts/builds require review of exact identities,
not replacement. Preserve all recorded pins with the manual run evidence.

### A. Source preflight and Bronze ingestion (writes start only in 6B-2)

```powershell
Tools scripts/check_statsbomb_source.py @ctx
Tools scripts/ingest_statsbomb_bronze.py @ctx
Tools scripts/inspect_context_catalog.py @ctx
$parent = Read-Sha 'Exact matches parent SHA from ingestion/catalog (not catalog JSON SHA)'
Tools scripts/ingest_statsbomb_match_data.py @ctx --parent-sha256 $parent
Tools scripts/inspect_context_catalog.py @ctx
$maxId = Read-Host 'bronze_max_id after successful full child ingestion'
if ($maxId -notmatch '^[1-9][0-9]*$') { throw 'Invalid Bronze boundary' }
$bronze = $ctx + @('--parent-sha256', $parent, '--bronze-max-id', $maxId)
```

No `--limit`: all available parent matches must be ingested. Reuse the exact
parent/boundary on retries; never advance the boundary mid-build. Source changes
can create additional immutable versions, never overwrite an old artifact.

### B. Bronze validation (read-only)

```powershell
Tools scripts/check_statsbomb_bronze.py @bronze
```

Expect complete events and lineups membership, 34 each for the reviewed source.
Parent GET verifies byte SHA; child HEAD checks catalog/path/metadata (not a full
download checksum). Ingestion already confirms exact uploaded bytes. Spark reads
then apply the unchanged payload/schema/DQ checks. On any mismatch stop.

### C. Silver builds, full check-only before each publish

```powershell
$silverJobs = [ordered]@{
  teams = @('scripts/publish_silver_lineup_domains.py', '--dataset', 'teams')
  players = @('scripts/publish_silver_lineup_domains.py', '--dataset', 'players')
  match_squads = @('scripts/publish_silver_lineup_domains.py', '--dataset', 'match-squads')
  event_core = @('scripts/publish_silver_event_core.py')
  pass_events = @('scripts/publish_silver_event_domains.py', '--dataset', 'passes')
  shot_events = @('scripts/publish_silver_event_domains.py', '--dataset', 'shots')
}
$silver = @{}
foreach ($name in $silverJobs.Keys) {
  $command = $silverJobs[$name]
  Spark @command @bronze --check-only
  Spark @command @bronze
  $silver[$name] = Read-Sha "Published $name Build ID (must equal check-only ID)"
}
Spark scripts/publish_silver_matches.py @ctx --parent-sha256 $parent --teams-build-id $silver['teams'] --check-only
Spark scripts/publish_silver_matches.py @ctx --parent-sha256 $parent --teams-build-id $silver['teams']
$silver['matches'] = Read-Sha 'Published matches Build ID'
Tools scripts/inspect_context_catalog.py @ctx
```

Each job must pass full DQ and complete source membership. Record output counts,
hashes and status. No universal WC row count is applied. Publication validates
output Parquet and commits the completion manifest/catalog using existing rules.

### D. Silver validation (read-only loader checks)

```powershell
$silverCli = [ordered]@{ event_core='event-core'; pass_events='passes'; shot_events='shots'; teams='teams'; players='players'; match_squads='match-squads'; matches='matches' }
foreach ($name in $silverCli.Keys) {
  Tools scripts/load_clickhouse_silver.py @ctx --dataset $silverCli[$name] --build-id $silver[$name] --check-only
}
```

These verify exact manifests/inventories and ClickHouse's source read, casts,
schema, DQ and target state, without INSERT/registration. Existing S3 named
collection/CA configuration is reused, not changed.

### E. Gold builds

```powershell
$statsPins = @()
foreach ($name in @('event_core','match_squads','pass_events','shot_events')) {
  $statsPins += @('--silver-build', "$name=$($silver[$name])")
}
$resultPins = @()
foreach ($name in @('event_core','matches','shot_events')) {
  $resultPins += @('--silver-build', "$name=$($silver[$name])")
}
$gold = @{}
foreach ($name in @('team_match_stats','player_match_stats')) {
  $cli = $name.Replace('_','-')
  Spark scripts/build_gold_match_stats.py @ctx --dataset $cli --transform-version "${name}_v2" @statsPins --check-only
  Spark scripts/build_gold_match_stats.py @ctx --dataset $cli --transform-version "${name}_v2" @statsPins
  $gold[$name] = Read-Sha "Published $name v2 Build ID"
}
Spark scripts/build_gold_match_stats.py @ctx --dataset match-results --transform-version match_results_v1 @resultPins --check-only
Spark scripts/build_gold_match_stats.py @ctx --dataset match-results --transform-version match_results_v1 @resultPins
$gold['match_results'] = Read-Sha 'Published match_results Build ID'
Tools scripts/inspect_context_catalog.py @ctx
```

No v1 stats publication/cutover is needed: installed BI views already use v2.
Results remain `match_results_v1`. A league with no period-5 events must still
pass unchanged results/DQ; do not invent shootouts to satisfy a WC fixture.

### F. Gold validation (read-only)

```powershell
foreach ($name in @('team_match_stats','player_match_stats')) {
  Tools scripts/load_clickhouse_gold.py @ctx --dataset $name.Replace('_','-') --transform-version v2 --build-id $gold[$name] @statsPins --check-only
}
Tools scripts/load_clickhouse_gold.py @ctx --dataset match-results --transform-version v1 --build-id $gold['match_results'] --check-only
```

### G. ClickHouse loads; H. exact same-build idempotency rerun

```powershell
function Load-SelectedContext {
  foreach ($name in $silverCli.Keys) {
    Tools scripts/load_clickhouse_silver.py @ctx --dataset $silverCli[$name] --build-id $silver[$name]
  }
  foreach ($name in @('team_match_stats','player_match_stats')) {
    Tools scripts/load_clickhouse_gold.py @ctx --dataset $name.Replace('_','-') --transform-version v2 --build-id $gold[$name] @statsPins
  }
  Tools scripts/load_clickhouse_gold.py @ctx --dataset match-results --transform-version v1 --build-id $gold['match_results']
}
Load-SelectedContext
# Review all outputs, then repeat exactly the same pins (no ingestion/build rerun):
Load-SelectedContext
```

First load expects `LOADED / REGISTERED` (or documented complete-load recovery).
Second expects `UNCHANGED / ALREADY_LOADED` and `ALREADY_REGISTERED` everywhere.
No concurrent loaders. An INSERT timeout is an unknown server outcome: wait for
the server query to finish before read-only inspection/retry, never immediately
issue another INSERT. Conflicting/partial state means STOP, not delete/reload.

### I. Generic serving validation

```powershell
Tools scripts/check_clickhouse_model.py @ctx --transform-version v2
Tools scripts/check_clickhouse_gold_model.py @ctx --transform-version v2
Tools scripts/check_clickhouse_match_results.py @ctx --bi
```

### J. API catalog; K. frontend visibility

```powershell
Api scripts/check_application_api.py @ctx
Invoke-RestMethod http://127.0.0.1:18000/api/v1/competitions
Invoke-RestMethod http://127.0.0.1:18000/api/v1/competitions/9/seasons
Invoke-RestMethod http://127.0.0.1:18000/api/v1/competitions/9/seasons/281/matches
```

Refresh `http://127.0.0.1:15173/`, select Competition 9 / Season 281, then a match.
Check score/result, teams, xG race, shots, player table and empty shootout section;
cross-highlighting, filters, 390x844 / 1440x900, back/forward and reload. Existing UI
catalogs are data-driven; do not edit selectors or automatically modify Superset.
Names remain localized ID labels as documented in Stage 6A, not newly fabricated
competition names. Review canonical context in URL and API requests on switching.

### L. Cross-context regression; M. final coexistence evidence

```powershell
foreach ($contextArgs in @($wc, $ctx)) {
  Tools scripts/inspect_context_catalog.py @contextArgs
  Tools scripts/check_clickhouse_model.py @contextArgs --transform-version v2
  Tools scripts/check_clickhouse_gold_model.py @contextArgs --transform-version v2
  Tools scripts/check_clickhouse_match_results.py @contextArgs --bi
  Api scripts/check_application_api.py @contextArgs
}
Api scripts/check_application_api.py @wc --wc2022-regression
# This historical command is intentionally WC-only, not a generic second-context check:
Tools scripts/check_clickhouse_match_visuals.py
$wcMatches = (Invoke-RestMethod http://127.0.0.1:18000/api/v1/competitions/43/seasons/106/matches).matches
$newMatches = (Invoke-RestMethod http://127.0.0.1:18000/api/v1/competitions/9/seasons/281/matches).matches
if ($wcMatches.Count -ne 64 -or $newMatches.Count -ne 34) { throw 'Unexpected reviewed-context coverage; STOP' }
Write-Output "43/106 matches=$($wcMatches.Count); 9/281 matches=$($newMatches.Count)"
```

Save both contexts' catalog IDs/counts, check output, idempotency statuses and UI
observations with the 6B-2 report. WC IDs/counts must equal the baseline; new-context
builds/load records must be unique and mapped to the same allowlisted tables.
Expected combined available-match count is 98 for this reviewed source only.
Only successful completion of these real checks may establish coexistence.

## Failure model and limits

- Source/preflight failure: stop before writes; repair transport without disabling
  TLS, then rerun. Availability does not prove Silver DQ or exact processing cost.
- Bronze interrupted: immutable objects/catalog registrations recover through
  existing checks. Do not delete successful versions; keep the parent pin fixed.
- Silver/Gold complete output with missing catalog: existing verified recovery may
  register it. Incomplete/conflicting prefix fails closed. Do not overwrite it or
  change a version merely to bypass an error. Stop and review a non-destructive
  recovery design if such state occurs; automatic partial repair is not provided.
- ClickHouse complete INSERT with missing metadata can recover registration.
  Partial INSERT or same-context conflicting build cannot be auto-replaced. Stop
  and diagnose read-only; no destructive rollback is permitted by this runbook.
- There is no multi-table atomic cutover: a new context may become partially visible
  while loads are underway. Keep application acceptance/testing after all loads and
  serving checks; WC is unaffected. A production atomic onboarding gate is future work.
- Catalog-bound snapshots assume no concurrent ingestion/manual catalog mutation.
  Source master may change between HTTP downloads; exact per-object content
  lineage, not a single upstream repository transaction, is the current contract.
- No second-context S3/Spark/CH payload validation was run here. Actual source DQ,
  resource usage and real coexistence remain the Stage 6B-2 acceptance gates.

## Verification commands and changed-file inventory

Offline Python, Spark and CLI checks use mounted project source and no real S3.
Live regression is SELECT/API-only. Browser tests use existing data or synthetic
intercepts. Commands verified in this work:

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
foreach ($suite in @('test_event_core.py','test_s3a_event_core.py','test_event_domains.py','test_lineup_domains.py','test_matches.py','test_gold_match_stats.py','test_match_results.py','test_context.py')) {
  docker compose run --rm --no-deps football-spark spark-submit "tests/spark/$suite"
  if ($LASTEXITCODE -ne 0) { throw "Failed: $suite" }
}
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'test_*.py'
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p integration_api.py
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
Push-Location frontend
npm.cmd test
npm.cmd run build
npm.cmd run test:smoke
Pop-Location
git diff --check
```

Runtime changes: `src/statsbomb/context.py`; Bronze ingestion scripts and
`src/common/postgres.py`; Silver job/matches_job/build_identity, matches defaults,
lineup/membership path readers, preview/publish CLIs; Gold job/inputs/stats_snapshot;
analytics build resolvers/jobs/model validators; model/results/S3/cutover CLI
wrappers. New read-only commands: `check_statsbomb_source.py`,
`check_statsbomb_bronze.py`, `inspect_context_catalog.py`.

Tests: new `tests/test_etl_context.py`, `tests/spark/test_context.py`, explicit WC
fixture helper `tests/context_fixtures.py`; existing Bronze/Silver/Gold/ClickHouse
unit and synthetic/integration fixtures updated to supply required context/pins.
Documentation: this report and README. `git diff --name-only` plus
`git ls-files --others --exclude-standard` provides the exact working-tree inventory.
No application/frontend runtime files, infrastructure definitions or dependencies
were changed by Stage 6B-1.

Final results: 428 offline unit tests, 97 synthetic Spark tests across eight suites,
26 API unit tests, 3 read-only API integration tests, 50 frontend unit tests and
13 browser smoke tests passed. Frontend production build, compose config and WC
Stage 4C/4D/4E regressions passed. Source preflight history and the latest transport
gate are distinguished above. CLI `--help` was checked for all
new/changed runbook commands; PowerShell blocks were syntax-checked without executing
publication/load commands.

The continuation adds exact resolver coverage for all seven Silver and three Gold
targets in both synthetic contexts: bound dataset/context/build parameters, no
latest fallback, rejection of wrong competition/season/build/version and missing
catalog rows. Existing coexistence/idempotency/conflict tests exercise the loader
state machines separately. No Stage 6A application code was reimplemented.
