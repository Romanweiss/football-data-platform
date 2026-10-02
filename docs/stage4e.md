# Stage 4E — Match Visual Analytics

Implementation + offline/read-only verification only. Codex did **not** apply
013 or modify Superset. The installed Stage 4C/4D validators passed. Existing
World Cup Overview and Stage 4D views remain unchanged; no Gold/S3 work is added.

Current operator-confirmed state: migrations **013 and 014 are applied live**.
Both historical files remain unchanged. **015 is prepared, not applied**; it
appends a human-readable Shot Map entity label. Only its SELECT was evaluated.
The existing four views and Superset configuration were not changed by Codex.

## Sources, architecture and grains

Inspected live SHOW CREATE for `bi_match_shots` and `bi_match_overview`, migration
012, Stage 4D validation/tests and actual coordinate ranges. All requested fields
exist; no additional raw event table is needed.

| New ordinary INVOKER view | Source | Grain (full context) | WC2022 rows |
| --- | --- | --- | --- |
| bi_match_xg_race | bi_match_shots + overview team IDs | competition_id, season_id, match_id, event_id; normal shot | 1453 |
| bi_match_shot_map | bi_match_shots | same; normal shot | 1453 |
| bi_match_shootout | bi_match_shots + overview team IDs | same; shootout shot | 41 |

All expose match_label unchanged, identity, index, timing, team/player fields,
xG, original outcome ID/name and period flags. Nullable player ID/name remain
nullable. Overview joins use all three match keys, never team names. New objects
in 013/014 are additive `CREATE VIEW IF NOT EXISTS ... SQL SECURITY INVOKER`.
015 uses `CREATE OR REPLACE VIEW` only for `bi_match_shot_map`, retaining INVOKER
security and the entire existing projection, with one appended String column.
The underlying shot grain is never expanded into fake events.

## xG progression contract

The WHERE clause selects `is_shootout=0` **before** window evaluation. Periods
3/4 remain. Canonical order is `(period, minute, second, event_index)` within
`(competition_id, season_id, match_id)`; event_index is the final tie breaker.
Validation rejects duplicate event_index within a match rather than silently
choosing a nondeterministic order. Consumers must explicitly ORDER BY: views do
not promise physical row order.

- `event_time_seconds = minute * 60 + second`: numeric **source match clock**,
  retaining original minute/second. It is not wall-clock elapsed duration.
- `event_order`: contiguous normal-shot rank in canonical order. This numeric
  axis keeps same-second shots separate and periods chronological.
- `team_cumulative_xg`: cumulative xG of the shooting team at its current shot.
- `home_cumulative_xg`, `away_cumulative_xg`: both teams' cumulative values at
  **every real normal shot**. Home/away IDs/names come from authoritative overview.
  These wide columns allow two complete step series without sparse opponent gaps.

All sums use `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, not default RANGE
peers. Integer order is exact; Float64 reconciliation uses existing abs/rel 1e-9.
Every intermediate cumulative value is checked, not only the final point.
Final xG for every team must equal `bi_match_team_stats.shot_xg`. Teams without
normal shots have zero cumulative xG but no fabricated own-shot row. A completely
shotless match would have an empty race. No kickoff/end-of-match anchor rows are
created: a curve starts at the first actual shot and ends at the last.

Final Argentina–France stored totals: Argentina **2.758305926**, France
**2.2726179490000002**. These are expected-goals progression, not the official
score. Period 5 must never contribute to any race column.

### Clock vs chart order (important limitation)

First-half stoppage time can exceed minute 45 while the second-half clock resumes
at 45; similar overlaps exist at later period boundaries. Multiple shots can
share minute/second. Therefore a single raw `event_time_seconds` axis grouped by
second can reorder periods or merge shots. Do not add arbitrary fractions to
claim extra time precision. The reliable initial chart below uses `event_order`,
labelled **ordered normal shots, not elapsed seconds**, while clock fields are
available for display/table/drill-down. A later true elapsed-time race requires a
reviewed period-duration/anchor contract; this stage does not infer one from shots.

## Shot-map coordinates

The view copies `start_x`, `start_y`, `end_x`, `end_y`, `end_z` exactly. It does not
rename them to invented location columns, fill NULLs, clip, scale or flip axes.
`is_goal` is Bool from `outcome_id=97`, not an outcome-name comparison.

StatsBomb's documented pitch grid is 120 by 80, origin at the top-left of the
diagram; y increases downward. These are pitch coordinates, **not geographic
latitude/longitude**. See [StatsBomb Open Data specification, Appendix 2](https://github.com/statsbomb/open-data/blob/master/doc/StatsBomb%20Open%20Data%20Specification%20v1.1.pdf).

Observed current **normal-shot** ranges (read-only inspection):

| Coordinate | Minimum | Maximum | NULL rows |
| --- | ---: | ---: | ---: |
| start_x | 59.0 | 120.0 | 0 |
| start_y | 0.7 | 79.2 | 0 |
| end_x | 87.2 | 120.0 | 0 |
| end_y | 0.1 | 80.0 | 0 |
| end_z | 0.0 | 7.6 | 464 |

The inspected periods/teams are consistent with shots attacking towards x=120,
not stadium-fixed opposite directions per half. This is a finding for the current
snapshot, not permission to flip away-team or second-half coordinates. No further
attack-direction normalization is needed for a common attacking-goal scatter of
this data. Any future stadium-oriented map must first establish its own proven
orientation contract and add new explicitly named display fields.

DQ checks preserve coordinate NULLs and require finite nonnegative non-null
values: x<=120, y<=80 and z<=7.6 for this reviewed WC2022 snapshot. **7.6 is an
observed snapshot ceiling, not crossbar height or a universal source rule**.
Do not reject high off-target shots by bounding z to goal height. Other StatsBomb
data may legally extend beyond pitch boundaries, as the provider's
[Working with R notes](https://blogarchive.statsbomb.com/uploads/2022/08/Working-with-R.pdf)
explain; extending this validator beyond WC2022 requires reviewing bounds, not
silently clipping source coordinates. Source-legal NULL coordinates remain valid.

## Ordered shootout contract

Only `is_shootout=1` rows are selected. `shootout_order` is ROW_NUMBER partitioned
by all three match keys, ordered by event_index. `team_attempt_number` adds team_id
to that partition. Both start at 1 and must be contiguous. Timing is preserved
but is **not** the ordering authority for this presentation.

`home_shootout_goals_after` / `away_shootout_goals_after` count goal-ID 97 events
through the current attempt with explicit ROWS frames and overview home/away IDs.
Saved, Off T, Goal and every other original outcome remain unchanged. Both final
running scores and attempts reconcile with overview; result/display_score are
not independently re-derived. Final: 8 attempts, Argentina 4 goals, France 2.

## Validation and tests

`scripts/check_clickhouse_match_visuals.py` first invokes the installed Stage 4D
validator, which also runs Stage 4C bi-v2 checks. All new queries use readonly=1;
there are no S3 calls or SQL write paths. Source schemas/rows are compared before
and after. The small WC2022 relations use the existing 10000-row guard.

For each new view, validation checks full schema/types/nullability and exact
source identity/values, including xG and outcomes. Additionally:

- race/map each 1453 rows, period 5 excluded and 45 extra-time shots retained;
- normal xG 155.8985419302, every cumulative step, monotonicity, final team totals;
- map goal-ID semantics, unmodified coordinates/NULLs and reviewed domain;
- shootout 41 rows/5 matches, every rank, attempt number and running/final score;
- full-key isolation, authoritative home/away context and unchanged match_label.
- Shot Map labels: exact deterministic expression, nonblank, unique within the
  full match context; full event identities and event_index also remain unique.

`--candidate` evaluates the 013/014/015 SELECT bodies without creating objects.
`--candidate-shot-map` evaluates only the 015 candidate while validating installed
013/014 views and Stage 4C/4D prerequisites. This is the current pre-migration mode.
Default mode checks installed views, including the enriched 015 schema; it must
fail before 015 is applied. Candidate PASS is **not** evidence of installation.
Tests include reversed input order at the same second in
real ClickHouse SELECT-only SQL, with distinct ROWS-prefix results.

## Superset 6.0: inspected plugins and manual chart configuration

Read-only inspection of the running container's static frontend confirmed both
**Stepped Line** and **Bubble Chart** (ECharts), including their preset
registrations. Legacy Bubble Chart also exists; choose the non-legacy ECharts
one. No frontend plugin, feature flag or Superset metadata was changed. The UI
has not been smoke-tested by Codex; confirm saved chart queries manually.

Register physical datasets `football.bi_match_xg_race`, `football.bi_match_shot_map`,
`football.bi_match_shootout` using the existing read-only ClickHouse connection.
Sync columns. Extend the existing **Match** native filter (`match_label`) to the
new charts only; retain single selection and competition_id=43/season_id=106.
Use No time filter/full tournament, not a recent relative date range. Do not
change World Cup Overview chart/filter scopes.

### xG Race — preferred long-form dataset after migration 014

`football.bi_match_xg_race_series` is an ordinary INVOKER view over the existing
wide race. Its grain is one team's cumulative state at one normal-shot event:
`(competition_id, season_id, match_id, event_order, team_id)` (equivalently the
full event_id plus team_id). Each wide row projects exactly two rows using
`UNION ALL`: home_team_id/name/home_cumulative_xg and
away_team_id/name/away_cumulative_xg. `is_home` is UInt8 1/0. No window or
cumulative recomputation, no shooting-team identity inference, no new shot event.
All event identity/timing fields and match_label are copied unchanged.

Expected WC2022: **2906 rows**; each full match/event_order has exactly one home
and one away state. The validator checks exact projection for every row and
final xG for all 128 team-match records against bi_match_team_stats using existing
Float64 tolerance. Argentina–France ends at Argentina 2.758305926 and France
2.2726179490000002. A zero-shot team still has its zero state at the opponent's
events. These rows are **team states**, not a shot-count dataset: COUNT(*) doubles
the shot count. The wide 013 source remains unchanged and available.

Manually register and sync dataset **football.bi_match_xg_race_series**, then
configure the Match Analysis **Stepped Line** chart:

| Control | Setting |
| --- | --- |
| X Axis | event_order |
| Metric | MAX(cumulative_xg) |
| Dimension / group by | team_name |
| X ordering | event_order ascending |
| Step type | End |
| Stack / contribution / rolling / resample | off |
| Legend | on; dynamic team_name values |
| Row limit | 10000; no two-series truncation |
| Match selection | existing native Match filter, column match_label |

**No chart-level match_id or match_label filter in the final dashboard.** Remove
any temporary Explore filter before saving. Extend the existing native Match
filter scope to this chart/dataset, retain required single selection, and inspect
generated SQL to verify propagation. Do not change World Cup Overview scopes.
Competition/season scope can remain 43/106; avoid a recent relative date filter.
Both teams now have points at every event_order, so the old sparse-series gap and
static Home/Away metric-legend limitations no longer apply. Numeric event_order
still means ordered shots, not elapsed minutes; there are no kickoff/end anchors.

#### Historical 014 follow-up commands (already applied; do not repeat)

Use the 015 runbook below for the current state. With the updated checker,
`--candidate-series` previews only 014 and requires the other installed contracts,
including 015 Shot Map labels. The commands below record the earlier installation.

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose failed; STOP' }

# Read-only: validate installed 013 plus candidate 014, including Stage 4C/4D.
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py --candidate-series
if ($LASTEXITCODE -ne 0) { throw 'Long-form candidate failed; STOP' }
Get-Content -Raw .\infrastructure\clickhouse\migrations\014_create_match_xg_race_series_view.sql
```

**STOP:** inspect 2906 rows and final reconciliation, then apply separately:

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\014_create_match_xg_race_series_view.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 014 failed; STOP' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
if ($LASTEXITCODE -ne 0) { throw 'Installed visual/series validation failed; STOP' }
```

Do not reapply/edit 013. IF NOT EXISTS does not repair a wrong existing 014 view;
stop and inspect rather than replace existing objects. Default validation now
requires all four visual views and the 015 Shot Map enrichment.
`--candidate` previews 013/014/015 without DDL.
After manual dataset/chart setup, switch between the final, Japan–Croatia and a
regulation match: labels must change to the selected teams, endpoints must match
Team Comparison, and no saved chart-level match filter may pin the first match.

### Original wide xG Race — retained fallback (013)

Create **Stepped Line**, dataset bi_match_xg_race:

| Control | Setting |
| --- | --- |
| X Axis | event_order (numeric, not a temporal column) |
| Metrics | MAX(home_cumulative_xg), MAX(away_cumulative_xg) |
| Dimensions / group by | empty (two metrics already define the two series) |
| Sort | X axis ascending; query order ascending, no metric-descending order |
| Step type | **End**; change occurs at the new shot, not before it |
| Stack / contribution / rolling / resample | off; no second cumulative calculation |
| Marker / legend | on |
| Y axis | minimum 0, numeric format e.g. .3f |
| Row limit | 10000; no series truncation |

Use metric labels **Home xG** and **Away xG**, with home/away team names visible in
the Match Header. This representation avoids gaps when the opponent shoots and
does not duplicate events. Do **not** SUM already cumulative values. Chart title:
“xG progression by ordered shots”; do not label event_order as elapsed minutes.

The Step control provides Start/Middle/End in the
[pinned 6.0 control panel](https://github.com/apache/superset/blob/6.0.0/superset-frontend/plugins/plugin-chart-echarts/src/Timeseries/Step/controlPanel.tsx).
Non-temporal X columns are supported by the shared
[query controls](https://github.com/apache/superset/blob/6.0.0/superset-frontend/packages/superset-ui-chart-controls/src/sections/echartsTimeSeriesQuery.tsx).

The old sparse shooting-team representation is also exposed: series=team_name,
Y=MAX(team_cumulative_xg), X=event_order, sorted ascending. However each team then
has rows only at its own shots. The stock chart may break lines at missing
opponent points; it also does not extend a team's final plateau. Do not replace
missing values with zero or present smooth interpolation as continuous xG growth.
For dynamic team-name legends use the dense 014 representation above, not this
sparse alternative. Adding
kickoff/end anchors or a true clock-axis representation is future work, not hidden
fake shot data. A plain Line fallback must explicitly disclose interpolation.

### Shot Map — numeric Bubble Chart, not a geographic map

After applying 015 and syncing dataset columns, use dataset
**football.bi_match_shot_map**, non-legacy **Bubble Chart** (ECharts):

| Control | Setting |
| --- | --- |
| Dimension | team_name |
| Entity | shot_label |
| X Axis | MAX(start_x) |
| Y Axis | MAX(start_y) |
| Bubble Size | MAX(statsbomb_xg) |
| X bounds | 55..120 |
| Y bounds | 0..80 |
| Max Bubble Size | 12 |
| Bubble opacity | approximately 0.4–0.5 |
| Palette | contrasting categorical team colors |
| Row limit | 10000 |
| Match selection | existing native Match filter on match_label |

**No permanent chart-level match filter.** Remove temporary Explore match filters
before saving. Keep single-match native filter scope and verify propagation in
generated SQL. Do not alter World Cup Overview filter scopes.

Each entity identifies one shot, not one player. Migration 015 appends this exact
expression; no Superset calculated column is needed:

```sql
concat(ifNull(s.player_name, 'Unknown player'), ' | ',
    toString(s.minute), ':', leftPad(toString(s.second), 2, '0'), ' | ',
    ifNull(s.outcome_name, 'Unknown outcome'), ' | #', toString(s.event_index)) AS shot_label
```

Live DESCRIBE/SHOW CREATE inspection found `player_name` and `outcome_name` are
both **Nullable(String)**. The current 1453 normal shots contain zero NULL/empty
values in either field. Explicit NULL fallbacks still protect future input;
original player/outcome fields are untouched (including NULLs and empty strings).
`shot_label` is non-null String. Seconds are zero-padded; minute is not truncated
at 90. The suffix is the authoritative `event_index`, not a visible UUID.

The read-only candidate produced **1453 rows, 1453 distinct full event identities,
and 1453 distinct full-match/shot_label identities**, with no blank labels.
Uniqueness is within `(competition_id, season_id, match_id)`, not globally by text.
The validator also rejects duplicate event_index in that context. Existing event
IDs remain authoritative identity fields; shot_label is a presentation field.
Every pre-existing column's type, nullability and value was compared to the 013
projection: coordinates, xG, is_goal, match_label and all context are unchanged.
Periods 1–4 remain (including 45 extra-time shots); period 5 remains excluded.

The Bubble tooltip still has **no arbitrary tooltip-field configuration**. It
shows entity and series plus X/Y/size. The label supplies player/time/outcome;
the full UUID stays available in the dataset without becoming primary tooltip
text. Size is normalized by the plugin, not calibrated xG-proportional area.
Optional `start_x IS NOT NULL AND start_y IS NOT NULL` filtering is display-only;
report omitted points rather than replace NULLs. Current starts have no NULLs.

#### Manual 015 runbook (013 and 014 already live)

Keep writers idle. Preview without changing any live view:

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose failed; STOP' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py --candidate-shot-map
if ($LASTEXITCODE -ne 0) { throw '015 candidate failed; STOP' }
```

**STOP:** inspect preservation and label results before the separate manual write.
Codex did not execute the following migration command:

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\015_enrich_match_shot_map.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 015 failed; STOP' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
if ($LASTEXITCODE -ne 0) { throw 'Installed validation failed; STOP' }
```

Only after installed PASS, manually sync columns in the existing Shot Map
dataset, change Entity from event_id to shot_label, apply the settings above and
refresh chart caches. Switch the native Match filter between Argentina–France,
Japan–Croatia and a regulation-only match. Verify readable labels, distinct
same-player shots and unchanged shot counts/xG; leave other charts unchanged.
Do not reapply or edit historical 013/014.

#### Pitch background investigation — not implemented

Read-only inspection of the installed Superset 6.0 frontend bundle confirmed the
ECharts Bubble plugin. Its controls/renderer match the pinned upstream
[Bubble control panel](https://github.com/apache/superset/blob/6.0.0/superset-frontend/plugins/plugin-chart-echarts/src/Bubble/controlPanel.tsx)
and [renderer](https://github.com/apache/superset/blob/6.0.0/superset-frontend/plugins/plugin-chart-echarts/src/Bubble/transformProps.ts).
This plugin exposes **no pitch/image background control, graphic-annotation
configuration or arbitrary ECharts option passthrough**. Its renderer builds
scatter series, axes, grid, legend and tooltip, not a custom pitch graphic.
ECharts capabilities alone do not make them available in this Superset chart.

Realistic next options:

- **A — keep native Bubble scatter (recommended now):** no new deployment or
  maintenance; readable entities and team colors work. It is a raw-coordinate
  scatter, not a true football-pitch rendering.
- **B — custom Superset chart plugin:** draw a pitch behind points in the same
  coordinate system and handle aspect ratio, resizing/zoom, Y direction and
  native filters together. Requires frontend build, deployment, compatibility
  maintenance and tests; a separate scoped task, not a config switch.
- **C — future React/SVG application component:** use a 120-by-80 SVG viewBox with
  pitch and shots sharing one transform. Serve read-only BI data through an
  authenticated backend, never browser DB credentials. Requires application/API
  work and match-filter integration; only appropriate for a planned application.

Do not use a CSS/static-image overlay as a reliable pitch: chart grid offsets,
resizing and zoom can misalign it. Prefer A now; consider B if staying entirely
in Superset, or C if an application is separately planned. Nothing was installed.

Orientation was checked against the StatsBomb specification linked above and
the provider's [plotting example](https://blogarchive.statsbomb.com/articles/soccer/doing-more-with-statsbomb-data-in-r/),
which reverses the plotting Y axis. StatsBomb uses X 0..120 and Y 0..80 with Y
downward in its pitch diagram; ordinary numeric Bubble Y increases upward.
The observed normal-shot X range 59..120 supports the current display crop
55..120, not a data transformation. Do not flip teams, X or Y in SQL. A future
pitch renderer must explicitly map the source orientation, preserve aspect ratio
and keep raw values unchanged; SVG's top-left/downward-Y convention can do this
without rewriting coordinates. No custom plugin or pitch background was added.

### Ordered Penalty Shootout table

After checks pass, manually replace the Stage 4D raw Penalty Shootout chart with
a new Table using bi_match_shootout. Preserve the old chart until smoke checks
pass; the existing Shootout Summary may remain. Use raw rows and columns:
shootout_order, team_name, player_name, outcome_name, team_attempt_number,
home_shootout_goals_after, away_shootout_goals_after. Sort **shootout_order ASC**,
never player/team name or outcome. Retain the Match native filter scope.

## Original 013 runbook — historical; use the 015 runbook above now

Keep writers idle during validation. First verify current serving and preview:

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose failed; STOP' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_analysis.py
if ($LASTEXITCODE -ne 0) { throw 'Stage 4C/4D prerequisite failed; STOP' }
Get-Content -Raw .\infrastructure\clickhouse\migrations\013_create_match_visual_analysis_views.sql
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py --candidate
if ($LASTEXITCODE -ne 0) { throw 'Candidate failed; STOP' }
```

**STOP:** inspect counts, xG, coordinates and three additive object names. Then,
as a separate manual action, stream migration from the Windows host (no
`/migrations` container mount):

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\013_create_match_visual_analysis_views.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 013 failed; STOP before changing charts' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
if ($LASTEXITCODE -ne 0) { throw 'Installed visual checks failed; STOP' }
```

With the follow-up checker, default installed checks also require 014 and 015.
For the current already-installed 013/014 state, follow the dedicated 015 sequence
above instead of repeating this historical installation block.

Three CREATE statements are not an atomic transaction. IF NOT EXISTS supports
resuming an interrupted additive installation but does not fix a wrong existing
definition. On failure, leave existing charts intact and inspect; do not drop,
replace old objects or apply unrelated rollback migrations.

After installed PASS, register/sync the three datasets, add charts and explicitly
extend Match filter scope. Smoke-test Argentina–France, Netherlands–Argentina,
Japan–Croatia and a regulation-only match. Check xG endpoints against team table,
normal counts, extra time, final 4:2 shootout order, no shootout table rows for a
regulation match, and event-level scatter entities. Verify the existing Match
Analysis tables and World Cup Overview remain unchanged. No new chart may silently
combine multiple matches; inspect generated SQL and force-refresh caches.

## Repeatable offline/read-only checks

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-python-tools python tests/integration/test_match_visuals.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_match_analysis.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_stats_cutover.py
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py --candidate
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py --candidate-shot-map
docker compose run --rm --no-deps football-python-tools python -m compileall -q src scripts tests
git diff --check
```

Checks use small synthetic/offline fixtures, SELECT-only live candidate
projections and installed prerequisites, not real S3 or live view replacement.
Current follow-up results: 416 offline tests and 11 SELECT-only integration tests
(6 Stage 4E, 3 Stage 4D, 2 Stage 4C) passed; candidate-shot-map passed with
1453 unique labels and unchanged
Stage 4C/4D/4E totals. Production chart correctness still
requires the manual UI checks. Validators are WC2022-specific; separate SELECTs
are not a cross-table snapshot transaction. No custom plugins or advanced football
metrics are introduced in this stage.
