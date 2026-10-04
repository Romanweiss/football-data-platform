# Stage 6B-F — Superset multi-context safety

## Before-change audit (2026-10-04)

The 6B onboarding added 34 Leverkusen fixtures (9/281) beside 64 World Cup
fixtures (43/106). Generic serving views correctly expose 98 matches; Superset's
World Cup Overview had no permanent context restrictions. Clearing Stage, Date
or Team therefore admitted both contexts. No ClickHouse data needs changing.

| Dashboard / chart | ID | Dataset ID / physical view | Existing restriction | Native scope / mixing risk |
| --- | --- | --- | --- | --- |
| WC / Total Matches | 1 | 2 / bi_team_match_stats | match_date: No filter | Stage/Date/Team ROOT, no exclusions; unsafe |
| WC / Team Total xG | 2 | 2 / bi_team_match_stats | match_date: No filter | same; unsafe |
| WC / Team Total Shots | 3 | 2 / bi_team_match_stats | match_date: No filter | same; unsafe |
| WC / Team Pass Attempts | 4 | 2 / bi_team_match_stats | match_date: No filter | same; unsafe |
| WC / Shots vs xG by Team | 5 | 2 / bi_team_match_stats | match_date: No filter | same; unsafe |
| WC / Top Players by xG | 6 | 3 / bi_player_match_stats | match_date: No filter | same; unsafe |
| WC / Top Players by Shots | 7 | 3 / bi_player_match_stats | match_date: No filter | same; unsafe |
| WC / Match Table | 8 | 2 / bi_team_match_stats | match_date: No filter | same; unsafe |
| Match / Match Header | 9 | 5 / bi_match_overview | match_date: No filter | Match ROOT, stored chartsInScope only [9]; unsafe |
| Match / Team Comparison | 10 | 6 / bi_match_team_stats | none | same; unsafe |
| Match / Player Stats | 11 | 7 / bi_match_player_stats | match_date: No filter | same; unsafe |
| Match / Shots | 12 | 8 / bi_match_shots | is_shootout=0 | same; unsafe |
| Match / Penalty Shootout | 13 | 11 / bi_match_shootout | none | same; unsafe |
| Match / Shootout Summary | 14 | 5 / bi_match_overview | result_method=PENALTIES | same; unsafe |
| Match / xG Race | 15 | 12 / bi_match_xg_race_series | none | same; unsafe |
| Match / Shot Map | 16 | 10 / bi_match_shot_map | match_date: No filter | same; unsafe |

Every dataset has filterable competition_id, season_id and match_id. All seven
Match Analysis datasets also have match_label. No identity migration is needed.
All nine datasets are physical; no virtual SQL or RLS enforces context.
The old Match native filter was single-select on match_label, creatable, without
a default or a query-side selected-match guard. Today's unique display labels
are not a future platform-wide identity guarantee.

## Implemented live contract

Applied in the existing Superset metastore on 2026-10-04, without any ClickHouse
DDL/DML or migration. [Before snapshot](stage6b-superset-before.json) contains
only scoped dashboard/chart/dataset configuration, not database connection URLs,
passwords, users or environment values.

### World Cup Overview

Approach B: every chart 1–8 now has a permanent custom-SQL WHERE condition:

```sql
competition_id = 43 AND season_id = 106
```

The same guard is recorded in both chart form_data and every saved query context.
The original metrics, native-filter configuration, visuals and analytical
conditions are preserved. Clearing native filters cannot remove a saved chart
condition; additional filters intersect it, never broaden it. Chart editors are
trusted administrators and can intentionally change this semantic contract;
ordinary dashboard users cannot remove it using Stage/Date/Team controls.

Datasets 2 and 3 retain their physical generic views. Their Superset-only
`fetch_values_predicate` has the same WC condition, so Stage/Team option queries
do not offer foreign-context values. This predicate alone is NOT the chart data
safety mechanism. A future platform-wide dashboard should use separate generic
Superset dataset descriptors for its filter options, not remove these WC guards.

### Match Analysis

Added a Superset calculated STRING column `match_identity` to existing datasets
5,6,7,8,10,11,12 (not a physical ClickHouse column):

```sql
concat(toString(competition_id), '/', toString(season_id), '/',
       toString(match_id), ' | ', match_label)
```

The existing Match selector now uses this value, displays the readable label
along with its full-key prefix, disallows invented/multiple/inverse selection,
and explicitly scopes all eight charts 9–16. The initial selection is
`43/106/3869685 | 2022-12-18 | Argentina - France`. No dashboard layout changed.
Old URLs/bookmarks with only match_label do not bypass the new guard: reselect
the new identity to display data.

Every Match chart also has a permanent Jinja WHERE guard using
`get_filters('match_identity')`. Exactly one IN filter with exactly one value
renders the full identity expression IN the dialect-escaped value. Missing,
multiple, inverse or contradictory filters render `0 = 1`. A forged nonexistent
or foreign-combination key matches no rows. No raw user text is interpolated into
SQL. Default selection/required-filter UI are convenience, NOT the safety boundary.
Even after clearing the selector, the query cannot aggregate across matches.

Superset `ENABLE_TEMPLATE_PROCESSING` is enabled for this guard. Inspection found
one active user, with only the Admin role. Template/chart editing must remain
trusted-admin-only: templating is not safe for untrusted SQL editors. See the
[Superset 6.0 templating contract](https://superset.apache.org/user-docs/6.0.0/configuration/sql-templating/).
No url_param, dynamic identifier interpolation or new template functions added.
The image was rebuilt and only football-superset recreated/health-checked;
no init service, migration, other project or data pipeline was started.

## Live SELECT-only validation evidence

[`scripts/superset_semantic_safety.py`](../scripts/superset_semantic_safety.py)
validates exact persisted form_data/query-context guards, selector scope and
calculated-column contracts, then uses the installed Superset 6.0 compiler and
executor against the existing SELECT-only ClickHouse reader. It exercises the
real chart-data request's first-query filter path (not a handwritten SQL-only
approximation or a visual-only check). Every original saved chart query also
executes successfully with the persisted analytical conditions preserved.
Full measured output: [validation evidence](stage6b-superset-validation.json).

Overview results:

| Chart | Result |
| --- | --- |
| 1 Total Matches | **98 before → 64 after** |
| 2 Team Total xG | 32 WC teams only |
| 3 Team Total Shots | 32 WC teams only |
| 4 Team Pass Attempts | 32 WC teams only |
| 5 Shots vs xG by Team | 32 WC teams only |
| 6 Top Players by xG | 20 WC player display rows only |
| 7 Top Players by Shots | 20 WC player display rows only |
| 8 Match Table | 64 WC match display rows only |

All eight individually resolve only 43/106 with native filters cleared.
All eight also pass with Stage=Final, Team=Argentina and Date=2022-12-18 together;
the player datasets resolve 26 Argentina squad records and team datasets one
team-match. Native Team options for both datasets contain exactly 32 WC teams.
WC aggregates remain 1453 normal shots, 68515 passes and xG 155.8985419302.
Selecting Bayer Leverkusen yields zero eligible rows in each WC chart. The
generic view still contains its real match 9/281/3895052 and all 34 new matches:
Bundesliga was excluded by dashboard semantics, not deleted from serving.

Match Analysis independently passes for:

| Dataset / section | Argentina–France 43/106/3869685 | Leverkusen–Leipzig 9/281/3895052 |
| --- | --- | --- |
| overview | 1 row | 1 row |
| team stats | 2 rows | 2 rows |
| player stats | 50 rows | 40 rows |
| raw shots | 38 incl. 8 shootout | 25 |
| xG race states | 60 (30 normal shots × 2) | 50 (25 × 2) |
| shot map / existing normal-shots chart | 30 | 25 |
| shootout | 8 | 0 |

Each of eight charts was tested with empty, WC, Bundesliga, both selected and an
invalid mixed-context identity. There are no foreign full keys in any result.
The original Shots is_shootout=0 and Shootout Summary result_method=PENALTIES
restrictions remain unchanged; Bundesliga's actual Shootout Summary is empty.
The identity probe intentionally counts all raw shots separately from the
original chart's filtered rows. Identical display labels across contexts are
tested offline and produce different predicates; labels are never sole identity.

All nine generic BI views remain physical/multi-context. Grouped counts match
the Stage 6B baselines: 34+64 overview matches, 68+128 team rows, 1353+3244 player
rows, 916+1494 raw shots, 1832+2906 race states, 916+1453 map shots.
Shootout has only WC's 41 rows because Bundesliga has no shootout, not because
its view was globally scoped. No Bronze/Silver/Gold, formulas, API or React changed.

## Reproducible commands

Run from the project root in PowerShell. Validation is read-only by default;
only explicit `--apply` commits a single scoped Superset metadata transaction.
The validator skips Superset's theme-seeding startup hook and query-log INSERTs,
and enforces a PostgreSQL read-only transaction. It never exports connection
credentials or raw exception text.

```powershell
# Existing image rebuilt for the single Superset configuration flag:
docker compose build football-superset

# Explicit, idempotent live metadata mutation (already executed):
docker compose run --rm --no-deps -v "${PWD}:/workspace:ro" --entrypoint python football-superset /workspace/scripts/superset_semantic_safety.py --apply
docker compose up -d --no-deps --wait football-superset

# Recommended subsequent check: no writes/publish/ingestion:
docker compose run --rm --no-deps -v "${PWD}:/workspace:ro" --entrypoint python football-superset /workspace/scripts/superset_semantic_safety.py --validate

docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=${PWD},target=/workspace,readonly" --entrypoint python football-superset:6.0.0 /workspace/tests/superset/test_semantic_safety.py
docker compose config -q
git diff --check
```

Tests: all 464 offline tests PASS (455 existing + 9 metadata contract tests);
six Superset-image offline Jinja/dialect tests PASS, including same-label
different-context identity, cleared/multiple/inverse selection and quote injection.
SELECT-only live chart/native/identity/generic/WC aggregate checks PASS.
Existing WC Stage 4C/4D/4E installed-view regression
(`scripts/check_clickhouse_match_visuals.py`) also PASS, including 1453 normal
shots, 41 shootout attempts, 2906 race states and exact v2 affected-key checks.
An independent before/after comparison of all sixteen charts proves that the
metrics, visual properties, original analytical filters and other saved-query
fields are unchanged; dashboard layouts, WC native filter metadata and physical
dataset references are unchanged. Only the documented guards, Match selector,
calculated identity columns and native-options predicates differ.
Compose config and diff whitespace checks PASS. No migrations, destructive
commands, credentials reads/prints, commit or push.

## Remaining limitations / Stage 6C readiness

The identified cross-context safety blocker is resolved. Ready to proceed to
Stage 6C without changing serving semantics. Browser visual acceptance was not
used as the evidence for this task: checks compile and execute persisted charts.
Refresh existing browser tabs to discard old in-memory dashboard/filter state.
Any later edit to charts, datasets, scope or feature flags must rerun the checker.
Calculated identity includes the display label, so an upstream label correction
can invalidate an old bookmark safely (empty data), never merge contexts.
This is semantic dashboard safety, not tenant security or an RLS authorization
system. Admins can deliberately edit contracts. Existing local/dev CSP and
in-memory limiter warnings remain outside this BI-semantic task.

A future generic multi-competition dashboard may use cascading
Competition → Season → Match full-key native filters, with its own Superset
dataset descriptors and the same fail-closed final selection guard. It is NOT
built here. World Cup Overview remains intentionally fixed to 43/106.
