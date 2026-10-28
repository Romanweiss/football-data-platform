# Stage 9B.1 — interactive match pass map

Publication update: [`fd6212d5972150e11ca0161efe0e5fa32cce4992`](https://github.com/Romanweiss/football-data-platform/commit/fd6212d5972150e11ca0161efe0e5fa32cce4992)
contains all 23 reviewed files. [CI fast](https://github.com/Romanweiss/football-data-platform/actions/runs/40764227972)
and [CI integration](https://github.com/Romanweiss/football-data-platform/actions/runs/40764227888)
passed for that commit, including Windows recovery/ACL. Pass Map is still not
deployed at production origin 18090. Pre-publication wording below records the
earlier implementation/review checkpoints, not the current publication status.

Baseline: `913feba6597bbe5c9db023e5ae11c015751a3310`. Local implementation;
no commit/push or production deployment. Stage 8C remains PARTIAL.

## Scope

Reads the existing ClickHouse `football.pass_events` with the existing read-only
API identity. No DDL/migration, S3 access, ingestion, Spark/Gold rebuild, new
service, backup/key access or restore-directory change. The existing composite
`/analysis`, shots, xG and shootout contracts remain unchanged. Only the existing
development API/web services were rebuilt to exercise the feature end-to-end.

## A — scoped serving/API

```text
GET /api/v1/competitions/{competition_id}/seasons/{season_id}/matches/{match_id}/passes
```

Optional filters: `team_id` / `player_id` positive UInt32, `period` integer 1–5.
Unknown, repeated, empty, overflowing or malformed query fields return JSON 400
before opening a database client. A wrong context/missing match returns 404
before reading pass rows. Valid filters with no matching passes return 200 with
empty arrays and zero counts. No new legacy alias is added.

SQL identifiers/expressions are code-owned constants; all request values use
typed SDK parameters, with `readonly=1`. Sort: `event_index, event_id`, preserving
the source event order rather than sorting minute values across periods. There
are at most 5000 drawable rows and a 4 MiB encoded JSON budget. Exceeding either
returns HTTP 422 `pass_result_too_large`, never a truncated/sampled success.

Two SELECTs read a filtered summary and drawable rows. Disagreement in counts or
duplicate event identities fails closed. This uses the current immutable serving
context; it does not promise a globally atomic snapshot during future concurrent
build replacement. No refresh/replacement mechanism is introduced here.

### Outcome semantics

Based on the [official StatsBomb event specification](https://github.com/hudl/open-data/blob/master/doc/Open%20Data%20Events%20v4.0.0.pdf):

| Source outcome | completion_status |
| --- | --- |
| Both outcome ID and name absent (successful-pass default) | `completed` |
| 9 Incomplete, 74 Injury Clearance, 75 Out, 76 Pass Offside | `failed` |
| 77 Unknown, unfamiliar IDs, name-only outcome | `unknown` |

IDs are authoritative for known failures. Null is not generically treated as
success: both outcome fields must be absent. Recipient can be the intended
recipient of a failed pass; its presence does not establish completion.

Missing coordinates, non-finite coordinates and out-of-bounds coordinates are
mutually exclusive exclusion reasons, evaluated in that order. Endpoints on
the boundary (0/120, 0/80) are valid. Missing recipient/player is preserved,
not replaced or silently used as an exclusion rule.

- `total_count` and `outcome_counts`: ALL matching source rows.
- `returned_count`: drawable rows in `passes`.
- `excluded.count`: total non-drawable rows, with explicit reasons.
- `total_count = returned_count + excluded.count`.
- `sum(outcome_counts) = total_count`.

Coordinates retain Float64 values, use StatsBomb units (not an asserted physical
metre grid), origin top-left, x right/y down. No flip or normalization is applied.
This is an event-based pass map, not tracking-based movement.

### Real read-only example

```powershell
Invoke-RestMethod 'http://127.0.0.1:18000/api/v1/competitions/9/seasons/281/matches/3895052/passes?team_id=904&player_id=3500&period=1'
```

Non-secret excerpt; the actual response contains all 31 passes:

```json
{
  "competition_id": 9,
  "season_id": 281,
  "match_id": 3895052,
  "filters": {"team_id": 904, "player_id": 3500, "period": 1},
  "total_count": 31,
  "returned_count": 31,
  "outcome_counts": {"completed": 27, "failed": 4, "unknown": 0},
  "excluded": {
    "count": 0,
    "reasons": {"missing_coordinates": 0, "non_finite_coordinates": 0, "out_of_bounds_coordinates": 0}
  }
}
```

Every pass contains event ID/index; team/player/recipient IDs and names;
minute/second/period; start/end XY; raw outcome ID/name; completion status.
The response also includes coordinate-system metadata and the row limit.

## B — React

Open the development Match Lab:

```text
http://127.0.0.1:15173/competitions/9/seasons/281/matches/3895052
```

Choose Granit Xhaka, period 1, then **Load pass map**. Explicit first loading
avoids adding a pass request to every initial shot-analysis load. Subsequent
team/player/period changes reload the scoped pass result; old requests are
cancelled and late responses ignored. Team changes reset player selection.

All returned passes are drawn. Solid mint / dashed orange / dotted purple
distinguish completed / failed / unknown. Arrows, start/end markers and a
persistent selected highlight accompany an accessible details panel. Maps over
250 passes explain overlap and suggest filtering; no sampling is applied.

The field is the complete 120×80 rectangle; padded SVG viewBox `-4 -4 128 88`
retains both halves, goals and boundary markers. The existing shot-map mapping
and pitch window are untouched. Pass selection is separate from shot selection.

Keyboard: Tab enters the pitch at a single roving tab stop, arrow keys browse
all passes, Home/End jump, Enter/Space select, Escape clears. All controls,
counts and details have EN/RU/ES text. Raw provider outcome names remain source
labels, alongside localized completion status.

Reviewed presentation labels for the two existing StatsBomb contexts display
World Cup / 2022 and Bundesliga / 2023/24. This is a small explicit UI mapping
from already audited source identities, not a newly persisted/live metadata
catalog; unfamiliar contexts retain honest ID labels. Context 9/281 displays:

```text
Partial coverage: Bayer Leverkusen matches only (34/306)
```

No league rankings are introduced. The API catalogs retain their existing shapes.

## C/D — verification evidence and limits

Read-only HTTP reconciliation visited every loaded match:

| Context | Matches | Passes | Completed | Failed | Unknown | Excluded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 9/281 | 34 | 39214 | 33332 | 5747 | 135 | 0 |
| 43/106 | 64 | 68515 | 56346 | 11775 | 394 | 0 |
| Total | 98 | 107729 | 89678 | 17522 | 529 | 0 |

Leverkusen–Leipzig 3895052: 1081 passes overall (908/168/5); Leverkusen 481
(396/81/4); Xhaka 3500 / team 904 / period 1: 31 (27/4/0), excluded 0.
All 98 responses reconciled count identities and sorted event order. Actual
ClickHouse SELECT-only synthetic expressions also checked missing/future/Unknown
outcomes, NaN/Infinity, missing/out-of-range XY and both field boundaries. No
tables/fixtures were written to the live database.

Repeat local checks:

```powershell
docker run --rm --network none --mount type=bind,source=F:\Learning_projects\football-data-platform,target=/app,readonly --env API_SERVING_MODE=development football-api:5a python -B ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python -B ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python -B ci/check_repository.py
python -B -m ruff check .
docker compose config -q
git diff --check
```

From `frontend/`: `npm test`, `npm run build`, `npm run test:ci-browser`,
`npm run test:smoke`. CI's existing offline application discovery includes
`test_passes.py`; its fixture-browser configuration additionally runs the new
synthetic pass-map test for desktop/mobile, with no real provider credentials.

Live browser evidence: `frontend/test-results/stage9b-pass-map-detail-1440.png`
and `stage9b-pass-map-detail-390.png` (ignored local artifacts, not publication
sources). Browser tests compare all 31 rendered Xhaka start/end coordinates to
the live endpoint and check counts, keyboard operation, axe accessibility and
existing shots/xG markers. The existing full smoke suite additionally covers
shootout, locale, history, selectors and responsive layouts.

Verified local results:

- Application contracts: 46 PASS on Linux Python 3.10.12 and 3.12.14.
  Includes the inclusive 5000-row boundary and ASCII/multibyte UTF-8 byte limits.
- Existing offline regression discovery: 787 tests, PASS, nine Windows-only skips
  on Linux. This task does not introduce/retest Windows key or ACL behavior.
- Frontend unit tests: 62 PASS; TypeScript / production asset build PASS.
- Fixture CI browser: four PASS across desktop/mobile; no real data dependency.
- Live smoke: 18 PASS, five existing opt-in production delivery tests SKIPPED.
  Includes 1440×900 / 390×844 real pass-map checks, exact coordinate comparison,
  keyboard/selection, axe and existing shot/xG/shootout/locale/history regression.
- Repository/security contracts, 23 CI contracts, Ruff, Compose config, syntax
  compilation, reviewed Markdown links and Git diff checks PASS.

Two browser issues were corrected without disabling assertions: use accessible
combobox-role selectors for nested-label selects; isolate the new pass filter CSS
class from the existing player-table screenshot selector. Subsequent regression
passed. Screenshots and generated build/test output remain ignored local files.

Production port 18090 has NOT been updated by this stage. Tests of the new
feature use the rebuilt development services; publishing/deploying requires
separate authorization. Large maps are bounded, not virtualized; filter to a
player to reduce overlap. Fully coincident segments can obscure pointer targets;
arrow-key navigation still reaches every event. Overlap cycling is not implemented.
Automated accessibility checks are not a substitute
for a full assistive-technology audit. No new remote GitHub CI result is claimed.

## Publication-readiness review

The original 21-file implementation is accompanied by two small completeness
contract changes (`ci/check_repository.py`, `tests/ci/test_contract.py`). New
pass-map source/test/documentation files must be present in the Git index;
CI must retain application test discovery and both desktop/mobile synthetic
pass-map and context browser tests. No quality gate was removed.

Verification uses a separate checkout of the intended staged tree, not the
working directory. Its initial contents contain only the 452 indexed files,
without `.env`, `.passes`, keys, venvs, node_modules, CA material, archives,
restore payloads or screenshots. Frontend dependencies are installed there with
`npm ci` from the committed lockfile. Linux test containers bind this checkout
at `/app`, set `/app` as their working directory and disable networking.
Python 3.10.12 CI dependencies are installed from the snapshot's
`requirements/ci.txt`, rather than relying on an outdated local CI image.

The staged-checkout checks cover the application, 787-test offline regression,
262-test explicit synthetic recovery/database-compatibility suite, 23 CI
contracts, Ruff and compileall on both Linux Python versions. Nine Windows-only
tests are skipped on Linux; Windows ACL implementation is unchanged and this
review does not claim a new Windows runtime test. Repository/security checks,
actionlint and Compose validation with public placeholders also pass. Production
API/web image builds pass from the same checkout under separate audit-only tags;
no production deployment or port 18090 update is performed.

The 98-match HTTP reconciliation is repeated against development and independently
agrees with read-only ClickHouse aggregates in the table above. Canonical and
legacy analysis responses agree; invalid pass parameters return 400 and a match
from the wrong competition/season returns 404. Xhaka's second-period filter
returns 17 passes (14 completed / 3 failed / 0 unknown), while a nonexistent
player returns an explicit empty result.

All 23 publication files are explicitly staged, not added using a directory-wide
`git add`. Staged diff, required-file inventory, ignored private paths and Docker
context rules are checked. Secret-signature checks supplement manual source
review; they are not an exhaustive secret/entropy or history audit. Generated
browser evidence stays only in ignored test output, never in the Git snapshot.
Commit/push and remote acceptance remain separate, unexecuted steps.
