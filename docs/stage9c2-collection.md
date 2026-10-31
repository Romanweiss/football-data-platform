# Stage 9C.2-B: synthetic collection, pagination and DQ

Baseline: `8f7728605e8de0c079f7cbb3a77e79463df803bb`, branch `master`.
Stage 9C.2-A foundation preserved. Provider: **PROVIDER_UNDECIDED**.
Real-source onboarding: BLOCKED. Stage 8C: PARTIAL.

This stage implements offline collection of invented schedules/tables only.
It does not connect a provider, run ingestion, write Bronze/catalog/serving,
publish snapshots, allocate build IDs or touch the running application.
The [Stage A runbook](stage9c2-provider-adapter.md) remains the source/licensing gate.

## Architecture and interface

```text
Offline Provider Adapter (typed metadata + synthetic JSON pages)
  -> Bounded Collector (cursor, limits, retry budget, source fences)
  -> A contracts + DQ/reconciliation
  -> Frozen CollectionSnapshot (data + safe checks + provenance)
  -> FUTURE approved Bronze integration (not executed or implemented here)
```

[collection.py](../src/providers/collection.py) extends the existing provider
package; there is no second ingestion framework or generic HTTP client.

`PagedProviderAdapter.describe(timeout_seconds=...) -> CollectionPlan` returns
one explicit context: A's immutable Snapshot with empty fixtures/standings,
declared expected counts, source revision and explicit `PhaseRules`.
`fetch_page(resource, cursor, timeout_seconds=...) -> bytes` accepts only fixtures
or standings. Competition, season, participants, stages, rounds, capabilities
and source freshness are bounded typed metadata, not separately paginated APIs.
`SyntheticPagedAdapter` implements this interface over an invented Snapshot.

`BoundedCollector(clock=..., policy=..., limits=...).collect(adapter, previous=...)`
returns a `CollectionSnapshot`, including on ordinary source/DQ failure. It owns
no persistent state. A new invocation starts pagination from the beginning.

The collector uses only callbacks to a trusted offline adapter. There is no URL
argument, SDK/HTTP transport, credentials reader, file writer or real scheduler.
This is not a sandbox for arbitrary adapter code: a future network adapter needs
separate approval and real transport enforcement. The existing live-provider
allowlist remains empty.

## Page and pagination contract

Each JSON page contains schema_version=1, resource, contiguous sequence starting
at 1, echoed request_cursor, next_cursor (null means terminal), source_revision,
declared total, explicit complete flag, and typed fixtures/standings arrays.
The unused resource array must be empty. Unknown fields, duplicate JSON keys,
non-finite values, coercions and malformed records fail closed through A's parser.

- Cursor tokens use the bounded A identifier grammar; they cannot be URLs/paths.
- Every cursor is visited at most once; sequence/echo checks catch gaps and loops.
- Totals must agree with initial metadata and unique observed entity counts.
- Empty pages are legal only for a declared zero-total terminal resource.
- Repeated row-set pages, canonical keys and external fixture identities fail;
  nothing is silently deduplicated, overwritten or truncated.
- A changed fixture revision appearing twice during one collection is a conflict,
  not permission to take the latest version. Restart collection against a stable
  source revision. A correction to an unseen row is detectable only if the source
  honors the revision/fence contract; no stronger guarantee is claimed.
- Final `describe` must exactly match the initial metadata fence, including source
  revision, counts, scope, rules and source freshness. The fence is SHA-256 recorded.
- Metadata fences are not an atomic provider snapshot. They cannot prove the
  absence of an invisible update that the source fails to expose in its revision.

The source revision must identify the same logical dataset across resources.
If a real provider cannot supply that, onboarding needs an explicitly weaker
consistency design and reconciliation window, not a fabricated revision token.

## Bounds and deterministic clock

Existing `RequestPolicy` defaults: 10s per attempt, three attempts, exponential
1s/2s backoff, 30 requests/minute, ten pages PER resource, 1 MiB per page.
`CollectionLimits` defaults/hard caps: 3000 paged entities in total, 4 MiB received
across page responses, 64 calls including metadata/retries, 120s collection budget
(configurable cap 300s), maximum single wait 30s (cap 60s), source age 3600s
(configurable cap one day). A's per-resource 2000-row caps also remain enforced.

The same request-spacing budget covers metadata, pages and retries. The timeout
is passed to the adapter and checked when it returns. This is a **cooperative**
deadline, not a preemptive timeout capable of interrupting a blocking callback.
A future HTTP adapter must implement actual socket/request timeouts and bounded
streaming reads. The collector cannot undo memory allocated inside arbitrary
adapter code before its return.

Clock `monotonic`, `now` and `wait` are explicit dependencies. Tests use
`VirtualClock`; waits advance virtual time and do not block. No real sleep or
automatic scheduling occurs. Backoff and rate spacing both consume the overall
deadline. An unreasonable Retry-After is refused, not silently shortened.

Only bounded typed records/identity indexes and at most 20 page receipts are
accumulated. Raw page bytes are discarded after decoding/hash calculation.
Receipts retain resource, sequence, row count, byte count, raw SHA-256 and cursor
SHA-256, not cursor text or source payload. The semantic digest uses A's normalized
content and excludes freshness; page boundaries, request attempts and collection
time do not change it. It is not a Silver/Gold build ID.

## Failure taxonomy and snapshot lifecycle

Retryable within budgets: HTTP_429, HTTP_500, HTTP_502, HTTP_503, TIMEOUT.
HTTP_429 honors a bounded supplied Retry-After; known QUOTA_EXHAUSTED stops
immediately. TLS, AUTHENTICATION, ACCESS_DENIED, UNSUPPORTED, malformed data,
cursor errors, duplicates, revision conflicts, source changes, limits and DQ
failures are not automatically retried. Retry exhaustion retains the safe code.
Unknown exceptions become MALFORMED without raw exception text or URLs.

CollectionSnapshot schema_version=1 separates:

| Dimension | States | Meaning |
| --- | --- | --- |
| state | SUCCEEDED / FAILED / UNSUPPORTED | Outcome of the collection operation |
| completeness | COMPLETE / PARTIAL / UNKNOWN | Coverage of the explicitly declared scope |
| freshness | FRESH / STALE / UNKNOWN | Age of source checked_at against supplied clock/policy |

It also contains provider/competition/season, UTC collection time, accepted page
count, collected fixture+standings count, request/received-byte counters, semantic
digest, source freshness, source-fence digest, immutable provenance and DQ checks.
FAILED/UNSUPPORTED returns no candidate data or semantic digest. Counts/provenance
may describe the typed prefix, never a publishable full dataset. COMPLETE page
coverage can coexist with FAILED quality/revision validation: this deliberately
does not collapse independent dimensions into one status. A gap or failed fence
leaves coverage PARTIAL/UNKNOWN instead.

A SUCCEEDED collection can still be PARTIAL or STALE. The complete candidate
gate `eligible_for_full_snapshot` requires fresh COMPLETE data, no FAIL checks,
and independently checked standings counters. `require_complete()` rejects all
other outcomes. This is synthetic eligibility, not authorization for a live write.
COMPLETE means the declared phase/group scope, **not every stage of a UEFA season**.

## DQ and football reconciliation

[reconciliation.py](../src/providers/reconciliation.py) reuses the existing
`src.dq.model.Rule` definitions/categories and numeric scalar discipline. It does
not fabricate numeric StatsBomb context IDs for `Run`, change DQ persistence or
write history. `Check` is a frozen provider-scoped observation; future persistence
needs an approved mapping into the existing framework.

Before success, A's type/namespace/uniqueness/reference/status/nullable-score and
round/tie contracts are rerun. The collector additionally verifies page coverage
and source fences. Each phase's explicit membership and schedule rules check:

PhaseRules must come from reviewed season configuration, not be blindly accepted
as a provider's claim about the competition format. Synthetic adapters embed this
test configuration; a real provider/rules registry has not been approved here.

- Members, all stage rounds, games per team, home/away balance, opponent frequency
  and at most one fixture per team per round; Nations return legs reverse venue.
- Club UCL/UEL: 36 teams, eight rounds/games, four home; Conference: six and three.
  These are synthetic scenario rules, not a hardcoded rule for every competition.
- National groups: explicit division and group, no cross-group participants.
- Finished league/group fixtures independently produce P/W/D/L/GF/GA/points;
  live, scheduled, postponed and cancelled fixtures do not enter the table.
- Scores use regulation goals; missing/invalid finished scores fail A validation.
- Provider entries must match recomputed counters. Incorrect data is rejected,
  never repaired or replaced with newly computed expected values to make tests pass.
- Declared point deductions are included explicitly, with WARN because their
  underlying disciplinary authority is not independently verified here.
- UEFA tie-breakers/official rank order are explicitly SKIP/unverified, not PASS.
  Equal provisional ranks remain valid; no points/GD-only official re-ranking.
- An incomplete schedule cannot establish all standings counters: the check is
  SKIP and the complete-candidate gate stays closed even if local totals agree.

This proves counters for the supplied scoped fixtures, not provider coverage,
disciplinary decisions, UEFA qualification or every official ranking criterion.

## Corrections and replay

Across successful collections, `validate_update(previous, current)` enforces A's
stable fixture/provider/team identity, status transitions, monotonic revision and
update time, and refusal to interpret missing old entities as deletion. A moved
kickoff changes the fixture revision, not its canonical ID. A finished correction
must also reconcile with the new table; the old snapshot is never mutated.

The collector neither publishes nor keeps an active pointer. On a failed refresh,
the caller still owns the previous immutable object. Existing StatsBomb serving
and its one-build-per-context guards are unchanged. Actual publication/rollback
is a future separately reviewed integration, not implemented by this gate.

## Synthetic evidence and tests

[scenario definitions](../tests/fixtures/provider_collection_scenarios.json) and
[fake helpers](../tests/provider_collection_fakes.py) generate invented teams and
deterministic schedules. They are not imitations of downloaded real matches.

| Scenario | Participants | Fixtures (all statuses) | Coverage |
| --- | --- | --- | --- |
| UCL | 36 | 144 | Complete declared synthetic league phase |
| UEL | 36 | 144 | Complete declared synthetic league phase |
| Conference | 36 | 108 | Complete declared synthetic league phase |
| Nations | 8 in two divisions/groups | 24 | PARTIAL competition; complete selected groups |

Future scheduled scores remain null. Only the first two invented rounds are
finished; current standings are independently rebuilt from those results.
Tests include retry/quota/timeout, schema drift, wrong cursors, missing/duplicate
pages, partial flags, correction races, conflicting revisions, result/table drift,
replay and safe diagnostics, plus a zero-total empty declared scope.

```powershell
& .venv/s3-recovery/Scripts/python.exe ci/run_unittest.py discover -s tests -p test_provider_collection.py
```

Existing fast CI automatically discovers these tests on Python 3.10.12/3.12.14.
No workflow, credentials, dependencies or quality gates were changed. Regression
results are recorded after local acceptance; no GitHub CI run is claimed here.

Local acceptance (2026-10-29):

| Gate | Result |
| --- | --- |
| Windows CPython 3.12.10 | 119 provider A+B tests PASS (61 A, 58 collection B) |
| Linux CPython 3.10.12, isolated container with networking disabled | 906 offline tests OK, 9 expected Windows/Spark skips; 40 CI contracts and 61 application tests PASS |
| Linux CPython 3.12.14, same restrictions | Same counts and PASS results |
| Both Linux versions | Ruff and compileall PASS |
| Repository/security | Existing tracked-file checks and explicit A/B source signature checks PASS |
| Workflow/whitespace | actionlint and existing/new-file diff checks PASS |

No real database restore or native Windows recovery/ACL drill was repeated in B;
those modules were not changed. Existing recovery tests ran in the Linux offline
suite. Files remain unstaged; a future publication must include both A's nine
files and B's seven new files and recheck the actual staged Git snapshot.

## Future Bronze boundary and next gate

A future approved integration can use the same bounded adapter/collector and
existing immutable Bronze/catalog patterns, but must explicitly capture exact
response bytes before discard into a private/unpublished collection attempt.
The receipts alone are not a backup or enough to reconstruct raw responses.
Only a verified candidate may advance; failed/partial attempts must not be
registered as complete seasons. No source URL, raw archival or cleanup policy is
invented before provider licensing/storage and real transport are approved.

Recommended 9C.2-C: confirm authenticated 2026/27 fixtures/standings payloads and
rights, including raw retention/backups/publication; then approve the concrete
adapter mapping, collection revision/freshness semantics and controlled read-only
onboarding. Do not ingest into production merely because synthetic tests pass.
No API key is requested by this stage, and React Current Competitions is not begun.
