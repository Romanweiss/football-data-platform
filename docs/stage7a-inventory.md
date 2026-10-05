# Existing validation inventory (before Stage 7A integration)

All generic CLI inputs require explicit competition/season and, for immutable
artifacts, exact parent/build pins. Historical WC-only checks are listed separately.
ERROR below means existing exception/non-zero exit blocks the invoking job. INFO
does not block. None had a normalized, append-only rule execution table before 7A.
Successful artifacts/load registrations are persisted, but are not DQ execution history.

| Check / implementation | Layer / dataset | Context / inputs | Existing rule and severity | Output / execution / persistence |
| --- | --- | --- | --- | --- |
| `check_statsbomb_source`, `statsbomb.context` | Source / matches, competitions, children | Explicit context; public catalog and match JSON, child HEAD | Source exists, context identity, unique membership: ERROR | JSON or safe failure; manual and Airflow source task; hashes in XCom, no DQ history |
| `check_statsbomb_bronze`, `bronze_reader`, `membership` | Bronze / matches, events, lineups | Exact parent SHA, frozen catalog boundary, S3 GET/HEAD | Parent SHA/context, complete child membership, key/size/metadata identity: ERROR; HEAD is not byte-level child SHA | Text and safe stage diagnostics; manual, Airflow Bronze gate; no DQ history |
| `check_s3`, `check_s3a`, `check_clickhouse_s3`, `test_s3_roundtrip` | Operational connectivity | Configured clients; sample object or exact build | Connectivity/CA and roundtrip hash: ERROR | Manual diagnostics; roundtrip writes only its fixed test object; excluded from read-only DQ execution |
| `silver.statsbomb.events` | Silver / event_core | Spark frame | Required IDs, unique event grain, valid match coverage: ERROR | Aggregate dictionary/text, exception; build/check/publish; deterministic artifact registration only |
| `silver.statsbomb.event_domains` | Silver / passes, shots | Raw events, selected matches, typed frames | Exact domain membership/grain, required fields, xG/domain validity: ERROR; optional NULL counts: INFO | Aggregate dictionary/text; build/check/publish; no independent DQ history |
| `silver.statsbomb.lineups` | Silver / squads, teams, players | Raw lineups and selected matches | Squad coverage/grain/two teams, team identity, references: ERROR; player spelling/nickname variations and optional NULLs: INFO | Aggregates and bounded identity samples; Spark build gates; no independent DQ history |
| `silver.statsbomb.matches` | Silver / matches | Parent JSON, teams build | Schema, unique matches, context, required fields, team references: ERROR | Aggregate dictionary/text; Spark build gate |
| `gold.statsbomb.periods`, `match_stats` | Gold / team/player stats v1/v2 | Exact Silver manifests/frames | Period/domain join integrity, full squad grain, no metric loss, nonnegative finite metrics: ERROR; period 5 excluded by v2 | Aggregate dictionaries/text, exceptions; Spark build/check/publish |
| `gold.statsbomb.match_results` | Gold / match_results | Matches/events/shots | Match coverage, teams, outcome/score/winner/shootout semantics: ERROR | Aggregate dictionary/text; Spark build/check/publish |
| Silver/Gold `manifest`, `publish`, analytics `silver_input` / `gold_input` | Silver/Gold / all ten datasets | Exact build, PG catalog, S3 manifests/file inventory | Immutable identity, schema digest, input lineage, complete files, row/match count: ERROR | Exceptions, safe stage diagnostics; publish reuse and loader preflight; artifacts/catalog persist, executions do not |
| `analytics.validation`, `loader`, `gold_loader` | Serving input / all datasets | Verified Parquet via ClickHouse s3(), target schema, current build, load catalog | Safe types, required fields, uniqueness/context/domain values, source vs target aggregates, conflict/partial-load detection: ERROR | Aggregate metrics and statuses; manual load/check-only and Airflow artifact/preflight/load tasks; successful load catalog only |
| `check_clickhouse_model`, `model`, `matches_model` | Serving / Silver plus stats | Explicit context and currently served registered build IDs | Hard match/squad/domain references, home/away coverage: ERROR; optional team/player event references: INFO | Per-check counts + exception; manual/Airflow serving gate; log/XCom only |
| `check_clickhouse_gold_model`, `gold_model` | Serving reconciliation / Gold stats | Exact served Gold/Silver IDs | Gold lineage and load registration; full squad coverage; Silver event/pass/normal-shot totals vs Gold; xG tolerance 1e-9: ERROR | Named aggregate pairs + exception; manual/Airflow; log/XCom only |
| `check_clickhouse_match_results.py/.sql` | Serving / results and enriched BI | Explicit context, current lineage | Coverage/grain, source scores, extra time, exact event-key shootout counts; BI grain/value projection: ERROR | SQL aggregate tuples/throwIf + exit code; manual/Airflow results gate |
| Stage 4B `audit_shootout_semantics` | Golden / WC2022 | Pinned old Silver/Gold serving fixture | Audit performance vs shootout contribution | Read-only audit JSON in docs; not a generic multi-context quality gate |
| Stage 4C `check_clickhouse_stats_cutover` | Golden / WC2022 v1/v2 + BI | Pinned Stage 4B audit, installed tables/views | Exact affected grains, v2 non-shootout semantics, audited totals, BI schema/projection: ERROR | Text + safe class; manual, synthetic/integration tests; static audit evidence |
| Stage 4D `check_clickhouse_match_analysis` | Golden / WC2022 BI | Stage 4C prerequisite, installed/candidate 012 views | Overview/team/player schemas, grain, filters, values: ERROR | Summary + safe class; manual, offline/integration tests |
| Stage 4E `check_clickhouse_match_visuals` | Golden / WC2022 BI | Stage 4C/4D prerequisites, 013/014/015 views | Shot coordinates/labels, normal shots, race/team identity/final xG, shootout separation and pinned counts: ERROR | Summary + safe class; manual, offline/integration tests |
| `check_clickhouse_bi_views.sql`, smoke SQL | BI / serving | Historical explicit WC fixture | Grain/coverage and query smoke evidence | SELECT output/throwIf; manual and ClickHouse integration suites |
| `check_application_api.validate` | API / context catalog + sampled match analysis | Local API or Django in-process; explicit context | Health, catalogs, typed JSON, ordering, teams/players/shots/race/shootout consistency: ERROR; optional explicit WC golden assertions | Result dict with counts/IDs/timings; manual/Airflow; no DQ persistence |
| `check_orchestration_snapshot` | Regression / both real contexts | PG catalogs, CH aggregates, all match analyses | Before/after build IDs, counts and API body hashes | Evidence JSON in docs; 6C replay acceptance; not a generic fixed-volume SLA |
| `superset_semantic_safety` | BI operational/semantic | Existing dashboard/dataset metadata and templated query results | WC context guards, match identity/filter safety, generic two-context coverage: ERROR | Safe audit/validation JSON; explicit separate Superset runtime, no automatic changes in 7A |
| `orchestration.runtime`, 60-task DAG | Operational + validation gates | Required context, exact frozen source/build pins | Stable build identity, CLI completion, gates, one Spark task: ERROR | Small allowlisted XCom, safe logs; Airflow owns run/task status, not DQ truth |

Test inventory: `tests/test_bronze*`, `test_statsbomb*`, `test_silver*`,
`test_domain_builds`, `test_lineup*`, `test_matches*`, `test_gold`,
`test_clickhouse*`, `test_bi_views`, `test_stats_cutover`, `test_match_*`,
`test_shot_labels`, `test_validator_context`, `test_etl_context`,
`test_superset*`, `test_orchestration`; eight `tests/spark` suites;
`tests/integration` ClickHouse suites; `tests/application` API contracts;
`tests/airflow/test_dag.py` parse/pool/dependencies; `tests/superset` image/semantic
tests. Tests exercise synthetic failures without corrupting live fixtures.

Grafana inspection: no Compose service, provisioning, configuration or existing
Grafana references were found in the repository. Stage 7A prepares PostgreSQL
read-only queries; installing Grafana remains Stage 7B work.
