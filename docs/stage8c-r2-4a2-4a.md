# Stage 8C-R2.4-A2.4-A: independent offline restore readiness

Date: 2026-10-24. **Stage 8C remains PARTIAL. Real restore NOT EXECUTED.**
The operator confirmed that the successful backup session is recorded in the
production Bitwarden note. This stage does not access Bitwarden or the original
production key, create a real destination, or contact any source service.

## Archive evidence and implementation gap

Session: `20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`.
Archive: `K:\FootballPlatformBackups\s3\20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`.
Previous collection/offline verification: 315 S3 objects, 356383409 plaintext bytes,
315 object SHA-256 checks PASS. Includes one separate encrypted local evidence
record: 316 archive records, 319 files, 357278273 total on-disk bytes.

Current read-only checks: protected owner-only archive ACL; no reparse points or
hardlinked artifacts; exact file count/total size match the private non-secret
session receipt. Sealed-manifest SHA-256 equals the previous verified receipt;
encrypted-index SHA-256 equals its descriptor in that manifest. Public headers
agree on session/scope/schema/SEALED. These are **structural and prior-receipt
checks, not fresh key-based authentication of all payloads**. No original key was
read and no production payload decrypted in this stage. The independent phone
key will authenticate the archive in B, before mkdir or any plaintext writes.

Existing `s3_backup.py verify` requires a key file; existing `restore_synthetic`
and `restore_synthetic_storage` reject live archives. They remain unchanged, and
must not be used as evidence of production restore.

New `src/recovery/s3_offline_restore.py` and `scripts/restore_s3_offline.py` provide
local restore using the existing schema-2 reader/AES-GCM/HKDF and embedded lineage.
No archive/crypto format or database recovery behavior changes. No S3 write adapter.
The same offline engine is tested with synthetic workflow archives AND live-scope
archives created exclusively through fake transport/artificial data.

## Independent data flow and security boundary

```text
Bitwarden ON PHONE --manual GUI entry--> recovered key in process memory
K: archive --> authenticated manifest/index + AES-GCM/SHA-256 + embedded lineage
           --> NEW private F: destination --> payload readback SHA-256 + object map
```

Selectel, PostgreSQL, ClickHouse, scheduler, Docker daemon, host S3 environment and
the original production key file are **not used** by this route. The original key
is neither removed nor used for comparison/fallback. The expected session ID plus
successful archive authentication proves suitability of the supplied key, not
its origin: PHONE is an explicit operator attestation, not programmatic vault proof.

The GUI is opt-in only, masks input by default, has an optional show-input toggle,
and never reads/writes the clipboard or saves the recovered key. No key CLI option,
dotenv discovery, credential handoff or automatic cloud access. A correctly parsed
input is removed from the widget before verification. Window/callback errors never
print raw exceptions. Immutable Python strings/SDK-independent crypto objects may
remain in RAM, swap, crash dumps or OS caches; this is not a secure-memory enclave.

Full workflow verification includes authenticated evidence, exact source record
binding, inventory/metadata fences captured at collection, build IDs and lineage.
No request is made to check whether the live source changed AFTER backup.

Object keys are NEVER interpreted as paths, including `../`, absolute paths,
Unicode, trailing slash, Windows reserved names or ADS syntax. Output is flat:

- `object-00000001.bin`, etc.: exactly the source objects (including zero-byte
  directory markers, which remain ordinary empty opaque files).
- `object-map.json`: original keys, sizes, SHA-256 and all stored string metadata,
  mapped to unique generated filenames; excludes the archive's evidence record.
- `restore-report.json`: completion evidence written last, including counts,
  manifest/map digests, SHA results and phone attestation; no key material.
  It is valid ONLY when `restore-report.pending.json` is absent and the files have
  no extra hardlinks. Pending is a sensitive incomplete record, never success.

The map and restored payloads are **sensitive plaintext**, not publishable reports.
Stored user metadata and `s3:*` headers are preserved as data, not applied as NTFS
attributes or live HTTP configuration. The format cannot recreate original S3
version IDs, server-side encryption state, IAM/ACL, bucket policies or historical
versions. This is byte/metadata recovery to local storage, NOT remote bucket restore.

Before writing: explicit confirmation, valid expected session, private archive and
existing private parent, no links/reparse points/hardlinks, distinct physical disks,
healthy local NTFS media, full offline archive authentication and space reserve.
Only a new destination may be created; existing even-empty destinations fail.
Only that new empty directory's permissions are initialized. No existing ACL repair,
overwrite, deletion, resume, rollback or automatic retry. Failures retain partial
plaintext and do not publish a valid successful completion report. Operator must inspect
it and authorize any later cleanup/new attempt separately.

All payloads are streamed by the existing bounded chunk iterator and fsynced.
Every restored file is reopened and SHA-256 checked; exact output set and the
original-key/metadata map are checked before the completion record is written.
Completion uses exclusive pending-file write, fsync, readback and ACL checks,
then atomic no-overwrite hard-link publication and removal of only its own pending
link. If the final unlink fails, both names remain: explicitly INCOMPLETE and
rejected by the single-hardlink safety contract. No fallible work follows commit.
Manifest digest is checked again. These checks do not defend against a compromised
administrator, concurrent privileged path replacement, malicious hardware, or
later modification of the unauthenticated local completion record. Preserve the
encrypted authenticated archive as the independent verification authority.

## Destination and space: read-only findings

- K: USB StoreJet Transcend, physical Disk 4, NTFS, Healthy.
- F: NVMe `MTFDHBA256TCK-1AS1AABHA`, physical Disk 2, GPT, NTFS, Healthy.
- C: physical Disk 1. F: is physically distinct from both K: and C:.
- F: free at inspection: **55845392384 bytes**, about **52.0 GiB**.
- Candidate: `F:\FootballPlatformRestoreDrills\20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`.
- Both candidate and its parent are absent; no conflicting destination exists.
  Existing path components pass no-reparse/path checks. Neither is created in A.
- F: root is SYSTEM-owned, DACL not protected and broad standard Windows grants
  exist. It is NOT an approved private parent. Do not change root permissions.
  A separately authorized NEW owner-only/protected restore parent is required.

Minimum payload storage is **356383409 bytes** plus the sensitive object map and
report. Runtime computes the map size from the authenticated index, adds 4096
report bytes and `max(64 MiB, ceil(payload_bytes/4))` reserve. With the 8 MiB map
limit, the conservative bound is **453871966 bytes**, about **433 MiB**; allow at
least **512 MiB**. Until phone-key authentication the exact map length/required
total is deliberately not asserted. F: capacity is ample. NTFS allocation
units/caches remain overhead.
No F: destination ACL can be declared PASS while the destination does not exist.

## Future A2.4-B: commands ONLY after separate operator authorization

1. Agree on creation of the new private parent and plaintext destination. Confirm
   which users/admins may access it and whether volume-level encryption is needed.
   Do not silently repair a preexisting parent. Do not use the repository or key vault.
2. Recheck physical disks/space/reparse points. Prepare ONLY the agreed new parent:

   ```powershell
   & .\.venv\s3-recovery\Scripts\python.exe -B -c "from src.recovery.s3_safety import prepare_directory; prepare_directory('F:/FootballPlatformRestoreDrills', confirmed=True)"
   ```

   This is an offline existing safety API, not `s3_backup.py create`; it does not
   require Docker. Audit owner/protected DACL afterwards. Stop if any path exists
   unexpectedly or initialization/audit fails; no root ACL changes or blind retry.
3. Use the matching reviewed interpreter/source and initiate the explicit GUI:

   ```powershell
   & .\.venv\s3-recovery\Scripts\python.exe -B scripts/restore_s3_offline.py `
     --archive 'K:\FootballPlatformBackups\s3\20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509' `
     --destination 'F:\FootballPlatformRestoreDrills\20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509' `
     --expect-session '20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509' `
     --confirm-restore --confirm-phone-key --confirm-independent-media
   ```

4. Manually read `key_hex` (64 hex characters, NOT key ID/session ID) from
   `Football Platform | S3 Recovery | Production` ON THE PHONE. Never reopen the
   original key file/viewer, send the key to chat or enter it into the shell.
   Attest PHONE only if true. No master password, MFA/recovery code or vault API.
5. The program authenticates the entire archive before presenting a final write
   confirmation. Check the displayed source count/bytes are **315 / 356383409**.
   Cancel on any mismatch; a wrong key/session must leave the destination absent.
6. Explicitly confirm the new plaintext destination. Restore/readback verification
   should produce 315 payload files + map + completion report, exact bytes and
   metadata, no missing/extra keys, 315 SHA-256 PASS. The evidence record is not
   restored as an S3 payload. Retain evidence without exposing the map/payloads.
7. Negative tests run ONLY on synthetic fixtures, never corrupt the K: archive.
   Keep production original key and archive unchanged. Any partial destination is
   sensitive: retain it, report failure, seek separate cleanup/retry authorization.

**A2.4-B execution remains BLOCKED pending explicit real-restore authorization,
approval/creation/audit of the private F: parent, and fresh manual PHONE key input.**
Implementation/synthetic readiness is separate from production execution. Success
in B would prove offline local byte recovery with a phone-supplied key, not cold
Bitwarden account recovery, recovery after loss of all devices, remote S3 restore
or complete machine-loss recovery. Stage 8C remains PARTIAL.

## Regression commands (synthetic, no real key or source)

```powershell
.\.venv\s3-recovery\Scripts\python.exe -B -m unittest tests.test_s3_offline_restore tests.test_s3_windows_acl tests.test_s3_archive tests.test_s3_workflow tests.test_recovery
# Existing CI discovers test_s3_offline_restore.py automatically on Linux/Windows:
python ci/check_s3_recovery.py
python ci/run_unittest.py discover -s tests/ci -p 'test_*.py'
python ci/check_repository.py
ruff check .
python -m compileall -q src/recovery scripts/restore_s3_offline.py tests/test_s3_offline_restore.py
git diff --check
```

Tests cover wrong keys/session, index/ciphertext corruption/missing chunks, explicit
confirmations, no source/original-key access, colliding/path-traversal/reserved keys,
binary/empty/Unicode/multichunk payloads, metadata, counts and exact output sets,
partial failures/no overwrite, low space, real Windows ACL/junction rejection,
physical disk identity and safe CLI defaults/errors. All test payloads/keys are
disposable artificial fixtures; no production key is involved.

### Executed acceptance in A

- Windows CPython **3.12.10**: new **17** tests PASS; relevant combined archive,
  workflow, offline restore, actual Windows ACL/junction and database-profile
  compatibility suite **118 PASS, no skips**.
- Isolated Git HEAD export plus exactly the five intended public changed/new
  files (no `.env`, `.passes`, vault, venv, CA or real archive): Linux **3.10.12**
  and **3.12.14**, each **257 recovery tests PASS** and **782 root tests PASS**,
  with **9 expected Windows-only skips**. Containers use `--network none`,
  read-only source/root filesystem and disposable `/tmp`; no live services mounted.
- Linux 3.12.14 application offline regression **30 PASS**; CI/repository contracts
  **21 PASS**. Existing recovery CI discovery includes the new test automatically;
  no workflow quality gate was changed. No remote CI/commit/push in this stage.
- Repository publication/security checker, explicit scan of all five public files,
  Ruff, Windows/Linux compileall, actionlint and Git/new-file whitespace checks PASS.
  Ruff cache was explicitly redirected to disposable `/tmp` for read-only snapshots;
  actionlint received explicit workflow paths because the export has no `.git`.
- An initial synthetic-scope test fixture retained extra Windows grants created
  by the old test writer. Only that disposable fixture's initialization was fixed
  to use the existing new-empty-directory permission guard; production ACL checks
  were not relaxed. The complete targeted suites then passed.

Changed public files: this document, `docs/stage8c.md`,
`src/recovery/s3_offline_restore.py`, `scripts/restore_s3_offline.py`,
`tests/test_s3_offline_restore.py`. No real restore directory or recovered-key file
was created; existing encrypted archive and production key remain untouched.

### Publication follow-up

The follow-up audit adds five synthetic regressions (22 offline-restore tests in
total): completion readback/ACL failures, final-name collision, failed pending-link
commit and manifest mutation during authentication. Completion is now published
only through the pending/no-overwrite protocol described above. The authenticated
manifest digest is retained across restore, rather than recaptured after validation.
No archive format, source-service code or production runtime is changed.

`ci/check_repository.py` now requires the four new restore source/test/runbook paths
in the Git index. A matching CI contract proves each missing file fails publication
and that the existing synthetic-only discovery gate includes the new suite without
invoking the operator CLI. This adds two CI-contract files to the five A2.4-A files:
seven public files total. Linux/Windows recovery discovery and all existing quality
gates remain enabled; no secrets or real recovery artifacts are CI inputs.

The publication check uses a separate checkout populated exclusively from the
candidate Git tree, not a working directory overlay. Final local/remote acceptance
results are reported against the actual published commit. Publication does not
authorize creation of the private F: parent or a production restore. Those remain
separate operator checkpoints; Stage 8C remains PARTIAL.

The first publication's Linux root tests exposed a nondeterministic negative-test
fixture: an arbitrary `glob` entry could be a zero-byte directory-marker payload,
so overwriting it with zero bytes did not corrupt anything. The follow-up test
selects a nonempty object from the authenticated map, flips its first bit and
requires the exact SHA-256 mismatch code (other variants require exact map/set
error codes). This is a test-only correction, not relaxed production validation.
It is published as a normal follow-up commit without rewriting the first commit.
