# R2.3-A/B/C/D publication audit

Scope: source completeness, security, isolated Git-snapshot reproduction, synthetic
CI integration and staging only. No commit/push, live S3 requests/backup, real key
generation, database recovery, ETL or modification of running services/volumes.

## Status, provenance and publication boundary

Branch `master`; HEAD, cached `origin/master` and read-only `ls-remote` agree on
`8e934a5f65eeb768de1546b03a1a965b91be959a` at the start of this audit.
Remote: `https://github.com/Romanweiss/football-data-platform.git`.
Previously confirmed remote CI is for that published HEAD, not the pending staged tree.

| Recovery boundary | Status |
| --- | --- |
| Synthetic archive/workflow/adapters/operator recovery | PASS |
| Live read-only dry-run | PASS, earlier R2.3-C evidence; not repeated here |
| Live encrypted S3 backup | NOT EXECUTED |
| Independent restore / remote S3 recovery | NOT VERIFIED |
| Secret escrow / complete machine-loss recovery | NOT VERIFIED |
| Overall Stage 8C | PARTIAL |

## Exact intended source set

The audit stages **31 files**; existing tracked database recovery source is already
in HEAD and is reused, not copied into a new parallel system.

| Classification | Paths |
| --- | --- |
| A: format | `src/recovery/s3_archive.py`, `tests/test_s3_archive.py`, `docs/stage8c-r2-3a.md` |
| B: storage/lineage/workflow | `src/recovery/s3_storage.py`, `src/recovery/s3_lineage.py`, `src/recovery/s3_workflow.py`, `tests/test_s3_workflow.py`, `docs/stage8c-r2-3b.md` |
| C: read-only adapters/dry-run | `src/recovery/s3_readonly.py`, `src/recovery/s3_metadata.py`, `src/recovery/s3_dry_run.py`, `scripts/check_s3_recovery_dry_run.py`, `tests/test_s3_readonly.py`, `docs/stage8c-r2-3c.md` |
| D: operator/safety | `src/recovery/s3_operator.py`, `src/recovery/s3_safety.py`, `scripts/s3_backup.py`, `requirements/recovery-s3.txt`, `tests/test_s3_operator.py`, `docs/stage8c-r2-3d.md` |
| Shared status | `docs/stage8c.md` |
| Publication hardening | `.gitignore`, `.dockerignore`, `README.md`, `.github/workflows/ci-fast.yml`, `.github/workflows/ci-integration.yml`, `ci/check_repository.py`, `ci/check_s3_recovery.py`, `tests/ci/test_contract.py`, `tests/test_s3_windows_acl.py`, `docs/stage8c-r2-3-publication.md` |

Some modules span later stages: A's reader supports D's authenticated live scope,
B's workflow includes D's explicitly gated collection path, and C's adapter retains
safe dry-run defaults with D's explicit inventory-bounded quota. Those are one shared
implementation, not independent commits that can be arbitrarily separated.

## Findings and changes made by this audit

- All 20 new A/B/C/D files were untracked; the shared status document was modified.
  The earlier working-directory test successes alone could not prove publication.
- The index completeness contract now requires every archive/helper/CLI/requirement,
  test, document and CI entry point so checkout CI cannot silently omit one again.
- General root test discovery already picked up S3 tests, but explicit coverage and
  a real Windows runner were missing. Add a named synthetic-only recovery gate to
  the existing Linux 3.10.12/3.12.14 matrix and a Windows 2022 / Python 3.12.14 job.
- The explicit runner uses a socket guard; only fake transports and owned ephemeral
  fixtures/keys are used. It includes database profile-v1 compatibility, not a live
  backup/restore CLI command. No recovery artifacts are uploaded by these jobs.
- Windows-specific tests exercise real ACL audit/setup, reject an injected broad
  grant without silently repairing existing paths, refuse reinitializing a nonempty
  directory and reject a real temporary junction. Linux explicitly skips those five
  tests; it is not reported as testing the Windows kernel/ACL implementation.
- A first Windows run passed 158 cases but its crypto-only host venv lacked boto3
  for the database-compatibility S3 inventory test. An isolated temporary venv is
  provisioned from the complete `requirements/recovery-s3.txt` for the acceptance
  run, without changing the old venv/runtime. The CI gate now fails early on a missing
  SDK/crypto dependency and installs the shared Python 3.10 unittest compatibility.
  The rerun passed all 159 cases with no skips; `pip check` found no broken requirements.
- Docker ignore rules previously allowed `data/work` and local temp state into build
  context. They now exclude runtime data/temp caches, preserving only the committed
  synthetic JSON sample. Git and Docker also exclude generic archive/key/dump/database
  suffixes outside the standard backup directories. Existing source/requirements,
  README and Compose remain included.
- A real Docker context probe using only synthetic canaries also proved that root
  `*.key` patterns did not cover nested artifacts. Explicit `**/` rules now protect
  nested key/archive/database files and credential names. After correction all 17
  fake private canaries were excluded and six essential source/config/sample paths
  retained. No real secret or object payload was used in this probe.
- README's red-CI/missing-8B-files statement was stale. It now distinguishes repaired
  published HEAD, earlier live evidence and the not-yet-published S3 staged tree.
  A/B/C/D documents retain their historical stage scope with links to this status.

No encryption, analytics, ETL, real credentials or database schemas were changed by
this publication audit. Existing fast/integration, Spark/Airflow, database, delivery
and frontend gates are preserved. Windows is allowed only for its dedicated job,
not as a blanket relaxation of the existing Ubuntu runner contract.

One targeted operator safety correction rejects output under any existing ancestor
`.git` (including a different repository/worktree), not just this source checkout.
Previously the explicit workspace check covered only the current project root.
Its regression uses a fake empty `.git` directory in a temporary fixture. No live
path/ACL is changed. Staging also caught and removed trailing blank EOF lines in
the formerly untracked safety module; the cached diff now checks all new files.

## Security boundary

Private names/paths are rejected before scanning file contents. Only explicitly
allowlisted public source/docs and Git-index blobs are inspected; `.env`, `.passes`,
`keys.txt`, existing backup/key folders and runtime payloads are not opened.
Signature scanning prints only path/line/kind, never matched values. It is a
high-confidence signature audit plus source review, not proof against every possible
encoded secret or an exhaustive historical Git-secret scan.

The only tracked data payload is `data/samples/sample_match.json`, a small synthetic
fixture. Real data/work, temporary state, dumps, encrypted artifacts, recovery keys
and restored databases are excluded from Git and Docker context. No production
archive, key, database dump or real object bytes are included in the staged source.

## Isolated-snapshot reproduction

The verification source is a Git tree made from the audited index via `git write-tree`,
exported with `git archive` into a newly created system-temp checkout. Its own Git
index is initialized from that exact tree without creating a commit. Ignored working
tree state, `.env`, `.passes`, keys, installed frontend dependencies and real archives
are not copied. Tests and builds use that directory, not a bind of the developer tree.

The final Git tree ID is reported externally (it cannot identify itself inside its
own content). Archive export disables `core.autocrlf` to avoid a Windows-only
line-ending conversion; `git diff --quiet` proves exported source equals the index.
An initial export with inherited CRLF conversion was rejected, not treated as a
successful clean-checkout test. The correct export contains 416 public tracked files.

| Check from isolated source | Result |
| --- | --- |
| CPython 3.10.12, outbound network disabled | 684 root tests, 30 application tests, 19 CI contract tests PASS |
| CPython 3.12.14, outbound network disabled | 684 root tests, 30 application tests, 19 CI contract tests PASS |
| Explicit S3 + DB-v1 compatibility gate on each Linux version | 159 tests, PASS with 5 explicitly skipped real-Windows-only cases |
| Full Windows gate, isolated SDK/crypto venv, exported Git source | 159/159 PASS, no skips; includes all 5 real ACL/junction checks |
| Final cross-repository output guard regression | PASS on Windows and both Linux versions |
| Ruff / compileall, both versions | PASS |
| Repository/index completeness, private-path and signature contracts | PASS |
| Actionlint and placeholder-only Compose / app-prod config | PASS |
| Frontend regression | 50 tests PASS; TypeScript + production build PASS |
| Production API and web Docker builds | PASS; both non-root/configuration/shipped-content audits PASS |
| Docker context probe | 17 fake private canaries excluded; essential public paths retained |
| Staged whitespace and explicit source inventory | PASS |

Frontend code comes only from the Git snapshot. Its package lock was compared byte
for byte with the preinstalled dependency image before using those dependencies;
developer `frontend/node_modules` was not copied. A production Docker build also
uses that snapshot/lock and normal declared installation steps. An initial
`--network none` Docker dependency-install attempt lacked public package downloads;
normal builds subsequently passed. Synthetic tests themselves stay network-disabled
and never access Selectel. No application/live-serving or database restore was run.

The Windows real-ACL run uses the same exported Git source and owned disposable
fixtures, with synthetic live-runtime/factory guards as documented in D. Hosted
Windows 2022 / CPython 3.12.14 remains a **new remote CI gate to observe after push**,
not an already-passed remote run. No actual live operator preflight is claimed.
The runner label is listed in the [official GitHub hosted-runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories).

The completed Windows run used the dependency-complete isolated CPython 3.14.3 venv
and mocked only live-runtime/factory acceptance, as D documents. The final safety
predicate/regression was tested separately from another staged Git export; both
Linux matrices ran the complete final source. Updating this evidence document does
not substitute a working-tree run for those Git snapshots.

## Proposed publication

Prefer one coherent commit because the shared format/workflow, explicit CI and
publication-completeness contract are mutually dependent:

```powershell
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: add gated S3 recovery archives and synthetic CI"
git push origin master
```

These commands are for separate confirmation; they were not executed. Never use
`git add .`, force-push or rewrite history. After the approved push, wait for both
new fast/integration runs, including the Windows job; old green CI is not a new
remote verdict. Do not upload synthetic/private archive artifacts to troubleshoot.

## Prerequisites for the first live backup remain separate

Supported host CPython 3.12.14 and optional `requirements/recovery-s3.txt`; approved
host SDK environment and CA trust; private independent physical storage with audited
permissions; sufficient fresh free space; separately recoverable key/vault unlock;
fresh bounded source preflight and exact identity/inventory digest; quiet collection
window; operator attestations and a separate live-run approval. The current 3.14.3
host recovery environment is not a passed live preflight. Historical versions/lock
remain UNKNOWN where C observed HTTP 403. Publishing source does not close Stage 8C.
