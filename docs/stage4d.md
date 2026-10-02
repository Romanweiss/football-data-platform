# Stage 4D — Match Analysis foundation

Status: implementation and offline/read-only verification only. Migration 012 has
**not** been applied by Codex; the new Superset datasets/dashboard are manual work.
Stage 4C v2 serving was verified read-only before implementing this layer.

## Architecture and grains

No new lake layer, Gold transform, S3 artifact, service or metric recomputation.
All four objects are ordinary `SQL SECURITY INVOKER` ClickHouse views. They are
separate from the existing World Cup 2022 Overview public contract.

| New view | Grain (with competition_id, season_id) | Source | WC2022 rows |
| --- | --- | --- | --- |
| `football.bi_match_overview` | match_id | match_results + matches metadata | 64 |
| `football.bi_match_team_stats` | match_id, team_id | bi_team_match_stats + overview label | 128 |
| `football.bi_match_player_stats` | match_id, team_id, player_id | bi_player_match_stats + overview label | 3244 |
| `football.bi_match_shots` | match_id, event_id | shot_events + overview context | 1494 |

`match_results` is authoritative for overview date/kickoff/stage/team information,
official score, extra time, shootouts, attempts/goals, winner, result_method and
display_score. `matches` adds only match_week, stadium_id/stadium_name and
referee_id/referee_name. Those nullable fields keep their source names and types.

Team/player views explicitly preserve all current public BI columns, including
team/opponent/is_home and existing match/result metadata. Player grain remains
squad-based, including zero-activity players. The upstream public views remain on
v2; migration 012 does not replace them or touch any v1/v2 table.

All joins use `(competition_id, season_id, match_id)`, never names. Shots require
no join to event_core: all needed timing, event_index, team/player and coordinate
fields already exist in shot_events. The full shot identity checked for uniqueness
and preservation is `(competition_id, season_id, match_id, event_id)`.

## Actual shot fields and semantics

Inspected migrations 001–011 and live SHOW CREATE for matches, match_results,
event_core, pass_events, shot_events, both v2 stats tables and both public BI views.
The existing Silver projection maps the original event location to **start_x,
start_y**, not location_x/location_y, in shot_events.

The shot view keeps every business column from shot_events:

- identity: competition_id, season_id, match_id, event_id (UUID), event_index;
- timing: period, timestamp (String), minute, second;
- team_id/team_name and nullable player_id/player_name;
- statsbomb_xg (Float64), outcome_id/outcome_name;
- body_part_id/name, shot_type_id/name, technique_id/name, key_pass_id;
- start_x/start_y, end_x/end_y/end_z (Nullable(Float64));
- first_time, open_goal, one_on_one, aerial_won, deflected (nullable flags).

No nonexistent coordinate aliases are invented, no Float32 casts and no NULL
replacement with zero/empty text. Silver already selects Shot events; an extra
event-type join/column is unnecessary. Provenance columns silver_build_id/loaded_at
are infrastructure fields and are not exposed as chart dimensions.

Additional context comes from overview: match_label, match_date, stage name,
display_score, result_method, went_to_extra_time, went_to_penalties, winner ID/name.
Match outcome is never derived from individual shots. Where validation counts
shootout goals it uses the existing stable `outcome_id = 97`, not outcome_name.

| Period | is_shootout | is_extra_time | Performance chart |
| --- | --- | --- | --- |
| 1 / 2 | 0 | 0 | Include |
| 3 / 4 | 0 | 1 | Include: extra time |
| 5 | 1 | 0 | Exclude; separate shootout chart |

**The shot view does not filter out period 5.** Every user-facing normal shot
table/map/xG chart must have a chart-level `is_shootout = 0` filter. A separate
shootout chart uses `is_shootout = 1` and must be clearly labelled. Never apply the
normal-shots filter to that separate chart or to match-result presentation.

WC2022 totals (43 / 106): 1494 raw shots = 1453 normal + 41 shootout; five shootout
matches; 45 extra-time shots are included in normal shots. xG: normal
155.8985419302, shootout 32.1235, raw 188.0220419302. Float64 aggregate comparisons
use existing relative/absolute tolerance 1e-9. Source values compare exactly,
including NULLs; tolerance does not excuse changed individual metrics.

## Shared Match filter

The label is computed **once**, in bi_match_overview:

```sql
concat(toString(r.match_date), ' | ', r.home_team_name, ' - ', r.away_team_name)
```

The other three views select `o.match_label` from that overview. Format:
`2022-12-18 | Argentina - France`, using an ASCII hyphen, no score. Date remains
a separate Date column. Every view exposes competition_id, season_id, match_id
and the same String match_label. Identity remains the numeric/full match key.

Labels must be nonempty, identical across all four relations and unambiguous
within the selected competition/season. The checker fails on label collision.
Do not use this convenience string as a data-model join key. Other tournaments
may contain label collisions and require a separately reviewed filter convention.

## Read-only validation

`scripts/check_clickhouse_match_analysis.py` first requires current Stage 4C
`--mode bi-v2` validation, including catalog/lineage and match_results checks.
Then it checks all four Match Analysis views:

- exact row counts, unique full grains, 64-match coverage and two teams per match;
- no missing/orphan matches; each team belongs to that match's home/away pair;
- full ordered schemas/types, preserving player and coordinate nullability;
- overview equals authoritative result columns plus allowed match metadata;
- every team/player source column and every shot business column is preserved
  at its full key, not merely tournament totals;
- labels, all period flags, finite xG, normal/shootout/extra-time counts and xG;
- known shootout IDs 3869219, 3869220, 3869321, 3869420, 3869685 exactly match
  match_results, with per-match/per-side attempts and goals checked;
- source schemas/contents are unchanged across the check.

All new queries have `readonly=1`. Only the small WC2022 result relations are
collected (maximum 10000 rows per relation, fail closed above that); the checker
does not collect all event_core or access S3. Driver exceptions are reported by
stage/class without raw exception text or credentials.

`--candidate` evaluates the exact SELECT bodies of unapplied migration 012 using
subqueries. It issues no CREATE and requires no new views. A candidate PASS proves
the SQL/schema/data projection on current sources, **not** that migration 012 has
been applied. Without the flag, the checker requires the actual installed views.
Validation is scoped to current WC2022, not arbitrary competitions. Keep writers
idle while checking: separate SELECT queries are not a cross-table transaction.

## Manual live sequence A–D (PowerShell)

Run each block deliberately from the project root. No Docker restart is required.

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose config failed' }

# A: verify current v2 serving and both existing Overview BI views.
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v2
if ($LASTEXITCODE -ne 0) { throw 'Stage 4C prerequisite failed; STOP' }

# B: inspect additive migration and preview SELECTs without installing anything.
Get-Content -Raw .\infrastructure\clickhouse\migrations\012_create_match_analysis_views.sql
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_analysis.py --candidate
if ($LASTEXITCODE -ne 0) { throw 'Candidate validation failed; STOP' }
```

**STOP:** review counts, confirm the four new object names and no changes to the
existing Overview contract. Only then apply manually:

```powershell
# C: host stdin, NOT a nonexistent container /migrations path.
Get-Content -Raw .\infrastructure\clickhouse\migrations\012_create_match_analysis_views.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 012 failed; STOP before Superset setup' }

# D: installed views, not candidate mode.
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_analysis.py
if ($LASTEXITCODE -ne 0) { throw 'Installed Match Analysis validation failed; STOP' }
```

The four CREATEs are not an atomic transaction. IF NOT EXISTS allows resuming an
interrupted additive installation but does not repair an existing wrong view.
If anything fails, leave the World Cup dashboard untouched, do not add new charts,
inspect the new definitions and resolve the cause. Do not drop/replace old views
or blindly run other migrations (especially Stage 4C rollback 011).

## E–I. Manual Superset setup and planned dashboard

Use the existing ClickHouse connection/read-only superset_reader, not an admin or
a new connection with broader privileges. Existing SELECT ON football.* covers
the new views; SQL SECURITY INVOKER retains caller permissions. Do not edit the
existing World Cup dashboard, datasets, charts or native filter scopes.

1. **E:** register four new physical datasets under schema `football`:
   bi_match_overview, bi_match_team_stats, bi_match_player_stats, bi_match_shots.
2. **F:** sync columns and inspect types. Set match_date as temporal/default time
   column; keep match_label filterable. No calculated rewrite of match_label.
3. **G:** create a separate dashboard named **Match Analysis**. Create new charts,
   do not reuse/edit charts belonging to World Cup 2022 Overview.
4. **H:** create a native Select filter named **Match**, source bi_match_overview,
   column match_label. Use single selection, a default match (the final), and
   require a selection. Scope explicitly to every Match Analysis chart across
   all four datasets. Verify generated query predicates rather than assuming
   same-named columns automatically link all datasets.
5. For this foundation, every chart uses competition_id=43 and season_id=106;
   time range is No filter or the full 2022 tournament, not a recent relative
   range. Keep filter scopes restricted to this new dashboard.
6. **I:** build the initial layout below, then force-refresh chart caches.

| Section/chart | Dataset | Fields / settings |
| --- | --- | --- |
| Header (one-row raw Table) | bi_match_overview | match_label, competition_stage_name, match_date, display_score, result_method |
| Team comparison (Table) | bi_match_team_stats | team_name, goals_for, shot_count, shot_xg, pass_attempts, under_pressure_events, counterpress_events |
| Player table | bi_match_player_stats | player_id, player_name, team_name, shot_count, shot_xg, pass_attempts, event_count |
| Normal shots (raw Table) | bi_match_shots | minute, second, team_name, player_name, statsbomb_xg, outcome_name, period; **is_shootout=0** |
| Optional separate shootout table | bi_match_shots | same shot fields; **is_shootout=1**, title clearly says penalty shootout |

Use raw records for the first implementation to avoid unintended extra
aggregation; if using aggregate mode, group by stable IDs as well as display names.
Do not use a player-name-only grouping or `event_count > 0` to remove substitutes.
Sort shots by period, event_index, event_id; minute/second are exposed for display
and future work, not a unique event order. Row limits must not truncate a selected
match's squad or shots. Use D3 date display `%Y-%m-%d`, not Date-to-String conversion.

Coordinates support planning a later Shot Map using start_x/start_y, but Stage 4D
does not implement a pitch visualization. Nullable coordinates must not be drawn
as (0,0); orientation/axis scale, pitch overlay and plugin support require explicit
verification later. Timing/xG/event_index are sufficient inputs for later xG-race
evaluation; no cumulative window metric is precomputed here.

## J–K. Smoke checks and existing dashboard regression

Select each match through the native filter and verify all four datasets' charts
change together (inspect View query/filter predicates):

- Argentina – France final: `2022-12-18 | Argentina - France`,
  `3-3 (4-2 pens)`, PENALTIES; normal charts include extra time but exclude shootout.
- Netherlands – Argentina: `2-2 (3-4 pens)`, PENALTIES.
- Japan – Croatia: `1-1 (1-3 pens)`, PENALTIES.
- A regulation-only match such as France – Poland: `3-1`, REGULATION, no shootout
  rows; empty shootout chart is expected, not a broken filter.

Each selection should show one header row and two team rows. Check squad players
with zero activity, nullable source values and the distinction between official
score/goals_for and shot_goals. Do not infer match winner from tied main scores.

**K:** open World Cup 2022 Overview unchanged and verify existing filters, charts
and result display. Full-tournament performance remains 1453 shots, 169 shot goals,
xG approximately 155.8985419302 and 68515 passes. Repeat the Stage 4C checker:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v2
if ($LASTEXITCODE -ne 0) { throw 'Existing Overview regression; STOP' }
```

## Repeatable offline / read-only tests

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-python-tools python tests/integration/test_match_analysis.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_stats_cutover.py
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_analysis.py --candidate
docker compose run --rm --no-deps football-python-tools python -m compileall -q src scripts tests
git diff --check
```

No command in this test block publishes or reads S3, installs views or changes
Superset. Synthetic fixture tests cover corruption/NULL/flags/grain/label cases;
integration tests use SELECT-only candidate relations and reject missing join
keys or accidental period-5 filtering. New ordinary views and Superset UI behavior
still require manual installation/verification above. No pass networks, heatmaps,
possession chains, advanced metrics, inferred positions/XI or animations are built.
