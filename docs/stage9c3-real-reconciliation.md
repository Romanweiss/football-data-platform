# Stage 9C.3: real UEFA read-only reconciliation

## Latest result: Stage 9C.3-D-Retry — SUCCESS

Reviewed: **2026-11-02 (Europe/Moscow)**. Published source HEAD remains
`29c057ee165eaf89d334c143eb1e0761d31b103b`. The historical failed attempt below is
preserved; it did not provide any of the current data counts or fingerprints.

| Gate | Current result |
| --- | --- |
| Real identity reconciliation | **READY** for this observed league-phase window |
| Real standings reconciliation | **READY**, TOTAL/HOME/AWAY arithmetic |
| Full published bounded observed-window verification | **READY / NOT_ATOMIC** |
| Persistent onboarding | **BLOCKED / LEGAL_REVIEW_REQUIRED** |
| Stage 8C | **PARTIAL**, unchanged |

### New authorization, transport and provenance

A separate single-use session received a **new maximum-six-attempt budget**. The
old session and its lock were not reused or reset. Before token entry, one TLS-only
preflight passed on Windows CPython **3.12.10 / OpenSSL 3.0.16**, through the existing
local system proxy, with default certificate validation, hostname verification and
SNI. This preflight sent no API GET. No additional diagnostic HTTP GET was made.

The operator entered their own API token through a masked GUI field with explicit
Paste, Ctrl+V, Shift+Insert and right-click paste support. It was never stored in
environment variables or command arguments. The operator confirmed completion and
closed the window; the probe process exited. No token or raw authenticated body
was written to disk. Only counts, fingerprints and safe validation evidence were
retained. Real in-memory registry/ledger bytes were not persisted either.

All **6/6 attempts completed GET and returned HTTP 200**, without redirects,
retries, repairs or additional provider requests. Each response was bounded to
1 MiB and each connection/read had a 15-second socket timeout. Actual response
sizes were below the bound. All six connections used **TLS 1.3**, with certificate
and hostname verification enabled.

| # | Resource and documented endpoint | HTTP | Bytes | Started UTC | Ended UTC |
| --- | --- | --- | --- | --- | --- |
| 1 | M: `https://api.football-data.org/v4/competitions/2001` | 200 | 6157 | 2026-11-01T21:23:42.070397Z | 2026-11-01T21:23:42.526138Z |
| 2 | F: `https://api.football-data.org/v4/competitions/2001/matches?season=2026` | 200 | 141389 | 2026-11-01T21:23:42.526673Z | 2026-11-01T21:23:43.068058Z |
| 3 | S: `https://api.football-data.org/v4/competitions/2001/standings?season=2026` | 200 | 28420 | 2026-11-01T21:23:43.075348Z | 2026-11-01T21:23:43.533635Z |
| 4 | F: same fixtures endpoint | 200 | 141389 | 2026-11-01T21:23:43.535727Z | 2026-11-01T21:23:44.076206Z |
| 5 | S: same standings endpoint | 200 | 28420 | 2026-11-01T21:23:44.082801Z | 2026-11-01T21:23:44.595745Z |
| 6 | M: same competition endpoint | 200 | 6157 | 2026-11-01T21:23:44.599313Z | 2026-11-01T21:23:45.035505Z |

The observation was **2026-11-01 21:23:42–21:23:45 UTC**, corresponding to
**2026-11-02 00:23:42–00:23:45 Europe/Moscow**. The published default window bound
of 120 seconds passed: **2.965108 seconds**, with ordered non-overlapping receipts.
This is observation duration, not an SLA or provider freshness guarantee.

### Actual payload and identity results

Both fixture/table read sets had identical observed aggregates:

| Measurement | LIVE_VERIFIED in this window |
| --- | --- |
| Competition / current season / fixture season | 2001 / 2557 / 2557 |
| Query season | `season=2026`, not the internal season ID |
| Fixtures / unique fixture IDs / duplicate IDs | 144 / 144 / 0 |
| Fixture team IDs / confirmed season memberships | 36 / 36 |
| Statuses | FINISHED 54; TIMED 90; no other status observed |
| Fixture stage | LEAGUE_STAGE, all 144 |
| Standings stage / views | LEAGUE_STAGE; TOTAL, HOME, AWAY |
| Standings entries | 36 per view; the same 36 teams, not 108 distinct teams |
| Kickoff range UTC | 2026-09-08T16:45:00Z through 2027-01-27T20:00:00Z |
| Missing kickoff / home ID / away ID | 0 / 0 / 0 |
| Null group | 144 fixtures |
| Fixture lastUpdated min and max | Both 2026-11-01T00:20:33Z |
| score.duration | REGULAR, all 144 |
| fullTime pairs | 54 both-integer pairs; 90 both-null pairs |
| regularTime / extraTime / penalties | Each absent in all 144 fixtures |
| Unsupported fixtures / unverified statuses | 0 / none |
| Recognized body pagination fields; Link/ETag headers | Not observed |
| Root revision/version/snapshotId evidence | Not observed; no provider-wide revision verified |

The published `IdentityRegistry` was populated only in memory from the reviewed
response IDs under internal namespace `football-data-org`. All fixture-to-season,
ordered home/away and membership bindings passed `validate_bound_snapshot` and
the published registry policy. Independent reverse-order allocation produced the
same canonical registry bytes. Closing-read bindings matched the original registry;
**identity conflicts: 0**. Existing StatsBomb IDs were not read or reassigned.

The resulting **192 identity records** are one provider, competition, season and
stage, eight rounds, 36 participants and 144 fixtures, plus 36 membership edges.
Stage binding uses the observed `LEAGUE_STAGE` code. Scoped round keys
`matchday:1` through `matchday:8` are explicit derivations of the observed matchday
field, not a claim that the API returned separate globally authoritative round IDs.
There is no fuzzy name/date matching or persistent adoption of this registry.

The schedule DQ passed eight matches/team, four home/four away, round participation
and opponent uniqueness for the observed league phase. This does **not** prove
full UCL-season coverage: qualification, knockouts, historical changes, deleted
records and provider-hidden omissions were not independently inventoried. Identity
stability is evidenced only across these two fixture responses about three seconds
apart, not across the season or arbitrary future corrections.

### Standings and published DQ

For **both** F/S read sets, independent recalculation from FINISHED fixtures matched
every team's played, won/drawn/lost, goals for/against, goal difference and points:

| View | Rows per read | Team-set equality | Mismatched rows / fields, either read |
| --- | --- | --- | --- |
| TOTAL | 36 | PASS | 0 / 0 |
| HOME | 36 | PASS | 0 / 0 |
| AWAY | 36 | PASS | 0 / 0 |

That is 864 field comparisons per read set, 1728 across the two sets. TIMED fixtures
were not counted as played. No provider counters, results or positions were repaired.

The published mapper/window returned **7 PASS and 2 SKIP checks**, with no FAIL:
supported mapping, rules coverage, schedule structure, TOTAL counters, observed
zero adjustments, HOME counters and AWAY counters passed. Official UEFA tie-breaker
ordering and independent points-adjustment authority remained **SKIP**, not PASS.
Agreement with `3 * wins + draws` is not independent verification that no official
disciplinary or administrative adjustment exists.

### Fences, local versions and replay

The actual response tuple, without reordering or fabricated observations, was
passed to published `prepare_registered_window`, which invokes published
`verify_observed_window`. The three matching content fences were:

| Resource pair | Equal content fingerprint SHA-256 |
| --- | --- |
| M1 / M2 | `d783ad10a3efdb504963420ddf7aad54f56b08476da41aa233eaba6b5f459954` |
| F1 / F2 | `411b6d5bd733794cca0b4d42d46224f7b7663e0a429e479c1db80004b2952bbc` |
| S1 / S2 | `80af2dba78996c915da057f3ed62831d58243ca9b8964e7ef841280d6cc5da5f` |

Each pair also had equal raw-byte SHA-256. Digests are evidence fingerprints,
**not authoritative provider revisions**:

- Raw M: `7d091a7e1671fa88987bb687fb73018ced9f2bfdb9fe67393f8f980ae007892f`.
- Raw F: `fd62a68c83952a0f6e244adfeb7869653f3fe30ba90a7ad353430948c4dcd575`.
- Raw S: `5c8d2b5592709160be68a8fad05f068a428e4cf5d3253cc9d05a81a7b8e04506`.
- Registry: `65efc0b53ff7c3f36e08c4ae98220b828f3d6949573047e83d486f4a7535d745`.
- Window semantic digest: `7c7a71ef66ee2e075a468407e173fdd5708b1f7fc52455d245fea3017b9ceed7`.
- Local proposal semantic digest: `3a05492ed50b359917d186c3a8446bd0cafda6e2e3d7b7eae8e93b5f7cf83e59`.
- Proposed ledger: `bc87bf58c9b529503ffde12dc194fe8a6ab9996a2043b8c201bd6f54b66d031e`.

The ephemeral proposal allocated **148 initial local content versions, all 1**:
144 fixture streams, season metadata and three standings streams. Replaying the
same six real responses at the same recorded observation times through the same
published registry policy created **zero new versions**, retained identical ledger
bytes and semantic digest, and left the input registry unchanged. These are locally
observed versions, never vendor revision counters.

Between fixture reads, kickoff, status, score and lastUpdated changes were all
zero. **Real correction behavior was NOT_OBSERVED**; synthetic correction tests do
not become real correction evidence. Equal reads cannot reveal invisible/ABA
updates or establish provider-wide transactionality.

The returned proposal remained an in-memory, partial league-phase analysis object;
it was not written, adopted into a persistent registry or published. Its gates were:

- `consistency=OBSERVED_WINDOW_STABLE_NOT_ATOMIC` (**NOT_ATOMIC**).
- `source_revision=None`.
- `publish_authorized=False`.

### Retry checks, restrictions and next step

No payload schema mismatch requiring a source-code change was found in the
observed REGULAR/TIMED/FINISHED league-phase scope. Other phases and unsupported
status/score semantics remain unverified, not implicitly supported.

- Windows Python 3.12.10: **174 provider + 62 football-data tests PASS**.
- Disposable fenced runner: **14 synthetic tests PASS**, including attempt cap,
  auth/redirect stop, TLS/timeout safety, changed fences, missing views, bounded
  window, arithmetic failure, deterministic real-shaped replay and masked paste.
- Python 3.12.14: **50 CI/security contracts PASS**.
- Repository/security checks, Ruff and compileall: **PASS**.
- No extra HTTP requests were used for tests or evidence inspection.

The previous failed session remains separate: it reserved one attempt and had no
confirmed completed send. This retry used exactly its separately authorized six
attempts, not seven under a single budget. No live ingestion, database/S3 writes,
production update, backup/key/Bitwarden operation, staging, commit or push occurred.
Published provider source contracts and HEAD remain unchanged. Only this non-secret
report is modified in the project; temporary runner/tests/aggregate-only evidence
remain outside Git.

Next minimal step: independent review/publication readiness of this evidence,
then an explicitly authorized offline persistence/adoption design for registry and
ledger. Persistent storage, caching/backup rights and public API redistribution
still require licensing review and separate implementation approval. Do not start
onboarding or frontend Current Competitions from this result.

## Historical Stage 9C.3-D: previous BLOCKED probe

Checked: 2026-11-01 (UTC). Branch `master`, published source HEAD:
`29c057ee165eaf89d334c143eb1e0761d31b103b`.

**Result: BLOCKED — TLS_FAILURE.** No real-response reconciliation was possible.
The single-use probe was not retried. No persistent onboarding was performed.

| Gate | Result |
| --- | --- |
| Real read-only identity reconciliation | BLOCKED — no authenticated response |
| Real standings reconciliation | BLOCKED — no authenticated response |
| Full observed-window verification | BLOCKED — transport failure and insufficient request sequence |
| Persistent onboarding | BLOCKED / LEGAL_REVIEW_REQUIRED |
| Stage 8C | PARTIAL |

### Published-source preflight

Local HEAD and cached `origin/master` matched the exact published SHA. The tracked
working tree and staging were clean. The unrelated untracked shortcut was left
untouched. No Git fetch, commit, push, reset, merge or rebase was performed.

The public GitHub Actions API confirmed SUCCESS for the same SHA:

- [CI fast](https://github.com/Romanweiss/football-data-platform/actions/runs/41331429499).
- [CI integration](https://github.com/Romanweiss/football-data-platform/actions/runs/41331429500).

The existing [mapper](../src/providers/football_data.py),
[registry](../src/providers/identity_registry.py),
[version ledger](../src/providers/observed_versions.py),
[registry policy](../src/providers/registry_policy.py),
[observed-window contract](../src/providers/observed_window.py) and
[reconciliation](../src/providers/reconciliation.py) were inspected without source
changes. Internal namespace `football-data-org` is the published identifier for
the vendor football-data.org; the domain spelling is not a new registry namespace.

### Exact provider budget and transport evidence

Authorization was for **at most six HTTPS GET exchanges**, in this exact order:

1. `https://api.football-data.org/v4/competitions/2001`
2. `https://api.football-data.org/v4/competitions/2001/matches?season=2026`
3. `https://api.football-data.org/v4/competitions/2001/standings?season=2026`
4. Repeat competition metadata.
5. Repeat season fixtures/results.
6. Repeat season standings.

No unauthenticated discovery request was made to this provider. Public GitHub CI
metadata lookups are separate from this football-data.org budget.

| Measurement | Actual observation |
| --- | --- |
| First attempt started UTC | `2026-11-01T18:36:32.847751Z` |
| Resource attempted | Competition metadata, endpoint 1 above |
| Conservatively reserved attempts | **1 / 6** |
| Confirmed completed GET sends | **0** |
| HTTP responses/statuses received | **0 / none**; HTTP status is unknown, not 401/403 |
| Safe diagnostic | `TLS_FAILURE`, exception class `SSLEOFError` |
| Requests 2–6 | NOT EXECUTED |
| Automatic redirects/retries | Disabled; no retry performed |

The counter reserves an attempt before transport setup, and marks a completed
send only after `HTTPSConnection.request` returns. That call failed with an SSL
EOF. Thus there is no confirmed successful GET send or response; this is not a
wire-level proof of zero bytes leaving the computer. The attempt remains charged
conservatively. The unused budget is not permission to repair/retry automatically.
There are no response bytes, response fingerprints or completed observation windows.

The operator entered their API token into a masked Tk field. Explicit Paste,
Ctrl+V (including a Russian keyboard layout), Shift+Insert and right-click paste
were provided. Clipboard insertion occurs only on operator action; the assistant
did not inspect the clipboard. This process did not write the token or raw bodies
to disk, arguments, logs, Git or reports. The operator closed the probe window;
the process exited. The application does not clear unrelated clipboard contents
or claim secure erasure of Python/Tk memory, clipboard history or the OS pagefile.

Transport used the existing local Windows HTTPS proxy through an HTTP CONNECT
tunnel, with the API host as the TLS peer. TLS verification and hostname checks
remained enabled. No DNS, proxy, trust-store or Git configuration was changed.
No insecure TLS fallback or alternate mirror was attempted. The available evidence
does not establish whether the EOF originated in the proxy, tunnel path or remote
TLS peer; it is not evidence of an invalid token or a mapper defect.

### Real-data results: not observed

| Required measurement | Result for this probe |
| --- | --- |
| Competition 2001 / season 2557 | Requested scope only; not LIVE_VERIFIED |
| Fixture/result count; FINISHED/TIMED/SCHEDULED/live counts | UNKNOWN |
| Stage values; kickoff range | UNKNOWN |
| Participant count; TOTAL/HOME/AWAY entry counts | UNKNOWN |
| Duplicate fixtures and fixture/team identity conflicts | NOT TESTED ON REAL RESPONSES |
| Deterministic real identity allocation and replay | NOT TESTED ON REAL RESPONSES |
| Per-team played/W/D/L/GF/GA/GD/points reconciliation | NOT TESTED ON REAL RESPONSES |
| Cross-observation fingerprints/stability | NOT TESTED |
| Real kickoff/status/score/table corrections | NOT OBSERVED |
| Coverage completeness/gaps | UNKNOWN; no current coverage claim |

Historical counts from the [previous provider probe](stage9c2-provider-evaluation.md)
are not substituted for current observations. No real registry state or local
content version was allocated from provider responses in this run. No COMPLETE
or publishable Snapshot or RegistryProposal was produced. Official UEFA ranks,
tie-breakers, adjustments and long-term identity continuity remain unverified.

### Consistency classification and remaining gates

The authorized order is `metadata -> fixtures -> standings` twice. It is **not**
the published `metadata -> fixtures -> standings -> fixtures -> standings -> metadata`
sequence, nor two independently fenced windows. Do not reorder or duplicate
observations to make that protocol appear satisfied.

- Classification: **NOT_ATOMIC**.
- `source_revision=None`.
- `publish_authorized=False`.
- Per-response real schema validation: BLOCKED by missing response.
- Cross-resource real reconciliation: BLOCKED by missing responses.
- Cross-observation real stability: BLOCKED by missing observations.
- Full bounded observed-window verification: BLOCKED even if the requested six
  responses were stable; a separately authorized correctly ordered budget is needed.

No persistence, public display, redistribution, backups or production onboarding
rights follow from technical API access. The existing licensing findings remain
unchanged: **BLOCKED / LEGAL_REVIEW_REQUIRED**.

### Offline checks and stop boundary

| Local check | Result |
| --- | --- |
| Windows CPython 3.12.10 provider foundation | 174 provider + 62 football-data tests PASS (236 total) |
| Disposable probe synthetic tests | 10 PASS, no provider network access |
| Python 3.12.14 CI/security contracts | 50 PASS |
| Repository/security checker | PASS |
| Ruff/provider compileall and disposable-probe correctness lint | PASS |

Synthetic checks cover the strict six-GET cap, stop on 401/403/429 and 3xx without
retry, response size/encoding limits, TLS/timeout/DNS safe diagnostics, unchanged
fixture identities, uncorrected arithmetic failures, deterministic replay, and
rejection of the actual six-read order by the full-window gate. Paste binding and
masked-input behavior were also tested without inspecting the system clipboard.
These are synthetic results, not real-response validation or new remote CI.

No published source defect was established, so no provider implementation was
patched or synthetic fixture added to the repository. The next minimal step is
a separately authorized transport/TLS-readiness diagnosis followed by a new bounded
probe with fresh manual token input and explicit request budget. Do not silently
retry this session, disable TLS verification or start ingestion.

Only this non-secret document is a new project file. The disposable probe, its
synthetic tests and aggregate-only evidence are outside the repository and must
not be staged. No S3, database, production, backup/restore, recovery-key or
Bitwarden operation occurred. No commit/push or persistent onboarding is authorized.
