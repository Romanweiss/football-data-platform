# Football Data Platform

Explore football matches through interactive event maps, team comparisons and
player statistics, backed by a reproducible data platform.

[English](README.md) · [Русский](README.ru.md) · [Documentation](docs/README.md)

## Match Lab

![Actual Match Lab pass map: Granit Xhaka against RB Leipzig](docs/assets/match-pass-map.png)

Actual development UI: Granit Xhaka, first half of Bayer Leverkusen–RB Leipzig,
2023/24 — 31 passes, 27 completed and 4 failed. This is not a mockup or a public demo.

Data: **StatsBomb Open Data**. The provider's official attribution logo:

<img src="https://raw.githubusercontent.com/hudl/open-data/master/img/SB%20-%20Icon%20Lockup%20-%20Colour%20positive.png" alt="StatsBomb" width="180" />

## Key features

- **Interactive pass map:** a full 120×80 StatsBomb field, directional arrows,
  team/player/period filters, completion outcomes and accessible event details.
- **Shot map and xG race:** synchronized shot selection, cumulative step lines
  and shared details; penalty shootouts are displayed separately.
- **Match analytics:** official results, home/away comparisons and team metrics.
- **Player contributions:** match-level statistics, activity filters and full-squad
  access, including players without events.
- **Context-aware navigation:** competition, season and match selectors, search,
  canonical deep links, browser history and refresh.
- **EN/RU/ES interface:** keyboard interaction and responsive desktop/mobile layouts.

These are match-level tools, not standalone team/player profile pages or tracking
movement analysis. The pass map is event-based; coordinates are not physical metres.

## Verified data coverage

| Dataset | Context | Matches | Pass events | Coverage |
| --- | --- | ---: | ---: | --- |
| FIFA World Cup 2022 | `43/106` | 64 | 68515 | All tournament matches |
| Bundesliga 2023/24 | `9/281` | 34 | 39214 | Bayer Leverkusen matches only: **34/306** league fixtures |
| Total | Two contexts | 98 | 107729 | Historical, loaded snapshots |

The Bundesliga sample must not be used for league-wide rankings. Current-season
**2026/27 is not integrated**. Coverage describes the verified platform snapshot,
not everything currently available from the provider. See [data sources](docs/data-sources.md).

## Architecture

```text
StatsBomb JSON → Selectel S3 Bronze → Spark Silver/Gold → ClickHouse → Django API → React
```

Bronze preserves original bytes; Silver normalizes events, lineups and matches;
Gold builds match-level analytical datasets. Immutable artifacts, deterministic
build IDs, manifests and PostgreSQL catalogs connect source data to serving rows.
Airflow orchestrates explicit pipeline runs; Superset and Grafana provide BI and
data-quality views. Browser requests read ClickHouse, not S3 or PostgreSQL.

See [architecture and data contracts](docs/architecture.md).

## Technology stack

| Area | Existing implementation |
| --- | --- |
| Application | React 19, TypeScript, Vite; Django 5.2 / Gunicorn |
| Analytics | ClickHouse 25.8; Spark 4.2.0 / Hadoop 3.5.0; Parquet |
| Lake and catalog | Selectel S3; PostgreSQL 17 |
| Orchestration and visibility | Airflow 3.2.2; Superset 6; Grafana 13 |
| Local delivery | Docker Compose; Nginx; Windows/PowerShell operator runbooks |
| Quality | unittest, Vitest, Playwright/Chromium, Ruff, GitHub Actions |

Versions are pinned in the repository; exact runtime distinctions are documented
in the [development guide](docs/development.md), not inferred from host Python.

## Safe first steps

Requires Git and Docker with Compose v2. From a fresh checkout:

```powershell
git clone https://github.com/Romanweiss/football-data-platform.git
cd football-data-platform
docker compose --env-file .env.example config -q
```

This validates public configuration only: it does not start services, provision
credentials or load data. A checkout contains source and synthetic fixtures, not
the real S3 lake or populated databases. Follow [development setup](docs/development.md)
before starting application containers; do not run historical ingestion commands.

With an already configured dev stack, Match Lab is at `http://127.0.0.1:15173`.
The optional production-like origin is `http://127.0.0.1:18090`, local only.
**Pass Map is accepted at local production-like 18090 (Stage 9B.1-D).**
See the [deployment acceptance](docs/stage9b1-deployment.md). Pressure Heatmap
(Stage 9B.2-A) is local development work, not published or deployed at 18090.

## Documentation

- [Documentation index](docs/README.md) — choose a guide or stage runbook.
- [Architecture](docs/architecture.md) — data layers, serving and trust boundaries.
- [Development](docs/development.md) — safe setup, API routes and offline tests.
- [Data sources](docs/data-sources.md) — coverage, event semantics and provider terms.
- [Operations](docs/operations.md) — service runbooks, DQ, secrets and recovery limits.
- [Pass Map contract and evidence](docs/stage9b1.md).
- [Historical archive](docs/archive/README.md) — the complete previous README and migration map.

## Status and limitations

Published product baseline: [`fd6212d`](https://github.com/Romanweiss/football-data-platform/commit/fd6212d5972150e11ca0161efe0e5fa32cce4992).
[CI fast](https://github.com/Romanweiss/football-data-platform/actions/runs/40764227972)
and [CI integration](https://github.com/Romanweiss/football-data-platform/actions/runs/40764227888) passed for that commit.

- This is a local production-like platform, **not a publicly hosted service**.
  Public authentication, TLS ingress, HA and load/capacity guarantees are not established.
- Pass responses are bounded at 5000 drawable rows / 4 MiB; oversized results fail
  explicitly. Dense overlaps remain; keyboard navigation reaches every pass.
- Metrics retain provider semantics: no new xG model, per90, tracking or current-season feed.
- Monitoring schedules do not automatically adopt source changes or trigger ingestion.
- Isolated local S3 recovery is **VERIFIED**; overall **Stage 8C remains PARTIAL**.
  Offsite, remote S3 and complete machine-loss recovery are not verified.
  See the [recovery evidence and remaining gates](docs/stage8c-r2-4a2-4c.md).

## Data attribution and licensing

Football data and source xG are provided by [StatsBomb Open Data](https://github.com/hudl/open-data).
Its [Public Data User Agreement](https://github.com/hudl/open-data/blob/master/LICENSE.pdf)
and attribution requirements apply; do not assume unrestricted redistribution or
commercial use. See the [source and licensing guide](docs/data-sources.md#attribution-and-licensing)
before publishing derived analysis. No separate software `LICENSE` is currently
included in this repository; no MIT/CC license or provider endorsement is implied.
