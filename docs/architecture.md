# Architecture

[Documentation index](README.md) · [Development](development.md) · [Operations](operations.md)

## Product and data flow

```text
StatsBomb Open Data (JSON)
        │ exact source bytes / SHA-256
        ▼
Selectel S3 Bronze ──► Spark Silver ──► Spark Gold
                         │                 │
                         └── immutable Parquet / manifests ──► ClickHouse
                                                                  │
                                             SELECT-only Django API ──► React Match Lab
                                                                  │
                                                       read-only Superset BI

PostgreSQL: ingestion catalog → build catalog → load receipts; DQ and alert history
Airflow: explicit orchestration of existing CLIs, not a second ETL implementation
Grafana: reads persisted DQ views; does not execute validators or own alert policy
```

This is the implemented batch architecture, not a streaming or tracking system.
Selectel is external object storage; no local S3 replacement service is deployed.

## Storage responsibilities

| Layer | Responsibility | Existing datasets |
| --- | --- | --- |
| Bronze | Raw immutable source bytes, keyed by SHA-256 | competitions, matches, events, lineups |
| Silver | Explicit typed source-aligned schemas | event_core, pass_events, shot_events, teams, players, match_squads, matches |
| Gold | Match-level business datasets | team/player match statistics, authoritative match results |
| ClickHouse | Materialized Silver/Gold serving copies and ordinary BI views | football event/domain tables, v2 stats, match views |
| PostgreSQL | Operational metadata, not a duplicate event warehouse | ingestion/build/load catalogs, DQ and incidents |

S3 object prefixes are key conventions, not real directories. Deterministic build
identity includes source context, input/schema fingerprints and transform version,
not a host path, timestamp or Git commit. Manifest validation, DQ and load receipts
provide lineage; they do not establish a global distributed transaction.

The context-explicit pipeline requires competition/season plus exact parent/build
pins. ClickHouse loaders enforce one approved serving build per dataset/context,
safe casts and fail-closed conflict/partial-state checks. Published migrations
are additive; a rollback migration is not a normal next initialization step.
See [ETL contracts](stage6b1.md) and [coexistence evidence](stage6b2.md#final-acceptance-real-coexistence).
Earlier Bronze/Silver/Gold design details remain in the [legacy archive](archive/README.md).

## Application request boundary

Canonical UI route:
`/competitions/{competition_id}/seasons/{season_id}/matches/{match_id}`.
API routes use `/api/v1` and the same match scope. Catalogs derive from available
serving rows; reviewed presentation labels name the two loaded contexts and
unknown contexts retain ID labels. Legacy match URLs resolve only unambiguous IDs.

The analysis endpoint composes match/team/player/shot/xG/shootout projections.
Pass Map has a separate, bounded, typed-parameter SELECT projection over existing
`football.pass_events`; it is not a new Gold build or ingestion pipeline.
The browser preserves source coordinates and existing analytical values.
See [Pass Map semantics](stage9b1.md) and [development API navigation](development.md#api-navigation).

## Runtime boundaries

- Dev: Vite `127.0.0.1:15173` proxies `/api` to Django; direct API is `:18000`.
- Optional local production-like delivery: Nginx `127.0.0.1:18090` serves compiled
  React and forwards `/api` to internal Gunicorn. No public hosted service is implied.
- Both modes use the SELECT-only ClickHouse reader. The frontend receives no S3,
  PostgreSQL, ClickHouse or recovery credentials. Request handlers do not run ETL.
- Airflow and Superset have separate internal metadata databases; platform
  PostgreSQL catalogs remain distinct. Persistent volumes are not disposable caches.
- Python SDK, Java S3A and ClickHouse have different TLS trust paths. Their current
  verified configurations must not be replaced by disabled certificate checking.

Pass Map is in the published source and verified dev UI; `18090` has not been
updated for it. [Delivery runbook](stage8b.md) describes separate operator deployment.

## Guarantees and limits

Stats v2 excludes penalty shootout events from normal match performance while
retaining extra time. Match scores/winners are not derived by summing xG or shot goals.
Pass outcomes use StatsBomb's checked semantics, including an explicit unknown class.
No playing-time/per90, new xG model, tracking movement or league-wide subset ranking
is introduced. [Coverage and interpretation](data-sources.md) define the boundary.

Source fences and cooperating writer locks detect specific state changes, not an
atomic S3/PostgreSQL/ClickHouse snapshot. Data updates, onboarding and serving
replacement require an explicit operator plan. The local recovery drill is evidence
for a bounded scenario, not proof of machine-loss availability or a production SLA.
