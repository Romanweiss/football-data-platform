# Stage 9B.2-A — interactive Pressure event heatmap

Local implementation against baseline `353a80d739e4ac85dbee61361b367d56a9b3e40a`.
**Not committed, not published and not deployed at production origin 18090.**
The accepted [Pass Map deployment](stage9b1-deployment.md) remains unchanged there.
Stage 8C remains PARTIAL. No ingestion, migrations, S3 or recovery operations.

## Meaning and spatial contract

This is the count/density of **registered StatsBomb Pressure events** (`type_id=17`)
in a selected match/team/period. It is not a tracking/movement map, time spent in
an area, pressure success model or pressing-effectiveness rating. It does not
aggregate the separate `under_pressure` flag on other event types.

- Full StatsBomb 120x80 field; origin top-left, x right, y down. Original Float64
  coordinates/orientation are preserved; no mirroring or half-pitch clipping.
- Fixed 12 columns x 8 rows: 96 cells of 10x10 StatsBomb units, not square metres.
- Index: `min(floor(x/10),11)`, `min(floor(y/10),7)` **only for valid coordinates**.
  Each cell includes its lower edge and excludes its upper edge, except that
  the final column includes x=120 and the final row includes y=80. Thus (10,10)
  belongs to column 1/row 1, and (120,80) to column 11/row 7, exactly once.
- Missing x/y -> `missing_coordinates`; otherwise NaN/Infinity ->
  `non_finite_coordinates`; otherwise outside [0,120]x[0,80] ->
  `out_of_bounds_coordinates`. Reasons are mutually exclusive, in that order.
  Excluded coordinates are sanitized before numeric SQL casts, not clipped into
  a valid cell. No imputation, deduplication, smoothing or modification of events.
- `total_count = eligible_event_total + excluded.count`;
  `sum(cells.count) = eligible_event_total`.
- Cells always appear in row-major order, including zeros. There is no hidden
  sampling. One SELECT groups the same input stream into at most 96 spatial and
  three excluded buckets; a LIMIT of 100 detects an impossible aggregate rather
  than silently dropping data. The response always contains exactly 96 cells.

### Shared intensity scale

The same absolute count bands apply to every match, team and period:
**0; 1; 2–3; 4–7; 8–15; 16+**. The legend and the scale metadata are fixed, not
normalized to the current result maximum or a competition's distribution.
The top band saturates at 16, but hover/focus details always disclose the exact
count. Equal colors mean the same count band across filters, not equal percentiles.

Counts are not adjusted for minutes, possession, player participation or event
coverage. A full match and a half are different exposure windows; equal colors
do not imply equal pressure rates. The event sample cannot establish continuous
player movement, absence of off-ball activity or league-wide strength rankings.
Equal cell counts on this shared scale are comparable absolute event frequencies;
a team's total Pressure count is not normalized pressing intensity.

## Read-only source audit

| Context | Matches | Pressure events | Missing | Non-finite | Out of bounds |
| --- | ---: | ---: | ---: | ---: | ---: |
| WC2022 43/106 | 64 | 16554 | 0 | 0 | 0 |
| Bundesliga 9/281 | 34 | 11419 | 0 | 0 | 0 |
| Total | 98 | 27973 | 0 | 0 | 0 |

Observed `type_name='Pressure'` corresponds to type ID 17. Event IDs are unique;
team/player/match identities and periods are present in the checked rows.
Bundesliga coordinate ranges: x=1.4..119.3, y=0.1..79.6; WC2022:
x=1.5..119.3, y=0.6..79.9. Audit uses the existing SELECT-only reader.

Unchanged event_core Silver build identities:

- 43/106: `f62c4943ef505dc56ce02b4c1724fedd69cfc773b23a8f3a1b6cf575bf2f526d`
  (234637 event_core rows).
- 9/281: `6da4cacc187df6a6bdf1d9f1687396bd4f94c5abf742a3310fa6dc67efc55288`
  (137765 event_core rows).

All 98 match aggregates were reconciled against direct source counts, along with
36 team/period combinations on two sample matches. The exact production SQL bin
expressions were also exercised on 15 literal synthetic rows inside ClickHouse
using SELECT only: 6 mapped, 3 missing, 3 non-finite, 3 out-of-bounds, none lost or
counted twice. Fixtures included internal boundaries, Float64 values just below
boundaries, both outer edges and overlapping invalid reasons; no table was made.

## Canonical API

```text
GET /api/v1/competitions/{competition_id}/seasons/{season_id}/matches/{match_id}/event-heatmap?type=pressure[&team_id=...][&period=...]
```

`type=pressure` is required and case-sensitive. Optional team ID is a positive
UInt32; period is 1..5. Omitting team or period includes both teams/all periods.
An unrelated positive team ID returns an empty selection, not another match's
data. Player, arbitrary types, custom grids, limits, repeated/unknown parameters
and malformed IDs are rejected before opening a connection.

The match must first exist in the requested canonical context. No new legacy
route or generic event query engine is introduced. SQL uses typed parameters,
the existing `readonly=1` repository and `football.event_core` only. Analysis,
passes, shot/xG/shootout APIs, serving views, Gold/Silver and schema are unchanged.

Response fields:

| Field | Contract |
| --- | --- |
| competition_id, season_id, match_id | Validated requested canonical scope |
| filters | type=pressure, team_id/period or null |
| coordinate_system | StatsBomb 120x80, top-left, source-preserved, tracking=false |
| grid | columns=12, rows=8, cell_width=10, cell_height=10, explicit boundary_rule |
| metric | pressure_event_count / Pressure / 17; definition; normalization=none; smoothing=none |
| intensity_scale | fixed_absolute_count; lower_bounds=[0,1,2,4,8,16]; top_bin=16+ |
| total_count | All source Pressure rows matching the filters |
| eligible_event_total | Valid coordinate rows counted in the grid |
| excluded | Count and three disjoint reason counts |
| cells | Exactly 96 objects with column, row, count, including zeros |

Counts are non-negative exact JSON integers. Unexpected aggregate schemas,
bucket duplication, invalid indices/counts or impossible bounds fail closed.
The bounded numeric response has no arbitrary-length source names/payloads.
The real example response is approximately 4 KiB. Errors retain existing safe
400/404/405/503/500 behavior and never include raw SQL or exception text.

## Real examples and UI

Development example (no production deployment command):

```text
http://127.0.0.1:18000/api/v1/competitions/9/seasons/281/matches/3895052/event-heatmap?type=pressure&team_id=904&period=1
http://127.0.0.1:15173/competitions/9/seasons/281/matches/3895052
```

Bayer Leverkusen, period 1: **63 Pressure events, 63 mapped, 0 excluded**;
41 nonzero cells; maximum cell count 4. For example, column 3/row 0 has count 1
(x in [30,40), y in [0,10)). Argentina-France `43/106/3869685`, Argentina team 779,
period 1: **59 events**, 39 nonzero cells, maximum 5. The scale is identical.

The independent panel follows Pass Map. Select team/period and press **Load
pressure heatmap**; initial analysis loading does not make a heatmap request.
After loading, filter changes refetch, abort obsolete requests and cannot render
a late previous context's result. Retry, loading, empty and all-excluded states
are distinct. Native selects keep accessible names, keyboard focus and the
existing CSS chevrons. All text is available in EN/RU/ES.

Tab enters one grid cell; arrows move spatially, Home/End jump to first/last,
Enter/Space select, Escape clears. Hover/focus exposes exact intervals/counts.
Pitch markings do not intercept pointer events. Selection does not affect
Pass Map, Shot Map, xG Race or Shootout. The Bundesliga 34/306 warning remains.

Local ignored evidence (not publication assets):

```text
frontend/test-results/stage9b2/pressure-9-desktop.png
frontend/test-results/stage9b2/pressure-9-mobile.png
frontend/test-results/stage9b2/pressure-43-desktop.png
frontend/test-results/stage9b2/pressure-43-mobile.png
```

## Verification commands and boundaries

Offline API tests, pinned CI environment:

```text
python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python ci/check_repository.py
ruff check .
```

From `frontend`, using existing pinned dependencies:

```text
npm test
npm run build
npm run test:ci-browser
```

For an already configured/running dev stack, PowerShell:

```powershell
$env:PLAYWRIGHT_CHANNEL = 'chromium'
$env:WEB_BASE_URL = 'http://127.0.0.1:15173'
npm run test:smoke
# Existing two-viewport harness, but ONLY the new dev read-only Pressure cases:
npm run test:delivery -- --grep 'live pressure'
```

The normal dev suite intentionally skips the five production-only cases; this
does not constitute new production acceptance. Synthetic CI preview checks use
fake transport with no real services/credentials. The new spec is explicitly
included in that existing gate. Dependencies and workflow pins are unchanged.

API projection/HTTP tests and frontend unit/build/fixture browser checks passed.
Real two-context checks passed in Chromium at 1440x900 and 390x844, including
whole-page axe, keyboard/pointer details, counts, empty period 5, languages and
no page overflow. The full existing dev regression suite covers Pass Map, Shot
Map, xG Race, Shootout, history and selectors; final counts are recorded in the
implementation handoff, not a remote CI success claim.

Local results: Python 3.10.12 and 3.12.14 each passed 787 root offline tests
(nine Windows-only skips), 56 application tests and 30 CI/security/documentation
tests. Frontend: 71 unit tests, TypeScript/build and six synthetic Chromium cases
passed. Full dev smoke: 21 passed, five expected production-only skips; explicit
two-context/two-viewport Pressure smoke: four passed. Ruff, compileall, actionlint,
Compose config -q and diff checks passed. There is no remote CI acceptance yet.

## Changed-file inventory for publication review

```text
README.md
README.ru.md
application/heatmap.py
application/services.py
application/transport.py
application/urls.py
application/views.py
ci/Dockerfile
ci/Dockerfile.dockerignore
ci/check_repository.py
docs/stage9b2.md
frontend/playwright.ci.config.ts
frontend/src/App.tsx
frontend/src/api.ts
frontend/src/components/PressureHeatmap.tsx
frontend/src/locales.ts
frontend/src/styles.css
frontend/src/types.ts
frontend/tests/fixtures.ts
frontend/tests/heatmap.test.tsx
frontend/tests/smoke/pressure-heatmap.spec.ts
tests/application/test_heatmap.py
tests/ci/test_documentation.py
tests/ci/test_heatmap.py
tests/integration/test_clickhouse_heatmap.py
```

Additionally preserve/include `docs/stage9b1-deployment.md`, the pre-existing
untracked acceptance report now referenced by both READMEs. It was not rewritten
in this stage. Do not include the unrelated untracked shortcut or ignored browser
screenshots/results. No files were staged by this implementation task.

No production application containers, databases, build identities, S3, backups,
recovery keys or volumes are modified by this feature. Only dev API/web images
and containers were updated for live testing. The unrelated shortcut and prior
deployment report are preserved. There is no commit/push or new GitHub run.

Before publication, review the complete Git snapshot (including new modules,
tests, this runbook and the previously untracked deployment report), run clean
checkout checks and obtain separate publication authorization. Real production
deployment requires another explicit approval.

## Stage 9B.2-B — publication review

The implementation numbers above record Stage A. Review adds targeted tests,
not changes to API, analytical semantics or the production application:

- A late old-match Pressure response cannot replace the next match's heatmap;
  obsolete requests are aborted and the shootout panel disappears after navigation.
- The frontend client rejects wrong context/match/filter responses and malformed
  request filters. The original previously flaky navigation test is unchanged,
  remains enabled and is included in all complete frontend test runs.
- ClickHouse/TLS-transport/timeout errors remain safe 503 responses without raw
  SQL or credential text. The actual SDK is required to use readonly=1.
- `tests/integration/test_clickhouse_heatmap.py` makes the exact SQL boundary and
  exclusion check reproducible, including deterministic repeat results. It uses
  only literal SELECT fixtures, never creates a table, and is selected by the
  existing CI ClickHouse harness. Outside isolated CI it requires explicit
  `HEATMAP_READONLY_SQL_TESTS=true` opt-in; ordinary offline tests do not connect.
- Publication contracts now require all new files in the Git index. The CI
  Dockerfile also copies the public Russian README required by documentation
  tests and the public `.gitignore` required by recovery/security tests.
  Its Dockerfile-specific ignore rules retain every root exclusion and add only
  `!.gitignore`; private files remain excluded and API/web build contexts are
  unchanged. A standalone CI image regression exposed the missing `.gitignore`;
  the fix does not skip or weaken those tests.

Fresh read-only reconciliation independently binned all 27973 source events in
memory and compared every one of 96 cells for all 98 matches; repeated match
responses were identical. The 36 sample team/period combinations, team 904 /
match 3895052 / period 1 = 63, zero exclusions, unique event IDs and the two
event_core build identities above were confirmed again. No raw source rows were
written to the snapshot. Aggregate review digest:
`742f61815daaaeb1d38a4aefe05d40cec92c9e04bd9a92fde6b1f51ff9fc4b4d`.

The reviewed staging contains 26 files: the inventory above plus the retained
Stage 9B.1-D deployment report. Temporary audit scripts, screenshots, node_modules,
private environment, keys, CA material and the unrelated shortcut are excluded.
The exact final tree ID and clean-snapshot results are provided in the review
handoff (not embedded here, which would change that tree's identity).
This stage stops at staging: no commit, push, new remote CI run or production
deployment is authorized or claimed. Stage 8C remains PARTIAL.

## Stage 9B.2-C — source-coordinate Smooth Heatmap

Local development only. This revision is not committed, published or deployed
to production 18090. The Stage A/B record above describes the original Grid
implementation and historical review; the following changes supersede its
Grid-only UI description. Stage 8C remains PARTIAL.

### Additive coordinate contract

The original `event-heatmap?type=pressure&team_id=...&period=...` response and
its exact 96 bins, exclusions, boundary rules and fixed count scale are unchanged.
A new canonical, match-scoped GET endpoint adds original coordinates:

```text
/api/v1/competitions/{competition_id}/seasons/{season_id}/matches/{match_id}/event-heatmap/coordinates?type=pressure&team_id={team_id}&period=1
```

It returns the same Grid fields plus `response_limit: 5000` and
`points: [{event_id, x, y}]`. Only valid, original Float64 coordinates appear;
there is no rounding, sampling, invented point or interpolation of event locations.
Excluded coordinates are classified and sanitized in SQL before JSON serialization.
One SELECT with typed parameters and stable `period, event_index, event_id` order
provides points and their independently reproducible bins. More than 5000 source
rows fails with HTTP 422 `heatmap_response_too_large`, never silent truncation.
Duplicate event identities fail closed. At the maximum reviewed identity/coordinate
sizes, the complete encoded response is under 1 MiB. Invalid/repeated query
parameters, canonical scope, read-only query settings and safe diagnostics retain
the original endpoint's protections. No new table, migration or build is required.

### Density method and colour scale

Smooth Heatmap is the default; Grid remains an explicit keyboard-accessible
button. Both load only on operator request, retain team/period filters and show
source total, mapped and excluded counts. Changing match, filter or mode invalidates
the request identity; aborted or late responses cannot replace current data.

Smooth uses actual `points`, **not smoothing of the 12 × 8 bins**. The frontend
evaluates a Gaussian event-intensity estimator on a fixed 120 × 80 raster: samples
at `(i + 0.5, j + 0.5)`, spacing one StatsBomb unit, isotropic bandwidth sigma = 6
StatsBomb units, no kernel truncation. For each source event `(x, y)`:

```text
wx[i] = exp(-0.5 * ((i + 0.5 - x) / 6)^2)
wy[j] = exp(-0.5 * ((j + 0.5 - y) / 6)^2)
density[i,j] += 100 * wx[i]/sum(wx) * wy[j]/sum(wy)
```

This is a discrete boundary-corrected Gaussian KDE/intensity estimate, not a
probability density: **there is no division by the number of events**. Each event,
including a touchline/corner event, contributes exactly one integrated unit:
`sum(density)/100 == mapped event count` within floating-point tolerance. The
boundary correction preserves mass inside the pitch; it is a modelling choice,
not evidence of additional observed events. Browser bilinear raster enlargement
smooths the display only, not the source locations or exact Grid counts.

Units are smoothed events per 100 square StatsBomb coordinate units (not physical
metres). The fixed colour transfer is `t = min(log(1+density)/log(17), 1)` with the
same transparent-teal/green/yellow/orange/red ramp in every selection; opacity is
`min(1, 1.8*t)`. Zero is transparent; low non-zero samples remain visible. Values
at or above 16 share the saturated top colour, explicitly labelled `16+`; the
underlying values are not clipped. Legend stops use this exact transfer, not a
selection maximum. It is not normalized per result, elapsed time or possession.
Different selections with identical densities have identical colours. Neither
mode alone measures pressing effectiveness or normalized pressing intensity;
these are registered events, not tracking movement. Source orientation is retained,
so do not infer common physical attacking direction across teams/periods.

Pitch markings are drawn above the raster. A transparent, keyboard-accessible
12 × 8 inspection overlay reports **exact area counts**, never labels them as
smoothed density. Grid retains its original six discrete colour bands. Methodology,
boundary rules and keyboard instructions are available in an expandable section;
the main introduction is deliberately brief. All controls and text support EN/RU/ES.

### Verification and local evidence

Read-only reconciliation of both endpoint representations against all 98 matches:
WC2022 16554, Bundesliga subset 11419, total 27973 distinct Pressure event IDs,
zero exclusions, all 96 cells identical for every match. Existing serving
`silver_build_id` values and event_core row counts remain the values recorded
above. England–Iran match 3857271, period 1: England/team 768 = 44; Iran/team 797
= 79. Both raw-coordinate counts exactly reconcile with Grid. This is not a rate
comparison or evidence about which team pressed more effectively.

Synthetic tests cover kernel mass, corners, empty samples, sub-cell coordinate
fidelity, additive density, fixed colours, unchanged bins, invalid/duplicate points,
5000-row/response bounds, exclusions, typed parameters, HTTP scope/errors and late
mode/filter/match responses. The literal-only ClickHouse integration test exercises
both production SQL readers, including NaN/Infinity sanitization and outer edges;
it performs SELECT only and needs the explicit opt-in described above.

Actual Chromium evidence is generated by:

```powershell
$env:PLAYWRIGHT_CHANNEL = 'chromium'
$env:WEB_BASE_URL = 'http://127.0.0.1:15173'
npm --prefix frontend run test:delivery -- --grep 'live pressure visuals'
```

This uses the already-running **dev** origin, not a production deployment.
Desktop 1440 × 900 and mobile 390 × 844 capture England and Iran in both modes:
`frontend/test-results/stage9b2c/{England,Iran}-{smooth,grid}-{desktop,mobile}.png`.
These eight screenshots are ignored local evidence, not Git assets. Tests also
exercise keyboard switching, area inspection, overflow and axe, and EN/RU/ES in
Smooth. Existing synthetic Chromium coverage checks Smooth then Grid, errors,
empty results and regressions for shots/xG/shootout; live regression checks retain
both existing contexts and Pass Map. No previously flaky test is removed or skipped.

For publication review, run both Linux Python pins (3.10.12 and 3.12.14), all offline,
application and repository/security contracts, frontend units/typecheck/build,
synthetic Chromium, live dev smoke, Ruff/compileall, actionlint and Compose config
from a new isolated staged-tree snapshot. Rebuild API/web images from that snapshot
without deployment. The previous staged tree
`294692997761193931d7dfaebb9decfc9d819f5b` was preserved before modifications.
The new snapshot contains the previous 26 paths plus `frontend/src/pressureDensity.ts`
and `frontend/tests/density.test.tsx`; exact tree identity and measured test results
belong in the final handoff, not self-referentially in this document.
