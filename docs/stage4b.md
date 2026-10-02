# Stage 4B — match results and shootout semantics

Status: implementation/offline and SELECT-only tests prepared; no Gold publication,
serving replacement, migration 007/008 application or Superset dashboard changes performed.

## Diagnostic evidence (2026-10-01)

Read-only ClickHouse audit of the current WC2022 context (43/106), exact loaded build IDs:
[full machine-readable report](stage4b_shot_audit.json). It includes **every affected
team/player grain**, current and corrected shot metrics, all other metric differences,
source build IDs and period counts. Float64 differences retain their actual precision;
the comparison tolerance is 1e-9, not a rounding of stored data.

**Both current Gold v1 datasets include period=5.** Their shot counts/goals/xG agree
with reconstruction from all Silver shots, joined to event_core on
competition_id/season_id/match_id/event_id. This was measured, not assumed from code.

| Period | Shots | Shot goals | xG |
| --- | ---: | ---: | ---: |
| 1 | 607 | 66 | 63.563824478399944 |
| 2 | 801 | 99 | 87.69281401059997 |
| 3 | 20 | 1 | 1.7197741302000003 |
| 4 | 25 | 3 | 2.922129311 |
| 5 | 41 | 26 | 32.1235 |

| Gold dataset | Rows | Shot-affected rows | Any-metric-affected rows | Removed shots / shot goals / xG | Removed event_count |
| --- | ---: | ---: | ---: | --- | ---: |
| team_match_stats | 128 | 10 | 10 | 41 / 26 / 32.1235 | 106 |
| player_match_stats | 3244 | 41 | 53 | 41 / 26 / 32.1235 | 86 |

After correction, normal shot totals are 1453 attempts and 169 shot goals; the
45 extra-time shots remain. Shot goals are not the official match score (own goals
are not reinterpreted). The 106 period-5 events comprise 41 Shot, 41 Goal Keeper,
10 Half Start, 10 Half End and 4 Bad Behaviour. Null-player events explain the
20-event team/player difference. In this snapshot pass_attempts, pressure,
counterpress and players_with_events have zero deltas. v2 still filters period=5
for **all** these metrics, so the semantics do not depend on this sample being zero.
Squad-based output grain and zero-activity players are retained.

For comparison: current v1 totals are 1494 attempts, 195 shot goals and approximately
188.0220419302 xG; normal match xG is approximately 155.8985419302. These are Float64
aggregates; the excluded contribution is 32.1235 xG in both team and player totals.

| match_id | Match | Official score | Shootout goals (home-away) | Attempts (home-away) |
| --- | --- | --- | --- | --- |
| 3869219 | Japan – Croatia | 1-1 | 1-3 | 4-4 |
| 3869220 | Morocco – Spain | 0-0 | 3-0 | 4-3 |
| 3869321 | Netherlands – Argentina | 2-2 | 3-4 | 5-5 |
| 3869420 | Croatia – Brazil | 1-1 | 4-2 | 4-4 |
| 3869685 | Argentina – France | 3-3 | 4-2 | 4-4 |

All five have real period 3/4 events. `went_to_extra_time` is nevertheless derived
from event evidence, never set to true just because penalties exist.

## Immutable Gold match_results_v1

Grain: one row per match. Inputs must be three **explicit registered immutable
Silver build IDs**: matches, event_core, shot_events. No silent latest selection for
this dataset or stats v2. Resolver checks catalog context/identity/location,
manifest identity/checksum/lineage, _SUCCESS and exact part inventory. Spark reads
only those parts, verifies counts/context/match membership, domain/core event keys,
type, team, player and period. Event domains must share exact Bronze event lineage.

Gold location:

```text
football/gold/statsbomb/match_results/competition_id=43/season_id=106/build_id=<sha256>/
  part-*.snappy.parquet
  _SUCCESS
  _manifest.json
```

One output partition. Existing immutable publisher/recovery/read-back and
metadata.gold_builds registration are reused. No overwrite/delete path.
Fingerprint includes canonical dataset/build_id/transform_version/schema_sha256/
bucket/prefix of all three inputs. Gold build identity includes that fingerprint,
source/layer/dataset/context, match_results_v1 and output schema SHA-256.
Timestamps and runtime state do not affect identity. v1 stats identities/defaults
remain unchanged; explicitly selected v2 has a different transform_version/build_id.

### Output schema

| Columns | Spark | ClickHouse |
| --- | --- | --- |
| competition_id, season_id | Long | UInt32 |
| match_id | Long | UInt64 |
| match_date | Date | Date |
| kick_off | String | String |
| competition_stage_id | Long | UInt16 |
| competition_stage_name | String | LowCardinality(String) |
| home_team_id, away_team_id | Long | UInt32 |
| home_team_name, away_team_name | String | LowCardinality(String) |
| home_score, away_score | Integer | UInt16 |
| went_to_extra_time, went_to_penalties | Boolean | Bool |
| home_shootout_attempts, away_shootout_attempts | Long | UInt64 |
| home_shootout_goals, away_shootout_goals | Long | UInt64 |
| winner_team_id | nullable Long | Nullable(UInt32) |
| winner_team_name | nullable String | Nullable(String) |
| result_method | String | LowCardinality(String) |
| display_score | String | String |
| gold_build_id (loader-added) | — | FixedString(64) |
| loaded_at (server-added) | — | DateTime64(3, 'UTC') |

Official scores and other selected matches columns are preserved exactly. For a
non-shootout all four shootout counts are **non-null zero** (one explicit contract).
For period=5 Shot events one exact event is one attempt; `outcome_id=97` is Goal,
as in the actual Silver schema/fixtures. Non-null outcome_name must agree with the ID.
Missed/saved shots count as attempts, not goals. No 90-minute-score reconstruction.

Winner is determined by shootout goals when penalties exist, otherwise by official
home_score/away_score. A non-shootout tied score has NULL winner ID/name.

- PENALTIES: at least one period-5 Shot exists; unequal shootout goals determine winner.
- EXTRA_TIME: no shootout, period 3/4 evidence, winner exists.
- REGULATION: no shootout or extra time, winner exists.
- DRAW: no winner (including an extra-time draw if present in a different source context).

Display uses an **ASCII hyphen**, e.g. `2-0` and `3-3 (4-2 pens)`. Numeric columns
are authoritative. Never sum the two scores into a fictional `7-5`.
Winner does not infer subsequent tournament advancement.

### Hard DQ and diagnostics

Nonempty unique match grain; full matches coverage; exact preservation of source
columns; context/required non-null fields; different home/away teams; nonnegative
scores/counts; shootout goals <= attempts. Shootouts require both teams' attempts,
unequal goal counts, tied main score and a winner. Non-shootouts require zero
shootout counts. Winner ID/name, result_method and display must agree with their
numeric inputs. Duplicate/missing domain events and mismatched teams/periods fail.
`penalties_without_extra_time` is an informational count, not a hardcoded assertion
that every competition must use extra time. No collecting event data to Python.

## Serving and BI changes

[007](../infrastructure/clickhouse/migrations/007_create_match_results.sql) creates
MergeTree football.match_results, partition (competition_id,season_id), order
(competition_id,season_id,match_date,match_id). Safe casts, non-replicated dedup
window and existing Gold loader lock/registration/idempotency/recovery are retained.
CLI adds `--dataset match-results`; exact `--build-id` is recommended.
Another build in the same serving context still fails, for results and stats v2.

[008](../infrastructure/clickhouse/migrations/008_enrich_bi_match_results.sql) replaces
only the two ordinary BI views, retaining SQL SECURITY INVOKER. It joins the
authoritative match_results on all three match keys and exposes flags, shootout
goals, winner, result_method, display_score. No independent shootout derivation.
**Apply only after match_results covers every context served by these views**:
an INNER JOIN otherwise hides rows. Both replacements are separate DDL statements,
not one atomic multi-view transaction: use a BI maintenance window and validate both.

`bi_team_match_stats.match_result` now means W/D/L **including the shootout winner**,
derived from match_results.winner_team_id. goals_for/goals_against/goal_difference
still describe the official main score: a shootout winner can have difference 0.
This intentional semantic change must be communicated to chart consumers.
The old Stage 4A score-derived W/D/L SQL check is not suitable after 008; use
`check_clickhouse_match_results.py --bi` instead. It checks current registered Gold/
Silver lineage, result DQ, coverage, source values, extra-time/shootout counts and
both enriched view grains/authoritative fields. It does not call S3.

## Controlled v1 → v2 serving cutover plan (NOT applied)

No `--force`, DELETE, TRUNCATE, partition replacement or mixed builds in one table.
Publishing v2 is **not** permission to replace v1 serving rows.

1. Freeze writers and record exact currently served Silver/Gold IDs, row counts,
   catalog records, view DDL and dashboard/export backup. Complete read-only v1
   model checks and the audit. Preserve immutable v1 artifacts and serving tables.
2. Build/publish team_match_stats_v2 and player_match_stats_v2 from the **same pinned
   four Silver inputs**, with only period 5 removed. Validate full read-back/DQ and
   deltas against the recorded audit. Extra-time metrics must remain.
3. In a separately reviewed cutover migration, create empty parallel serving tables
   `football.team_match_stats_v2` and `football.player_match_stats_v2` with exactly the
   existing schema/engine/settings. Load each exact v2 build using the existing Gold
   state machine with a fixed, reviewed GoldSpec `table_override` for that table and
   `version='v2'`. Register metadata.clickhouse_gold_loads with the **actual versioned
   target table**; never rewrite v1 catalog records. The existing CLI intentionally
   has no arbitrary table override. This step needs the reviewed cutover entrypoint,
   not a hand-written ad-hoc INSERT or disabling the one-build guard.
4. Validate the shadow tables' exact row/grain/content and registered lineage, run
   v2 model comparisons (`period != 5`, retaining periods 3/4), compare all metric
   deltas, and verify results/BI coverage. Do not compare v2 to unfiltered v1 totals.
5. Pause BI traffic; save both current view definitions. In a reviewed follow-up BI
   migration point **both** views to their versioned v2 tables, retaining the same
   public view names and match_results join. Revalidate both before resuming traffic.
   Do not assume two CREATE OR REPLACE statements are atomic. Clear/refresh Superset
   chart caches and verify filters/metrics.
6. Rollback: while BI is paused restore both saved view definitions pointing to v1,
   validate and refresh caches. Original v1 tables/artifacts/catalog records remain
   intact. Retaining old data is intentional; retirement is a separate task.

This historical plan is now implemented by [Stage 4C](stage4c.md), **not applied
automatically**. `load_clickhouse_gold.py --transform-version v2 --build-id ...`
maps only to the fixed `_v2` shadow table and requires the audited Silver snapshot.
The model-check CLI v2 mode checks these same shadow targets. Follow the Stage 4C
PowerShell runbook for migrations 009/010 and explicit rollback 011; do not use
ad-hoc INSERTs or destructive workarounds. No live v2 serving success is claimed.

## Manual commands (PowerShell)

### Safe diagnostics and offline tests — no S3

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python scripts/audit_shootout_semantics.py
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-spark spark-submit tests/spark/test_match_results.py
docker compose run --rm --no-deps football-spark spark-submit tests/spark/test_gold_match_stats.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_match_results.py
git diff --check
```

### Explicit manual S3 read/publish — not executed by Codex

The following IDs are the audited serving snapshot, **not secret values**. Check
that they remain the intended context; do not silently substitute latest builds.
Even `--check-only` here reads real Selectel; running these commands is your explicit
manual decision. Publisher without --check-only writes a new immutable Gold build.

```powershell
$eventBuild = 'f62c4943ef505dc56ce02b4c1724fedd69cfc773b23a8f3a1b6cf575bf2f526d'
$matchesBuild = 'e9949f2c1c976fc6b21b25ed99c3206e62b7e64dbd3fec663ed67e0bd54e0c7b'
$shotBuild = 'a67da8f5404c02ce557f6f2a5c8a95e052ecaeb5e8e8b5ac271c9bb5c4992584'
$squadBuild = 'e00cc4605530a68a791981771b75c26f283bba55070014c33db27f4bed0443bd'
$passBuild = '635dc7e21a3e07793c3d7129c2263dccebfa3fea13956225a574b2a94d45553a'

$resultArgs = @('--dataset','match-results',
    '--silver-build',"matches=$matchesBuild",
    '--silver-build',"event_core=$eventBuild",
    '--silver-build',"shot_events=$shotBuild")
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py @resultArgs --check-only
if ($LASTEXITCODE -ne 0) { throw 'Result check-only failed' }

# Separate deliberate publication, after inspecting the check-only output:
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py @resultArgs
if ($LASTEXITCODE -ne 0) { throw 'Result publication failed' }
```

Check expected 64 result rows, 5 PENALTIES and the final display; use the new build ID
printed by the publisher, never an invented hash. Optional v2 preparation:

```powershell
$statsInputs = @('--silver-build',"event_core=$eventBuild",
    '--silver-build',"match_squads=$squadBuild",
    '--silver-build',"pass_events=$passBuild",
    '--silver-build',"shot_events=$shotBuild")
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py --dataset team-match-stats --transform-version team_match_stats_v2 @statsInputs --check-only
if ($LASTEXITCODE -ne 0) { throw 'Team v2 check failed' }
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py --dataset player-match-stats --transform-version player_match_stats_v2 @statsInputs --check-only
if ($LASTEXITCODE -ne 0) { throw 'Player v2 check failed' }
```

Only after approval to publish immutable v2 artifacts, rerun those exact two commands
without `--check-only`. This still does not perform a ClickHouse serving cutover.

### Manual migration 007 and results load — not executed by Codex

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\007_create_match_results.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 007 failed' }

$resultBuild = Read-Host 'Exact match_results Gold build ID printed by the successful publisher'
if ($resultBuild -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid Gold build ID' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset match-results --build-id $resultBuild --check-only
if ($LASTEXITCODE -ne 0) { throw 'Result load preflight failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset match-results --build-id $resultBuild
if ($LASTEXITCODE -ne 0) { throw 'Result load failed' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_results.py
if ($LASTEXITCODE -ne 0) { throw 'Result serving validation failed' }
```

A second identical load should report UNCHANGED / ALREADY_LOADED and ALREADY_REGISTERED.
On an INSERT timeout wait for the server query to finish before retrying; no cleanup.

### Manual BI migration 008 — only after complete result coverage

Pause dashboard use, preserve existing view DDL, and first pass result validation.
For any context beyond 43/106, validate that context too before applying global views.
The existing stats v1 can remain served while result semantics are enriched; label
shot/xG charts as v1 including shootouts until the separately approved v2 cutover.

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\008_enrich_bi_match_results.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 008 failed; keep BI paused and review both views' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_results.py --bi
if ($LASTEXITCODE -ne 0) { throw 'Enriched BI validation failed' }
```

## Superset Match Table (manual UI only)

Add dataset `football.match_results` for one-row-per-match presentation, or use the
enriched views only at their own team/player grain. Refresh columns after 008.
Do not count rows of a team/player view as matches.

Table columns: match_date, competition_stage_name, home_team_name, away_team_name,
display_score, result_method. Example: Argentina | France | `3-3 (4-2 pens)` | PENALTIES;
France | Poland | `3-1` | REGULATION. Keep match_date a real **Date**; in Table column
formatting set the D3 date format **`%Y-%m-%d`** (or your preferred display equivalent).
Do not convert Date to String to hide midnight. Preserve temporal filters and sorting.
No Match Analysis dashboard is created in Stage 4B.
