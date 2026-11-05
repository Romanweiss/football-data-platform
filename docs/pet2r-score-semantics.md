# PET-2R: source-score semantics and incomplete results

Date: **2026-11-04**, Europe/Moscow. Baseline:
`012322d5d21e02ca8e945c6e14d4ef866c79391c`.

**READY for the offline remediation contract.** Full pinned batch:
**ACCEPTED_WITH_LIMITATIONS**; **not** a certification of complete results,
regulation-time scores, standings, public serving or persistent onboarding.
Stage 8C: PARTIAL. football-data.org remains a separate
BLOCKED / LEGAL_REVIEW_REQUIRED source. No ingestion, network, database,
production, Airflow, backup or recovery operation is part of this stage.

## 1. Immutable evidence and historical rejection

Only the previously acquired **local** file was used. No repeat download,
authenticated API request or new external score reference was made.

| Attribute | Verified value |
| --- | --- |
| JSON source | `openfootball/football.json` |
| Commit | `e6744429ee395bc86f247348c6184bb08d4eb361` |
| Path | `2024-25/uefa.cl.json` |
| Bytes | 58305 |
| SHA-256, before and after processing | `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6` |
| Original acquisition, UTC | `2026-11-04T15:25:13.686750+00:00` |
| New local observation, UTC | `2026-11-04T16:31:26.203721+00:00` |
| Local evidence | `data/work/pet2-openfootball/<commit>/pet2r-verification.json` (ignored) |

The source, acquisition receipt, materialized manifest, mapping and original
profile are unchanged. CC0/provenance and separate upstream Football.TXT reference
are inherited from the [PET-2 audit](pet2-openfootball-dataset-validation.md).
That report's initial all-or-nothing rejection is preserved, with a dated update
link; it is not rewritten as a historical success. Existing PET-1 runbook describes
the initial implementation; this document specifies its explicit PET-2R extension.

## 2. Minimal source-specific contract extension

Changes are limited to `src/providers/openfootball.py` and associated tests/docs.
No existing StatsBomb, canonical `Fixture`/`Score`, UEFA collection/registry
policy, API or React contract is modified. This is still **not** a canonical
Snapshot or a generic provider query engine.

Frozen fixture fields:

| Field | Meaning |
| --- | --- |
| `source_ht` | original typed half-time pair, or None |
| `source_ft` | original typed reported FT pair, or None; **not automatically 90 minutes** |
| `source_et` | original typed et pair, or None; inclusive vs incremental meaning unverified |
| `source_p` | original typed p pair, or None; **not a certified penalty-shootout score** |
| `source_score_state` | ABSENT / EMPTY / COMPONENTS, preserving the distinction |
| `result_availability` | REPORTED only when a source ft pair exists; otherwise MISSING |
| `score_quality` | REPORTED_FULL_TIME_UNKNOWN_PERIOD / AMBIGUOUS_SOURCE_COMPONENTS / MISSING_RESULT |
| `regulation_score=None` | no confirmed 90-minute pair |
| `after_extra_time_score=None` | no canonical final-after-ET pair inferred from source_et |
| `penalty_shootout_score=None` | no canonical shootout pair inferred from source_p |
| `winner_id=None` | no inferred match/tie winner, including unequal p |
| `standings_eligible=False` | not an authorized standings input |
| `points_home`, `points_away` | None, never fabricated points |

All present component pairs must be two exact integers 0–100: bools, floats,
negative values, strings, nulls and malformed pairs are rejected. Only the
observed optional keys ht/ft/et/p are supported; arbitrary unknown details remain
FATAL. New optional support is bounded and typed, not a catch-all raw payload.
HT cannot exceed FT componentwise when both are present. No relation between et
and FT is asserted because incremental/inclusive semantics are unknown.

An absent score, `{}`, or partial components without ft retain the fixture with
`status=UNKNOWN`, missing full result and explicit DQ. They do **not** become 0–0,
FINISHED, a draw, zero points or a zero-played standings row. Actual `ft=[0,0]`
remains a reported pair. With ft present, FINISHED retains the original narrow
adapter meaning of a source result record (`status_origin=source_ft_present`),
not external proof of period semantics/tie progression. Explicit reviewed
postponement/schedule evidence remains separate; a scored fixture conflicting
with a non-finished status review is still FATAL.

Raw `p=[4,4]` is safely representable **as an unverified source component**, not
as a valid final shootout. It receives both penalty-semantics and tied-pair
limitations. Even `p=[1,4]` does not grant winner inference without independently
confirmed semantics. No external facts, including the missing final score from
PET-2 reference checks, are substituted into source bytes or normalized records.

## 3. FATAL vs NON_FATAL DQ

Fatal failures raise `OpenFootballError` with a frozen diagnostic containing only
safe code, optional row index and `severity=FATAL`. First failure still rejects
the **whole** batch, with no returned proposal and no registry/ledger mutation.
FATAL includes corrupt schema/unknown fields, invalid identity/scope, duplicates,
self-match, impossible numeric scores, HT > FT, future finished records,
status/score conflicts, stale state, version conflict and unauthorized reversion.
No old fatal check was globally disabled.

An accepted proposal contains a frozen `DQReport(fatal_count=0, limitations=...)`.
Each limitation has a safe code, canonical fixture ID and `severity=NON_FATAL`.
This is distinct from an invalid source row: none is silently discarded. Returned
`dq.counts` is a copy. Warning order is deterministic by canonical fixture order
and code, not source row position, so reordering does not perturb replay.

Measured limitations for this file:

| Code | Count | Interpretation |
| --- | ---: | --- |
| KICKOFF_UTC_UNKNOWN | 189 | source local times do not establish a UTC kickoff |
| REGULATION_SCORE_UNKNOWN | 188 | a source FT pair is not a confirmed 90-minute score |
| HALF_TIME_SCORE_MISSING | 10 | optional HT pair absent; do not synthesize it |
| EXTRA_TIME_SEMANTICS_UNKNOWN | 2 | preserve et without assigning inclusive/incremental semantics |
| PENALTY_SEMANTICS_UNKNOWN | 2 | preserve p without assuming a valid shootout score |
| TIED_PENALTY_PAIR | 2 | p=[4,4] cannot establish the shootout winner |
| RESULT_MISSING | 1 | empty final score; fixture retained with UNKNOWN result |
| **Total limitations** | **394** | multiple independent limitations may refer to one fixture |

`SCORE_COMPONENTS_WITHOUT_FT` additionally covers safe partial score objects in
synthetic tests; zero occur in this pinned file. Limitations deliberately do not
vanish to produce a cosmetic green report. An accepted batch can be incomplete.

## 4. Full local batch and identity reconciliation

| Check | Result |
| --- | --- |
| Discovered / accepted fixtures | **189 / 189**, zero dropped |
| Teams / unique fixture IDs | **36 / 189** |
| Exact PET-2 identity bindings retained | **189/189**, identity-only state fingerprint matches |
| Source FT pairs present | **188** |
| Reported FT pairs without explicit et/p | **186**, source-level scores only, not externally certified |
| Explicit ambiguous et/p fixtures | **2** |
| Unknown result | **1**, final remains UNKNOWN / no FT pair |
| Confirmed regulation / canonical ET / canonical penalties | **0 / 0 / 0** |
| Inferred winners / points | **0 / 0** |
| Fatal DQ | **0** |
| Non-fatal limitations | **394** |
| Batch status | **ACCEPTED_WITH_LIMITATIONS** |
| Fixture coverage | **UNKNOWN**, not fully externally reconciled |
| Result coverage | **INCOMPLETE** |
| Publication authorization | **False** |

The 186 count is the useful reported-score-only partition, **not a claim of
verified actual results or 90-minute scores**. FT period semantics remain unknown
for all 188 scored fixtures, not just the two explicitly marked et/p records.
The two unmarked after-extra-time examples identified in PET-2 remain part of
that unknown-period population. No hidden external correction overlay is used.
League/knockout counts remain the measured 144/45 from PET-2. Qualifiers,
standings/tiebreak correctness and complete tournament coverage are not asserted.

## 5. Determinism, version boundary and transaction safety

Fixture identity allocation is unchanged: source namespace and dataset/scoped
round/date/ordered participant composite, **never score content**. Reconstructed
identity-only registry fingerprint, matching PET-2 exactly:

`3a6aeadfa9e2cd85628626eba080101671f1ae27844cf75790b2b9747c061ccf`.

Normalized result contract is now **schema_version=2**, with fingerprint domains
`openfootball-results-semantic-v2`, `openfootball-metadata-v2` and
`openfootball-dataset-semantic-v2`, and season format `openfootball-results-v2`.
This is not a change to the original JSON format/manifest schema 1. Old normalized
semantic digests are **not** silently reinterpreted as v2 digests. Legacy proposal
replay requires explicit review. There was no accepted real PET-1/PET-2 batch or
production normalized state to migrate. Existing canonical provider domains are
untouched.

Source-specific fields/state/quality now participate in the v2 fixture semantic
fingerprint. Score/ET/p corrections keep fixture identity and allocate the next
local version. ABSENT → EMPTY is an observable source-state change, not a new
fixture. Review-reference-only refresh remains provenance, not football content.
Known reversion, out-of-order observation and conflicting same-time content retain
the published ledger's fail-closed policy. A finished score cannot be silently
removed; such correction still requires review. Input objects are not modified.

Full accepted semantic fingerprint:

`2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b`.

Fresh same-byte replay returned the same fixtures, DQ and semantic fingerprint,
**zero new local versions**, unchanged registry and unchanged version histories;
last-observed timestamps may advance. A reversed **derived parsed document**
also produced the same semantic fingerprint, identities and DQ. That derived
document is not represented as the original acquisition-hash-verified bytes.
Both original-byte runs checked the pinned whole-file SHA-256. All mutable caller
registry/ledger inputs remained unchanged; prospective states are inert in-memory
proposal bytes, not applied/persisted normalized state. Late failure after an
earlier successful cloned ledger observation is regression-tested.

## 6. Future Bronze → Silver → Gold → ClickHouse boundary

No pipeline is implemented or executed here. Future authorized work must retain:

- Bronze: original immutable bytes, hash, pin/path, acquisition and licence.
- Silver: all 189 identities, all nullable raw score components, source_score_state,
  result_availability, score_quality, precision, per-fixture DQ and provenance.
- Gold/serving: explicit coverage/capability/quality metadata and UNKNOWN results;
  no coercion into canonical 90-minute scores, zeroes, winners or points.
- Idempotency: the same accepted v2 semantic content maps to the same build
  identity/content inputs, subject to existing build contracts, not observation
  clock or a falsely global Git revision.

Capabilities are copied from the validated manifest into the proposal:
fixtures/results remain DECLARED; standings/event/player/xG capabilities remain
UNAVAILABLE. The existing strict canonical Snapshot validation rejects this
source-specific proposal; there is no implicit pass-through into UEFA standings.
All fixtures have `standings_eligible=False` and no points. Even the 186 ordinary
reported scores are not an authorization to compute standings. Standings would
need a separate verified score-semantic/coverage/competition-rules contract and
explicit exclusion/error policy for unknown results; do not create a reduced
table that silently treats missing matches as draws or unplayed fixtures.

An immutable local Git file is not an atomic live multi-provider snapshot.
Existing UEFA **NOT_ATOMIC** policy is untouched, `source_revision=None` and
`publish_authorized=False`. Nothing is persisted to S3, Spark or ClickHouse.

## 7. Verification and PET-3 entry gates

All CI tests remain synthetic/offline; the ignored acquired file and local
verification helper are not CI dependencies. Earlier score-edge tests were
updated to assert safe explicit representation rather than the superseded
UNKNOWN_FIELD/REQUIRED rejection. Fatal malformed-value/schema/identity and
transactional checks remain, with additional regression coverage. No skipped or
disabled test replaces a failing assertion.

Executed verification on 2026-11-04:

| Check | Result |
| --- | --- |
| Windows CPython 3.12.10 OpenFootball tests | 54 PASS |
| Linux CPython 3.10.12 / 3.12.14 full offline suite, each | 1077 run: 1068 PASS, 9 Windows-only skips |
| Application regression, each Linux version | 61 PASS |
| CI/security/documentation contracts, each Linux version | 60 PASS |
| Ruff repository policy and full F checks for changed Python | PASS |
| compileall of src/tests/ci and local verification helper, both Linux versions | PASS |
| Repository/publication and explicit changed-file secret-signature checks | PASS |

Linux suites used the existing disposable CI test images, network disabled and
repository read-only; no Docker configuration, images, application services or
persistent volumes were modified. The nine Windows-only skips are **not passes**.
Windows recovery/ACL, frontend/browser and live database tests were not rerun;
none of their implementations changed. No test depends on the local acquired
JSON, mapping or ignored verification helper. The original two-file staging tree
remains `317393e115d581d40ba7a5d7efd34fe9edc95aa0`.

PET-3 can be **proposed for an explicitly scoped historical fixtures/source-result
pipeline**, not silently begun, only when:

1. The approved v2 code/docs/tests are included in a reviewed reproducible Git
   snapshot; current publication and staging remain separately controlled.
2. The operator explicitly accepts INCOMPLETE results / unknown periods / the
   394 limitations, and source-only capabilities, not full-season analytics.
3. The ingestion design preserves all rows, raw bytes and typed components, DQ,
   licence/provenance, no-overwrite/source hashes and existing build/idempotency
   contracts; missing final and ambiguous p remain visible.
4. Gold/API/UI must not compute standings, infer winners/points, mark UNKNOWN
   results FINISHED or label source FT as 90-minute scores. These require their
   own verified semantics/rules and authorization later.
5. There is a separate explicit authorization for real Bronze/Silver/Gold writes.

Full verified-results/standings onboarding remains **BLOCKED** pending those
semantic/completeness decisions. Do not re-download or overwrite the pinned file
to hide defects. No commit/push, staging or PET-3 execution is authorized here.

## 8. PET-2S: published reproduction recipe

Publication review found that the local exact mapping was only in ignored
evidence. This declarative recipe closes that gap without publishing the raw
dataset, acquisition artifacts or temporary scripts. It specifies the inputs
needed to reconstruct the accepted v2 fingerprint from **separately acquired,
hash-verified original bytes** and the public adapter API. CI remains synthetic;
this section neither downloads nor authorizes another acquisition/ingestion.

<!-- pet2s-mapping-recipe -->
```json
{
  "recipe_version": 1,
  "repository": "https://github.com/openfootball/football.json",
  "commit": "e6744429ee395bc86f247348c6184bb08d4eb361",
  "path": "2024-25/uefa.cl.json",
  "content_sha256": "12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6",
  "source_name": "UEFA Champions League 2024/25",
  "acquired_at": "2026-11-04T15:25:13.686750+00:00",
  "observed_at": "2026-11-04T16:31:26.203721+00:00",
  "date_start": "2024-09-17",
  "date_end": "2025-05-31",
  "expected_rows": 189,
  "expected_teams": 36,
  "evidence_reference": "pet2-pinned-name-round-review-v1",
  "team_key_prefix": "name-v1-",
  "round_columns": ["source_round", "stage_key", "stage_name", "kind", "round_key", "order"],
  "rounds": [
    ["League, Matchday 1", "league", "League phase", "league_phase", "md1", 1],
    ["League, Matchday 2", "league", "League phase", "league_phase", "md2", 2],
    ["League, Matchday 3", "league", "League phase", "league_phase", "md3", 3],
    ["League, Matchday 4", "league", "League phase", "league_phase", "md4", 4],
    ["League, Matchday 5", "league", "League phase", "league_phase", "md5", 5],
    ["League, Matchday 6", "league", "League phase", "league_phase", "md6", 6],
    ["League, Matchday 7", "league", "League phase", "league_phase", "md7", 7],
    ["League, Matchday 8", "league", "League phase", "league_phase", "md8", 8],
    ["Playoffs, Matchday 1", "knockout-playoffs", "Knockout phase play-offs", "knockout", "leg1", 1],
    ["Playoffs, Matchday 2", "knockout-playoffs", "Knockout phase play-offs", "knockout", "leg2", 2],
    ["Finals, Round of 16", "knockout-finals", "Knockout finals", "knockout", "r16", 1],
    ["Finals, Quarterfinals", "knockout-finals", "Knockout finals", "knockout", "qf", 2],
    ["Finals, Semifinals", "knockout-finals", "Knockout finals", "knockout", "sf", 3],
    ["Finals, Final", "knockout-finals", "Knockout finals", "knockout", "final", 4]
  ],
  "expected_semantic_digest": "2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b"
}
```

Reconstruction rules, in order:

1. Check the SHA-256 of original bytes **before parsing**; reject anything not
   matching this recipe. Only this already-reviewed immutable byte set is covered
   by the evidence label. This is not automatic approval of names in future files.
2. Parse the JSON and check the exact source name, 189 rows, 36 distinct team labels
   and the exact set of the 14 round labels. Do not remove country suffixes or
   normalize names, case, spaces, accents or Unicode forms.
3. Sort the exact distinct team1/team2 labels by Python string order. For each
   label construct `TeamBinding(label, "name-v1-" + sha256(label.encode("utf-8")).hexdigest(), label)`.
   These are reviewed source-local project keys, **not** upstream/global team IDs.
4. Construct each `RoundBinding` from its row in the column order above, converting
   `kind` with `StageType(value)`. Construct `OpenFootballMapping` using the
   listed name/date bounds/expected_rows and
   `IdentityEvidence(True, "pet2-pinned-name-round-review-v1")`; status_reviews is
   the empty tuple. Do not infer tie IDs or merge the two knockout stages.
5. Use `dataclasses.replace(UCL_2024_25, content_sha256=..., acquired_at=...)`,
   parsing the UTC timestamps with `datetime.fromisoformat`. Its licence,
   capabilities, dataset/competition/season identifiers remain the public template
   values; they are also inputs to canonical identity/metadata construction.
6. Call `prepare_openfootball(original_bytes, mapping=..., observed_at=...,
   manifest=...)` with empty registry/ledger defaults. Assert the expected semantic
   digest, 189 identities, the DQ counts in section 3 and INCOMPLETE result coverage.
   Continue replay with returned prospective states and previous proposal as
   described by the public API; do not apply/persist them in this review.

The recorded historical observation is useful for exact reproduction, not a
freshness claim. A genuinely later local observation must use its actual timestamp;
it must produce the same semantic digest, while last-observed metadata may differ.
No ignored file or host-specific path is needed to construct this mapping.
