# PET-3D: Historical UCL production-like integration

Date: **2026-11-07**. Result: **BLOCKED — preflight, before persistent writes or deployment**.

Published HEAD: `575192e9851be7e62de83ccaafd2410d6254c071`, branch `master`.
Stage 8C: **PARTIAL**. This report does not claim historical production acceptance.
No source code, Compose configuration, application images, or database objects were changed.

Follow-up: [PET-3D-FIX readiness](pet3d-production-readiness.md) implements and tests
the three missing handoffs locally. That follow-up does not change this historical
attempt's BLOCKED status: production persistent load and deployment are still not
executed, and the existing application on 18090 has not been updated.

## 1. Deployment blockers

Three independent gaps prevent using the published code as a configuration-only rollout:

1. [The existing ClickHouse loader](../src/openfootball_etl/clickhouse.py) is an
   `IsolatedClickHouse` adapter, not a production publisher. Its constructor requires
   an isolated container/database name, a specific image, `network=none`, no exposed
   ports, a test-scope label, and only tmpfs mounts. Calling the unchanged constructor
   with `football-clickhouse` / `football` fails with `ISOLATED_CONTAINER` before
   Docker access. No production write was attempted. The isolated gate must not be
   disabled, spoofed, or bypassed through container aliases.
2. [The published API reader](../application/historical_repository.py) explicitly
   accepts only `pet3-openfootball-ch-<hex>` hosts and
   `pet3_openfootball_api_<hex>` databases. A pinned production database cannot be
   enabled simply by setting `HISTORICAL_API_ENABLED=true`. Executing the unchanged
   factory function with inert dependencies and the intended production target
   returns the NOT_READY/503 gate without calling the SDK. This targeted AST check
   is not represented as a full Django integration test. Published connection tests
   intentionally enforce production-target rejection.
3. [The API Dockerfile](../docker/api/Dockerfile) copies application sources but only
   two files from `src/common`; it does not package `src/openfootball_etl` or
   `src/providers`. Historical routes import the Gold contract and provider modules.
   Loading the unchanged published historical repository source in a short-lived
   Python process inside the current API image reproduces
   `ModuleNotFoundError: src.openfootball_etl`. The current Dockerfile has the same
   relevant `src` COPY layout. No replacement image was built or deployed; this is
   an import-layout diagnosis, not a failed production rollout.

These are not missing football-data.org credentials or missing Gold data. The
historical production handoff and image packaging need a small tested integration
change before deployment can proceed safely. Rebuilding/recreating the current
API immediately would not solve these gates and could break application startup.

## 2. Read-only data preflight

The existing source and sealed phases were read locally, without downloads,
reprocessing, Spark, Airflow, S3 access, or dataset writes.

- Source: `openfootball/football.json@e6744429ee395bc86f247348c6184bb08d4eb361`,
  `2024-25/uefa.cl.json`, 58,305 bytes.
- Source SHA-256:
  `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6` — **MATCH**.
- Normalized semantic fingerprint:
  `2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b`.
- Gold batch:
  `ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc` — **MATCH**.

| Sealed phase | Files | Manifest SHA-256, matched retained evidence |
| --- | ---: | --- |
| Bronze | 3 | `49d588edab73a4bf9c4c28e01e361c41ff403fe149ffacbc5b2564b410f70d81` |
| Silver | 12 | `bd28db879f9b080eb9232d370fc427f9ffdf05770ca782e7002962b8141a12a1` |
| Gold | 16 | `c7043c4cad0438007dd4152e3b83622f7458fa4de9482ed7e1a12ac31d973a98` |

| Gold dataset | Rows | Logical row SHA-256 |
| --- | ---: | --- |
| historical_fixtures | 189 | `55d66c3f22b571c28d553469032f446b6f47394167f00daa56fbade0276e4b8a` |
| competition_participants | 36 | `a77c6cf8918eb4916786e6f69c469c2a4217825e60149062ace74ec40d48cb5a` |
| stage_round_coverage | 14 | `2a2f16af9b794aa7909693251312fb071ab977d81688f554efd5e1c23632f06f` |
| source_quality | 394 | `842f201eb009f5e9da1d169be2d22a54a4d32214b8d77edfadb7b631fc98dd89` |

All four logical fingerprints match the published pinned contract: **633 Gold rows**.
This is not a persistent historical serving count. No matching historical serving
objects were present in the checked namespace; none were created.

No verified regulation scores, winners, points, or standings were generated.
The accepted source-only limitations remain in force: 188 source-reported FT
results, one UNKNOWN final, and two ambiguous ET/penalty cases. They were not
reclassified or supplemented from another source during this preflight.

## 3. Existing runtime and image references

Before and after: **6 running containers, all healthy**, with unchanged identities:
Web, API, ClickHouse, PostgreSQL, Superset, and Superset metadata PostgreSQL.
No container/network was created, restarted, stopped, removed, or recreated.
No cleanup action was necessary.

| Application | Image before = after | Existing tag |
| --- | --- | --- |
| API | `sha256:87192239feefa3221951fbe77faea97140a40925aba669f1f6f4434c675daf40` | `football-api:9b2f-8f77286` |
| Web | `sha256:b2e9855d2477ea20526e200acdb46f466b1e012d13b305c543ce34873225239f` | `football-web:9c4d-8af030e` |

Both exact image IDs are locally available. They are rollback **references**, not
proof of a newly rehearsed PET-3D rollback. No rollout/rollback was executed.
The existing read-only API role has a SELECT grant covering `football.*`; only a
boolean scope result was retained, not role credentials or raw grant statements.
No grants or users were changed. A dedicated new database would require a separate
privilege assessment; it must not inherit write credentials into the API.

Observed same-origin HTTP results on `127.0.0.1:18090`:

| Route | HTTP | Meaning |
| --- | ---: | --- |
| `/healthz` | 200 | Existing Web healthy |
| `/api/v1/health` | 200 | Existing API healthy |
| `/api/v1/competitions/historical` | 404 | Historical API not deployed |
| `/competitions/historical/uefa-champions-league/2024` | 200 | SPA shell only; not historical UI acceptance |
| `/competitions/current/uefa-champions-league/2026` | 200 | SPA shell only; no new browser acceptance claimed |

Target historical URL remains
<http://127.0.0.1:18090/competitions/historical/uefa-champions-league/2024>.
It is **not accepted as a working historical page** in this stage.

## 4. StatsBomb and PostgreSQL integrity

Two fresh read-only production audits were compared with each other and with the
retained pre-cleanup baseline, using the original algorithms, not changed expected
hashes:

- **98/98** scoped Match Lab `/analysis` response SHA-256 values: unchanged.
- **12/12** original ClickHouse physical tables: row counts, sorted per-row SHA-256
  aggregates, schema hashes, and build-identity groups unchanged.
- **5/5** PostgreSQL metadata catalogs: canonical row hashes and counts unchanged.
- Production API/Web IDs, image IDs, start timestamps, and health unchanged.

The complete two audit documents have the same canonical SHA-256:
`3c8d098d393d49a29196279e38c280657a9dcc4b65aa65e50831af08f316c4a7`.

The real existing API Xhaka control request also passed:

```text
GET /api/v1/competitions/9/seasons/281/matches/3895052/passes?team_id=904&player_id=3500&period=1
31 total / 31 returned / 27 completed / 4 failed / 0 unknown / 0 excluded
```

This is an HTTP/API regression check, not a new Chromium visual acceptance.
Historical desktop/mobile, keyboard/axe, localization, filters, pagination,
loading/503 and source-badge acceptance were **NOT RUN**, because deployment gates
failed first. Previous isolated browser evidence is not substituted for production
acceptance.

## 5. Backup and rollback boundary

The historical serving target has not been created. No destructive rollback or
database restore is needed for this attempt. Before any future persistent write:

1. Fix and test the explicit persistent handoff while preserving default isolated
   behavior and the existing no-production-fallback guarantee.
2. Choose a fixed new namespace, record its verified absence, and inventory exact
   owned object names/UUIDs. Never delete an object based on a prefix alone.
3. Prepare a protected, no-overwrite recovery capsule outside temporary storage:
   pinned Gold bundle, schema/content manifests, creation receipt, and exact
   rollback recipe for only the newly owned scope. Verify readback and restore
   before writing. Existing Gold seals alone are not a rehearsed serving rollback.
4. Reuse the single-bundle atomic publication and readback contract; test idempotent
   replay, wrong target/schema, partial insertion, and content drift without
   touching original StatsBomb objects.
5. Package/import-test all historical runtime dependencies in the non-root API
   image. Build the published frontend from a clean, bounded source snapshot.
6. Produce durable deployment and rollback overrides pinning the exact API/Web
   image IDs above, preserving effective existing configuration without exporting
   secret values. Validate them before recreating only those two services.
7. Recheck source/production fingerprints, then perform the separately reviewed
   rollout and real Chromium acceptance. Roll back only through the verified
   scoped procedure if acceptance fails.

No backup from K:, recovered plaintext from F:, recovery key, or Bitwarden data was
opened. No Superset metadata, PostgreSQL data, S3, persistent volume, or external
provider was changed or queried through a new ingestion path.

## 6. Git preservation and local evidence

HEAD stayed `575192e9851be7e62de83ccaafd2410d6254c071`; no application source edits.
The main index retains only the original two licensing documents, with exact blobs:

- `docs/stage9c5-provider-comparison.md`:
  `fac8b0073dc67bab8f5341b4304036ea78d91e54`.
- `docs/stage9c5-provider-licensing-review.md`:
  `6fe2394c0dc11ded3199c5e7d75c173d96bc9ddd`.

Planning documents and the unrelated shortcut were retained and hashed. Existing
unpublished Superset scripts/tests/reports were not staged, edited, or included in
a build context. New deliverable: this untracked report. Diagnostic Python helpers
and non-secret JSON receipts are ignored under `.tmp`; none are staged.

Local ignored evidence directory: `.tmp/pet3d-20261107/`, containing
`production-readonly.json`, `production-after-readonly.json`, `preflight.json`,
`blocker-checks.json`, and `xhaka.json`. These are local evidence, not committed
deployment assets or a durable rollback capsule. No staging/commit/push occurred.

## 7. Next minimal step

**PET-3D-FIX: explicit persistent serving handoff, packaging, and rollback tests**.
Do not rerun upstream ingestion, licensing research, or the earlier adapter review.
Keep the published Grid/heatmap, Match Lab, and synthetic Current Competitions
contracts unchanged. After the small handoff is verified, resume the deployment
from the backup/rollback gate, not from upstream acquisition.

Remaining portfolio work is production-like historical acceptance and its evidence,
followed by a concise reproducibility/demo handoff. More providers, new metrics,
infrastructure layers, or full-platform disaster recovery are not prerequisites
for this bounded historical feature. Stage 8C remains PARTIAL.
