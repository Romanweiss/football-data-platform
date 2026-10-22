# Stage 8C-R2.4-A1: Windows backup environment preparation

Date: 2026-10-22 (Europe/Moscow). Baseline:
`bea3d8dd94f87f1e3f683c13541d77db361fc423`.

Scope: local runtime/dependencies, private empty directories and offline tests only.
No Selectel request, real object download, real key/archive generation, real database
backup/restore, credential/IAM change, ETL, commit or push is authorized here.
**First live S3 backup remains BLOCKED; overall Stage 8C remains PARTIAL.**

## Runtime choice and bounded compatibility policy

[CPython 3.12.14](https://www.python.org/downloads/release/python-31214/) is a
source-only security release: no official Windows installer is published.
[CPython 3.12.10](https://www.python.org/downloads/release/python-31210/) was the
last 3.12 release with an official Windows installer and is available in the
[actions/python-versions manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json).

The operator installed the official Windows x64 runtime at
`F:\Soft\Python3.12\python.exe`; preparation verified its exact version 3.12.10,
64-bit CPython implementation and valid Python Software Foundation Authenticode
signature. Preparation uses that supplied executable without modifying other
Python/PATH settings or the existing database venv.

Before changing the gate, 99 archive/workflow/fake-adapter/real-Windows-ACL tests
passed on that runtime. The S3 operator now allows only:

- CPython 3.12.14, preserving the existing policy;
- additionally CPython 3.12.10 on Windows x64 (64-bit process and AMD64/x86_64 host).

It does not allow all 3.12 patches, Windows ARM64/x86 for the new exception,
non-CPython interpreters, Linux 3.12.10 or Python 3.13/3.14. Linux/CI/production
image pins are unchanged. Runtime failures use `S3_LIVE_PYTHON_UNSUPPORTED`;
`required_live_python` describes the actual host-specific supported versions.
Host-only, dependency/Docker, path/ACL, key, inventory, quiet-window and explicit
operator-confirmation gates remain mandatory. Database profile-v1 guards are untouched.

Compatibility tests do **not** backport subsequent security fixes to 3.12.10 or
prove live S3 recovery. This deliberately narrow availability choice retains that
known limitation; a patched trusted Windows build or future supported runtime
requires its own review, not silently broadening the allowlist.

## Dedicated virtual environment

Venv: `F:\Learning_projects\football-data-platform\.venv\s3-recovery`.
Dependencies were installed strictly via `requirements/recovery-s3.txt`, using pip
isolated mode and the public PyPI index. No extra CI/lint packages were installed
into this venv. Direct pins: boto3 1.40.21, cryptography 50.0.2; resolved botocore
1.40.76. Imports, CLI help and `pip check` pass. Existing `.venv\recovery` remains
unchanged. Both Git and Docker ignore the S3 venv; this is not a portable runtime
backup or a newly locked transitive-dependency set.

```powershell
$python = '.\.venv\s3-recovery\Scripts\python.exe'
& $python -I -B -c "import sys,boto3,cryptography; print(sys.version.split()[0],boto3.__version__,cryptography.__version__)"
& $python -m pip --isolated check
& $python -B scripts/s3_backup.py --help
```

## Destination and separate key directory

A0 identified K: as separate physical USB Disk 4, StoreJet Transcend, NTFS/Healthy,
not the physical disks holding C: or F:. Only these four new directories were
created during local preparation; the continuation audits/reuses them without
resetting existing ACLs:

```text
K:\FootballPlatformBackups
K:\FootballPlatformBackups\s3
<Windows user profile>\FootballRecoveryVault
<Windows user profile>\FootballRecoveryVault\s3
```

The profile comes from `[Environment]::GetFolderPath('UserProfile')`, not a hardcoded
username. Each directory has the current user's owner SID, a protected DACL and no
Allow rule for another principal. Existing ancestors have no reparse routing; the
four directories have no symlinks/junctions/reparse points and pass `s3_safety.py`.
K: root and Windows profile root ACLs were compared before/after setup and unchanged.
Both `s3` leaf directories remain empty. No actual key file has been generated.

The proposed future key filename is `s3-first-session.key` inside the private
profile vault. Path/non-overlap checks are not proof of independent escrow.
Existing project `.recovery-keys` files are not opened, moved or reused.

Estimate only, not fresh S3 inventory: 315 objects / 356,383,409 bytes. Existing
`space_plan()` computes 373,303,289 bytes archive upper bound + 93,325,823 bytes
reserve = **466,629,112 bytes (445.01 MiB)** required free. About 122.06 GiB is
available on K:. Recompute after fresh source preflight. No benchmark, power-loss
test, BitLocker configuration or existing-data cleanup was performed. An attached
USB disk is not immunity against ransomware, theft or workstation compromise.

## Host credentials and CA: operator action still required

The CLI uses only process environment: `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY`, `AWS_CA_BUNDLE`. It does not load `.env`, `.passes`
or `keys.txt`, or copy source credentials from Docker. No values are recorded here.
If any required variable is unavailable, do not run source preflight.

The operator must select an approved secret mechanism to inject the existing
source credentials into this host process, without literal secrets in command
history, `setx`, Git, CI, reports or unapproved files. Do not rotate credentials or
change IAM to make preparation pass. Do not infer a read-only IAM scope merely
from using the restricted adapter.

`AWS_CA_BUNDLE` must name an existing **Windows host** PEM trust bundle, not a
container `/etc/ssl/...` path. The tested botocore public bundle lacks GlobalSign
Root R6. A future host bundle should preserve the approved CA set and add the
verified public [GlobalSign Root R6](https://support.globalsign.com/ca-certificates/root-certificates/globalsign-root-certificates)
(CN GlobalSign, OU GlobalSign Root CA - R6), checking its identity against the
official certificate. Keep it outside Git, for example under the ignored venv's
`certs` directory, and recheck it when rebuilding the venv. No trust-store change,
CA-bundle file creation or TLS-handshake acceptance is claimed by this preparation.
Never use `verify=False` or disable hostname/certificate validation.

## Practical escrow procedure: not executed

1. The operator selects a separately protected vault or separate offline medium,
   not K: and not a copy available only on this workstation. Do not choose a vendor
   or upload/copy secret material automatically.
2. After separate approval for key generation, store a protected recovery copy and
   a private key reference. After collection, map the returned session ID to that
   key reference in the private recovery register. Keep vault unlock/2FA recovery
   available independently of the lost workstation too.
3. From the intended second device/recovery identity, retrieve the key to a new
   private directory outside Git/K:. Never print it, use a literal in a command,
   place it in CI, or attach it to the encrypted archive.
4. Check the recovery file's permissions and 32-byte size, then use offline archive
   `verify` with the recovered key; record only session/reference and PASS/FAIL.
   No current key/archive exists to demonstrate this yet. Do not assert
   `--confirm-key-recoverable` merely to bypass a blocker.

## Local preflight and remaining boundary

```powershell
$python = '.\.venv\s3-recovery\Scripts\python.exe'
$keyDir = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'FootballRecoveryVault\s3'
$keyFile = Join-Path $keyDir 's3-first-session.key'
& $python -B scripts/s3_backup.py preflight `
  --destination 'K:\FootballPlatformBackups\s3' --key-file $keyFile `
  --source-bytes 356383409 --source-objects 315
```

This estimate-only command performs no source requests or writes. A missing real
key is intentional. Runtime/dependencies/path/ACL/space readiness does not authorize
key generation or `create`. Credentials/host CA, actual key/independent escrow,
fresh bounded source identity/inventory/lineage preflight and a quiet collection
window still require operator preparation and separate live-run approval.

Historical versioning/Object Lock visibility remains UNKNOWN where prior audit
received HTTP 403. Live encrypted backup: NOT EXECUTED. Independent/remote restore,
secret escrow and complete machine-loss recovery: NOT VERIFIED.

## Verification

| Local check | Result |
| --- | --- |
| Signed official CPython 3.12.10 x64, dependency imports, CLI startup, pip check | PASS |
| Pre-change Windows archive/workflow/fake-adapter/real-ACL compatibility | 99 tests PASS |
| Windows 3.12.10 full S3 + database-v1 compatibility gate | 163 tests PASS, no skips; includes all 5 real Windows ACL/junction tests |
| Final exact-runtime policy tests on Windows | 4 tests PASS, including 135 platform/architecture/patch combinations |
| Linux CPython 3.10.12 and 3.12.14, network disabled | Each: 163 recovery + 688 root tests PASS; 5 real-Windows-only skips in each suite |
| CI contracts / repository security contracts | 19 tests PASS / PASS |
| Ruff / compileall on Windows 3.12.10 / Git diff checks | PASS |
| Four existing private directories, key path/non-overlap and free space | PASS; both S3 leaf directories still empty |
| Local estimate-only CLI preflight | BLOCKED as intended, writes_performed=false, live_backup_executed=false |

The full Windows gate and a separate final runtime-policy run cover the resulting
implementation; Linux runs include the cross-platform test-fixture isolation fix
and final matrix cases. No real database restore or cloud IO was run. These are
working-tree tests, not clean-checkout or newly published remote CI acceptance.

Actual local preflight reports supported Python 3.12.10, both dependencies present,
Docker CLI/host runtime available and no SQLite requirement. Remaining CLI blockers:
`S3_OPERATOR_ENVIRONMENT_INCOMPLETE`, `S3_FRESH_SOURCE_PREFLIGHT_REQUIRED`,
`S3_PRIVATE_PATH_MISSING` (the deliberately absent real key). Independent key
recovery is also unverified; preflight cannot establish it through a flag or path.

Changed project files: `src/recovery/s3_operator.py`, `tests/test_s3_operator.py`,
`docs/stage8c.md`, `docs/stage8c-r2-3d.md`, and this document. No staging, commit or
push was performed. The local venv is ignored; no backup/key artifact is published.
