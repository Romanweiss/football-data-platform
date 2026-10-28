# Historical archive and README migration map

[Current documentation](../README.md) · [English overview](../../README.md) · [Русский](../../README.ru.md)

## Preserved snapshot

[README-legacy.md](README-legacy.md) retains the entire previous README from
published commit `fd6212d5972150e11ca0161efe0e5fa32cce4992`: **2674 lines /
186565 UTF-8 bytes** before the archive notice and link retargeting.
Original Git blob: `d52ff3465056bf4d404f670e46bb98755e901161`.
The [original GitHub file](https://github.com/Romanweiss/football-data-platform/blob/fd6212d5972150e11ca0161efe0e5fa32cce4992/README.md)
also remains available by immutable commit reference.

The archive adds a warning and changes only local Markdown destinations from
`docs/...` to `../...`; no paragraph, command, dataset contract or evidence is removed.
After removing the notice and reversing that link retargeting, normalized UTF-8
SHA-256 must equal:

```text
261f8afb3c1067482c7e0e8684ecff070e05728b4f0363b75bc1e8b793e0b4b1
```

Offline documentation tests verify that invariant without needing Git history.
Existing stage runbooks and JSON/CSV/PNG evidence remain at their original paths.

## Classification and replacement destinations

| Old README material | Classification | Current place to start |
| --- | --- | --- |
| Match Lab, pass map, API/React features | Current product, with outdated pre-publication wording | [English overview](../../README.md), [Russian overview](../../README.ru.md), [Pass Map](../stage9b1.md) |
| Component roles and data-layer explanations | Architecture; early future-tense statements are obsolete | [Architecture](../architecture.md) |
| Ports, environment and application commands | Developer instructions; historical setup is not a fresh-data bootstrap | [Development](../development.md), [delivery runbook](../stage8b.md) |
| Bronze immutable bytes/catalog and fan-out | Deep historical implementation contract | [Legacy ingestion](README-legacy.md#statsbomb-bronze-ingestion), [fan-out](README-legacy.md#statsbomb-match-fan-out-ingestion), [current context-explicit ETL](../stage6b1.md) |
| Silver schemas, S3A/committer, manifests and DQ | Deep technical reference; old WC-only CLI examples are superseded | [Legacy Silver](README-legacy.md#stage-2b---direct-s3a-and-immutable-silver-builds), [context/runbook](../stage6b1.md) |
| ClickHouse loaders, safe casts, one-build policy | Technical reference and recovery behavior | [Legacy loaders](README-legacy.md#stage-3a---clickhouse-analytics-foundation), [current orchestration](../stage6c2.md) |
| Gold grain, identity, metrics and match dimension | Technical reference, not new ingestion instructions | [Legacy Gold](README-legacy.md#stage-3c---gold-match-analytics), [results/v2 semantics](../stage4b.md) |
| Superset bootstrap, reader and chart instructions | Historical operator setup, later safety changes apply | [Legacy Superset](README-legacy.md#stage-4a---superset-bi-foundation), [multi-context safety](../stage6b-superset-safety.md) |
| Airflow, DQ, Grafana, alerts and CI summaries | Repeated summaries of existing runbooks | [Documentation index](../README.md) |
| Backup/restore status and boundaries | Operations/security; earlier blockers are historical | [Operations](../operations.md), [latest closure evidence](../stage8c-r2-4a2-4c.md) |
| Provider names, coverage and attribution | Source/interpretation policy | [Data sources](../data-sources.md) |
| Volume deletion, forced service recreation, outdated unscoped loads | Unsafe/superseded operational examples, retained as history only | Do not execute; use [operations safety](../operations.md) |

## Anchors and historical claims

The documentation review found no inbound Markdown links targeting old root
`README.md#...` anchors in the repository. The old headings remain available on
the archived file; use its path for external bookmarks to an old technical section.
If a future link audit finds an old root anchor, retarget it rather than restoring
thousands of historical lines to the product README.

The snapshot intentionally retains contradictions between early and later stages:
empty tables versus loaded serving; fixed WC-only parents versus explicit contexts;
pre-cutover metrics versus v2; local-only code versus subsequently published work.
Earlier commands can lack required flags or carry destructive effects. The archive
does not override newer evidence, authorize a replay or claim those commands still work.
