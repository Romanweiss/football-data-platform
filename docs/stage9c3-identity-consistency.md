# Stage 9C.3-A: offline identity registry and consistency policy

Checked: 2026-11-01 (Europe/Moscow). Branch `master`, baseline:
`175643f1ea734264e9e70876c797c48298fd7f66`.

- **Offline identity/consistency: READY** for synthetic data and serial ownership.
- **Live read-only reconciliation: BLOCKED** until a separate authorized request
budget, safe token handoff and reviewed real identity evidence are supplied.
- **Persistent onboarding: BLOCKED / LEGAL_REVIEW_REQUIRED.**
- **Stage 8C: PARTIAL.** No live registry, database tables or publication exist.

Baseline [CI fast](https://github.com/Romanweiss/football-data-platform/actions/runs/41190967727)
and [CI integration](https://github.com/Romanweiss/football-data-platform/actions/runs/41190967641)
were checked SUCCESS for the exact published SHA. These are baseline evidence,
not remote acceptance of this uncommitted stage. The
[C/D evaluation](stage9c2-provider-evaluation.md) and
[E mapping contract](stage9c2-football-data-mapping.md) retain the provider and
legal limitations. No new UEFA HTTP requests or credential reads were made.

## Identity contract

[identity_registry.py](../src/providers/identity_registry.py) provides an
in-memory `IdentityRegistry`, frozen `IdentityRecord`/`Participation`, and explicit
`IdentityEvidence(confirmed=True, reference=...)`. Evidence is an operator/caller
attestation with a non-secret bounded label, not proof obtained by this library.
No identity is allocated when confirmation or required references are missing.

Canonical IDs have form `uefa:<kind>:<sha256>`. SHA-256 covers a fixed identity
domain, provider namespace, entity kind, exact external ID and applicable scope.
Names, scores, observation time and kickoff are NEVER identity keys. Internal
IDs are separate from source IDs; existing StatsBomb IDs are not reassigned or
merged. There is no fuzzy matching, integer/string coercion or name/date fallback.

| Kind | External-ID uniqueness scope | Immutable relationship |
| --- | --- | --- |
| provider | Provider namespace | Root record; external ID equals namespace |
| competition | Provider + competition external ID | Provider root; club/national type |
| season | Provider + competition + season external ID | Competition |
| participant | Provider + participant external ID | Provider root; club/national type |
| stage | Provider + season + stage external ID | Season and stage kind |
| round | Provider + stage + round external ID | Stage and unique round order |
| fixture | Provider + fixture external ID, NOT season-local | Season and ordered home/away participants |
| tie | Provider + stage + tie external ID | Knockout/qualifying stage, unordered pair, one/two legs |

Example public API, using synthetic evidence only:

```python
registry.register(provider, IdentityKind.COMPETITION, external_id,
                  parent_id=provider_id, team_type=TeamType.CLUB,
                  evidence=IdentityEvidence(True, "synthetic-reviewed-v1"))
registry.confirm_participation(season_id, participant_id, evidence=evidence)
```

Exact repeated bindings return the existing record. New evidence for the same
binding retains the first evidence reference; it cannot reassign identity.
Different external IDs are not aliases even if display names match. Participants
keep IDs across seasons, but each season requires separate confirmed participation.
National teams cannot join a club context or change a club's existing binding.

Kickoff reschedules do not change fixture ID. A changed team, swapped home/away,
or fixture external-ID reuse in a different season is **CONFLICT**, even if all
teams are otherwise known. No automatic correction/rebinding is implemented for
those identity changes. Stage/round/tie source IDs also require confirmation;
the module does not invent real tie IDs from names or dates. Provider-specific
external-ID reuse beyond these scopes needs a separately reviewed key policy.

## Local version and correction policy

[observed_versions.py](../src/providers/observed_versions.py) provides
`VersionLedger`, `StreamRef`, `VersionReceipt`, semantic fingerprint helpers and
optional `ProviderRevisionEvidence`.

Four different facts stay separate:

1. **locally observed content version**: a contiguous local integer, starting at
   1 only after accepted content is first observed. Never a server revision.
2. **Semantic digest**: canonical content SHA-256, not an authoritative vendor
   version. Fixture score/status/kickoff/stage/participants belong to content.
3. **Observation timestamp**: supplied aware UTC; no implicit wall clock and no
   conversion of time into a revision.
4. **Source lastUpdated**: optional separately retained evidence; a new poll
   timestamp alone does not create a football content version.

Provider revision is **None for this football-data.org path**. A low-level caller
may separately attach a confirmed provider revision token for one stream, never
a global atomic snapshot. This is NOT an API access token. Tokens are opaque;
there is no lexicographic ordering. An optional integer sequence is accepted only
as explicitly confirmed provider-counter evidence. No token is read from a
process environment, credentials file, SDK or HTTP client.

`VersionLedger.observe(ref, digest, observed_at=..., expected_version=...,
source_updated_at=..., provider_revision=None)` has these rules:

- Identical content keeps its version. An exact replay also leaves serialized
  state unchanged; a later observation updates evidence times, not content version.
- Changed content increments exactly once, preserving fixture identity.
- Stale expected versions, backwards observations, same-time different content
  and regressing source timestamps fail without changing the stream.
- A previously confirmed source timestamp/provider fence cannot silently disappear.
- The same provider revision token cannot describe different content. Confirmed
  monotonic counters cannot regress or conflict. A new token for unchanged content
  need not create a new local version.
- Reversion to an earlier content digest requires explicit review. A newer client
  timestamp is not sufficient evidence to accept an old response as a correction.
- TOTAL/HOME/AWAY standings and season metadata have separate version streams;
  corrected table order does not fabricate changed fixture versions. Official
  tie-breaker correctness remains unverified by this policy.

No disciplinary point adjustment, extra-time/penalty meaning, xG or coordinates
are inferred. Unsupported statuses/scores retain E's explicit unsupported record
and cannot become a registered candidate.

## Observed-window handoff and transaction boundary

[registry_policy.py](../src/providers/registry_policy.py) exposes:

```python
context = bind_mapping_context(registry, empty_snapshot, external_fixture_ids, ledger)
proposal = prepare_registered_window(observations, registry=registry,
                                    versions=ledger, context=context,
                                    previous=optional_previous_snapshot)
```

The boundary is:

```text
Provider adapter / offline bytes -> six-read collector protocol
  -> confirmed registry bindings -> existing E DQ/reconciliation
  -> local version proposal -> immutable Snapshot + evidence
```

This does not fetch data. The existing strict E protocol is invoked directly:
metadata -> fixtures -> standings -> fixtures -> standings -> metadata.
Its 120s default/300s cap, six 1 MiB responses, repeated fingerprints, scope and
TOTAL/HOME/AWAY reconciliation remain unchanged. No legacy B source fence is
weakened or silently replaced with this alternative.

Mapping bindings use the current local version or an explicitly prospective
initial local 1 **only to parse** the neutral format. They do not record state or
claim a vendor version. Source-window evidence therefore describes the pre-version
mapping; consumers must use `proposal.snapshot` for final local revisions.

After DQ, all identity relationships are checked again. The ledger is forked in
memory; all fixture, metadata and table observations must succeed. A refresh
requires the previous Snapshot paired with this ledger, including its semantic
fingerprints, local versions and source timestamps. Invalid pairings fail closed.
The proposal contains deterministic `ledger_after_state` bytes and safe receipts;
the input registry, ledger and previous Snapshot are NOT mutated. Adopting the
proposed in-memory state is an explicit caller action, not publication.

The new `validate_observed_update` policy projects timestamp-only changes for
comparison with A's existing strict guard, while independently enforcing actual
source-clock monotonicity and local version sequence. Returned data keeps the real
latest source timestamp. Display names/season labels are metadata, not new IDs.
The original A/B `validate_update` and revision-fenced collector are unchanged:
their old strict behavior is explicitly tested. There is no global weak mode.

The proposal always states **NOT_ATOMIC** (`OBSERVED_WINDOW_STABLE_NOT_ATOMIC`),
`source_revision=None`, `publish_authorized=False`. Conflict/DQ/fence failure
produces no proposal. Equal reads cannot detect invisible updates or ABA, prove
provider accuracy, or establish an atomic S3/database/provider transaction.

## Serialization, limits and recovery of local state

`IdentityRegistry.to_bytes()/from_bytes()` and corresponding `VersionLedger`
methods operate on canonical JSON bytes only; there is no file path argument,
writer or PostgreSQL registry. Schema version 1 uses strict field sets, exact
types, validated references and deterministic ordering. Fixture home/away tuples
are positional and are not reordered as generic sets.

Bounds: 2000 identity records, 3000 participation edges, 2000 version streams,
32 content versions and 128 provider token bindings per stream; serialized state
at most 1 MiB per registry/ledger. Exceeding a bound stops processing; history is
not silently trimmed. Production retention/concurrency/storage need separate design.

Snapshots are **unsigned**, not encrypted or authenticated. Passing an externally
trusted `expected_fingerprint` to `from_bytes` detects changed bytes. Computing
that expected hash from an untrusted input is not authentication. Without a pin,
restore is for trusted in-memory bytes/synthetic fixtures only: a maliciously
rewritten internally consistent snapshot cannot be detected from itself.
Future disk persistence needs approved integrity/access control and licensing.

Identity hashes do not depend on insertion order; reordered equivalent snapshot
records restore to identical canonical bytes. Version history remains ordered,
contiguous and monotonic. Snapshot bytes contain identities/evidence and hashes,
not raw response bodies or API credentials; do not export real state into Git.

## Synthetic evidence and quality checks

[Synthetic helpers](../tests/provider_identity_fakes.py) reuse invented JSON
fixtures from E. The bootstrap has 192 identities, 36 participation edges, 144
fixtures and 148 version streams (144 fixtures + metadata + three tables).
Its initial 36 finished/108 future fixtures are not a new observation of real UCL.

Tests cover duplicate/namespace IDs, unconfirmed/missing teams, club/national
conflicts, season membership and fixture-ID reuse, reschedules, score/status/table
corrections, timestamp-only replay, stale/conflicting versions, out-of-order
observations, deterministic restore, pinned tamper detection, input-state
atomicity, source fences, DQ, and denied network/storage/logging side effects.
They require no API key and never contact a provider. Local regression evidence
on 2026-11-01:

| Check | Result |
| --- | --- |
| New identity/version/policy tests | 55 PASS (35 registry/version + 20 proposal tests) |
| Windows CPython 3.12.10, complete provider foundation | 236 PASS (119 A/B + 62 E + 55 new) |
| Linux CPython 3.10.12 and 3.12.14, each | 1023 offline tests OK, with 9 Windows-only skips; 50 CI/security contracts and 61 application tests PASS |
| Both Linux versions | Repository checker, Ruff and compileall PASS |
| Source audit | Explicit scan of eight new source/test/doc files, Markdown links and whitespace/diff checks PASS |

At the Stage 9C.3-A checkpoint, Linux checks used read-only public-source snapshots, cached pinned dependency
images and networking disabled. The snapshot contains the published baseline
plus the explicit eight-file overlay, not local secrets, venv or runtime files.
Nothing was staged at that checkpoint; these A results are not staged-tree publication review or remote CI evidence.
No frontend/API code changed. No actual database restore or native Windows
recovery/ACL drill was repeated; those modules are unchanged and their published
baseline CI evidence is separate from the local tests above.

## Requirements for the first real read-only gate

Before a separately authorized probe, the operator must approve the provider
namespace/scope and identity evidence, safe in-memory auth route, temporary-use
rights, request budget and a bounded collection window. The operator cannot
freeze the provider: changed reads reject the window, not become a supposedly
atomic snapshot. At least six bounded GET
responses are needed to instantiate this protocol: competition 2001 metadata
twice; matches and standings with `season=2026` twice each. Season ID 2557 must
be checked in responses, not substituted for the documented query year.

Validate the actual participant/fixture inventories and all table counters before
calling a candidate verified. Stop on unknown identities/status semantics, changed
fences, 401/403/429 or incomplete coverage; do not spend extra requests to repair a
failed window without authorization. Real identity binding approval, provider
correction history and real fixture/table reconciliation remain unverified here.
No raw payload retention, ingestion, live publication or Current Competitions UI
is authorized by these offline tests. Persistent onboarding remains blocked by
licensing/storage and the unimplemented serving/persistence design.
