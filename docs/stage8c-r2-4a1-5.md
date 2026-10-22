# Stage 8C-R2.4-A1.5: Windows host S3 credentials and TLS readiness

Date: 2026-10-22 (Europe/Moscow). Baseline:
`bea3d8dd94f87f1e3f683c13541d77db361fc423` plus local, uncommitted A1 changes.
Host interpreter: `.venv/s3-recovery/Scripts/python.exe`, CPython 3.12.10 x64.
This is bounded read-only acceptance, **not** authorization for backup or keygen.
Overall Stage 8C remains **PARTIAL**.

## Existing configuration and explicit process-only handoff

`compose.yaml` supplies `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY`
and `S3_SECRET_KEY` by Compose interpolation to the existing scheduler, Python tools
and Spark services. Compose normally interpolates from its caller environment / `.env`;
the YAML alone cannot prove the private file used to start an existing container.
There is no `.passes` / `env_file` credential loader for these services in the YAML.
`src/common/s3.py` and `s3_operator.build_sources()` read process variables only;
they do not auto-load private files. No private file contents were inspected here.

All five parameters were present in the running project scheduler; all six host
variables (including `AWS_CA_BUNDLE`) were absent. The new **explicit read-only**
launcher retrieves only those five named parameters from that existing runtime:

1. Resolve one running scheduler by project/service labels, never expanded Compose
   config or container-environment inspection.
2. Fixed `docker exec` Python snippet emits only the allowlist to a captured PIPE.
   Values are never command arguments, PowerShell variables, console output, new
   plaintext files or reports. No credential is created/changed.
3. Validate the host public CA before the handoff. Temporarily set the six variables
   only inside the dedicated host Python process to construct the existing SDK client.
4. Restore previous variables (remove newly introduced variables) in `finally`, **before**
   metadata Docker subprocesses. The resolved SDK session retains credentials in memory.
5. Suppress all Python logging during the handoff and audit; restore prior logging
   afterwards. CLI failures contain a fixed code/stage, never raw exceptions/output.

The original backup CLI does not acquire a credential-export behavior. The separate
launcher has no create/keygen/write-source operation. This is a single-threaded
operator-process mechanism, not a general-purpose secret manager. It does not prove
least-privilege IAM: the adapter's operations are read-only, but reused credentials
may have broader rights. Docker administrators, host compromise, process dumps,
swap/pagefile and secure erasure of immutable Python strings are outside its guarantee.
No runtime credential is an encryption/recovery key.

## Public Windows CA bundle

Public certificates only were copied from the working scheduler's existing
`/etc/ssl/certs/ca-certificates.crt` to:

```text
F:\Learning_projects\football-data-platform\.venv\s3-recovery\certs\selectel-system-ca.pem
```

No root-store change, certificate download, private key or SSL bypass was needed.
The bundle contains 122 PEM certificates, has no non-certificate content and contains
GlobalSign Root CA - R6 with SHA-256:
`2cabeafe37d06ca22aba7391c0033d25982952c453647349763a3ab5ad6ccf69`.
The pin is cross-checked against the [Mozilla inclusion record](https://bugzilla.mozilla.org/show_bug.cgi?id=1478476)
and [GlobalSign root information](https://support.globalsign.com/ca-certificates/root-certificates/globalsign-root-certificates).
Bundle SHA-256: `0f7b5a92320179a052dfa4e535f970fd2810dda317e75d7e0080e1751aa6d6cd`.

The helper parses the PEM trust store, checks the R6 pin, `CERT_REQUIRED` and hostname
verification, and verifies the actual botocore HTTP session uses this host path.
It refuses symlink/reparse/hardlinked CA files and different existing bundle contents;
public bundle creation is exclusive and read back. This does not independently attest
every other trust anchor or protect against a compromised Docker daemon/host.
Shared SigV4, virtual addressing, standard SDK retries and 10s/60s timeouts are unchanged.

## Safe repeat commands

From the project directory, no literal secret in the command/history:

```powershell
$python = '.\.venv\s3-recovery\Scripts\python.exe'
$ca = Join-Path $PWD '.venv\s3-recovery\certs\selectel-system-ca.pem'
# Existing parent certs directory required; public certificates only, never overwrite.
& $python -B scripts/check_s3_host_readiness.py --prepare-ca --ca-bundle $ca
# Explicit bounded source audit; no destination/key and no full-read authorization.
& $python -B scripts/check_s3_host_readiness.py --check-source --ca-bundle $ca
```

Repeat only when a fresh audit is needed. No background schedule or environment
persistence was installed. Do not use this launcher to authorize future collection.

## Collection and safety boundaries

The launcher reuses `S3ReadOnly`, `audit_source`, `DockerMetadataSource` and existing
before/after metadata/inventory fences. GET is limited to small lineage JSON and
three one-byte payload probes, 256 KiB per object / 2 MiB total by default. Correct
and deliberately incorrect native HEAD `IfMatch` are tested; ETags are not hashes.
There is no call to full-read authorization, archive/key creation, ETL or restore.
Versioning/Object Lock/ListObjectVersions 403 must remain **UNKNOWN / ACCESS DENIED**.
No global S3/PostgreSQL/ClickHouse atomic snapshot is promised.

Existing archive/key parents were read-only audited again with `s3_safety`:
`K:\FootballPlatformBackups\s3` and the current Windows profile's
`FootballRecoveryVault\s3`. Both are private, correctly owned, protected-DACL,
non-overlapping, non-reparse directories; both remain empty. No key file was read.
Free K space: 131,061,084,160 bytes. For the prior 315-object/356,383,409-byte baseline,
the existing conservative plan requires 466,629,112 free bytes. No K write/ACL change.

## Acceptance results

Fresh host audit: **PASS_HOST_READ_ONLY_AUDIT** / **PASS_READ_ONLY_DRY_RUN**.
Bucket `football-data-platform-dev-v1`, endpoint `https://s3.ru-3.storage.selcloud.ru`,
virtual addressing. Identity is endpoint/bucket-bound, not independently verified
account ownership; provider LIST did not expose a canonical owner.

| Layer | Objects | Bytes |
| --- | ---: | ---: |
| Bronze | 202 | 321,473,523 |
| Silver | 78 | 34,559,914 |
| Gold | 35 | 349,972 |
| Total | **315** | **356,383,409** |

- Formats: 224 JSON, 47 Parquet, 22 directory markers, 22 extensionless markers.
- 312 registered objects; 2 legacy and 1 test object remain included in the inventory.
- 22 manifests / 22 published build identities / 22 loaded receipts reconcile.
  Metadata catalog has 199 ingestion rows, 14 Silver builds, 8 Gold builds,
  14 Silver and 8 Gold load receipts; ClickHouse serving comprises 12 tables.
- World Cup 43/106: 64 matches; Bundesliga 9/281: 34 matches.
- Successful audit: 630 HEAD, 3 LIST (initial/final plus owner probe), 30 GET attempts
  (24 small JSON documents + 3 correct one-byte ranges + 3 expected HTTP 412 probes).
  Optional capability requests are additional to those adapter counters.
- **455,754 bytes** read by that successful audit, not a full object payload collection.
  Byte SHA-256 verified for 24 small documents; 291 objects' full-byte hashes remain
  unverified. No Parquet file was fully downloaded.
- Correct native HEAD conditions pass; incorrect conditions return 412 in all layers.
  47 LIST vs HEAD ETags differ, retained distinctly, not mistaken for SHA-256.
- Versioning, Object Lock and ListObjectVersions each return HTTP 403: state UNKNOWN.
- Initial/final full inventory and before/after metadata digest fences pass.
  Inventory SHA-256: `1507a7676eed78b676ac8d82177fc451a4ca9a081f2aab5e5c6888abb2d931b6`.
- TLS verification and hostname verification remain enabled. Temporary host S3
  variables were restored/removed, SDK session closed, no persistent environment set.

The first full host audit returned the launcher's fixed, anonymized failure with no
complete report. Its exact cause is **not established**; do not label it a timeout
or TLS failure from speculation. A separate minimal host LIST returned HTTP 200,
metadata snapshot passed, and the repeated full bounded audit above passed with
operation-only counters. The byte/call totals above describe the successful audit,
not total network traffic including the incomplete first attempt and diagnostics.

## Checks and remaining gates

Checks use synthetic credentials/public CA fixtures and disabled network; no real
key/archive is used by tests. New tests cover allowlisted pipe handoff, absence from
command arguments/files/output, environment/logging restoration on success/failure,
invalid/extra fields, raw transport/CLI exception suppression, public-only pinned CA,
exclusive bundle writes, actual SDK CA/config resolution, environment removal before
metadata subprocesses, metadata drift rejection and SDK cleanup.

| Check | Result |
| --- | --- |
| Native Windows CPython 3.12.10 full recovery suites | **174 PASS**, no skips, 513.165s |
| Real Windows owner / ACL / junction checks | **5 PASS**, included above |
| New host handoff / CA / security tests | **11 PASS**, included above and rerun separately |
| Linux CPython 3.10.12 and 3.12.14 recovery suites | 174 each, PASS, 5 Windows-only skips each |
| Linux 3.12.14 root unit regression | 699, PASS, same 5 Windows-only skips |
| Repository / CI contracts | 19 PASS |
| Repository security checks, Ruff, compileall, pip check | PASS |
| Changed-file signature/whitespace checks, including new untracked sources/docs | PASS |
| Git diff check; staged diff | PASS; staging remains empty |

Native suites include database-profile compatibility only, not a real database restore.
No remote CI/commit/push was performed. Existing A1 runtime-policy WIP is preserved.
The ordinary backup CLI's no-source offline preflight correctly remains BLOCKED:
host variables are absent again, no key was created and no fresh audit is implicit.
Use the explicit read-only launcher above, not persistent credentials or relaxed gates.

**Host read-only credentials/TLS readiness: PASS. First real backup: BLOCKED.**
Still required: an actual separately recoverable key and proven off-machine escrow
chosen by the operator, fresh preflight/quiet window, explicit independent-media and
key-recoverability confirmations, and separate live-backup approval. K media durability,
BitLocker/unlock recovery and protection against workstation/admin compromise are
not established by ACL/free-space checks. No independent S3 byte copy, remote S3
restore, secret restore or complete machine-loss recovery has been verified.
The public CA is ignored with `.venv` by Git and Docker; private files remain excluded.
