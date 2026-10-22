# R2.4-A2.1: production recovery-key preparation and manual escrow

Baseline: `8ec15a2b60907b5639dabe9a1a2d4fad6ff1c273` (fast/integration CI green).
Authorization covers one actual local key, NOT S3 collection. Stage 8C is PARTIAL.
The operator subsequently confirmed saving the production note, checking all 64
characters on the phone and closing the key viewer. A2.1's manual-save checkpoint
is OPERATOR CONFIRMED. Independent retrieval is the separate
[A2.2 comparison checkpoint](stage8c-r2-4a2-2.md), subsequently completed with a
validated production PHONE MATCH receipt and fresh read-only source/media checks.
Live backup remains BLOCKED pending separate approval. No commit/push is authorized here.

## Existing contract and minimal addition

Existing `s3_safety.generate_key` already uses OS CSPRNG for exactly 32 bytes,
exclusive creation, permission audits and fsync. `s3_operator.create` separately
loads that existing key and never replaces/generates it. `S3ArchiveWriter` assigns
a fresh UTC/UUID session ID only when a backup starts; an archive is not necessary
to escrow the master key beforehand. AES-256-GCM, HKDF, schema 2 and database
profile v1 are unchanged. Synthetic viewers remain synthetic-only.

`s3_key_escrow.prepare(archive_directory=..., confirmed=True)` adds an offline
operator preparation step: exact supported Windows host, existing safe/private
profile vault, separate safe/private archive tree (audited read-only), unique
`s3-recovery-<UTC>-<UUID>` ID, key and non-secret register record. Both files are
exclusive and owner-only; Windows file DACLs are explicitly protected, not merely
inherited from the protected vault. No existing directory/file ACL is repaired.
Files created by a failed attempt are retained; stop and inspect, never blindly
rerun generation, overwrite, delete or silently replace a partially prepared key.

Paths resolve from the current profile:

```text
<Windows profile>/FootballRecoveryVault/s3/<key_id>.key
<Windows profile>/FootballRecoveryVault/s3/<key_id>.json
```

No copy is made to `K:\FootballPlatformBackups\s3`, Git, logs or CI. The public
record has schema_version=1, purpose, key_id, created_at (UTC), encoding=hex,
key_file (basename), backup_sessions=[], escrow_status=PENDING_OPERATOR_CONFIRMATION
and independent_recovery=NOT_VERIFIED. It has NO key material or key fingerprint.
Keep the record private despite its non-secret content. It is an operator register,
not an authenticated archive, escrow proof or backup-authorization mechanism.

## Session binding contract (future, NOT executed)

Until a backup starts, use `backup_session=PENDING_NOT_CREATED` in Bitwarden;
never invent a session/build ID. Once a separately approved backup actually starts,
record its returned real session ID against this key ID in the private register
and the operator's Bitwarden entry, including aborted attempts. Use a new exclusive
binding receipt, never overwrite the key or reinterpret the key ID as a session.
Before treating a completed binding as verified, authenticate the actual archive
using this key and check its real session ID. Public record editing alone cannot
establish that binding. No automatic binding/cloud/vault operation is added here.

## Operator checkpoint: save manually, then STOP

1. Stop screen recording/sharing; do not take screenshots. Open the local production
   viewer only through the provided command, supplying a non-secret key ID:

   ```powershell
   & .\.venv\s3-recovery\Scripts\python.exe -B scripts/show_s3_recovery_key.py `
     --key-id '<prepared key ID>' --confirm-local-display
   ```

   The viewer audits the record/key/owner/protected DACL and displays the hex key in
   four 16-digit lines using nonselectable labels. It does not use clipboard APIs,
   print material, create/export a key, or read/control Bitwarden. Errors are fixed
   codes, including Tk callback failures. Closing it is NOT escrow confirmation.

2. Manually create a **separate secure note** named:

   ```text
   Football Platform | S3 Recovery | Production
   ```

   Do not use/overwrite `Football Platform Recovery Test`. Manually enter:

   ```text
   purpose=production-s3-backup
   key_id=<shown non-secret identifier>
   backup_session=PENDING_NOT_CREATED
   encoding=hex
   key_hex=<type all four displayed lines as ONE 64-character value>
   created_at=<shown UTC creation date>
   usage=32-byte AES-256 recovery master key for the first independent S3 backup;
         retain original private file; bind real session IDs when created;
         never use as S3/API credentials; recovery requires matching archive/runtime.
   ```

   Hex is reversible encoding, not encryption; the vault supplies protection.
   No shell literals/history, terminal output, chat, screenshots, clipboard/history,
   plaintext exports, Git, CI or automatic upload. Never provide master password,
   MFA or account recovery codes to the agent.

3. Save. On the **phone**, manually locate this production note and exact key ID,
   then compare every digit of the 64-character key with the local display. Confirm
   UTC date and PENDING session reference. Do not confuse it with the test entry.
4. Close the local key window and desktop note view. Do NOT delete the original
   production key. Reply only that the production note was saved, the phone entry
   and digits were checked, and the local viewer is closed. Never send the material.

## A2.2 handoff and security limits

Phone visibility/digit comparison is only an operator attestation, NOT independent
retrieval verification. A2.2 requires separate operator confirmation and a masked
phone-to-private-process recovery path with no original-key fallback for input.
Compare standard SHA-256 fingerprints of the original/retrieved 32-byte values
using `hmac.compare_digest` in memory; expose only MATCH/FAIL and key ID, not either
value or digest. Check wrong input as well. Preserve the original production file;
do not repeat the synthetic drill's original-key deletion. This comparison and
receipt are NOT implemented/executed by A2.1.

The existing live create confirmations, fresh source identity/inventory, independent
media and quiet-window gates remain unchanged. Preparing/viewing/closing a key
cannot call backup code or set key-recoverable=True. A failed escrow stops at this
operator boundary. Reused runtime credentials are not recovery keys.

Host/admin compromise, GUI screen capture, process memory/pagefile/crash dumps,
malicious concurrent filesystem replacement and vault/device/account availability
remain outside these ACL/process guarantees. Windows 3.12.10 does not gain later
security patches through compatibility tests. Loss of all copies makes recovery
impossible; a key compromise also permits archive-authentication forgery.

## Tests and evidence boundary

Prepared actual key reference (NOT key material):

```text
key_id=s3-recovery-20261022T204016Z-3e0f028ad7184961bb3b6b4377beeae9
created_at=2026-10-22T20:40:16Z
status=KEY_PREPARED_ESCROW_PENDING
acl=PASS_PROTECTED_OWNER_ONLY
backup_session=PENDING_NOT_CREATED
independent_recovery=NOT_VERIFIED
```

Exactly one production `.key` plus its non-secret `.json` register were created
under the private profile vault, after all tests below. The viewer has NOT been
opened by the agent; the operator must first stop screen capture/sharing and run
the viewer command. No actual key was copied to K, supplied to tests, deleted or
used for an archive. A2.1's manual-save confirmation was received afterwards;
the immutable creation register above deliberately records the earlier pending state.

| Local verification before actual generation | Result |
| --- | --- |
| Windows CPython 3.12.10, full synthetic recovery/database compatibility | 206 PASS, no skips, 252.285s |
| Native Windows ACL/junction suite | 7 PASS, included above |
| Linux CPython 3.10.12 and 3.12.14, network disabled | 206 recovery each; 7 Windows-only skips each |
| Linux root regression, both versions | 731 each; 7 Windows-only skips each |
| CI contracts / repository-security contracts | 20 PASS / PASS |
| Explicit new/changed public-source signature scan | 5 files, zero findings |
| Ruff / compileall / Git diff checks | PASS |

These are local working-tree checks, not new remote CI or publication evidence.

`tests/test_s3_key_escrow.py` uses ONLY owned disposable system-temp fixture keys,
mocked host/profile selection and blocked sockets/Docker. Native Windows tests use
real file/parent DACL audits; Linux tests retain offline compatibility. Tests cover
32-byte format, absent secret output/repr/record, explicit confirmations, separate
locations, reference collisions/no overwrite, partial ACL failures, malformed or
misleading records, source-free operation and later synthetic archive compatibility.
The real production key is never supplied to a test or a synthetic archive.

Run existing recovery/Windows ACL suites, repository/security contracts, Ruff,
compileall and Git diff checks. Actual test results and prepared non-secret ID are
recorded in the operator handoff; no assertion of completed Bitwarden escrow or
live S3 backup follows merely from passing tests.
