# R2.4-A1–A1.7 publication readiness

Baseline: `bea3d8dd94f87f1e3f683c13541d77db361fc423`, branch `master`.
This is a source/publication audit, not authorization for a key or live collection.
Stage 8C remains **PARTIAL**. Commit and push require separate approval.

## Evidence and boundaries

| Capability | Evidence/status |
| --- | --- |
| Synthetic S3 archive/workflow/restore | PASS in offline suites; no real payloads |
| Windows host runtime, private paths/ACLs | [A1](stage8c-r2-4a1.md) |
| Live bounded read-only source audit | [A1.5](stage8c-r2-4a1-5.md): PASS, historical 315 objects / 356,383,409 bytes, 22 build identities |
| Local synthetic escrow and safe diagnostics | [A1.6](stage8c-r2-4a1-6.md): PASS locally, not independent escrow |
| Manual phone/Bitwarden synthetic retrieval, offline verify, restore/SHA-256, negatives and cleanup | [A1.7](stage8c-r2-4a1-7.md): PASS, phone provenance operator-attested |
| Live encrypted S3 backup / actual recovery key | NOT EXECUTED / NOT CREATED |
| Independent real S3 restore | NOT VERIFIED |
| Bitwarden account/MFA recovery after loss of all devices | NOT VERIFIED |
| Complete machine-loss recovery / real-secret escrow and restore | NOT VERIFIED |

The prior green workflows cover the baseline only. Staging or local tests do not
constitute a new GitHub CI result. Historical runbooks keep their stage-specific
counts and decisions; A1.7 supersedes A1.6's then-unselected synthetic escrow route,
not its real-key/backup boundary. Do not repeat any completed manual session.

## Complete publication inventory

| Stage | Paths |
| --- | --- |
| A1 runtime policy | `src/recovery/s3_operator.py`, `tests/test_s3_operator.py`, `docs/stage8c-r2-4a1.md` |
| A1.5 host credential/TLS read-only launcher | `src/recovery/s3_host.py`, `scripts/check_s3_host_readiness.py`, `tests/test_s3_host.py`, `docs/stage8c-r2-4a1-5.md` |
| A1.6 typed safe diagnostics and local escrow | `src/recovery/s3_diagnostics.py`, `src/recovery/s3_readonly.py`, `tests/test_s3_diagnostics.py`, `tests/test_s3_escrow.py`, `docs/stage8c-r2-4a1-6.md` |
| A1.7 manual synthetic checkpoint helpers and Windows restore ACL fix | `src/recovery/s3_manual_drill.py`, `scripts/show_synthetic_escrow_key.py`, `scripts/receive_synthetic_escrow_key.py`, `src/recovery/s3_archive.py`, `tests/test_s3_manual_drill.py`, `tests/test_s3_windows_acl.py`, `docs/stage8c-r2-4a1-7.md` |
| Shared runbooks/publication security | `README.md`, `docs/stage8c.md`, `docs/stage8c-r2-3d.md`, `.gitignore`, `.dockerignore`, `ci/check_repository.py`, `tests/ci/test_contract.py`, this document |

These are 27 distinct changed/new files. Existing `requirements/recovery-s3.txt`,
`ci/check_s3_recovery.py` and both workflows already supply the pinned dependencies
and discover **all** `test_s3_*.py` plus database-profile compatibility tests. They
need no duplicate suite or new credentials. Publication completeness contracts now
require the new sources/scripts/tests/runbooks in the Git index as well.

Linux remains pinned to 3.10.12 / 3.12.14, Windows to 3.12.10. The Windows job keeps
real owner/DACL/Everyone-grant/junction checks and scoped hosted-runner owner setup.
Linux-only skips cannot replace the native Windows run. The small restore ACL fix
initializes **only a newly created empty synthetic destination** before plaintext
writes; it neither repairs operator directories nor changes database profile v1.

## Reproduction and safe configuration

Materialize the index into a fresh system-temp checkout, initialize an isolated Git
index with exactly those tracked files, and assert its `git write-tree` equals the
staged tree. No commit object is needed. Run checks there, never against a working
directory with untracked helpers. The final operator report records the actual tree
hash and results; do not embed a self-referential tree hash in this file.

Native Windows (use the existing absolute interpreter path, not the global Python):

```powershell
& $recoveryPython -B ci/check_s3_recovery.py
```

Linux, using the existing test images and a read-only checkout mount, network disabled:

```text
python -B ci/check_s3_recovery.py
python -B ci/run_unittest.py discover -s tests -p test_*.py
python -B ci/run_unittest.py discover -s tests/application -p test_*.py
python -B ci/run_unittest.py discover -s tests/ci -p test_*.py
python -B ci/check_repository.py
ruff check --no-cache .
python -X pycache_prefix=/tmp/football-compile -m compileall -q application src scripts tests ci dags
```

Also run actionlint and Git whitespace/index checks. Recovery CI blocks socket
creation and uses fake SDK/metadata transports; it must never invoke live source
audit, keygen/create, database backup or Docker-volume recovery. Production frontend,
API, Spark/Airflow and database code are unchanged; their existing CI gates remain.

The archive and key directories are explicit CLI arguments, not source defaults.
K is the operator's chosen physical medium, not proof encoded in a path name.
Resolve the Windows profile using `[Environment]::GetFolderPath('UserProfile')`;
manual fixtures use the system temporary directory and fresh UUIDs. No username
or deleted historical fixture is required to build/test a checkout. The manual
synthetic helper additionally refuses K, deliberately keeping tests off backup media.

The CA bundle is an explicit `--ca-bundle` host path. It is not shipped in Git:
public PEM/CRT/CER files, venvs, environment files, recovery keys/archives, dumps and
runtime payloads remain excluded from Git and Docker contexts. Source pin hashes
and non-secret historical session IDs are not CA bytes or keys. The host launcher
uses captured allowlisted credentials only in memory, restores environment/logging,
and does not add credential acquisition to the actual backup CLI. No Bitwarden
integration, cloud upload or programmatic vault inspection is present.

## Proposed publication and next live boundary

Proposed single logical commit, **not executed by this audit**:

```text
feat: prepare Windows S3 recovery and manual key escrow
```

Before approval, inspect staged names/diff, `git diff --cached --check`, completeness
and secret-signature contracts. Their high-confidence signatures are not a guarantee
against every secret or a full-history/entropy audit. Record the final 27-file tree
and leave the original HEAD/history unchanged.

Before first live backup: separately approve actual key creation, independently
escrow/retrieve **that** key with a session mapping, verify current private media/ACLs,
CA/runtime and space, obtain a fresh bounded inventory/lineage/source identity and
quiet window, then explicitly authorize collection. Historical S3 capabilities
returning 403 remain UNKNOWN. Independently verify the resulting real archive and
plan an isolated restore; a phone synthetic PASS is not a substitute. Patched Windows
runtime availability, USB durability/ransomware exposure, vault/MFA recovery and
separate escrow of runtime secrets remain operator risk/prerequisite reviews.
