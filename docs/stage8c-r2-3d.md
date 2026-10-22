# Stage 8C-R2.3-D: live S3 backup preparation and safety gates

This document records stage D evidence. For current isolated-snapshot and publication
checks, see the [publication audit](stage8c-r2-3-publication.md). Its future operator
procedure remains unexecuted; publication approval is not live-backup approval.

The subsequent [R2.4-A1 Windows environment preparation](stage8c-r2-4a1.md)
records the narrow Windows Python availability exception and current local paths.
The later [A1.5 host credentials/TLS acceptance](stage8c-r2-4a1-5.md) adds a separate,
explicit read-only launcher with allowlisted captured-pipe credentials. The original
backup CLI and its key/backup confirmations remain unchanged.

Implementation date: **2026-10-21**. This stage implements a future full collection
path and tests it with **synthetic objects/fake SDK only**. No Selectel request,
real archive, real recovery key, database recovery, IAM/data/volume change or
commit/push was performed in D. The earlier C dry-run remains the last live evidence.

**First real backup authorization: BLOCKED pending operator prerequisites.**
Stage 8C remains **PARTIAL**. A local path or operator attestation is not proof
of independent storage, key escrow, remote restore or machine-loss recovery.

## Shared implementation, not a second backup format

`scripts/s3_backup.py` delegates to `src/recovery/s3_operator.py` and the existing
S3 workflow. Synthetic and live wrappers share `_backup()` in `s3_workflow.py`:

1. Initial full root LIST/HEAD, retaining distinct LIST and HEAD validators.
2. Detached PostgreSQL catalog/receipt and ClickHouse serving baseline through
   `DockerMetadataSource`. Require all known registered objects/build markers.
3. Check destination/key/space, expected source identity and exact preflight
   inventory digest. Correct/wrong conditional GET probes in all three layers
   must pass before any archive session is created.
4. Authorize full streaming reads against the observed inventory's exact total
   byte quota and maximum object size. This explicit method cannot be enabled by
   the default dry-run constructor or an environment toggle. Each read remains
   at most 64 KiB; encryption buffers at most one configured chunk (64 MiB max).
5. GET every current object with its native HEAD `IfMatch`; verify returned HEAD
   fields/metadata and length, hash original bytes and encrypt via existing
   AES-256-GCM/HKDF/chunk/index implementation. Registered Bronze byte hashes must
   equal PostgreSQL catalog SHA-256. ETag is never a content checksum.
6. Reopen/decrypt/hash written ciphertext from the destination before fences.
   The check is of filesystem readback, not a claim that OS/device write caches
   survive power loss or that an independent medium has been proven.
7. Final full LIST/HEAD, unchanged source identity and metadata digest; run full
   byte-aware lineage, exact file sets, deterministic build identities and receipt
   reconciliation. No transformation/DQ/build-ID changes.
8. Append the encrypted/authenticated evidence object. Recheck placement, key
   availability/content, free-space reserve and session ACLs. `seal()` verifies
   the on-disk encrypted index and all chunks before publishing its HMAC manifest.

Every listed object is included, registered or not. No historical-version backup
is implemented. Interrupted sessions are retained unsealed/aborted, with no delete,
cleanup, overwrite, resume or incremental fallback. Retry creates a new UUID/salt
session with a new source fence and SDK quota. No manual request retry loops added.

### Backward compatibility

Schema remains **2**: the same core fields, AES-GCM/AAD, HKDF parameters, authenticated
envelope, index and chunk records. The authenticated `scope` enum now additionally
permits `live-current-objects`; default `synthetic-local` serialization is unchanged.
Live writers require a permission guard; old synthetic readers/writers remain usable.
Old pre-D readers intentionally reject the previously unknown live scope rather than
mislabel it. Use current matching source/version for a live archive.

The live evidence record uses `scope=live-current-objects` and `recovery_role=live-evidence`;
synthetic evidence remains unchanged. N source objects still produce N+1 archive
records. Safe verification authenticates and checks all source bytes and stored
lineage without contacting the source. It returns counts/digests, never decrypted
keys, metadata or payloads. Synthetic restore refuses a live-scope archive; no real
cloud restore/write adapter or destination credentials are introduced.

Database schema/profile v1, `archive.py`, `operations.py`, `runtime.py`,
`scripts/backup.py`, database requirements and all DB/ETL/serving data are unchanged.

## CLI and defaults

```text
scripts/s3_backup.py [preflight]        read-only dependency/path/space plan; no implicit S3 calls
                    preflight --check-source
                                      bounded real read-only C-style audit, never full collection
                    init-directory    explicit new private local directory only
                    keygen            explicit new separate random 32-byte key only
                    create            full archive, explicit multi-gate operator opt-in
                    verify            offline full integrity + lineage verification
                    inspect           same authenticated safe summary, not raw index/manifest dump
```

No command defaults to key generation, directory creation or backup. An offline
size estimate is labelled `OPERATOR_ESTIMATE_NOT_FRESH_INVENTORY`; it cannot count
as source acceptance. Preflight changes no permissions/files. Missing dependencies
are reported even before crypto/SDK import. `--help` requires only stdlib.

`create` requires **all** of:

- Explicit existing `--destination` and separate `--key-file`.
- `--expect-source-id` and `--expect-inventory-sha256` copied from a fresh preflight.
- `--confirm-live-backup`, `--confirm-key-recoverable`,
  `--confirm-independent-media`, `--confirm-quiet-window`.
- Supported host Python/dependencies, safe paths, private ownership/permissions,
  available unchanged key, enough space, correct source identity and source fences.

Confirmations are operator attestations, not empirical proof. Do not invoke them
merely to make preflight green. Any failed gate blocks seal; no bypass flag exists.

## Paths, permissions and media

Output and key paths must be absolute and have no `..`, symlink, Windows reparse
point or UNC/device-path routing. Refuse workspace descendants **and ancestors**,
filesystem roots, secret directories/files, known Docker data roots and discovered
Docker volume mountpoints. Windows Docker application-data roots are also blocked.
The operator is host-only; known Docker/Podman container execution is refused.
Run as the filesystem owner, not inside a container with an ambiguous bind/volume.

The destination parent and key parent are existing **non-overlapping private directory
trees**. A key cannot be inside the backup directory, and the key directory cannot
contain the backup directory. Existing database `.recovery-keys` locations are not
reused. Hardlinked key/artifact files are refused. Session/artifact writes are exclusive.

POSIX: current effective UID, directories 0700 and files with no group/other permissions.
Windows: protected directory DACL, current owner and no allowed principal other than
the current SID. `init-directory`/a new live session remove extra grants only on the
newly created empty directory, then audit the result. Existing operator paths/keys
are never silently chmod/ACL-reset. ACL setup/audit failure is fatal; uncertain partial
directories are retained, never automatically deleted. Administrator/host compromise,
malicious concurrent filesystem replacement and OS privilege escalation are outside
this protection boundary. Do not use FAT/exFAT or a filesystem unable to prove ACLs.

Windows tests exposed two actual portability issues: PowerShell `-Command -` did not
execute the multiline probe as one script, and `Set-Acl` attempted an unavailable
privilege. The implementation now uses escaped literal paths in an encoded command
and DACL-only `icacls` changes restricted to new empty directories, followed by an
independent read-only ACL audit. No existing real directory's ACL was changed.

Use a separate physical NTFS medium, or another independent filesystem with
working audited ownership/ACLs; not ordinary FAT/exFAT.
Record device identity, encryption/BitLocker unlock recovery, capacity and where the
device is stored/disconnected. A different folder/drive letter alone is insufficient
to prove machine-loss or administrative independence. No device was selected here.

### Space planning

Last C observation: **315 objects / 356,383,409 bytes**. D did not re-inventory or
download those objects. Current default planning for that operator-supplied baseline:

| Item | Bytes |
| --- | ---: |
| Source bytes | 356,383,409 |
| Conservative archive upper bound | 373,303,289 |
| Required additional reserve | 93,325,823 |
| Required free destination space before collection | **466,629,112** |

The bound includes maximum index/evidence allowances, bounded chunk overhead and
headers; reserve is max(64 MiB, 25% of upper bound). Actual file-count/chunk/index
limits still fail closed: 9,999 source objects + one evidence record, 20,000 chunks,
8 MiB index, 1 MiB per cached lineage document / 8 MiB total cached documents/evidence.
Before seal only the remaining reserve is required; the already-written archive
is not charged twice. Space/quota/device failure can still occur after a successful
check and must leave the session unusable, never trigger cleanup.

## Runtime and secret sources

The original D live policy pinned **host CPython 3.12.14**. R2.4-A1 additionally
accepts exactly **CPython 3.12.10 on Windows x64**, after compatibility checks on
the signed official Windows runtime; 3.12.14 remains accepted. Non-Windows hosts
still require 3.12.14. This is not an arbitrary 3.12.x range, a production-image
change or a claim that 3.12.10 contains later source-only security fixes. See the
[A1 rationale, limitations and checks](stage8c-r2-4a1.md). CI Python 3.10.12 proves
only offline/synthetic compatibility; Python 3.13/3.14 remain unsupported for live
collection. Unsupported runtimes report `S3_LIVE_PYTHON_UNSUPPORTED`, with the exact
host-specific requirement in `runtime.required_live_python`.

S3 archive operations do **not** need SQLite. The existing database/Grafana backup
still separately requires `serialize`/`deserialize` support; this implementation does
not weaken or bypass that guard and imports no database recovery operations.

Host optional requirements: `requirements/recovery-s3.txt` includes existing
`cryptography==50.0.2` and `boto3==1.40.21` pins. No application/runtime images change.
The host needs Docker CLI/Desktop access to existing PostgreSQL/ClickHouse metadata
and read-only volume mountpoint discovery. No service recreation is necessary.

For this future CLI, the S3 SDK runs in the **operator host process**. The operator
must provision `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
and `AWS_CA_BUNDLE` into that process using an approved private secret mechanism.
These must target the existing source context. The CA bundle must be an existing
host PEM trust bundle, including the required GlobalSign trust; a container-only
`/etc/ssl/...` path is not a Windows host path. Existing shared SDK SigV4/virtual
addressing/standard retries/timeouts/TLS verification remain unchanged.

The CLI never reads `.env`, `.passes`, `keys.txt`, prints credential values or exports
them from a container. Unlike the C-only launcher, D does not copy a key/destination
into the scheduler or transport bulk object bytes via console/Docker stdout. PostgreSQL
and ClickHouse continue using their existing container-owned credentials through
read-only runtime helpers. Source credentials never reach a cloud destination adapter.
Adapter restrictions do not establish the IAM policy's actual privilege scope.

Actual no-network host preflight here reported **Python 3.14.3**, crypto available,
boto3 absent, source SDK environment absent, and no destination/key selected. These
are explicit BLOCKED results, not a reason to install/change credentials automatically.

## Operator-controlled key recovery

`keygen` alone generates `os.urandom(32)`, writes a new exclusive key file in a previously
private external key directory, audits permissions, fsyncs and checks its length.
It never sends key bytes/fingerprints to stdout, Git, images, CI artifacts or archives.
`create` never generates/replaces a missing key: it requires an existing 32-byte
private file, checks access before source IO and compares it again before sealing.
Tests generate only ephemeral synthetic keys in their own temporary directories.

Before a real collection:

1. Assign an operator-controlled key reference and backup-session mapping in a private
   recovery register. Paths themselves are not secret material, but keep the register private.
2. Make a separately controlled recoverable copy through an approved password manager,
   offline vault or second protected medium, not the backup disk/workstation alone.
3. Prove access from the intended recovery identity/device and record that check without
   recording key bytes. Keep any BitLocker/vault-unlock recovery independent too.
4. After future backup, detach/reattach or independently copy the encrypted session,
   retrieve the key through the recovery route and run offline `verify`/`inspect`.
5. For machine loss, first recover matching source code/runtime, independent archive
   and key/vault unlock; authenticate all chunks/evidence before designing an isolated
   restore. A missing key cannot be reset or derived from runtime S3/DB credentials.

A new random HKDF salt/UUID separates sessions even if an operator reuses a recovery
key for a retry. Prefer an explicit session-specific key lifecycle. No real key
generation, escrow copy or recovery proof was performed here.

## Future PowerShell procedure — NOT executed by this task

Locate a verified, explicitly supported host CPython first: 3.12.14, or 3.12.10 on
Windows x64 only. Do not assume `py -3.12` selects an approved patch release.
These are operator instructions, not authorization to execute the real collection now.
Choose actual independent drives/paths; examples below intentionally use placeholders.

```powershell
Set-Location F:\Learning_projects\football-data-platform
$runtime = '<absolute path to verified supported python.exe>'
& $runtime -m venv .venv\s3-recovery
$python = '.\.venv\s3-recovery\Scripts\python.exe'
& $python -m pip install -r requirements/recovery-s3.txt
& $python scripts/s3_backup.py preflight

# Future explicit local setup, after selecting media and checking parent paths.
& $python scripts/s3_backup.py init-directory --destination 'E:\FootballS3Archives' --confirm-new-private-directory
& $python scripts/s3_backup.py init-directory --destination 'G:\FootballKeyVault' --confirm-new-private-directory
& $python scripts/s3_backup.py keygen --key-file 'G:\FootballKeyVault\s3-session.key' --confirm-key-generation

# Provision host SDK variables securely; no literal credentials in this document/history.
# After key escrow/access proof, get a fresh bounded source preflight.
& $python scripts/s3_backup.py preflight --check-source --destination 'E:\FootballS3Archives' --key-file 'G:\FootballKeyVault\s3-session.key'

# ONLY AFTER a separate live-run approval; use identity/digest from that preflight.
& $python scripts/s3_backup.py create `
  --destination 'E:\FootballS3Archives' `
  --key-file 'G:\FootballKeyVault\s3-session.key' `
  --expect-source-id '<fresh-source-resource-id>' `
  --expect-inventory-sha256 '<fresh-inventory-sha256>' `
  --confirm-live-backup --confirm-key-recoverable --confirm-independent-media --confirm-quiet-window

# <session-id> is returned by the future successful create. No source access for these.
& $python scripts/s3_backup.py verify --archive 'E:\FootballS3Archives\<session-id>' --key-file 'G:\FootballKeyVault\s3-session.key'
& $python scripts/s3_backup.py inspect --archive 'E:\FootballS3Archives\<session-id>' --key-file 'G:\FootballKeyVault\s3-session.key'
```

Do not invent a fresh digest, use an estimated digest, rerun an aborted session in
place, overwrite an old key or remove partial evidence. Correct the specific cause,
retain the failed session and start a new one. There is no cleanup/resume subcommand.

## Consistency, stop conditions and acceptance

This is a non-atomic collection bounded by observations. PostgreSQL repeatable-read
does not atomically snapshot ClickHouse or S3. HEAD ETag + GET conditions + final
metadata/inventory fences detect observed changes but cannot prove no ABA/transient
replacement or defeat a malicious provider reusing validators. Immutable pipelines
and a quiet operator window remain prerequisites. Historical version/lock/versions
access was HTTP 403 in C: **UNKNOWN**, not disabled and not backed up.

Stop without a valid SEALED manifest on any wrong source/digest, missing known key,
conditional failure/ignored condition, unavailable provider, short/changed stream,
Bronze SHA mismatch, source/catalog/receipt drift, lineage/file-set mismatch,
ciphertext/plaintext/index/authentication failure, ACL/key change, capacity problem,
unsupported runtime or interrupted/seal failure. Keep partial state; never delete
source objects or other archives as recovery from a failed attempt.

To authorize the first live collection, all are still required: supported host
environment/CA/source process credentials; selected private independent storage;
separately recoverable key; sufficient fresh free space; fresh bounded preflight
with exact source ID/digest; quiet window; operator checklist and separate user
approval. No real full-backup acceptance, independent S3 copy, secret escrow/restore,
remote restore or complete machine-loss recovery is claimed by these tests.

## Changed files and checks

New:

- `src/recovery/s3_safety.py`
- `src/recovery/s3_operator.py`
- `scripts/s3_backup.py`
- `requirements/recovery-s3.txt`
- `tests/test_s3_operator.py`
- `docs/stage8c-r2-3d.md`

Updated:

- `src/recovery/s3_archive.py`: authenticated live scope and mandatory permission checks.
- `src/recovery/s3_workflow.py`: shared full workflow, strict live guards and safe evidence verification.
- `src/recovery/s3_readonly.py`: explicit inventory-bounded full-read quota; dry-run defaults unchanged.
- `docs/stage8c.md`: D link/status.

Earlier A/B/C working-tree changes remain uncommitted. No source was staged/published.

Final local verification:

| Check | Result |
| --- | --- |
| Python 3.10.12, network-disabled CI image | 679 root + 30 application + 16 CI tests PASS |
| Python 3.12.14, network-disabled CI image | 679 root + 30 application + 16 CI tests PASS |
| New D fake-transport/safety suite | 30 tests PASS in both matrix environments |
| Windows synthetic operator suite | 29-test run PASS, followed by 4 targeted latest-code regression tests PASS |
| Existing A/B/C + database recovery v1 | Suites remain green in both root runs |
| Ruff / compileall, both versions | PASS |
| Repository/publication/CI contracts | PASS |
| Git + explicit public-source whitespace and high-confidence secret-signature audit | PASS |
| `.env`, `.passes`, `keys.txt` | Git-ignored; existing Docker ignore rules preserved |
| Real default/estimate-only host CLI invocation | Safely BLOCKED, no network or data/key/directory writes |
| Full real S3 backup / real key generation / database restore | NOT RUN |

Windows uses the current 3.14.3 host for synthetic tests with an explicitly mocked
live-runtime acceptance policy, not a claim that the live 3.12.14 host preflight passed.
Linux CI containers also mock only the operator host/runtime/factory boundary and use
the real archive, encryption, permissions, streaming, lineage and failure code over
fake data. Their Docker/SDK production transports are not invoked. Tested failures
include unsupported runtime, no confirmation/destination, low space, workspace/volume/
secret paths, bad ACLs including a late pre-seal ACL rejection, wrong/changed key,
interruption and fresh-session restart, repeated session IDs/overwrite protection,
bad Bronze SHA, truncated streams, missing/unavailable/changed sources, ignored
conditions, final-inventory/receipt drift, ciphertext readback and seal failure.

Reproduce offline checks using existing dependencies/images (repeat with `py310`):

```powershell
docker run --rm --network none -e PYTHONPYCACHEPREFIX=/tmp/pycache --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python ci/run_unittest.py discover -s tests -p 'test_*.py'
docker run --rm --network none -e PYTHONPYCACHEPREFIX=/tmp/pycache --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python ci/run_unittest.py discover -s tests/application -p 'test_*.py'
docker run --rm --network none -e PYTHONPYCACHEPREFIX=/tmp/pycache --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 ruff check --no-cache .
docker run --rm --network none -e PYTHONPYCACHEPREFIX=/tmp/pycache --mount "type=bind,source=$PWD,target=/workspace,readonly" -w /workspace football-publication-checks:9cda694200-py312 python -m compileall -q src application scripts infrastructure dags tests ci
python ci/check_repository.py
git diff --check
git check-ignore .env .passes keys.txt
```

These are local results over the pending working tree, not a clean published checkout
or a new GitHub Actions run. Commit/push and any first full live-run approval remain
separate user decisions. Stop after D; do not execute the future procedure automatically.
