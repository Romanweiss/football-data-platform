# PET-2: pinned OpenFootball acquisition and validation

> Historical PET-2 result below is preserved. **PET-2R update, 2026-11-04:**
> [Source-score remediation](pet2r-score-semantics.md) now accepts all 189 fixture
> identities from these unchanged bytes as **ACCEPTED_WITH_LIMITATIONS**. The
> missing final result and unknown FT/ET/penalty semantics are retained, not
> corrected. This supersedes the adapter-acceptance block, **not** the original
> observations or the prohibition on automatic ingestion/standings. PET-3 still
> requires a separately approved scope and the entry gates in that document.

Audit date: **2026-11-04**, Europe/Moscow. Project baseline:
`012322d5d21e02ca8e945c6e14d4ef866c79391c`.

**Result: BLOCKED for whole-season adapter acceptance / PET-3 ingestion.**
Acquisition and profiling succeeded; the unchanged PET-1 adapter correctly
rejected the complete dataset. This is a completed validation with a negative
data-readiness result, not a failed download. No row was silently skipped and no
production persistence, Spark job, Airflow task or serving update was performed.
football-data.org persistent onboarding remains BLOCKED / LEGAL_REVIEW_REQUIRED
for that separate provider. Stage 8C remains PARTIAL.

## 1. Source correction check, pin and acquisition integrity

The PET-1 manifest already points to the **correct JSON repository**. No source
correction or relaxation of its validation was necessary. The five PET-1 files
are preserved unchanged. The upstream Football.TXT repository is recorded
separately in the local acquisition/manifest evidence; it is not used as the JSON
download origin, and no TXT dataset was acquired.

| Attribute | Observed value |
| --- | --- |
| JSON repository | `https://github.com/openfootball/football.json` |
| Immutable commit | `e6744429ee395bc86f247348c6184bb08d4eb361` |
| Exact path | `2024-25/uefa.cl.json` |
| Bytes | **58305** |
| Content SHA-256 | `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6` |
| Git blob SHA-1 | `b0fcef5633b9d359ee963b85a4c4d559082fd226` |
| Acquired at, UTC | `2026-11-04T15:25:13.686750+00:00` |
| Licence | publisher CC0-1.0, per prior licensing research and pinned licence reference |
| Separate upstream source | `https://github.com/openfootball/champions-league` (Football.TXT) |
| Exact generating TXT revision | **UNKNOWN**, `upstream_revision=null` |

[Pinned JSON file](https://github.com/openfootball/football.json/blob/e6744429ee395bc86f247348c6184bb08d4eb361/2024-25/uefa.cl.json)
and [pinned licence](https://github.com/openfootball/football.json/blob/e6744429ee395bc86f247348c6184bb08d4eb361/LICENSE.md).
Credit openfootball contributors as project provenance policy, not a fictional
CC0 attribution condition. This is not a licence grant for logos/trademarks or
an assertion of UEFA endorsement. No new commercial legal clearance is claimed.

Exactly **one dataset file** was downloaded. Acquisition made two public GETs:

1. Official GitHub recursive tree metadata for the pinned commit. The tree was
   not truncated and contained exactly the target blob/path.
2. `raw.githubusercontent.com/openfootball/football.json/<commit>/2024-25/uefa.cl.json`.

The raw bytes' Git blob hash was recomputed with the Git `blob <length>\0` header
and matched the tree entry and the previously observed blob ID. The received byte
count also matched the tree. SHA-256 was computed independently over file bytes;
it is not the blob SHA-1. Strict offline JSON parsing additionally rejected
duplicate keys/non-finite constants; the acquired document is valid JSON.

Both acquisition responses used standard TLS verification, SNI/hostname checks,
25-second socket timeout, bounded reads (2 MiB metadata / 1 MiB dataset), no
automatic redirects and no retries. No token/credential was supplied. Public
UEFA reference pages were separately consulted for tournament structure and a
small number of score-semantic spot checks; no second dataset was stored.

## 2. Local staging and manifest state

Dedicated **non-production, Git-ignored** local acquisition directory:

```text
data/work/pet2-openfootball/e6744429ee395bc86f247348c6184bb08d4eb361/
  2024-25/uefa.cl.json
  acquisition.json
  manifest.json
  mapping.json
  profile.json
```

No file above is part of the proposed source publication. Raw data was not copied
to S3/Bronze or another dataset directory. Files were written exclusively without
overwriting an existing acquisition. Local one-shot helpers reside under ignored
`.tmp/pet2-openfootball/`; they are diagnostics, not a new provider framework or CI
dependency. The acquisition helper was run **once**, not repeated after the task
continuation.

The source-code `UCL_2024_25` remains an unacquired **template**: its SHA-256 and
timestamp are still None. A validated local `replace(UCL_2024_25, ...)` instance
was materialized into `manifest.json` using the measured hash and timestamp above.
It retains source schema version 1, `coverage=UNKNOWN`, fixtures/results DECLARED
and unsupported capabilities unavailable. This does not turn a successful
download into accepted/complete football data. Separate upstream repository and
unknown generating revision are recorded as provenance fields, not invented
build lineage. No global/atomic revision for another provider is implied.

## 3. Measured schema and coverage

- Root keys: exactly `name`, `matches`; name `UEFA Champions League 2024/25`.
- **189 match records**, **36 distinct exact source team names**.
- All 189 rows have exactly `date`, `round`, `score`, `team1`, `team2`, `time`.
- **189 distinct composite fixture keys** and **189 distinct canonical fixture
  IDs** in a separate in-memory identity-only audit; no collision/conflict.
- Date range **2024-09-17 through 2025-05-31**, nondecreasing input date order.
- No missing/malformed date or time; source times: 150 at `21:00`, 38 at `18:45`,
  one at `21:15`. These are unqualified source times, **not verified UTC**.
- Zero self-matches; zero exact duplicate rows; zero date/home/away duplicate
  candidates. Zero null-field/schema problems outside the score issues below.
- No upstream team/fixture IDs, status fields, standings, timezone or revision
  fields appear. Display-name spellings/country suffixes remain source-specific;
  they are not an authoritative cross-provider identity or country registry.

Round labels are retained exactly; counts were measured before comparison with
any expected tournament structure.

| Exact source round | Records | FT present | HT present | ET / p present |
| --- | ---: | ---: | ---: | ---: |
| League, Matchday 1 | 18 | 18 | 15 | 0 / 0 |
| League, Matchday 2 | 18 | 18 | 18 | 0 / 0 |
| League, Matchday 3 | 18 | 18 | 17 | 0 / 0 |
| League, Matchday 4 | 18 | 18 | 18 | 0 / 0 |
| League, Matchday 5 | 18 | 18 | 17 | 0 / 0 |
| League, Matchday 6 | 18 | 18 | 16 | 0 / 0 |
| League, Matchday 7 | 18 | 18 | 17 | 0 / 0 |
| League, Matchday 8 | 18 | 18 | 18 | 0 / 0 |
| Playoffs, Matchday 1 | 8 | 8 | 8 | 0 / 0 |
| Playoffs, Matchday 2 | 8 | 8 | 7 | 0 / 0 |
| Finals, Round of 16 | 16 | 16 | 16 | 2 / 2 |
| Finals, Quarterfinals | 8 | 8 | 8 | 0 / 0 |
| Finals, Semifinals | 4 | 4 | 4 | 0 / 0 |
| Finals, Final | 1 | 0 | 0 | 0 / 0 |
| **Total** | **189** | **188** | **179** | **2 / 2** |

League phase: **144** rows. Each matchday includes 36 distinct teams, and each
team has four home matches, four away and eight distinct opponents. Knockout:
**45** rows, including 16 play-offs, 16 round-of-16, eight quarter-final, four
semi-final and one final fixture. Pair/reciprocal-leg checks found eight two-leg
play-off pairs, eight R16 pairs, four quarter-final pairs and two semi-final pairs;
the final has one pair/one fixture. This is a structural audit, not tie-winner
calculation.

### Independent coverage assessment

Checked on **2026-11-04**:

- [UEFA league-phase draw, Match system](https://www.uefa.com/uefachampionsleague/news/028e-1b1125f199a1-ace85e395aa8-1000--uefa-champions-league-league-phase-draw/)
  documents the 36-team/eight-matchday/144-match structure and four home/four away
  format. The observed league rows fit this independently documented structure.
- [UEFA 2024/25 results, stage headings](https://www.uefa.com/uefachampionsleague/news/0290-1bbe6365b47a-0668db2bbcb1-1000/)
  confirms the season's knockout stages and final date, and provides the spot
  checks below. No full 189-fixture external identity/date/result diff was done.

Therefore: **STRUCTURE_CONSISTENT_RESULTS_INCOMPLETE_NOT_FULLY_RECONCILED**.
All expected league matchday/knockout labels are represented, but that arithmetic
is not proof that every source result is correct or complete. Qualifying rounds
are outside this file's observed scope. No standings/tiebreak completeness,
2026/27 current-season coverage, live freshness or season-wide certified accuracy
is claimed. A missing final result explicitly disproves complete-results coverage.

## 4. Score analysis and externally detected ambiguities

Observed score object shapes:

| Keys | Rows |
| --- | ---: |
| `ft`, `ht` | 177 |
| `ft` only | 9 |
| `et`, `ft`, `ht`, `p` | 2 |
| empty object `{}` | 1 |

All score fields that are present are integer pairs within the adapter's numeric
bounds; no componentwise HT > FT contradiction was found. This does **not** prove
the semantic validity of shootouts/extra time. Every row has a score field; one
is empty. FT exists for 188 records, not 189 certified finished matches. HT is
absent in ten records (including the empty final). No missing value was filled.

Zero-based row diagnostics and limited relevant evidence:

| Row | Fixture / date | Observed source score | Finding |
| --- | --- | --- | --- |
| 169 | Liverpool vs Paris, 2025-03-11 | `ht=[0,1], ft=[0,1], et=[0,1], p=[4,4]` | `et`/`p` unsupported; tied p does not identify a shootout winner |
| 174 | Atlético vs Real Madrid, 2025-03-12 | `ht=[1,0], ft=[1,0], et=[1,0], p=[4,4]` | same unsupported/ambiguous structure |
| 188 | Paris vs Inter, 2025-05-31 | `{}` | final result missing; no substitution with zero-zero or another source |

UEFA's results page reports shootouts of 1–4 and 2–4 respectively, rather than
the source's identical p pairs, and a 5–0 final. These are reference discrepancies,
**not corrections applied to the pinned file**. Penalty winner inference is blocked.
The generating parser/meaning of p was not independently established.

There is also a subtler FT problem: the JSON records PSV–Juventus on 2025-02-19
as `ft=[3,1]`, and Inter–Barcelona on 2025-05-06 as `ft=[4,3]`, **without et**.
UEFA labels both results as after extra time. Thus presence/absence of et cannot
reliably split regulation from additional ET goals. A universal `ft → regulation`
mapping would be wrong. The two explicit et pairs also cannot safely be treated
as additional ET goals merely because of their key name. Original fields remain
unchanged; the existing canonical `Score` contract is not modified.

## 5. PET-1 adapter, identity and deterministic rejection

The real-file validation used the original full bytes and the materialized
manifest's SHA-256. Local `mapping.json` records exact inspected names and all
14 reviewed round labels. Teams use source-local project keys derived from the
exact reviewed name (`name-v1-<sha256>`); there is no claim of stable vendor IDs
or cross-provider reconciliation. Changes to those source names still need review.

Mapping: eight league rounds under LEAGUE_PHASE; two play-off rounds under a
KNOCKOUT stage; four finals rounds under another KNOCKOUT stage. No tie/leg winner
or standings values are synthesized. Unknown team/round mappings after explicit
review: **zero**. Identity-only registry checks include all 189 fixtures and
are order-invariant, but are **not an accepted results proposal**.

| Validation scope | Result |
| --- | --- |
| Full 189-row adapter batch | **REJECTED**, `UNKNOWN_FIELD`, zero-based row **169** |
| Accepted fixtures in full proposal | **0** (no proposal returned) |
| Rows not accepted due to atomic batch failure | **189** |
| Separate per-row structural diagnostics | 186 valid / 3 invalid |
| Invalid rows | 169 UNKNOWN_FIELD; 174 UNKNOWN_FIELD; 188 REQUIRED |
| Input registry/ledger after failure | byte-for-byte unchanged |
| Same original bytes, same mapping, repeated validation | identical rejection code/index |
| Full accepted semantic fingerprint | **NOT AVAILABLE**, because validation failed |
| Identity-only replay / reverse input order | same 189 canonical IDs / registry fingerprint |

The 186 figure is a diagnostic partition, **not a partial import or a guarantee
of football correctness**. Per-row checks deliberately use unacquired template
provenance because a derived single-row document cannot match the original
whole-file hash. Only the original full-byte attempt is acquisition-hash verified.
No normalized accepted subset, registry state or version ledger was persisted.
No source row was dropped to obtain a green whole-season result. Valid-content
semantic replay remains tested on synthetic inputs; a successful full real-data
semantic replay is not claimed.

## 6. Minimal synthetic reproductions and regression

Added `tests/test_openfootball_score_edges.py`, using **only artificial teams**
and existing synthetic helpers, not real JSON/downloads. Minimal score fragments
inside otherwise valid synthetic knockout rows:

```json
{"score": {"ft": [0, 1], "et": [0, 1], "p": [4, 4]}}
```

Expected: `UNKNOWN_FIELD`, no proposal. Separately:

```json
{"score": {}}
```

Expected: `REQUIRED`, not FINISHED/zero-zero. Omitting the score field entirely is
the distinct already-supported UNKNOWN case, not permission to rewrite an empty
source object. Tests also cover late-batch atomic failure, repeatable rejection,
record reordering, unmarked FT remaining source-only, and the JSON/TXT repository
distinction. No unknown field allowance or missing-score fallback was added.

Offline commands (no dataset needed):

```powershell
python ci/run_unittest.py discover -s tests -p 'test_openfootball*.py'
python ci/run_unittest.py discover -s tests -p 'test_*.py'
python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python ci/check_repository.py
ruff check --no-cache .
git diff --check
git diff --cached --check
```

Execution results are included in the final PET-2 handoff. Existing CI discovery
includes the new tests automatically. No workflow/network requirement is added.

Executed on 2026-11-04:

| Check | Result |
| --- | --- |
| Real original-byte full-file validation | BLOCKED as detailed above; no proposal |
| Windows CPython 3.12.10 OpenFootball synthetic suites | 41 PASS (34 PET-1 + 7 PET-2) |
| Linux CPython 3.10.12 / 3.12.14 full offline suite, each | 1064 run: 1055 PASS, 9 Windows-only skips |
| Application regression, each Linux version | 61 PASS |
| CI/security/documentation contracts, each Linux version | 59 PASS |
| Ruff repository policy; full F rules for new Python files/helpers | PASS |
| compileall of src/tests/ci and local helpers, both Linux versions | PASS |
| Repository and explicit new-file secret-signature checks | PASS |

The Linux runs used existing disposable CI images with network disabled and the
repository mounted read-only, without changing persistent volumes/services. The
nine Windows-only recovery skips are not passes. Recovery/browser/live database
tests were not rerun; no recovery, frontend or application implementation changed.

## 7. Git preservation and next decision

The original prepared staging is preserved exactly:
`317393e115d581d40ba7a5d7efd34fe9edc95aa0`. No staging, commit, push, reset,
clean or rebase. Four existing licensing/planning documents, five PET-1 files and
the unrelated shortcut are preserved. This stage adds only this report and the
new synthetic regression file to the future source-file set, plus the explicitly
ignored acquisition/profiling materials listed above.

**PET-3 whole-season ingestion: BLOCKED.** The smallest next task is a separately
authorized PET-2 remediation/score-contract decision, not building a pipeline:

1. Choose whether to request upstream correction/new reviewed pin or explicitly
   support lossless source-only et/p plus missing-result DQ in a narrow results
   contract. Do not invent shootout winners or patch values from UEFA silently.
2. Establish source FT/ET/p semantics and review the missing final; any new source
   bytes need a new acquisition record/hash, never overwrite this verified pin.
3. Rerun complete validation and independent reconciliation before claiming
   complete results. An explicitly scoped league-phase-only path could be
   evaluated separately, but no reduced-scope import is authorized or performed
   here.

Until that decision, retain the immutable local evidence and fail-closed adapter.
No Bronze/Silver/Gold, database or UI integration follows automatically.
