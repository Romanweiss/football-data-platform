# PET-3D-FIX: Historical serving production readiness

Date: 2026-11-07. Baseline: `575192e9851be7e62de83ccaafd2410d6254c071`.
**READY for publication review of the handoff code. Live persistent load and
deployment remain NOT AUTHORIZED / NOT EXECUTED. Stage 8C: PARTIAL.**

This is an isolated integration result, not historical acceptance on port 18090.
The original [blocked deployment report](pet3d-historical-deployment.md) remains
the record of that attempt. No new ETL, acquisition, licensing research, or React
implementation was performed.

## Three fixes

1. [Persistent publisher](../src/openfootball_etl/persistent.py): a separate bounded
   handoff for the already sealed Gold. The original isolated loader and its code
   identity are unchanged; therefore the pinned existing ETL batch remains valid.
2. [Historical connection gate](../application/historical_connection.py) and
   [repository](../application/historical_repository.py): explicit production-pinned
   mode, independent authorization/configuration pins, live server identity, four
   logical content checks, and generation fences. No production or synthetic fallback.
3. [API Dockerfile](../docker/api/Dockerfile): ships the pure ETL contracts, shared
   serving pins, provider dependencies, and checksum module. It deliberately does
   not ship the persistent publisher, Spark, pipeline, recovery modules, credentials,
   tests, or local datasets in the application filesystem.

## Immutable dataset and target policy

- Host: exactly `football-clickhouse`; database: exactly `football`, engine `Atomic`.
- Dataset ID: `openfootball:uefa-champions-league:2024`.
- Batch: `ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc`.
- Source SHA-256: `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6`.
- Semantic fingerprint: `2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b`.
- All four exact counts/fingerprints live in the shared
  [serving contract](../src/openfootball_etl/serving_contract.py), unchanged from
  the published API pins. Full dataset field sets, batch, source hash, counts and
  content digests are checked before the first write.

Writer opt-in requires the exact `AUTHORIZATION` value, fresh expected full
container ID and image ID, project/service labels, expected server UUID, and an
operator-reviewed namespace fingerprint. A mismatch stops before mutation.
The production factory selects the fixed host, not an arbitrary CLI address.
The rehearsal factory separately verifies the exact test-name pattern, image,
scope label, network isolation, lack of published ports, and tmpfs-only storage.
It cannot target the live container. No production writer was activated in this
stage; every write was to a newly created test server.

Exact SQL is allowlisted at the writer transport boundary, including projections,
schemas and generated candidate names. It rejects generic SELECTs, foreign table
names, arbitrary SQL, CREATE USER/GRANT, and DROP/TRUNCATE/ALTER. It never selects
StatsBomb payloads. Writer authentication uses the existing target-container
mechanism without exporting credential values to the host or receipts. Future
operations must separately review the writer role; no production grants changed.

## Publication boundary and rollback

The only permitted persistent objects are:

```text
football.pet3d_ucl_2024_25_records
football.pet3d_ucl_2024_25_historical_fixtures
football.pet3d_ucl_2024_25_competition_participants
football.pet3d_ucl_2024_25_stage_round_coverage
football.pet3d_ucl_2024_25_source_quality
football.pet3d_ucl_2024_25_candidate_<generated 32 lowercase hex>
```

These are one MergeTree bundle plus four projection views, not four independent
INSERT transactions. Existing namespace metadata requires an explicitly reviewed
fingerprint; unknown names or view definitions are rejected. An interrupted load
remains in its candidate; the active empty generation remains NOT_READY. Retry
requires a new reviewed namespace fingerprint and uses a new candidate rather
than overwriting or deleting the partial one.

Before switch, the candidate must contain **633 unique dataset/business-key rows**
and the complete pinned four-dataset content. One `EXCHANGE TABLES` switches the
bundle name; all four views refer to that same name. The old table is retained
under the candidate name. Active UUID checks and complete readback follow the
switch. Reader requests load the whole verified bundle before producing a response;
a before/after active-table UUID fence rejects a generation change during the read.
Incomplete, different, or mixed content gets 503, not partial JSON.

This is **not a multi-query atomic snapshot or a transactional CAS for concurrent
administrator DDL**. A single operator/quiet metadata window is a live prerequisite.
UUID/fingerprint conflicts stop for review; no force apply or automatic destructive
repair exists. Unrelated writers/administrators cannot be prevented by this tool.

Replay of the already correct immutable dataset is `REUSED` without INSERTs or
duplicates. A different nonempty active dataset is rejected, not replaced. This
version does not implement arbitrary multi-season updates or version promotion.

For first deployment the previous logical state is an empty NOT_READY generation.
Rollback verifies the exact target, receipt batch, namespace fingerprint, current
and previous table UUIDs, current pinned content and previous emptiness, then
exchanges those two owned objects back. The new valid generation is retained.
Rollback restores the previous UUID and HTTP 503 state; **it does not delete newly
created schema objects or claim to restore physical namespace absence**. The
rehearsal confirms this bounded rollback, not a full ClickHouse restore. Future
physical cleanup needs its own exact-owned-object authorization.

## Django configuration, disabled by default

Historical serving still defaults to isolated/disabled behavior. Production mode
requires all of these reviewed settings, not ordinary `CLICKHOUSE_*` fallbacks:

```text
HISTORICAL_API_ENABLED=true
HISTORICAL_SERVING_MODE=production-pinned
HISTORICAL_DATASET_ID=openfootball:uefa-champions-league:2024
HISTORICAL_PINNED_BATCH=<exact batch above>
HISTORICAL_PRODUCTION_AUTHORIZATION=<DATASET_ID>:<exact batch above>
HISTORICAL_CLICKHOUSE_HOST=football-clickhouse
HISTORICAL_CLICKHOUSE_DATABASE=football
HISTORICAL_EXPECTED_SERVER_UUID=<fresh independently pinned server UUID>
HISTORICAL_CLICKHOUSE_USER=<reviewed SELECT-only role>
HISTORICAL_CLICKHOUSE_PASSWORD=<existing safe runtime handoff; never CLI plaintext>
```

The SDK client is checked against the expected UUID, current database and Atomic
engine before use. SDK/query failures close the client and become sanitized 503.
All repository queries retain `readonly=1`, typed parameters, result bounds, exact
four fingerprints, nullable scores and provenance. No S3/Parquet access or synthetic
fallback is introduced into HTTP handlers. Match Lab SQL/routes are unchanged.

## Verification

The manual [isolated rehearsal](../scripts/check_historical_handoff.py) uses the
existing Gold and a fresh ClickHouse `25.8.23.13-alpine` with only tmpfs data/logs,
no production mounts/ports, and a newly created internal test network. The actual
new API image runs Django and the real read-only SDK against that server. Exact
created resource IDs are retained in local receipts. The script saves its receipt
before cleanup and removes only its returned container/network IDs; no prune,
volume deletion, shared-image deletion, or production lifecycle operation.

Reproduction (manual isolated tests only):

```powershell
python scripts/check_historical_handoff.py --confirm-isolated-tests `
  --gold-store data/work/pet3-openfootball-isolated `
  --api-image football-api:pet3d-fix-20261107 `
  --evidence .tmp/pet3d-fix-next/rehearsal.json
```

Evidence path must not exist. No full dataset is added to Git or the API image.

| Scenario | Result |
| --- | --- |
| No writer opt-in / wrong target | Rejected before production access |
| Wrong batch / source hash / content fingerprint | Rejected before mutation |
| Interrupted candidate load | Active remains empty, not published |
| Complete candidate | 189 fixtures / 36 participants / 14 coverage / 394 DQ |
| Replay | REUSED; active count stays 633 |
| Failed replacement | Existing pinned version retained |
| Conflicting rollback receipt | Rejected, no switch |
| Rollback | Original empty active UUID restored; new valid table retained |
| Django after rollback | 503 historical_not_ready |
| Authorized re-handoff | Actual Django routes return 200 and pinned content |
| Real HTTP application pagination | 189 unique fixture IDs over four pages |
| Bad reader authorization / batch / server UUID | 503; valid configuration recovers |

The HTTP assertions use Django's test client with a real authenticated ClickHouse
connection, not a fake transport or public browser. They do not claim Chromium/
Gunicorn network/browser acceptance on 18090. The summary preserves 188
source-reported FT, one UNKNOWN result, two ambiguous components, and no verified
regulation scores, winners, points, or standings.

Additional checks: application regression; targeted publisher gates; CI/security
contracts; Ruff; compileall; repository and diff checks. New offline tests are
discovered by existing CI patterns; the real-Gold rehearsal remains a manual gate
because the pinned dataset is intentionally absent from Git/CI. No remote CI ran.

Final local totals: **85 application tests** on Linux Python 3.12.14 in the new
image, **8 publisher/harness gate tests**, and **82 CI/security contract tests** passed.
Ruff, compileall, repository checks, documentation links and diff checks passed.
Python 3.10 and remote CI were not run at the initial implementation checkpoint;
they are mandatory gates in the subsequent publication review below.
The final real-Gold run and cleanup receipts are local ignored files
`.tmp/pet3d-fix-20261107/rehearsal-verified.json` and
`rehearsal-verified.cleanup.json`. Production audit and source/image preservation
checks are in that directory as `production-after.json` and `verification-complete.json`.

Early rehearsal failures were not counted as PASS: Docker `--tmpfs` inspection
needed `HostConfig.Tmpfs` rather than nonempty `Mounts`; test DB bootstrap needed
to avoid a transient entrypoint initialization race; the client fixture needed
`PYTHONPATH=/app` and a filename that did not shadow stdlib `http`. Each failed
attempt was cleaned up and receipts retained. The first unit harness attempt
also correctly rejected missing synthetic `DJANGO_SECRET_KEY`; the corrected
run supplied only a test value, not production secrets.

## Built image and safety boundary

Temporary image: `football-api:pet3d-fix-20261107`.
Image ID: `sha256:72818133ca3e8b8b8c73117e8872a972087870cb55b9529caf89a36eb4c6b4eb`.
Built from a clean published HEAD archive plus an explicit source overlay, not
the dirty repository or existing licensing index. No licensing/planning documents,
ignored dataset, local secrets, helpers or recovery files were added to that context.

Image-only checks pass historical views/repository/contract imports, Django URL
resolution, disabled HTTP 503, non-root execution, Gunicorn configuration, and
application-filesystem private-artifact exclusions. The image has Python 3.12.14,
Django 5.2.17, clickhouse-connect 0.15.0, Gunicorn 23.0.0. Shared writer/pipeline
modules are absent from the shipped API package. The temporary tag does not replace
the live API tag or container.

The original six production containers and their images/start identities remain
unchanged. Read-only fingerprints cover the original 98 analyses, 12 ClickHouse
tables and five PostgreSQL catalogs; source/Gold seals retain their pinned values.
Licensing staging, planning files and shortcut are preserved. No staging/commit/
push, deployment, persistent ingestion, external API request, S3 change, Superset
change, migration, or recovery-key access was performed.

Both read-only production audits match the retained original fingerprint:
`3c8d098d393d49a29196279e38c280657a9dcc4b65aa65e50831af08f316c4a7`.
Source/Gold and the exact two licensing staged blob IDs also match the earlier
preflight. Running containers before/after: **6 / 6**, all healthy. All rehearsal
containers and networks, including failed attempts, were removed; the temporary
API image was retained. No volume, shared image, or cache was removed.

## Exact change set for later publication review

These 12 original files belong to PET-3D/FIX; do not mix them with licensing or Superset
work, planning documents, the shortcut, datasets, temporary helpers, or evidence:

```text
application/historical_connection.py
application/historical_repository.py
docker/api/Dockerfile
src/openfootball_etl/persistent.py
src/openfootball_etl/serving_contract.py
scripts/check_historical_handoff.py
tests/application/test_historical_production.py
tests/test_historical_handoff.py
tests/integration/historical_handoff_http.py
tests/ci/test_historical_api.py
docs/pet3d-historical-deployment.md
docs/pet3d-production-readiness.md
```

The two licensing documents remain the only staged files with their original
blobs. This change set is **not staged** and has no proposed tree/commit SHA yet.

## PET-3D-FIX-REVIEW publication checkpoint

The review adds only three minimal CI files/changes to the original 12-file unit:

```text
.github/workflows/ci-integration.yml
ci/check_delivery.py
tests/integration/test_historical_handoff.py
```

Total publication unit: **15 files**. Main licensing staging is independent of the
temporary publication index. Exact tree/commit and workflow outcomes are recorded
in the publication handoff, not guessed in advance here.

The new mandatory recovery-job step exercises the real publisher with a fresh
networkless tmpfs ClickHouse, artificial four-dataset rows and test-only pinned
fingerprints. It uses actual Django requests with a native read-only CLI result
adapter, not the production SDK factory. No runtime flag allows synthetic pins in
the production code. Production expected row count now derives from the immutable
four contract counts (still 633), avoiding a second hardcoded manifest total.

Four integration cases cover partial failure, complete publish, replay, wrong
batch/content, rollback conflict, previous visibility, reader fingerprint/UUID
fences, and **three concurrent HTTP requests held across a physical EXCHANGE**.
Those overlapping requests must return 503 without partial summary; later requests
see either NOT_READY or the complete approved bundle. Each request must validate
the same fixed four content hashes and batch before returning any response, so a
different batch cannot be silently mixed even with an ABA name switch. This is
not a global ClickHouse transaction or protection against concurrent admin DDL.

The existing API image audit now actually imports historical modules, resolves
the route and asserts default 503 inside the built production image. Both additions
run in existing jobs without new services, credentials or upstream datasets.
The real-Gold + actual SDK rehearsal remains an intentionally local gated check;
CI uses synthetic data and must not claim production/real-Gold acceptance.

Publication requires clean-snapshot Python **3.10.12 / 3.12.14** offline/application/
CI tests, isolated integration, image build/import, Ruff/compileall, Compose,
actionlint, documentation/security/diff checks, a fresh unchanged remote, preserved
licensing blobs, one normal commit/push, and successful mandatory GitHub jobs.
No live load or deployment is part of this review/publication authorization.

## Conditions before the next live attempt

1. Review/publish these source changes and require CI SUCCESS; retain the exact
   reviewed source snapshot and image build provenance.
2. Obtain separate operator authorization for persistent handoff and API/Web rollout.
3. Fresh read-only target identity, namespace inventory, source/Gold pins and
   StatsBomb/PostgreSQL fingerprints. Serialize operators and freeze namespace DDL.
4. Create and verify a durable owner-only no-overwrite serving recovery capsule
   (Gold, schemas, target/UUID manifests, receipts/hashes); the test's ignored receipts
   are not a durable production backup. Preserve the reviewed previous-state recipe.
5. Prepare exact existing API/Web image rollback configuration and verify effective
   runtime configuration without printing or persisting secret values. Provision no
   new role/grant without a separate scope review; inject reviewed SELECT-only
   historical credentials through the established runtime mechanism.
6. Explicitly authorize `PersistentPublisher.production(...)`, publish the sealed
   Gold once, verify the complete bundle and durably save the returned receipt.
   No unrestricted SQL operator step, upstream re-ingestion, or silent force retry.
7. Only then enable the explicit Django gate and roll out the scoped API/Web images.
   Perform real desktop/mobile/browser/keyboard/localization and Match Lab acceptance
   on 18090, including Xhaka 31/27/4 and Current 2026 DEMO DATA marking.
8. On failure use the reviewed image rollback and receipt-bound logical serving
   rollback. Any UUID/content drift stops for manual review, preserving all tables.

No live load or deployment command was executed by this task.
