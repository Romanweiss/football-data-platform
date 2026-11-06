# SUPERSET-UX-4 — desktop-first acceptance and isolated PostgreSQL readiness

Date: **2026-11-06**. Baseline `master`:
`d3443f77c24445c3d2fb0978c10d0b57155561e8`.

**Publication: READY for a separate authorization/review of the proposed snapshot.**
**Live apply: BLOCKED pending a separately authorized durable backup, verified
restore rehearsal and explicit production-target adapter review/authorization.**
This stage does not activate a production writer or apply a live patch.

Stage 8C remains **PARTIAL**; PET-3D **NOT STARTED**. Persistent football-data.org
onboarding remains **BLOCKED / LEGAL_REVIEW_REQUIRED** and is unrelated to this BI change.

## 1. Accepted product policy and frozen candidate

Apache Superset Match Analysis is **desktop-first**. React remains the primary
mobile-first product UI. Native `?standalone=1` is an optional mobile presentation
profile, not a fix to normal navigation. Normal mobile width **418/390 px** remains
**NOT PASS**. Baseline/native contrast, language, heading and menu findings are
not fixed; **overall axe PASS is not claimed**. No new visual revision was made.

The product decision accepts these documented limitations; it does not turn a
failed technical criterion into a passing test. The fixed candidate-specific
clipping and `scrollable-region-focusable` results remain those of
[UX-3](superset-match-analysis-ux3.md), supported by
[UX-2](superset-match-analysis-ux-acceptance.md) and
[UX-1](superset-match-analysis-ux-review.md).

Frozen revision: **ux3-r2**. Trusted SHA-256 values:

| File | SHA-256 |
| --- | --- |
| before.json | `37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86` |
| candidate-config.json | `d741625a585e12a96f786994e18df92b04ce5d1a2ecae91881938da530ec3555` |
| config-patch.json | `3d6d2c5037c7c1a9e3f8cd7c1f2ef3e5441ae7ae43cdc89358cb8b2cd18c2a6c` |
| rollback-fields.json | `35652191f52c20cfa9a0329a06df9a28936435cfa5383925608bc0490c78a22e` |

Original UX-1/r1/r2 bundles and byte-reproduced r2 remain intact. Fresh bounded
read-only live metadata/domain export equals the UX-3 export. Its canonical JSON
SHA-256 is `329eac17fb49e9f6f6fa3087b535c064a20c0e2acb671f31b865de8202bec6d6`.
This is a metadata + bounded domain fingerprint, **not** a new full-table scan.

Consequently the existing real-source evidence is retained, not rerun:
98 exact display labels/canonical keys; 32 chart cases; 35 invalid-selection
checks; 93 NOT_APPLICABLE / 5 DATA_AVAILABLE; all 8 charts; final Summary 4:2 and
8 attempts; 8 desktop/mobile UI cases; no new serious scrollability regression.
No fuzzy mapping, source record, result, metric or visual parameter was changed.

## 2. PostgreSQL adapter — a new isolated gate, not removal of the old gate

[superset_ux_postgres.py](../scripts/superset_ux_postgres.py) reuses the existing
22-field CAS protocol/column writer. The SQLite adapter still **rejects PostgreSQL**.
The new adapter only permits this explicit synthetic target:

- backend PostgreSQL, host `127.0.0.1`, port 5432;
- database `football_superset_ux4`, user `ux4_fixture`;
- no password or URL query overrides;
- pre-existing marker table `ux4_target_guard`, row 1, exact test marker;
- byte-authenticated ux3-r2 bundle and a caller-supplied reviewed state fingerprint.

There is **no production hostname, database allowlist entry or live-apply CLI**.
Changing a URI or disabling a backend check is not an approved deployment method.
The marker is a mistake-prevention guard, not a credential or protection against
an administrator who can rewrite code/database state. Container/network isolation
is part of the test boundary.

Transaction behavior:

1. Refuse an already active caller transaction without rolling it back.
2. Start SERIALIZABLE; local lock timeout 2 s, statement timeout 15 s.
3. Verify/lock marker; lock fixed owners/RBAC/metric association tables.
4. Lock base rows of charts, datasets, dashboards and columns with `FOR UPDATE`;
   expire the ORM identity map before reading CAS values.
5. Compare complete scoped-state/protected-metadata fingerprint, then all 22 CAS
   field values. Only runtime `shared_label_colors` remains outside CAS ownership.
6. Update only the 22 approved paths, flush, check protected metadata and readback.
7. One transaction commit. Conflict/error: rollback, no partial success.

Row locks deliberately use Core base-table SELECTs: Superset ORM eager/default
queries can contain DISTINCT, which PostgreSQL cannot combine with FOR UPDATE.
This incompatibility was found by the real test, corrected and retested.

Protected state includes IDs, UUIDs, owners, original column IDs/attributes, all
unowned chart/dataset/dashboard attributes, RBAC and relevant associations/metrics.
No database connection/password export is used. Receipts contain only safe codes,
counts and digests. SQLAlchemy exceptions are reduced to fixed diagnostic codes;
no SQL/parameters/URL/traceback is printed by the public test runner.

Superset's automatic `changed_on` audit timestamps and PostgreSQL sequence
positions are explicitly excluded from exact round-trip equality. Sequence values
can advance even after rollback; this is not a partial data write. No other
metadata difference is silently ignored. Added display/status columns are owned
by the reviewed patch; original column IDs and UUIDs must remain unchanged.

## 3. Real isolated PostgreSQL acceptance

PostgreSQL **17.6**, existing immutable image:
`sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94`.
Superset **6.0.0**, image:
`sha256:fe90eca2116e101b8a34a3bbfbfde881014e34857490faec75873f60d0ca8fe8`.
Backend Python is **3.10.19** (not a 3.10.12/3.12.14 matrix claim).

Two independent ephemeral PG instances were used: initial diagnostic fixture and
a clean reproduction through the proposed public runner. PG has **network none**,
loopback-only listen address, no published ports, no volumes and a 256 MiB tmpfs
PGDATA. Runner shares only that network namespace and receives read-only mounts
of code/tests/trusted non-secret bundle. It has no network route to production.
Local trust authentication is confined to this isolated test namespace; it is
not a production recommendation. No production DB user/password was copied.

Fixture: real Superset ORM models, 16 charts / 12 datasets / 2 dashboards, pinned
non-secret configuration, synthetic owner/role and an **unconnected** synthetic
analytical Database. No ClickHouse connection or chart query occurs in this test.
Schema setup creates only model dependencies, not migrations. Initial broad
create_all hit an unrelated SQL Lab FK incompatibility; the published setup is
targeted and the fresh reproduction passed without bypassing writer checks.

| Check | Actual outcome |
| --- | --- |
| Clean apply, 22 fields, one commit | PASS |
| New semantic/config readback against pinned r2 | PASS |
| Duplicate apply with fresh candidate fingerprint | CAS_CONFLICT; unchanged |
| Committed operator edit before apply | METADATA_FINGERPRINT_CONFLICT; edit retained |
| Operator edits unowned Overview params | METADATA_FINGERPRINT_CONFLICT |
| Writer holds row; independent operator UPDATE | PostgreSQL 55P03, blocked |
| Operator holds row before writer | POSTGRES_LOCK_CONFLICT; no patch |
| Owner association / RBAC changes | METADATA_FINGERPRINT_CONFLICT |
| Wrong isolated target marker | ISOLATED_POSTGRES_MARKER_REQUIRED |
| Exception after actual flush | POSTGRES_TRANSACTION_FAILURE; full rollback |
| Operator edit before rollback | conflict; operator change retained |
| Clean rollback, one commit | PASS |
| Old semantic/config validator | all 22 fields restored |
| Whole fixture metadata/owners/RBAC comparison | PASS, documented audit/sequence exclusions only |

Final PostgreSQL fixtures are **old contract**. Existing real-source SQL/chart
validator evidence belongs to UX-3 and was not misreported as new PG chart queries.
No repeat of the four-match browser suite was necessary: same authenticated
configuration, exact stored readback, unchanged source fingerprint and no rendering
or query behavior change. No additional browser PASS is claimed for UX-4.

Reproduction entry points:
[runner](../scripts/check_superset_ux_postgres.py),
[contracts](../tests/integration/superset_ux_postgres_contracts.py),
[offline gates](../tests/test_superset_ux_postgres.py).
Only in a new, approved network-isolated test container with the test PG already
running and the trusted r2 bundle mounted read-only:

```sh
/app/.venv/bin/python /ux/scripts/check_superset_ux_postgres.py \
  --confirm-ephemeral-postgres --bundle-dir /ux/bundle
```

The runner authenticates bounded bundle bytes **before** any bootstrap write,
ignores image/live config, and refuses an already populated fixture by default.
The bundle is an explicit retained input, not fetched from live services and not
embedded in Git. CI fast automatically discovers offline gates/completeness
contracts; this real Superset/PostgreSQL harness was run locally, **not in GitHub CI**.

## 4. Durable scoped backup design — not executed

No live metadata backup or new private directory was created in this stage.
Proposed operator-configurable root, outside `.tmp`, repository and recovery keys:
`Join-Path $env:LOCALAPPDATA 'FootballPlatformOperations\SupersetMetadata'`.
This is not tied to a particular Windows username or the S3 recovery-key vault.

Before a future live apply, require a separately authorized backup tool/rehearsal:

1. Validate no reparse points; reject existing insecure parent. Create a new
   versioned directory with protected **owner-only** DACL and audit actual owner/
   ACEs. **no-overwrite** files, no relaxed fallback, no backup under repository.
2. Read only an allowlisted scoped export in a consistent PostgreSQL read-only
   transaction: old 22 fields, rollback data, original column IDs/attributes,
   object IDs/UUIDs, owners/RBAC guard fingerprints, Superset/schema versions.
   Never export connection URIs/passwords, users/password hashes or full metadata DB.
3. Manifest records format/revision, timestamp, source identity, reviewed before
   fingerprint, target identities and SHA-256/byte length of every included file.
   Include candidate/inverse pins. Write files exclusively, flush, then read back
   and verify hashes/ACL. A partial directory is NOT a completed backup.
4. Authenticate manifest against a separately retained trusted digest/receipt;
   a self-contained SHA-256 manifest alone is not tamper-proof. Preserve complete
   bytes outside temporary artifacts before considering cleanup.
5. Restore rehearsal on a separate equivalent ephemeral PG copy: verify trusted
   digest, schema/object identities and owner/RBAC guards, apply candidate, restore
   scoped old state transactionally, run old validator and compare protected state.
   Current synthetic rollback is evidence for the writer, **not** proof that the
   not-yet-created durable backup can be restored.
6. Immediately before live write, lock and CAS against the reviewed backup
   fingerprint. Any intervening edit requires a new review/backup; never force it.

Proposed retention: keep last 3 successful scoped generations for at least 90 days;
keep the latest verified rollback generation while that configuration is deployed.
Never delete the only verified generation, an unresolved-incident generation or
one under review. Rotation/deletion and any independent copy need separate approval;
ACL-only local storage is neither encryption nor offsite protection.

## 5. Publication unit and verification

Exact proposed unit: **16 files** (one existing tracked script modified, the rest
currently untracked). The infra report is included because UX-2/UX-3 link to it;
licensing/planning documents and shortcut are explicitly excluded.

1. `docs/infra-audit-2026-11.md`
2. `docs/superset-match-analysis-ux-review.md`
3. `docs/superset-match-analysis-ux-acceptance.md`
4. `docs/superset-match-analysis-ux3.md`
5. `docs/superset-match-analysis-live-readiness.md`
6. `src/analytics/superset_ux.py`
7. `scripts/superset_semantic_safety.py`
8. `scripts/superset_ux_metadata.py`
9. `scripts/superset_ux_validate.py`
10. `scripts/build_superset_ux_layout.py`
11. `scripts/superset_ux_postgres.py`
12. `scripts/check_superset_ux_postgres.py`
13. `tests/test_superset_ux.py`
14. `tests/test_superset_ux_postgres.py`
15. `tests/integration/superset_ux_postgres_contracts.py`
16. `tests/ci/test_superset_ux_publication.py`

New UX-4 work is files 5, 11, 12, 14, 15 and 16. Earlier UX history/reports remain
unchanged. A separate temporary Git index is initialized from baseline and receives
only the above exact paths. Proposed tree hash is recorded in the final handoff
and local receipt, not inside this file (which would create a self-hash cycle).

Verification from the isolated source snapshot (no project secrets, venv,
node_modules, helper or dataset mounts):

- Linux Python **3.10.12** and **3.12.14**, each: **1112 offline tests**, with
  **1103 passed / 9 skipped**, plus **79 application** and **81 CI/security** tests
  passed. Nine skips are Windows-only ACL/junction/disk tests; not counted as PASS.
- Windows Python **3.12.10**: **50 targeted offline tests passed**, no skips.
  The Windows-only recovery suite was not rerun for this metadata-only change.
- Full snapshot Ruff/compileall and repository/workflow/security checks passed.
  All 16 files passed high-confidence secret-signature checks; local Markdown
  links/anchors and temporary-index diff/whitespace checks passed. Signature
  scanning is not a proof that arbitrary sensitive prose cannot exist; the
  publication scope was also reviewed for raw exports/private artifacts.
- Clean source index reconstructs exactly the proposed tree. Windows' initial
  archive export applied CRLF conversion; a new LF-controlled export was used
  and its write-tree was verified equal, without changing original files.
- GitHub CI, frontend rebuild and a new browser suite were **not** executed here;
  existing UX-3 browser evidence is retained for the unchanged candidate.

The exact snapshot hash is recorded in the final handoff/local receipt.
No screenshots, raw exports, trusted bundle files, fixture DB, ephemeral helper,
licensing/planning document, credential or CA material is included in that tree.
The new completeness test prevents a checkout missing one of the 16 dependencies.

Main index remains only the two licensing documents, with original blob IDs:

- comparison: `fac8b0073dc67bab8f5341b4304036ea78d91e54`;
- licensing review: `6fe2394c0dc11ded3199c5e7d75c173d96bc9ddd`.

An index backup is retained locally; the primary index is not replaced. HEAD,
licensing/planning content and shortcut are preserved. Worktree is intentionally
dirty, not falsely called clean. No staging in main index, commit/push or deployment.

## 6. Test-container whitelist — no cleanup executed

The four UX-2/UX-3 instances have the same immutable Superset image, no Docker
volumes and only read-only code mounts. Bounded process inspection found only the
server process, no active harness; host process inspection found no running UX
test runner. This is a point-in-time observation, not proof no user can reconnect.
Bundles/pins/screenshots/receipts remain present. Recheck before any later cleanup.

| Exact name / port | Exact container ID | State |
| --- | --- | --- |
| football-superset-ux2-20261106 / 18089 | `a12f5c742199bdd04a0f2373323b1f3ce9537211e4452f22edea76d5f139f42f` | running, UX-1 candidate |
| football-superset-ux2-v2-20261106 / 18091 | `39e76ad6ea41ac8ceeaad7702996c2e4051212341562213792860aafbbf848e1` | running, old |
| football-superset-ux3-r1-20261106 / 18092 | `08d7d2c5d0bcd65222d652bf6b3dfb892416f6aeaaa95d2aab29ea2212515daa` | running, old |
| football-superset-ux3-r2-20261106 / 18093 | `7f2a753eabc9df067027ed290b0c4e8df4c2006534ab04a00dd16ac22ba34791` | running, old |

Whitelist is **only those names AND matching IDs**, after separate cleanup approval
and durable preservation of evidence outside `.tmp`. Never include live
`football-superset`, `football-superset-db`, other projects, image/network or volumes.
No stop/rm/prune command was executed. Existing UX-3 report contains a future-only
named command proposal; it is not an instruction to execute it now.

Additional UX-4 fixtures are inventoried separately, **not silently added to that
four-container cleanup authorization**: `football-superset-ux4-pg-20261106` and
`football-superset-ux4-pg-repro-20261106` (running, network none, tmpfs),
`football-superset-ux4-contracts-20261106` and `football-superset-ux4-repro-20261106`
(exited test runners). They were not removed. Stopping PG loses the tmpfs fixture;
retain non-secret result receipts first. No production volume is attached.
The clean-checkout Linux tests also left exited, network-none containers
`football-superset-ux4-offline310-20261106` and
`football-superset-ux4-offline312-20261106`; they likewise need separate cleanup
approval. Any final-snapshot rerun uses separately named `-final-` test containers.

## 7. Minimal safe next actions

1. Separate authorization for publication of exactly this tree; verify fresh remote
   baseline, protect licensing blobs/index, one normal commit/push, wait for CI.
   Suggested message: `feat: prepare desktop-first Superset metadata UX patch`.
2. Separately authorize durable scoped backup implementation/rehearsal and an
   explicitly reviewed production PostgreSQL target adapter. Do not repoint this
   isolated adapter or remove its gates. Reconfirm desktop-first policy/limitations.
3. Only after verified durable backup/restore and fresh source/metadata CAS gates,
   request explicit live-apply permission and maintenance window. Single transaction,
   readback/semantic checks and targeted desktop smoke; rollback only against the
   exact reviewed candidate, never overwrite concurrent operator edits.
4. Separate operator acceptance and later explicit cleanup of whitelisted fixtures.

Live Superset 18088, Web/API 18090, production PostgreSQL/ClickHouse, datasets,
Compose, ETL, S3, K: backups, F: restore and recovery keys were not changed. No
authenticated UEFA request, ingestion, Spark/Airflow job or PET-3D was started.
