# Stage 9C.2-E: football-data.org offline mapping and consistency

Checked: 2026-10-30. Branch `master`; HEAD/origin-master:
`8f7728605e8de0c079f7cbb3a77e79463df803bb`.

- **Offline mapping: READY** for the explicitly configured, synthetic league phase.
- **Technical real-source integration: BLOCKED**: no HTTP adapter, approved
  identity/version registry, end-to-end real reconciliation or serving cutover.
- **Persistent onboarding: BLOCKED / LEGAL_REVIEW_REQUIRED** for storage,
  retention, backups, derived tables, public display and Django redistribution.
- **Stage 8C: PARTIAL**. Existing StatsBomb data/pipelines are unchanged.

## Evidence and implementation boundary

The [C/D evaluation](stage9c2-provider-evaluation.md) records exactly three
authenticated GET responses in D: UCL competition 2001, season 2557; 144 fixture
slots (54 FINISHED, 90 TIMED); TOTAL/HOME/AWAY league-stage tables with 36 rows
each. The fields/shapes are evidence; private payloads were not saved or reused.
There are **no new network requests** in E. No token is required or read.

The [artificial fixture specification](../tests/fixtures/football_data_synthetic.json)
and [generator](../tests/football_data_fakes.py) use invented club names, fixture
IDs, kickoff times and scores. The generator reuses B's artificial balanced
schedule, not downloaded data. Its 36 finished and 108 scheduled fixtures are
deliberately **not** D's live 54/90 distribution. Passing these tests does not
independently reconcile the real 144 fixtures or verify all UCL season phases.

No CLI, transport, provider registration, Bronze/Silver/Gold job, application
route, table, migration, database write or scheduler is introduced. A/B source
and checks remain unchanged; their historical runbooks are preserved.

## Offline mapper API

[football_data.py](../src/providers/football_data.py) exposes:

```python
map_responses(metadata_bytes, fixtures_bytes, standings_bytes,
              context=mapping_context, fetched_at=aware_utc,
              previous=optional_previous_snapshot) -> MappingResult
```

Inputs are three bounded in-memory JSON byte strings. `MappingContext` contains
A's validated **empty** Snapshot and explicit `FixtureBinding` records. The
supported scope is one club league phase: 36 configured participants, eight
rounds and 144 fixture bindings. It is not a universal season/query engine.

### Identity and versions

Canonical competition, season, stage, round, participant and fixture IDs must
already be supplied by the caller. Provider numeric IDs become exact strings in
`ProviderIdentity`, never canonical StatsBomb IDs; no name/date-based allocation
or cross-provider merging occurs. Runtime provider namespace is `football-data-org`
to satisfy A's existing identifier grammar.

`FixtureBinding.neutral_revision` is **CALLER_SUPPLIED**. There is no default
revision=1, auto-increment, timestamp-as-revision or fabricated provider revision.
The existing Fixture contract requires a positive neutral version; an approved
caller-owned version registry is a prerequisite for actual integration. The
synthetic caller supplies its invented versions explicitly. `revision_origin`
states `CALLER_SUPPLIED_NEUTRAL_VERSION_NOT_PROVIDER_REVISION`.

With `previous=...`, A's unmodified `validate_update` enforces identity continuity,
legal transitions, retained old entities, greater neutral versions on changes,
and non-regressing source update times. A wrong version blocks rather than being
silently repaired. A future local registry needs separate review; this stage
neither allocates nor persists one.

### Mapping contract

| Input | Neutral representation / handling |
| --- | --- |
| Competition id/name; type CUP | Configured Competition identity/name; CLUB is explicit context, not inferred knockout format |
| currentSeason.id/startDate/endDate | Requested configured season identity; valid ordered dates, not full-season coverage proof |
| match.id, homeTeam.id, awayTeam.id | Explicit fixture binding and configured participant identities; team names must agree across resources |
| utcDate | Aware UTC kickoff; null remains null, never invented |
| lastUpdated | Required per fixture, aware UTC, not later than fetched_at; not a revision |
| matchday / LEAGUE_STAGE | One configured Round 1..8 / LEAGUE_PHASE; unknown stages fail closed |
| FINISHED + REGULAR + numeric fullTime pair | Regulation Score; extra-time and penalties remain null |
| TIMED + null fullTime pair | Scheduled fixture with null Score, not 0-0 |
| TOTAL standings | One neutral StandingsEntry per stage/participant |
| HOME / AWAY standings | Separate TableView records; never duplicate TOTAL's neutral keys |
| position | Retained provider provisional rank; no local points/GD re-sort |
| draw / playedGames / goalsFor / goalsAgainst | drawn / played / goals_for / goals_against |
| extraTime / regularTime / penalties with numeric values | Unsupported score semantics, retained separately; no inclusive-to-additional guess |
| Coordinates, xG, incidents, lineup/player statistics | Not manufactured or advertised as verified capabilities |

Unmapped optional fields such as odds/referees/logos are not capability evidence.
Required semantic fields are strictly validated; unrelated fields are not mapped.
Duplicate JSON keys, NaN/Infinity, bool-as-integer, wrong shapes, IDs, context,
duplicates and incomplete inventories fail closed. No silent truncation occurs.

Each response is at most 1 MiB with maximum JSON nesting depth 32. The complete scoped fixture array must contain
exactly 144 unique IDs and agree with `resultSet.count` and, when supplied,
`resultSet.played`. Explicit continuation/pagination fields are unsupported, not
ignored. This offline decoder is not a transport-enforced streaming HTTP bound.

### Status and unsupported-result handling

Only **TIMED/FINISHED** occurred in D. SCHEDULED -> scheduled, IN_PLAY -> live,
POSTPONED -> postponed and CANCELLED -> cancelled are conventional mappings
tested **only synthetically**; they appear in `synthetic_only_statuses` and cannot
pass the stronger observed-window acceptance gate in this stage.

SUSPENDED, ABANDONED, the unverified LIVE alias and unknown statuses produce
`UnsupportedFixture`, not a fabricated UNKNOWN neutral fixture with a lost score.
It preserves provider ID/status, reason, duration and nullable full-time,
regular-time, extra-time and penalty pairs. Postponed/cancelled fixtures retaining
a score are handled the same way because A cannot represent that combination.
Missing duration or finished score also blocks candidate creation.

Any unsupported fixture means `snapshot=None`, `semantic_digest=None` and
`ready_for_offline_use=False`; no supposedly complete partial subset escapes.
All exceptions expose fixed `football_data_mapping:<CODE>` messages, never source
values or original exception text. There is no logging or runtime credential use.

## Standings and schedule reconciliation

The mapper reuses [A validation](../src/providers/validation.py) and
[B reconciliation](../src/providers/reconciliation.py) without weakening them:

- 36 unique configured participants; 144 fixtures; eight games per team;
  four home/four away; unique opponents and no repeated team in one round.
- No missing/out-of-scope/duplicate fixture or team identities.
- Each supplied TOTAL/HOME/AWAY table has exactly the configured 36 members.
- P/W/D/L/GF/GA/points are recomputed independently from **finished fixtures only**.
  Scheduled/live/postponed/cancelled fixtures contribute nothing to table counters.
- Each view is checked separately; HOME/AWAY counters are not added as 72 extra
  participants. Goal difference and P=W+D+L must agree.
- Provider counters are never replaced to force reconciliation PASS.
- Unknown points adjustments are not inferred from a difference. A nonzero
  unexplained difference fails; disciplinary authority remains unverified/SKIP.
- Official UEFA tie-break/rank validation remains SKIP. Matching arithmetic does
  not prove that a provisional provider order follows every UEFA rule.

TOTAL is mandatory for mapping. Missing HOME/AWAY views are explicit SKIP checks,
not inferred zeros; the stronger window gate below requires all three views.
Failed structural/counter DQ yields no candidate Snapshot or semantic digest.

## Explicit alternative consistency contract

[observed_window.py](../src/providers/observed_window.py) exposes:

```python
verify_observed_window(tuple_of_six_observations, context=mapping_context,
                       max_window_seconds=120,
                       previous=optional_previous_snapshot) -> WindowEvidence
```

This takes **already supplied offline responses**, not an adapter/network callback.
The exact observation order is:

```text
M0 metadata -> F0 fixtures -> S0 standings -> F1 fixtures -> S1 standings -> M1 metadata
```

The caller supplies UTC start/end of each observation. Overlap, backwards/naive
timestamps and an excessive window fail. Default maximum is 120s; configurable
hard cap 300s. There are exactly six responses, each at most 1 MiB: at most 6 MiB
input bytes, no retries, unbounded paging or real sleep.
Source update times and known finished/live kickoff times must not be later than
their own response's completion, not merely a later resource/collection time.

For each resource, compute canonicalized content SHA-256. Object keys are sorted;
the known record-set arrays `matches`, `standings`, `table`, `seasons` are sorted
canonically **without deduplication**. Rank/matchday/IDs/counters remain values in
the records; a changed value still changes the fingerprint. Other arrays retain
their order. Reordering JSON keys or these record sets alone is not source drift.

Require M0=M1, F0=F1 and S0=S1 fingerprints, then independently map/reconcile both
sets, require all three tables and compare deterministic semantic digests. A
source timestamp change also closes the conservative content fence. Do not
discard a changed response and choose the preferred one. Any changed fence,
unsupported state, scope mismatch or DQ failure rejects the window.

Provenance is an immutable tuple of six resource receipts: resource, sequence,
start/end UTC, received bytes, raw response SHA-256 and content fingerprint.
It retains no payload, URL, header or token. Caller-owned input bytes are not
persisted; receipts and results are returned only in memory.

The semantic digest includes A's normalized snapshot content and ALL supplied
table views, excluding collection freshness and receipt metadata. It retains
source fixture update times and explicit neutral versions. Replaying the same
content at another collection time or record order gives the same digest. It is
neither a provider revision nor a Silver/Gold build identity.

The result says **OBSERVED_WINDOW_STABLE_NOT_ATOMIC**, `source_revision=None`,
`publish_authorized=False`. This is **not an atomic** provider snapshot. Two
equal reads cannot detect change-and-revert (ABA), hidden/cached updates, false
upstream timestamps or a self-consistent but incomplete/incorrect provider feed.
Repeated metadata alone is insufficient; arithmetic agreement alone is also
insufficient. Bounds depend on truthful caller observation times; no real HTTP
timeout enforcement is claimed by this pure validator.

This alternative is isolated from B's revision-fenced `BoundedCollector` and its
`CollectionPlan.source_revision`. B still rejects a missing revision. Nothing
automatically falls back to this weaker contract or bypasses a live-provider gate.
A future real collection needs explicit acceptance of this weaker consistency
model, a separately authorized HTTP budget/transport and persistence approval.

## Local tests and publication boundary

```powershell
& .venv/s3-recovery/Scripts/python.exe ci/run_unittest.py discover -s tests -p 'test_football_data*.py'
& .venv/s3-recovery/Scripts/python.exe ci/run_unittest.py discover -s tests -p 'test_provider*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python ci/check_repository.py
python -m ruff check src/providers tests ci
```

The existing CI fast Python 3.10.12/3.12.14 discovery includes the new tests;
no workflow, dependency or secret is needed. The new CI contract enumerates all
eight E files and checks the offline boundary, synthetic fixtures and runbook.
Local acceptance on 2026-10-30 (no remote workflow run):

| Runtime / gate | Result |
| --- | --- |
| Windows CPython 3.12.10 | 62 new mapper/window tests PASS; 119 existing A/B tests PASS |
| Windows CPython 3.12.10, network-denied recovery gate | 262 synthetic recovery tests PASS, including real temporary Windows ACL/junction checks; no real backup/restore drill |
| Linux CPython 3.10.12 | 968 offline tests OK (9 expected Windows/Spark skips); 45 CI contracts and 61 application tests PASS |
| Linux CPython 3.12.14 | Same counts and PASS results |
| Both Linux versions | Ruff and compileall PASS |
| Repository / new files | Tracked-file contracts plus explicit scan of all eight E files PASS; local Markdown links/whitespace PASS |
| Workflow syntax | actionlint PASS with explicit workflow filenames (archive snapshots have no .git project discovery) |
| Preservation | SHA-256 unchanged for all 18 pre-existing A/B/C/D source/evidence files |

Linux runs used cached images, networking disabled, read-only root/source and
ephemeral `/tmp`. The source snapshot was `git archive HEAD` plus the explicit
18 pre-existing and eight E source/doc/fixture files: no local environment,
venv, runtime state or ignored dependencies were copied. This is an isolated
source reproduction, not a staged/committed clean checkout. No staging was done.
Frontend/browser tests were not rerun because no frontend/application code changed;
the 61 existing application tests passed on both Linux versions.

Nothing is staged, committed or pushed. A/B/C/D's pre-existing untracked source
and docs must also be included in a future reviewed publication snapshot; E alone
is not a self-contained checkout. The existing deployment evidence and unrelated
shortcut are preserved. No API/UI, runtime, data, backup or key was accessed.

## Next minimal task

Review the offline source set and identity/version/observed-window contracts,
then seek concrete storage/public-display/redistribution clarification. Only
after separate authorization should a bounded, memory-only real mapping and DQ
reconciliation probe test all 144 real fixtures against the real TOTAL/HOME/AWAY
tables. An independently authorized transport/request budget is required. Do not
start ingestion or implement public serving automatically from these tests.
