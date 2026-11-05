# PET-1: OpenFootball offline results adapter and DQ

> Historical PET-1 contract and evidence follow. The current source-specific v2
> contract is documented in [PET-2R](pet2r-score-semantics.md); the original-file
> acquisition and initial rejection are documented in [PET-2](pet2-openfootball-dataset-validation.md).
> In particular, the old score-key restrictions and NOT ACQUIRED statement below
> describe PET-1, not the current v2 parser or the later local acquisition.

Implementation date: **2026-11-04**. Baseline:
`012322d5d21e02ca8e945c6e14d4ef866c79391c`.

**Offline synthetic implementation only; real dataset NOT ACQUIRED.** No actual
season match count or complete coverage has been certified. football-data.org
persistent onboarding remains **BLOCKED / LEGAL_REVIEW_REQUIRED for that provider**.
Stage 8C: PARTIAL. No runtime, database, recovery material or existing local
licensing/planning document is changed by PET-1.

## 1. Boundary and public API

New modules:

- `src/providers/openfootball_manifest.py`: frozen declarative candidate manifest.
- `src/providers/openfootball.py`: pure `prepare_openfootball`, mapping contracts,
  frozen results/proposal and structured DQ diagnostics.

`prepare_openfootball(source, *, mapping, observed_at, manifest=UCL_2024_25,
registry=None, versions=None, previous=None)` accepts UTF-8 JSON **bytes**, or an
already-parsed exact `{name, matches}` dictionary containing record dictionaries.
It does not accept URLs, filenames or iterators. No transport, clock, credential,
file read/write, subprocess, source acquisition or automatic publication exists.
All inputs are validated at this boundary, including parsed dictionaries.

The result is an **inert proposal**, containing canonical Competition, Season,
Participant, Stage and Round models; source-aware `OpenFootballFixture` records;
semantic digest; observation time; local version receipts; and prospective registry
and ledger bytes. Caller-owned registry/ledger/records are never modified. There
is no database commit/apply function. `publish_authorized=False` and
`source_revision=None` remain explicit.

This is deliberately **not** a `ProviderAdapter`/`Snapshot` implementation. That
existing interface requires regulation-score semantics for FINISHED fixtures;
this source's knockout `ft` interpretation is not yet fully verified. Pretending
compatibility would corrupt meaning. Its exact-date/unknown-timezone fields also
need an honest boundary before future serving. Existing UEFA contracts are not
weakened or changed.

## 2. Declarative source manifest

`UCL_2024_25` declares:

| Field | Value / confidence |
| --- | --- |
| Dataset identifier | `openfootball-ucl-2024-25-json-v1` (project-defined) |
| Repository | `https://github.com/openfootball/football.json` |
| Immutable candidate commit | `e6744429ee395bc86f247348c6184bb08d4eb361` |
| Exact relative path | `2024-25/uefa.cl.json` |
| Source format / schema | `openfootball-json-matches` / adapter schema `1` |
| Competition mapping | project key `uefa-champions-league`, UEFA Champions League |
| Season mapping | project key `2024-25`, display `2024/25` |
| Licence | `CC0-1.0`, pinned repository `LICENSE.md` |
| Attribution | credit openfootball contributors as project provenance policy |
| Whole-file content SHA-256 | **unset (`None`) until PET-2** |
| Actual acquisition timestamp | **unset (`None`) until PET-2** |
| Coverage | **UNKNOWN** |
| Fixtures/results capability | **DECLARED**, not whole-file VERIFIED |
| Other capabilities | unavailable in this adapter, including standings, events, xG |

Commit/path/licence references come from the existing local research document
`docs/stage9c5-open-datasets.md`, not a new download. The research
inspected repository metadata and a 4096-byte prefix, not the complete file.
[Pinned licence](https://github.com/openfootball/football.json/blob/e6744429ee395bc86f247348c6184bb08d4eb361/LICENSE.md).
The published CC0 grant is the selected basis for covered data reuse; it is not a
warranty of all upstream rights, logos, trademarks or endorsement. Credit is a
project requirement, not misrepresented as a CC0 attribution condition. Carry
licence/provenance forward; do not import club badges or provider-private data.

Manifest validation allows only the reviewed repository/path/competition/season
shape. A later commit may be supplied explicitly with its matching pinned licence
reference; it is provenance for this file, **not a global provider revision or a
monotonic sequence**, and not evidence about any other provider. No code fetches
or verifies a Git commit. PET-2 must establish the authenticity of the acquisition.

If a future manifest sets `content_sha256` and `acquired_at`, both must be present;
the adapter then requires exact matching original bytes and UTC acquisition time
not later than observation. Parsed dictionaries cannot prove a source byte hash.
`input_sha256` hashes the caller's supplied bytes (including synthetic bytes);
it never silently fills the manifest's acquisition fields.

## 3. Actual supported source fields and semantics

| Source field | Boundary result / rules |
| --- | --- |
| Root `name` | exact equality with explicitly reviewed mapping; not fuzzy tournament discovery |
| Root `matches` | non-empty bounded array; every row validated, no dropped records |
| `team1`, `team2` | exact reviewed name-to-project-key bindings, then canonical IDs; home/away preserved |
| `round` | exact reviewed RoundBinding, with explicit stage kind/key, round key/order; raw string retained |
| `date` | strict real calendar `YYYY-MM-DD`, within reviewed bounds in 2024–2025; retained as date string |
| Optional `time` | strict `HH:MM`, retained as **source local time of unknown timezone** |
| Optional `score.ft` | two integers 0–100 (no bool/float), retained as `source_ft` |
| Optional `score.ht` | pair, retained as `source_ht`; componentwise must not exceed ft |

Only `ft` is required inside a present score object. Explicit null is rejected,
not treated like an absent optional field. `ht` without ft, new score layouts,
extra-time or penalty keys require a reviewed contract extension, not guessing.
Unknown fields at root/row/score level are rejected with `UNKNOWN_FIELD`.

`ft` present derives `FINISHED` **in the limited sense of a source result record**;
it does not imply a certified 90-minute result, winner, tie outcome or shootout
decomposition. A future-dated finished record relative to UTC observation date
is rejected. No ft means `UNKNOWN`, not automatically SCHEDULED or POSTPONED.
For a separately evidenced postponement/cancellation/schedule, callers may supply
an explicit `StatusReview` for the composite fixture key with confirmed review
reference. This is operator evidence, not a fictional upstream status field.
Unused/duplicate reviews or scored fixtures with such reviews fail closed.
The non-secret review reference is retained as `status_review_reference`.

`kickoff_utc=None`, `regulation_score=None`: never convert local times to UTC or
invent midnight. No events, players, lineups, possession, shots, xG, aggregate
ties, standings or tiebreaks are manufactured. FT draws are valid in league,
group and knockout rows; a knockout draw alone says nothing about tie progression.

## 4. Identity and review rules

Use the published `IdentityRegistry` under provider namespace **openfootball**.
Its `uefa:<kind>:<sha256>` allocation includes provider namespace and scope, so
IDs do not collide with StatsBomb or football-data.org. Competition/season/project
team keys are explicit and not borrowed numeric identifiers. Mapping evidence
must be `IdentityEvidence(confirmed=True, reference=...)`; this is an operator
attestation, not library proof that external research happened.

Source lacks stable IDs in the inspected shape. Teams therefore require a
reviewed, exact name-to-project-key table. An explicit alias may retain a team
key; no case folding, transliteration, trimming or fuzzy matching occurs. Keys
are source-local until separately reconciled, not automatic global club IDs.

Fixture external key is `composite:` + SHA-256 of a domain-separated canonical
document containing dataset ID, mapped stage/round keys, source date and ordered
home/away project team keys. **No score, observation time, row index, Git commit
or kickoff local time** enters that key. Registry canonicalization then applies
its existing provider-scoped rules. Source round strings remain separately stored.

Limitations are intentional:

- Reordering input records or correcting scores/local time retains identity.
- Date, mapped round or participant changes can change the composite key. They
  are **not** asserted stable across corrections. When a season already has
  registered fixtures, its complete fixture-key set must match: otherwise
  `IDENTITY_REVIEW_REQUIRED`, even when a caller omits `previous`.
- An unchanged external key with changed home/away binding conflicts in the
  existing registry. There is no silent reassignment.
- Genuine additions/deletions/rescheduling need an explicit future reconciliation
  decision; PET-1 has no automatic merger/rekey/override path. Do not empty a
  registry to bypass that review.
- Without prior state, no algorithm can detect an unseen earlier source edit.
  Deterministic composite IDs alone are not proof of cross-release stability.

## 5. Replay and transactional validation

Reuse `VersionLedger`/`StreamRef`/`VersionReceipt`, not a second version engine.
Fixture semantic fingerprints include source-aware football content but exclude
the local revision number and review reference (provenance, not football content).
Metadata has a separate season stream. Dataset
fingerprints exclude observation/acquisition times, original byte formatting,
input order and candidate Git commit. Registry/ledger serialization is deterministic.

Replay identical content keeps local content versions; last-observed time may
advance. A score/time/status correction allocates the next local version. Known
reversions require explicit review via existing ledger policy. Older observations
and changed content at the same timestamp fail. Removing a finished score also
requires review; it cannot silently downgrade to unknown. No commit is used as a
provider clock/counter. Source observation time is **not match time**.

Continue a serial proposal with `IdentityRegistry.from_bytes(result.registry_after_state)`
and `VersionLedger.from_bytes(result.ledger_after_state)`, passing `previous=result`.
Existing content streams require that previous proposal to match the input states;
stale/missing state or prior fixture content inconsistent with its ledger fails.
This is an in-memory, single-writer contract, not
persistent/concurrent onboarding. If snapshots cross a trust boundary, restoring
them requires an **independently trusted fingerprint**, using the published
`expected_fingerprint` parameter. A caller-supplied hash of untrusted bytes is not
authentication. No pickle, eval or arbitrary code loader is used.

All processing occurs on cloned registry/ledger states. Any invalid row, registry
collision, late version conflict or state-size failure rejects the **entire**
proposal. Earlier valid rows are not applied. No source input is mutated.

## 6. Fail-closed DQ and limits

Limits: **1 MiB original JSON bytes, 512 match rows, 128 team aliases, 128 round
bindings, 160 characters per text value**, plus published registry/ledger byte,
record, stream and history limits. Parsed inputs have the same narrow structure
and per-field/row bounds; arbitrary nested values never enter normalized output.
JSON rejects duplicate keys, non-finite constants, malformed Unicode/encoding and
unsupported shapes. Empty datasets are not accepted as evidence of coverage.

`OpenFootballError.diagnostic` is a frozen `{code, row}` object, with optional
zero-based row index. Messages contain only `openfootball:<CODE>`, not raw teams,
records, URLs, credentials or internal exceptions. First error rejects the batch;
this is not an exhaustive report of every bad row.

Important codes: `SCHEMA`, `REQUIRED`, `UNKNOWN_FIELD`, `NULL`, `LIMIT`, `DATE`,
`TIME`, `SCORE`, `DUPLICATE`, `SELF_MATCH`, `UNKNOWN_TEAM`, `ROUND`, `SCOPE`,
`COVERAGE`, `SCORE_STATUS`, `CONTENT_MISMATCH`, `IDENTITY_REVIEW_REQUIRED`,
`REVIEW_REQUIRED`, `UTC`, `OUT_OF_ORDER`, `VERSION_CONFLICT`,
`REVERSION_REQUIRES_REVIEW`.

Coverage remains UNKNOWN even when a reviewed `expected_rows` check passes:
that verifies the supplied file's count, not every match of the competition.
Membership fences additionally reject record deletion/addition during replay.

## 7. Synthetic verification and existing CI

`tests/test_openfootball.py` uses only artificial teams/results. It exercises
league/group/knockout, draw, missing time, reviewed postponement, strict schemas,
date/score/status conflicts, duplicates, aliases, namespace/participant collisions,
semantic replay, corrections, ordering, reversion, out-of-order observations,
content digests and transactional failure. No production key/data is used.
`tests/ci/test_openfootball.py` checks the complete source set, secret signatures,
offline imports and discovery by the existing Python 3.10.12/3.12.14 CI matrix.
No new workflow, dependency or framework is introduced.

Commands (existing CI environment):

```powershell
python ci/run_unittest.py discover -s tests -p test_openfootball.py
python ci/run_unittest.py discover -s tests -p 'test_*.py'
python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python ci/check_repository.py
ruff check --no-cache src/providers/openfootball.py src/providers/openfootball_manifest.py tests/test_openfootball.py tests/ci/test_openfootball.py
git diff --check
```

Actual execution totals are recorded in the PET-1 handoff report; commands above
are not claims of real-source verification. No staging/commit/push is part of PET-1.

Local verification on 2026-11-04:

| Check | Result |
| --- | --- |
| Windows CPython 3.12.10 targeted adapter suite | 34 PASS |
| Linux CPython 3.10.12 / 3.12.14 full offline suite, each | 1057 run: 1048 PASS, 9 Windows-only skips |
| Application regression, each Linux version | 61 PASS |
| CI/security/documentation contracts, each Linux version | 59 PASS |
| Ruff (repository policy; additionally all F rules for new Python files) | PASS |
| compileall of src/tests/ci, both Linux versions | PASS |
| Repository publication/private-artifact contracts | PASS |

Linux tests used existing disposable CI images, network disabled and repository
mounted read-only, with no persistent volume or running service changes. The nine
Windows-only recovery skips are **not passed tests**; Windows recovery/ACL suites
were not rerun for this provider-only change. Frontend/browser and real-source
tests were not run; no frontend or application implementation changed.

## 8. Minimal next boundary: PET-2, then separately authorized PET-3

PET-2 needs separate approval for **one pinned file**. Retrieve immutable source
bytes with existing transport guards, verify the pin/licence, compute the whole
SHA-256, record real acquisition time, profile all keys/rounds/names/score layouts,
count rows and date bounds and identify gaps. Build reviewed team/round mappings;
verify ft/knockout semantics. Unknown keys must block until reviewed, not be
silently ignored. Derive no standings until rules, complete inputs and tiebreaks
are validated. Do not assume a specific season total from tournament format.

Future pipeline boundary, **not implemented**:

`pinned OpenFootball bytes → Bronze → Spark Silver → Gold → ClickHouse → Django → React`.

Bronze should retain source bytes, hash, dataset/pin/path, actual acquisition and
licence metadata using existing mechanisms. Silver can consume the deterministic
source-aware mapping/DQ; Gold should expose only verified result capabilities.
Keep date precision and unknown timezone explicit, and source-aware FT separate
until score semantics are established. Serving/UI must distinguish licensed
historical data from synthetic demo and football-data.org API observations.
Use existing build identity/idempotency and Airflow retry contracts later, not a
parallel framework or an execution path in this adapter. PET-1 changes no Spark
job, DAG, schema, API, frontend or production environment.
