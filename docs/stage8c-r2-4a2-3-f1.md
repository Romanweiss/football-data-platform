# Stage 8C-R2.4-A2.3-F1 — safe production create handoff

Implementation/synthetic acceptance only. No live create, Selectel reads/writes,
service startup, production-key access, database recovery or commit/push here.
Stage 8C remains **PARTIAL**. This is not backup authorization.

## Cause and opt-in route

The bounded host launcher acquired scheduler parameters through a captured pipe,
created a client, then removed its temporary environment. A later standalone
`s3_backup.py create` expected an already populated shell environment instead.
Wrapping the whole create command in that environment would expose source secrets
to metadata/Docker subprocesses unnecessarily.

`create --host-ca-bundle <existing-public-PEM>` now opts into the existing handoff.
No secret-bearing CLI argument or plaintext credential file is introduced.
The legacy environment-based API remains compatible; it is NOT the recommended
Windows route. Existing read-only scripts keep their CLI/return schema.

1. Existing create confirmations and expected identity/inventory arguments remain
   mandatory before key reads, Docker discovery or SDK construction.
2. The host route requires all six S3/CA environment variables absent, plus
   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN and AWS_SECURITY_TOKEN.
   Conflicts fail before mount discovery, without silent removal or fallback.
3. Select exactly the running project scheduler through the existing Compose-label
   selector. Capture the original five parameters over the existing pipe. No dotenv,
   Config.Env inspection, vault access or new secret transport.
4. Validate the existing public CA/R6 pin; inside the short-lived environment,
   create the shared SigV4/virtual client and require its exact verified CA path.
5. Require the signer's exact botocore Credentials class, method=explicit, no token,
   and frozen access/secret values equal to the handoff. Refreshable/deferred and
   default-chain credentials fail closed without refresh. No values/fingerprints
   are returned in reports.
6. Clear temporary environment BEFORE metadata selection, subprocesses and workflow
   IO. The clean-start requirement ensures no restored source secrets remain for
   child processes to inherit. SDK objects retain the explicit resolved credentials.
7. Keep logging disabled until client closure. Finally closes the client, restores
   logging/environment and suppresses raw exceptions, including close failures.

This is a single-threaded trusted-host operator entry point. Python strings/SDK
objects may retain credentials in memory: no secure-erasure claim or protection
against administrators, debugger/crash dumps, compromised Docker or concurrent
threads spawning processes inside the short environment scope. Original source
credentials remain owned by the scheduler, not a new persistent credential store.

## Unchanged safety and consistency

Runtime allowlist, private destination/key ACLs, independent-media/escrow/quiet-window
attestations, source identity, expected inventory, lineage, space checks, exclusive
session creation and final fences remain in the original operator/workflow. No
AES-256-GCM/HKDF/SHA-256 or archive-schema change; no cloud write adapter.

Conditional GET plus final inventory/metadata equality is NOT an atomic global
snapshot. Changes/read failures prevent successful sealing; incomplete artifacts
remain for investigation, not automatic overwrite/resume/deletion. The original
key is retained. Retry requires fresh gates and a new exclusive session.

## Future commands — NOT executed here

First arrange a separately approved running source runtime without starting ETL,
then run the bounded read-only audit:

```powershell
& .\.venv\s3-recovery\Scripts\python.exe -B scripts/check_s3_host_readiness.py `
  --check-source --ca-bundle .venv/s3-recovery/certs/selectel-system-ca.pem
```

Review fresh identity/inventory, key/PHONE receipt, K: physical identity, ACLs and
space. Previous successful digests are not fresh evidence. Only after separate
explicit create authorization and an actual quiet collection window:

```powershell
$backupSourceId = '<fresh source_check.source.resource_id>'
$backupInventorySha = '<fresh source_check.inventory_sha256>'
$backupKeyPath = Join-Path $env:USERPROFILE 'FootballRecoveryVault\s3\s3-recovery-20261022T204016Z-3e0f028ad7184961bb3b6b4377beeae9.key'

& .\.venv\s3-recovery\Scripts\python.exe -B scripts/s3_backup.py create `
  --host-ca-bundle .venv/s3-recovery/certs/selectel-system-ca.pem `
  --destination 'K:\FootballPlatformBackups\s3' `
  --key-file $backupKeyPath `
  --expect-source-id $backupSourceId `
  --expect-inventory-sha256 $backupInventorySha `
  --confirm-live-backup --confirm-key-recoverable `
  --confirm-independent-media --confirm-quiet-window
```

No access/secret key is typed into the shell. Do not manually export credentials.
If the clean-environment gate fails, stop without printing conflicting values.
Placeholders intentionally fail validation; this document reserves no session ID.
After successful collection, offline `verify` must use the returned archive and
original key path. Retain non-secret session references separately; manually add
the session ID to the production Bitwarden note. SEALED/VERIFIED does not prove
remote restore or complete machine-loss recovery.

## Synthetic acceptance

Tests use fake scheduler/HTTP transports, temporary artificial bytes/keys and
blocked sockets. Actual botocore signing runs after cleanup with provider reload
forbidden. A real child process checks absence of credential variables only.
Refreshable/deferred providers, bad binding/CA, failures before/after client,
credential/TLS/timeout errors, stale inventory/identity, final metadata mutation,
logging restoration, no automatic create and confirmation gates are exercised.

Acceptance on 2026-10-24 (Europe/Moscow):

| Check | Result |
| --- | --- |
| Native Windows CPython 3.12.10 full recovery/profile-v1 compatibility | 240 PASS, no skips (1132.151s), including all 7 real ACL/junction tests |
| Final strengthened host-create suite on Windows | 22 PASS; provider resolution forbidden during construction and subsequent signing |
| Linux 3.10.12 / 3.12.14, isolated source snapshot, network disabled | 240 recovery + 765 root regressions each; 7 Windows-only skips each |
| Application / CI contracts, both Linux versions | 30 / 21 each, PASS |
| Repository/security main, host and isolated Git snapshot | PASS; new sources/docs included in snapshot scan |
| Ruff, compileall and Git diff checks | PASS |

Linux regression exposed an existing test's dependence on glob enumeration order:
it corrupted an arbitrary chunk but updated the first index entry's checksum. The
test now selects the exact first authenticated index descriptor. GCM assertions
are unchanged; the corrected case also passed separately on Windows. No crypto,
archive format, shared client, read-only adapter or workflow source was changed.

Read-only Docker status showed the scheduler, PostgreSQL and ClickHouse healthy;
this task did not start/restart them. No live source audit or production-key access
occurred. Fresh source/lineage/TLS/media/key readiness must be assessed next; prior
inventory/PHONE evidence is not silently substituted for that fresh preflight.

**READY for a subsequent infrastructure preflight. Live backup remains BLOCKED
pending fresh source/media/key checks, confirmed runtime availability at execution,
quiet window and separate create authorization.**
