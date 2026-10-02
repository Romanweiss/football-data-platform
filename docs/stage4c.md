# Stage 4C — safe stats v2 shadow serving cutover

Implementation and offline/read-only verification only: **no live cutover has been
performed by Codex**. Run the blocks below manually, in order, from
`F:\Learning_projects\football-data-platform`. Do not paste the whole runbook as
one unattended script. Stop on every nonzero exit code or unexpected result.

## Contracts and safety

| Dataset / loader version | Fixed ClickHouse target |
| --- | --- |
| team-match-stats / v1 (default) | football.team_match_stats |
| player-match-stats / v1 (default) | football.player_match_stats |
| team-match-stats / v2 | football.team_match_stats_v2 |
| player-match-stats / v2 | football.player_match_stats_v2 |

The closed registry accepts no arbitrary CLI table override. v2 requires an exact
Gold build ID and the four reviewed Silver input IDs below. Manifest/S3 validation,
safe casts, source row counts, writer lock, occupied-context protection, recovery
and idempotency remain in the existing loader. An occupied v1 table does not block
its separate v2 target; a conflicting build already occupying v2 still fails.

Migration 009 creates only the two shadow tables, matching v1 columns, MergeTree,
partitioning, ordering and current settings (deduplication window 1000,
index_granularity 8192). Existing PostgreSQL `metadata.clickhouse_gold_loads`
already records the actual database/table and has a unique
`(clickhouse_database, clickhouse_table, gold_build_id)` key. No catalog migration,
record rewrite or second metadata system is needed. All v1 artifacts, rows and
catalog history remain rollback assets.

v2 transformation semantics are unchanged: filter input events with `period != 5`,
including generic pass filtering; retain periods 3/4 and zero-activity squad
players. Version participates in deterministic build identity, so immutable v2
publication does not overwrite v1 prefixes.

The validator checks registered pinned lineage, row counts 128/3244, 64 matches,
unique grains, all values reconstructed independently from serving Silver, and
orphan match/team/player references. Every grain/metric delta is compared with
`stage4b_shot_audit.json`, including zero deltas outside the affected set. Expected:

- affected team keys 10; player keys with any metric change 53 (41 shot/xG keys);
- removed event_count: team 106, player 86;
- both datasets: shots 1453, shot goals 169, xG approximately 155.8985419302;
- pass attempts, pressure and counterpress unchanged; extra time retained;
- existing Float64 tolerance (relative/absolute 1e-9), exact integer comparisons.

`shadow` validates v2 without changing/depending on the current BI view source.
`bi-v2` additionally verifies both view sources, full ordered public column/type
contracts, coverage and values including authoritative match_results fields.
`bi-v1` validates current/rollback v1 without requiring shadow tables.

## Preparation — read-only

Use a dedicated PowerShell session. Keep writers stopped by operational agreement
through validation/cutover; do not run Docker down. These checks are scoped to
competition 43 / season 106. The views themselves are global: if other contexts
are served, **STOP** and extend/review their shadow coverage before switching.

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v1
if ($LASTEXITCODE -ne 0) { throw 'Baseline validation failed' }

@'
from contextlib import closing
from src.common.clickhouse import create_clickhouse_client
with closing(create_clickhouse_client()) as client:
    for table in ('team_match_stats', 'player_match_stats', 'match_results'):
        rows = client.query('SELECT competition_id, season_id, count() FROM football.' + table + ' GROUP BY competition_id, season_id', settings={'readonly': 1}).result_rows
        print(table, rows)
        if not rows or any(tuple(row[:2]) != (43, 106) for row in rows):
            raise SystemExit('STOP: unexpected serving context; review global view coverage')
'@ | docker compose run --rm -T --no-deps football-python-tools python -
if ($LASTEXITCODE -ne 0) { throw 'Context coverage requires review' }
```

The following build/loader commands access real Selectel, even in check-only mode.
They are **manual actions**, not part of Codex verification. Do not read/print .env
or use `docker compose config` without `-q`.

## A–C. Build check-only and inspect — STOP

```powershell
$statsInputs = @(
    '--silver-build','event_core=f62c4943ef505dc56ce02b4c1724fedd69cfc773b23a8f3a1b6cf575bf2f526d',
    '--silver-build','match_squads=e00cc4605530a68a791981771b75c26f283bba55070014c33db27f4bed0443bd',
    '--silver-build','pass_events=635dc7e21a3e07793c3d7129c2263dccebfa3fea13956225a574b2a94d45553a',
    '--silver-build','shot_events=a67da8f5404c02ce557f6f2a5c8a95e052ecaeb5e8e8b5ac271c9bb5c4992584'
)
$teamArgs = @('--dataset','team-match-stats','--transform-version','team_match_stats_v2') + $statsInputs
$playerArgs = @('--dataset','player-match-stats','--transform-version','player_match_stats_v2') + $statsInputs
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py @teamArgs --check-only
if ($LASTEXITCODE -ne 0) { throw 'Team build preflight failed' }
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py @playerArgs --check-only
if ($LASTEXITCODE -ne 0) { throw 'Player build preflight failed' }

$teamBuild = Read-Host 'Exact team v2 Build ID from successful check-only'
$playerBuild = Read-Host 'Exact player v2 Build ID from successful check-only'
if ($teamBuild -cnotmatch '^[0-9a-f]{64}$' -or $playerBuild -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid build ID' }
```

**STOP C:** inspect exact input IDs, transform versions, deterministic build IDs,
DQ PASSED, 64 matches and 128 team / 3244 player rows. Repeating check-only must
produce identical IDs. Never substitute latest or guess an ID.

## D–E. Publish immutable Gold — STOP

```powershell
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py @teamArgs
if ($LASTEXITCODE -ne 0) { throw 'Team publication failed' }
docker compose run --rm --no-deps football-spark spark-submit scripts/build_gold_match_stats.py @playerArgs
if ($LASTEXITCODE -ne 0) { throw 'Player publication failed' }
```

**STOP E:** both publications must finish successfully and be registered. Their
printed IDs must exactly equal `$teamBuild` / `$playerBuild`; inspect immutable
output prefixes, DQ and row counts. Existing complete identical builds may report
UNCHANGED/ALREADY_BUILT and ALREADY_REGISTERED. Publication alone changes no BI view.

## F–H. Create shadow tables and preflight loads — STOP

Migrations are streamed from the Windows host; there is no `/migrations` mount.
009 does not redirect views. Do not apply 009–011 as a batch: **011 is rollback**.

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\009_create_gold_stats_v2_shadow_tables.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Migration 009 failed' }

$teamLoad = @('--dataset','team-match-stats','--transform-version','v2','--build-id',$teamBuild)
$playerLoad = @('--dataset','player-match-stats','--transform-version','v2','--build-id',$playerBuild)
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py @teamLoad --check-only
if ($LASTEXITCODE -ne 0) { throw 'Team shadow preflight failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py @playerLoad --check-only
if ($LASTEXITCODE -ne 0) { throw 'Player shadow preflight failed' }
```

**STOP H:** verify target diagnostics name only the corresponding `_v2` table,
exact build IDs, validated schemas and source row counts. Builder uses the full
`team_match_stats_v2`/`player_match_stats_v2` version; loader uses short `v2`.
Never work around a conflicting build or schema failure with deletion/force.

## I–L. Load, repeat, fully validate — STOP

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py @teamLoad
if ($LASTEXITCODE -ne 0) { throw 'Team shadow load failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py @playerLoad
if ($LASTEXITCODE -ne 0) { throw 'Player shadow load failed' }

# K: identical repeats must be idempotent, with no second INSERT.
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py @teamLoad
if ($LASTEXITCODE -ne 0) { throw 'Team repeat failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py @playerLoad
if ($LASTEXITCODE -ne 0) { throw 'Player repeat failed' }

docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode shadow
if ($LASTEXITCODE -ne 0) { throw 'Full shadow validation failed; do not switch BI' }
```

**STOP L:** repeats must report ALREADY_LOADED/UNCHANGED and ALREADY_REGISTERED;
both shadow validations, all exact deltas and the match_results prerequisite must
PASS. Registration must record actual `_v2` targets, leaving v1 records intact.
After an INSERT timeout, first wait for the server query to finish and inspect its
state; do not immediately retry concurrently or delete partial rows. Existing
recovery either registers a complete load or rejects inconsistent/partial state.

## M. Back up both current BI definitions

Keep writers frozen. Save both definitions locally before any view replacement.
This SELECT/SHOW-only backup contains no environment or credential values.

```powershell
$viewBackup = @'
import json
from contextlib import closing
from src.common.clickhouse import create_clickhouse_client
with closing(create_clickhouse_client()) as client:
    names = ('football.bi_team_match_stats', 'football.bi_player_match_stats')
    print(json.dumps({name: client.query('SHOW CREATE TABLE ' + name, settings={'readonly': 1}).result_rows[0][0] for name in names}))
'@ | docker compose run --rm -T --no-deps football-python-tools python -
if ($LASTEXITCODE -ne 0) { throw 'View DDL backup query failed' }
$savedViews = ($viewBackup -join "`n") | ConvertFrom-Json
if (-not $savedViews.'football.bi_team_match_stats' -or -not $savedViews.'football.bi_player_match_stats') { throw 'Incomplete view backup' }
$backupDirectory = Join-Path (Get-Location) ('logs\stage4c-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backupDirectory -ErrorAction Stop | Out-Null
[System.IO.File]::WriteAllText((Join-Path $backupDirectory 'bi_views_before.json'), ($viewBackup -join "`n"), [System.Text.UTF8Encoding]::new($false))
Write-Host "View DDL saved in $backupDirectory"
```

Inspect the backup against the reviewed migration 008 / rollback 011 projections.
If custom changes exist, **STOP**: review the rollback before proceeding. Preserve
the backup outside the disposable containers. Existing Superset dashboard/export
backup should also be retained; do not recreate datasets.

## N–P. Explicit maintenance window, switch, validate, smoke test

Pause BI use/refreshes, keep all relevant writers frozen, announce the window.
Two `CREATE OR REPLACE VIEW` statements are **not one atomic two-view transaction**.
The first may succeed and the second fail, leaving mixed sources. Keep BI paused
until both pass, or roll back both. Do not infer success from one view.

```powershell
# Recheck immediately before switching, including authoritative match_results.
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode shadow
if ($LASTEXITCODE -ne 0) { throw 'Shadow prerequisite changed; do not switch' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v1
if ($LASTEXITCODE -ne 0) { throw 'Current view baseline changed; do not switch' }

Get-Content -Raw .\infrastructure\clickhouse\migrations\010_switch_bi_views_to_stats_v2.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Cutover failed; keep BI paused and follow Q' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v2
if ($LASTEXITCODE -ne 0) { throw 'BI v2 validation failed; keep BI paused and follow Q' }
```

Migration 010 preserves every migration 008 projection and SQL SECURITY INVOKER;
only the two stats sources change. `football.match_results` remains authoritative
for winners, main scores, shootouts, extra-time flags and display_score. No new
derivation of shootout outcomes is introduced.

**Manual Superset smoke tests before ending the window:**

- Keep datasets `football.bi_team_match_stats`, `football.bi_player_match_stats`,
  `football.matches`, `football.match_results`; create no `_v2` datasets.
- Refresh/force-refresh chart caches. Public columns/types should be unchanged;
  unexpected schema drift is a validation failure, not a reason to silently
  reconfigure charts. Column sync is only needed for an explicitly reviewed change.
- Verify World Cup 2022 Overview opens, Native Team filters still affect intended
  charts, and date/stage filters and sorting work. Preserve Date fields.
- At full tournament scope, team/player shots 1494 → 1453, shot goals 195 → 169,
  xG approximately 188.0220419302 → 155.8985419302; pass attempts unchanged.
- Match Table: Netherlands | Argentina | `2-2 (3-4 pens)` | PENALTIES;
  Argentina | France | `3-3 (4-2 pens)` | PENALTIES. Winners/W-D-L remain based on
  match_results, not the tied main score. Extra time remains in performance stats.
- Confirm 64 matches, 128 team-grain rows, 3244 player-grain rows; do not interpret
  team/player row counts as match counts. Check a zero-activity squad player.

Only resume BI/writers after all checks pass and record the exact served build IDs.

## Q. Explicit rollback if switch or smoke checks fail

Keep BI paused. 011 restores **both** v1 sources with match_results enrichment;
it is never the automatic next migration after 010. No tables, artifacts or
catalog rows are deleted. This intentionally restores old v1 performance metrics
including shootouts while preserving correct result display.

```powershell
Get-Content -Raw .\infrastructure\clickhouse\migrations\011_rollback_bi_views_to_stats_v1.sql |
    docker compose exec -T football-clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery'
if ($LASTEXITCODE -ne 0) { throw 'Rollback failed; keep BI paused and inspect both view definitions' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v1
if ($LASTEXITCODE -ne 0) { throw 'Rollback verification failed; keep BI paused' }
```

Refresh Superset caches and repeat filter/Match Table checks. Confirm v1 tournament
totals 1494 shots, 195 shot goals, approximately 188.0220419302 xG. Only then resume
BI. Leave shadow tables and v2 immutable artifacts available for investigation;
do not perform destructive cleanup or retry cutover without finding the cause.

## Repeatable offline/read-only verification (no S3)

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-spark spark-submit tests/spark/test_match_results.py
docker compose run --rm --no-deps football-spark spark-submit tests/spark/test_gold_match_stats.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_stats_cutover.py
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_stats_cutover.py --mode bi-v1
docker compose run --rm --no-deps football-python-tools python -m compileall -q src scripts tests
git diff --check
```

The integration test reconstructs virtual v2 using SELECT-only CTEs against the
audited current v1/Silver state; it does not create/load shadow tables. Synthetic
Spark tests use local fixtures. Real v2 publication, shadow INSERT, applied view
DDL, privileges and Superset UI behavior still require the manual gates above.
