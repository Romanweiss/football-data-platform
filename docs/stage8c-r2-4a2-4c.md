# Stage 8C-R2.4-A2.4-C: production restore evidence and bounded recovery closure

Evidence review: **2026-10-28, Europe/Moscow**. **S3 recovery: VERIFIED** for
the single current-object backup / isolated local restore described here.
**Overall Stage 8C: PARTIAL**, not COMPLETE. No new backup, restore, decryption,
key access, source-service call, ejection or cleanup is performed in C.
The subsequent documentation-only publication has separate operator authorization.

## Scope and identities

- Published restore implementation: `817b76dbc8e2c17241b799fc49066a50082e4af1`;
  fast/integration CI passed for that commit. These documentation changes are
  a separate documentation change; the restore result does not itself establish
  the publication commit's remote CI result. See Git/GitHub for that commit and runs.
- Session: `20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`.
- Archive: `K:\FootballPlatformBackups\s3\20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`.
- Restore: `F:\FootballPlatformRestoreDrills\20261024T110123Z-ac8cfb544a2e46688b406d2dcc168509`.
- Completion report: `restore-report.json` in that restore directory.
- Production key ID (NOT material):
  `s3-recovery-20261022T204016Z-3e0f028ad7184961bb3b6b4377beeae9`.
- One real collection and one real restore; no replay/overwrite or second attempt.
  Backup receipt completion time: `2026-10-24T11:04:46Z`. The session name is not
  the restore time. The restore report has no start/finish timestamps; no complete
  disaster-recovery RTO can be inferred from it.

The verified backup covers the observed current objects collected on October 24,
not an assertion of the live bucket's current state on October 28. No fresh S3
inventory was requested in C. Collection used operator-confirmed quiet-window,
object conditional reads and final inventory/metadata fences; this is NOT a
global atomic S3/PostgreSQL/ClickHouse snapshot.

## Evidence reconciliation

| Evidence boundary | Observed result |
| --- | --- |
| Source objects represented in backup and restore receipts | 315 / 356383409 plaintext bytes |
| Archive logical records | 316: 315 S3 objects + one encrypted local evidence record |
| Encrypted archive directory | 319 files / 357278273 bytes |
| Restored directory | 315 payload files + object map + completion report = 317 files |
| Independent readback in B2 and again in C | 315/315 SHA-256 PASS; 22 empty objects preserved |
| Object mapping | 315 unique source keys and unique opaque local names; zero missing/extra |
| Stored string metadata | 1696 key/value pairs; map digest unchanged from completed restore |
| Embedded lineage | 22 manifests / published / loaded identities; registered 312, legacy 2, test 1 |
| Key recovery | fresh manual PHONE entry in B2, explicitly confirmed by operator |
| Original production key / source services used by restore | false / false |
| Completion | `RESTORED_LIVE_OFFLINE_LOCAL`; no pending report, all artifacts single-hardlinked |
| Current ACL audit | parent + session directories and all 317 files protected, current-owner-only |

The published GUI first authenticated the manifest/index, decrypted and verified
the archive (including the evidence record), and reconciled embedded lineage.
The operator then explicitly confirmed the 315-object / 356383409-byte write
checkpoint. Source keys were map DATA, not filesystem paths; no source service or
original local key fallback was used. The operator confirmed PHONE/PASS/window
closure. Phone provenance is **operator-attested**, not a programmatic Bitwarden
audit or proof of cold vault recovery after loss of all devices.

During B2 the files initially inherited only owner-only rules from the protected
session directory. To meet the stricter per-file protected-DACL requirement, the
317 newly restored files alone were made non-inheriting while preserving those
rules; payloads were rehashed afterwards. Root F: and parent permissions were not
changed. C only reaudited these ACLs: zero inherited rules, foreign allow entries,
owner mismatches, links or reparse points. The published engine does not itself
promise explicit per-file DACL protection: future drills must audit this distinction
and obtain approval before any necessary scoped post-restore hardening. Never
silently repair arbitrary preexisting directories/files.

### Minimal non-secret audit references

| Artifact | SHA-256 |
| --- | --- |
| Backup session receipt | `c8d6d75a32bad20cbf04b7d5bbed8838fe01e569943d792592b015ac1282ac20` |
| Earlier PHONE equivalence receipt | `8b4c861bc3a00b86ab37856e531694d20330a574f9e10b6fa62cf91c387e8ab8` |
| Restore completion report | `2c07411387abc4075704e587cd676ce6963d99c039ba8c60e84bcb446c1ed2c0` |
| Sensitive local object map (digest only) | `974cc5636c31f182691dcd2b5d31451c86d90bcce12ecf29ed693b5607dc0849` |
| Sealed archive manifest | `be3bd0c6ead83504ced083cb9ebcc680c7b4ce759be5df0b1a85e6d1b7f6377d` |
| Collected source inventory | `1507a7676eed78b676ac8d82177fc451a4ca9a081f2aab5e5c6888abb2d931b6` |

Private receipt locations, not files to publish:
`%USERPROFILE%\FootballRecoveryVault\s3\<key-id>.backup-<session>.json` and
`<key-id>.recovery-<attempt>.json`. C read these exact non-secret receipts, NOT
the `.key` file. Backup/restore receipts agree on session, key reference, source
identity, count, bytes, manifest digest, verification and lineage. Historical
receipt fields such as pending manual note update or pre-backup comparison status
describe their creation checkpoint: the operator subsequently confirmed the
Bitwarden session update. Do not rewrite immutable historical receipts to pretend
an automated vault inspection or remote restore occurred.

The completion report passed an exact field/value allowlist: only schema/status,
session/resource IDs, counts, digests, route/usage booleans, disk numbers and fixed
lineage aggregates. It contains no key material, credentials, object keys, metadata
values or plaintext payloads. It still contains operational identifiers, so do not
blindly dump private receipts into public Git/CI. Only the reviewed minimal facts
and digests above are included here. `object-map.json` and all `.bin` payloads are
sensitive and must remain outside Git, Docker contexts, logs and CI artifacts.

The local receipts/completion report are operator records, **not independently
authenticated signatures**. Digest agreement with an earlier observation detects
change relative to that record, not malicious replacement of every record. The
encrypted archive's authenticated manifest/index and byte checks are the recovery
authority. C rehashed restored payloads and checked encrypted index/manifest binding
without a key; C did not rerun AES-GCM decryption. Authentication PASS is the witnessed
B2 result from the published reader, not a claim of a new key-based check in C.

## What is and is not closed

| Scenario | Status |
| --- | --- |
| Current-object encrypted backup on independent physical K: | VERIFIED |
| Offline isolated local restore to F: using manually recovered PHONE key | VERIFIED |
| Restore without Selectel, PostgreSQL, ClickHouse, scheduler or original key file | VERIFIED for this drill |
| Offsite or additional independently administered archive copy | NOT VERIFIED / not created here |
| Fresh Windows machine bootstrap and old NTFS owner-SID handling | NOT VERIFIED |
| Loss of workstation + phone; cold Bitwarden/MFA account recovery | NOT VERIFIED |
| All application/runtime secrets recovered and services reconstituted | NOT VERIFIED |
| Remote S3 destination restore and service cutover | NOT VERIFIED |
| Historical object versions, versioning/Object Lock state | UNKNOWN (prior HTTP 403); not backed up |
| Full-platform machine-loss recovery, RPO/RTO/SLA | NOT VERIFIED / not established |

K: is a separate USB StoreJet Transcend (Disk 4 at inspection); F: is NVMe Disk 2.
Both were NTFS/Online/Healthy. They are still attached to the same workstation;
physical separation of disks does not establish offsite storage or protection from
host-admin compromise. One archive generation on one USB device is still a single
physical failure point. HealthStatus is not a guarantee of sector integrity or
power-loss durability. The source after collection may have changed; that later
state is not protected by this generation.

## Operator-only safe disconnection and storage of K: (not executed)

1. Keep the session/key mapping and minimal receipts recoverable separately from
   the computer. Keep the recovery key off K:; never put a key export/printout in
   the archive folder, shell history, Git or CI. Do not modify Bitwarden automatically.
2. End all archive reads/verifiers/copies and close Explorer/archive viewers and
   terminals whose current directory is on K:. Do not unplug during activity.
3. In Windows, use **Safely Remove Hardware and Eject Media**, select the Transcend
   device after checking the currently assigned drive/device identity, and wait for
   **Safe To Remove Hardware**. Disk numbers/drive letters can change on reconnect;
   do not trust the number 4 as permanent identity.
4. If Windows says the device is busy or ejection fails, stop. Identify/close the
   holder normally; do not force dismount, kill services, change cache policy or
   pull the cable. Only disconnect after Windows reports safe removal.
5. Label the medium with a non-secret inventory reference/session date, store it
   disconnected in an operator-approved secure, dry location away from the working
   computer, and control physical access. A different room is not evidence of an
   offsite/disaster-independent location. Record actual custody/location privately,
   not the storage address in Git. No ejection or relocation is claimed in C.

This follows [Microsoft's safe-removal instructions](https://support.microsoft.com/en-gb/windows/hardware/safely-remove-hardware-in-windows).
The [Windows removal-policy documentation](https://learn.microsoft.com/en-us/windows/client-management/client-tools/change-default-removal-policy-external-storage-media)
explains why cached writes require safe removal; no device policy was inspected
or changed as part of this documentation task.

## Proposed generations, media checks and independent key escrow

This is a starting policy **for operator approval**, not an enabled schedule or
permission to create/copy/delete archives:

- Create immutable new session generations after approved source changes and,
  during active development, plan a weekly checkpoint. Keep four weekly and three
  monthly checkpoints initially, with at least two separately verified generations
  before considering any retirement. Counts are a proposal, not an existing stock.
- Plan a second physical medium/approved independent copy and alternate custody so
  one verified copy can remain offline/offsite while another is attached. Do not
  overwrite the only working generation to create the next. No extra copy, provider,
  account, access key or storage purchase is selected/created by this runbook.
- Size future storage from measured encrypted bytes per generation, growth and
  reserves. This session is 357278273 bytes; future context/data growth is unknown.
- Keep a private, minimal generation register: session, creation/verification date,
  key ID, manifest digest, source inventory digest, counts, media label/copy custody
  and last restore result. Never include key material or plaintext object maps.
- Keep the production key's manual Bitwarden route independent of K:. Retain each
  old key ID/session association while any generation needs it. Key rotation or
  deletion requires separate approval and tested access to all retained generations.
  Recoverability of Bitwarden master credentials and MFA after losing existing
  devices needs an operator-selected independent route, not storage only on this
  workstation/phone. No automatic vault export or external upload is authorized.
- On each approved reconnect: confirm device identity, filesystem/health/space and
  absence of filesystem errors. Monthly, plan full authenticated read verification
  with an operator-recovered key; quarterly, plan an isolated restore, rotating media
  and including an alternate host when ready. These are future separately authorized
  reads/drills, not new work in C. Do not run automatic repair, format or sanitization.
- If a medium/read/checksum fails, preserve evidence and the remaining good copies.
  Do not repair or retire the only copy. Stop and approve a recovery/replacement plan.
- Generation retirement requires review of the retained independent copies, keys,
  latest verification/restore evidence and retention needs. No automatic pruning.

## Future plaintext cleanup on F: — separate approval required

The restore directory is retained, contains sensitive plaintext, and is NOT itself
an independent backup. No file is deleted in C.

1. Confirm there is no ongoing analysis/recovery dependency. Preserve only an approved
   non-secret completion/audit receipt and its digest in a private register outside
   the directory before cleanup. Do not copy the object map or payloads into Git.
2. Review an exact inventory against this session: 315 opaque payloads plus map and
   report, 317 files, 356383409 payload bytes; require no pending completion, unknown
   entries, reparse points or hardlinks. Missing/corrupt/unexpected content means stop
   and investigate, not broaden the deletion scope.
3. Resolve and approve ONLY the exact session path shown above, a direct child of
   `F:\FootballPlatformRestoreDrills`. Exclude F: root, the parent itself, all other
   sessions, K:, the key vault and Git. Recheck at execution time; never use a glob,
   computed unvalidated path, cross-shell deletion or broad recursive command.
4. Obtain explicit deletion authorization, preview exact targets, then use a reviewed
   literal-path/native-Windows workflow for that session alone. No destructive command
   is provided or executed by this stage. Confirm the exact target is absent afterwards
   and retain the approved non-secret evidence. Do not delete or mutate K: or keys.
5. Ordinary deletion, including bypassing the Recycle Bin, is **not a secure-erasure
   guarantee**. SSD wear-leveling, OS caches, snapshots and previous plaintext copies
   remain separate risks. No encryption/BitLocker change, free-space wipe, TRIM or
   whole-device operation is authorized. Agree on the required confidentiality and
   media-sanitization approach separately before claiming erasure.

[Microsoft's BitLocker operations guide](https://learn.microsoft.com/en-us/windows/security/operating-system-security/data-protection/bitlocker/operations-guide?tabs=powershell)
notes that deleted files can remain recoverable in free space and distinguishes
used-space-only from full-volume encryption. No volume-encryption state is assumed
or changed here.

## Remaining recovery tests and closure gates

1. Separately approve/archive an independent offsite copy and verify ciphertext and
   full authenticated readback there. A different location and administrative failure
   domain must be real, not inferred from a new folder or bucket name.
2. Design a fresh-machine drill with the pinned runtime, published source, dependency
   bootstrap, independent key/vault/MFA retrieval and no original host credentials.
   The reader enforces current-owner ACLs: old Windows SIDs on another machine need
   a separately reviewed, synthetic-tested read/copy/ownership handling procedure.
   Do not silently weaken checks or change the original archive's ACL to make it pass.
3. Separately design/approve remote S3 restore into a new isolated destination with
   no-overwrite, least write permissions, original key/metadata mapping and post-PUT
   readback. It is not implemented/verified by the local `.bin` output.
4. Test recovery of all required runtime encryption secrets and full service/catalog
   reconstruction. The existing PostgreSQL/ClickHouse/Grafana drills do not by themselves
   prove the entire application can be rebuilt after loss of the workstation.
5. Resolve historical-version observability/permissions with the operator; HTTP 403
   means UNKNOWN, not disabled. Do not invent an historical-version backup guarantee.

## Documentation publication checks

C changes only README and three runbooks. Repository/security contracts passed
(`python -B ci/check_repository.py`), all 22 CI contract tests passed
(`python -B ci/run_unittest.py discover -s tests/ci -p 'test_*.py'`), and
`python -B -m ruff check .` / `git diff --check` passed. The new, initially untracked
runbook was also explicitly checked for credential signatures, UTF-8, whitespace
and local Markdown links; all four changed documents passed. No private receipt,
map, payload, key or CA file is included. These checks are not a new remote CI run
or a replay of the recovery suites; no application/restore code changed in C.
The evidence audit stopped before staging/commit/push. Their subsequent execution
was separately authorized for exactly these four documentation files; the published
commit and its workflow results must be checked in Git/GitHub.

**Closure verdict:** evidence-consistent current-object isolated local S3 recovery
is **VERIFIED**. Documentation-only publication is separately authorized;
cleanup, ejection and further drills still require their own authorization.
Overall Stage 8C stays **PARTIAL** until the remaining independently evidenced
scenarios are resolved.
