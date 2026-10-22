# Stage 8C-R2.4-A1.7: manual Bitwarden external synthetic key drill

Date: 2026-10-22 (Europe/Moscow). HEAD:
`bea3d8dd94f87f1e3f683c13541d77db361fc423`, preserving prior local WIP.
**Independent manual synthetic key recovery: PASS (operator-attested phone route).**
**A1.7 completion: PASS — operator cleanup confirmed by a read-only absence check.**
Stage 8C remains PARTIAL; real key generation and first live S3 backup remain BLOCKED.
Checkpoint instructions below are historical evidence; do not recreate the session
or repeat viewer/input/cleanup actions. The entire local test fixture has been removed.

## Trust/access boundary

The operator reports Bitwarden account/extension/mobile installation, master password,
MFA, successful phone login and an existing secure note named
`Football Platform Recovery Test`. These are operator-supplied facts, not agent
inspection or proof of this session's escrow/recovery.

No Bitwarden API, CLI, vault, extension, browser storage, cookies, application files,
mobile application or password/recovery codes are accessed programmatically. All
vault edits, sync and phone retrieval are manual operator actions. Public Bitwarden
help documentation was consulted, not an authenticated vault. No Selectel/DB call,
cloud write by the tool, real key/archive, credential change, commit or push.

## Test material (removed after completion)

Session ID:

```text
20261022T183934Z-ca45a25fd32c4eacae02998a4bec5c5a
```

Dedicated private fixture root, outside Git, Docker build context, K and the real vault:

```text
<system temp>\football-bitwarden-synthetic-e79ee036f531402ca22c54a8e381c2d3
```

- `archives/<session_id>/`: schema-2 `synthetic-local` AES-256-GCM archive containing
  three tiny artificial JSON/binary/empty objects, using the existing archive API.
- `original/synthetic.key`: formerly the synthetic OS-random 32-byte master key;
  now removed at the confirmed checkpoint. No hex/text key file or second local copy.
- `recovered/`: held the manually entered phone-retrieved 32-byte synthetic key;
  protected owner/DACL audited before cleanup. Now removed with the fixture tree.
- `prepared.json`: non-secret type/session marker only; contains no key/key hash.

Original key, archive and fixture directory passed private path/ACL checks at preparation.
Archive sealing re-read/decrypted/verified the bytes with the original local key;
this is preparation, NOT verification using a Bitwarden-recovered key. Crypto,
requirements, production keygen/create gates and existing database recovery are unchanged.

The fixture was intentionally retained across the manual checkpoints. After all
recovery checks it was removed by the operator; the agent confirmed the exact root
is absent and is not a symlink. Never recreate a key/archive under this recorded ID.

## Operator checkpoint 1: manual escrow and phone visibility (completed)

The operator has explicitly confirmed save/phone visibility and closure of the key
window in chat. This is an operator attestation, not programmatic vault inspection.
Instructions below record the completed step; **do not reopen the original viewer**:
its source key has now been removed, so it must refuse to display it.

1. Stop screen sharing/recording. From the project directory run the local-only viewer:

   ```powershell
   # Historical example ONLY; this completed fixture no longer exists.
   $fixture = Join-Path ([IO.Path]::GetTempPath()) 'football-bitwarden-synthetic-e79ee036f531402ca22c54a8e381c2d3'
   & .\.venv\s3-recovery\Scripts\python.exe -B scripts/show_synthetic_escrow_key.py --session-root $fixture
   ```

   This opens a Tk window. It reads only this synthetic fixture, authenticates its
   synthetic-scope archive and shows the key locally as four lines of 16 hex digits.
   No terminal output, copy button, selectable key field, clipboard write or key file
   encoding is used. The viewer never reads or controls Bitwarden. Errors are fixed
   non-secret codes. The GUI display itself is sensitive: no screenshot/photo/chat.

2. Manually open the existing Bitwarden secure note `Football Platform Recovery Test`.
   Add a TEST ONLY block without overwriting unrelated note content:

   ```text
   purpose=synthetic-test-only
   session_id=20261022T183934Z-ca45a25fd32c4eacae02998a4bec5c5a
   encoding=hex
   key_hex=<manually enter the 64 hex digits from the LOCAL WINDOW, not this document>
   ```

   Join the four displayed lines into exactly 64 characters (`0-9`, `a-f`), no spaces,
   line breaks or `0x` prefix. This represents exactly the original 32 bytes. Hex is
   encoding, not encryption; protection of the saved entry is supplied by the vault.
   Type the key manually. Do not put it in PowerShell, chat, an ordinary text editor,
   screenshots, email, a vault export or general/cross-device clipboard/history.
   Session ID is not a secret and can be copied separately.

3. Save the note. On the **phone**, manually open Bitwarden and locate the same note
   and exact session block. Confirm the session ID and all 64 key digits are present.
   If needed, manually sync in the mobile app following
   [Bitwarden's sync instructions](https://bitwarden.com/help/vault-sync/).
   Do not export the vault, change MFA or provide any unlock/recovery code to the agent.

4. Close the local key viewer and desktop note/extension view. Reply only:
   **"Сохранил, на телефоне вижу сессию ca45a25fd32c4eacae02998a4bec5c5a; окно ключа закрыто."**
   Never include the key or a screenshot in the reply.

Phone visibility alone is not yet a completed independent retrieval drill.

## Operator checkpoint 2: manual phone input (completed)

The operator explicitly confirmed manual entry from Bitwarden on the phone, the
Offline verify PASS message and closure of the input window. The agent then checked
the exact `recovered-from-phone.json` receipt, original-key absence and the new
32-byte recovered file with its private ACL. No original-key fallback or new session
was created. The instructions below describe the completed checkpoint, not a request
to re-enter/overwrite the recovered key.

After that explicit reply, `exclude_original` checked the exact fixture/session,
private owner/ACLs, allowed file sets, synthetic archive header and empty recovery
directory. It unlinked only `original/synthetic.key`, without loading/copying its bytes.
`original-excluded.json` contains only session ID and confirmation/absence flags.
The actual check returned `original_key_exists=false`, `recovered_directory_entries=0`.
Ordinary unlink is not forensic erasure of memory, SSD, pagefile or cached vaults.

Keep the desktop Bitwarden view/extension manually closed or locked. Open the secure
note on the **phone**, and run from the project directory:

```powershell
# Historical example ONLY; do not rerun the completed checkpoint.
$fixture = Join-Path ([IO.Path]::GetTempPath()) 'football-bitwarden-synthetic-e79ee036f531402ca22c54a8e381c2d3'
& .\.venv\s3-recovery\Scripts\python.exe -B scripts/receive_synthetic_escrow_key.py --session-root $fixture
```

Check the exact session ID displayed by the form. Manually type ONLY that note's
`key_hex` (64 hex characters, no spaces/newlines/`0x`); do not use the old viewer,
shell arguments, clipboard/cross-device paste or chat. The local Entry is masked,
paste/copy/cut are blocked, and the phone-source checkbox starts unchecked. Check
it only if you actually read the value from the phone. No Bitwarden password, MFA
or account recovery code is required or requested.

Click **Verify and save synthetic key**. Wrong format/key does not write a key file;
correct input authenticates/verifies the synthetic archive first, then exclusively
writes the recovered 32-byte key under the private `recovered/` directory, fsyncs/
audits/readbacks it, and records a non-secret `recovered-from-phone.json` receipt.
Existing recovered material is never overwritten. No vault/network API is used.

After seeing **Synthetic key saved. Offline verify PASS**, reply only:
**"Ввёл ключ с телефона; получил Offline verify PASS; окно закрыто."**
Do not send the value, screenshot or vault export. If an input error occurs, report
only the fixed error message, not the input. The actual entry and subsequent tests
are now complete as recorded below; no repeated input is needed.

## Next checkpoint, only AFTER the operator reply

The agent must not simulate this confirmation or import the original key as recovered.

1. Record the operator's phone confirmation (no key values) for this exact session.
2. Remove ONLY `original/synthetic.key` from the validated fixture tree after the
   viewer is closed; verify it is absent. Do not read/reuse its bytes during recovery.
   Ordinary deletion is not forensic secure erasure of SSD/RAM/pagefile data.
3. Keep the desktop extension closed/locked manually. The operator reads the key
   **from the phone** and enters it through the separate local private recovery input
   above, not shell arguments/history/chat/clipboard. The original viewer is
   display-only and must not be reused as an import command.
4. Decode exactly 64 hex digits into a NEW exclusive 32-byte key file under `recovered/`,
   audit owner/DACL/links and use only that file. No local key-copy fallback.
5. Offline authenticate/verify archive, restore synthetic objects to a NEW private
   temporary destination and compare all original sizes/SHA-256 with the fixed fixture.
6. Negative test: wrong key must fail before plaintext destination creation. Reject
   existing destination/overwrites and any session/key mismatch without secret output.
7. Record only outcomes/session ID, plus the fact that phone provenance is an operator
   attestation supported by the original file's absence and authenticated recovery.
   No programmatic vault audit/forensic proof of where a manually typed key came from.
8. Cleanup only this explicitly validated UUID fixture tree, recovered key and restored
   synthetic files. Inspect for unexpected entries/links first; never delete all Temp,
   the real key directory, K, unrelated files or Bitwarden items automatically.
   Ask the operator to manually remove the test block if desired; no automatic vault deletion.

## What this can and cannot establish

Successful phone retrieval and authenticated recovery demonstrate a manual key route
independent of the original Windows file/profile for this **synthetic session**,
with phone provenance explicitly attested by the operator. Cached phone
access/login alone does not prove future cloud-account/MFA recovery after all devices
are lost, availability of a real backup/key, an independent archive copy or full
machine-loss recovery. Phone provenance is not a programmatic/forensic audit of the
vault; no such access was attempted. A real key must later be separately
authorized, escrowed and retrieved; do not reuse this synthetic key.

## Current evidence

| Check | Status |
| --- | --- |
| New synthetic archive and original 32-byte test key, private ACLs | PASS |
| Baseline sealing/readback with original local key | PASS (preparation only) |
| Operator saved this key and sees it on phone; original viewer closed | OPERATOR CONFIRMED in chat |
| Original local key excluded/deleted | PASS; exact original file removed without reading its bytes |
| Actual retrieval from phone/Bitwarden | OPERATOR CONFIRMED; matching persisted input receipt checked |
| Offline verify with retrieved key | PASS; authenticated again independently by agent |
| Synthetic restore / size / SHA-256 | PASS; 3 objects / 113 bytes, all match fixed synthetic payloads |
| Wrong-key restore | PASS; S3_MANIFEST_AUTHENTICATION_FAILED before plaintext destination creation |
| Existing destination | PASS; S3_DESTINATION_EXISTS, contents unchanged |
| Private ACLs of final restored output and all cleanup targets | PASS after the targeted new-directory ACL fix below |
| Final cleanup of manual fixture | PASS; operator removal confirmed, exact UUID root absent on read-only check |
| Real backup/key / source object GET / DB restore | NOT EXECUTED |

Preparation/receiver/helper tests: 7 PASS on native Windows. The added cases exercise
confirmation/session gates, original absence and no original read, invalid/wrong key
without a write, successful simulated input, no overwrite, and no secret in errors.
Those local simulations do NOT count as real Bitwarden retrieval. Linux Python 3.12.14
synthetic recovery gate: 193 tests PASS, 6 intentional Windows-only skips. The 19
repository/CI contracts, source/ignore security checks, Ruff, compileall and diff/
whitespace checks PASS. Repository checks used the existing tooling Python with
PyYAML; no dependencies were added to the dedicated recovery venv.
Tests create/clean their own separate random fixtures, never this retained manual one.
Tk/Tcl 8.6 / 8.6.15 is available; actual viewer opening/entry/sync remain operator actions.

## Completed restore and discovered Windows ACL issue

Only the existing session `20261022T183934Z-ca45a25fd32c4eacae02998a4bec5c5a`
and `recovered/synthetic.key` were used. No session/key/archive was regenerated.
The full authenticated archive/index/chunks and all restored object SHA-256 passed.
A one-bit-different key was constructed in memory solely for the negative test;
it was never saved, logged or treated as a recovery key. It failed manifest
authentication before creating `wrong-key-destination`. Reusing the existing valid
destination was refused and a second SHA-256 comparison showed no overwrite.

The first restore's post-check exposed extra explicit Windows Allow rules on its
new destination/files. Owner was the current user and directory DACL was protected,
but that alone was insufficient; `assert_private` correctly refused it. The separate
recovered key directory/file remained private. No key was present in restored payloads.

`restore_synthetic` now invokes the existing `session_permissions(initialize=True)`
immediately after creating its NEW EMPTY destination, before any plaintext write.
This removes extra grants and independently audits the destination. It never repairs
an existing directory, changes crypto/schema or modifies the database backup profile.
A native Windows regression injects an Everyone grant into a new fake-verifier
destination and proves the real restore path removes it before writing. All 7 native
Windows ACL tests pass. No new archive session was made by this regression test.

Only the four known files/empty directory of the first restored output were removed
after exact path/file-set/link checks; archive and recovered key were retained. The
same session was restored again with the corrected ACL initialization. All original
positive/negative checks and private ACL checks then passed.

## Final cleanup boundary and completed operator action

Before final deletion the agent validated the exact UUID temp root/session, every
file/directory set, private owner/DACL, and absence of reparse points/hardlinks. The
remaining approved inventory was **14 files and 6 directories including the root**:
three archive chunks plus session/index/manifest, three public checkpoint markers,
one recovered test key, and four restored output/index files. The original key
directory was empty. No unexpected items were allowed.

The final PowerShell cleanup command was **rejected by execution policy before
CreateProcess**. None of its deletions ran. The agent did not retry through another
API or weaken the safety checks. Read-only confirmation showed the root, recovered
test key and final restored output still present. Earlier removal of the first four
restore-output files was a separate, successful scoped action, not final cleanup.

The operator then confirmed manual removal of ONLY this exact test folder through
the requested Explorer/Shift+Delete route (not the whole Temp directory, K or the
real recovery vault):

```text
<system temp>\football-bitwarden-synthetic-e79ee036f531402ca22c54a8e381c2d3
```

The subsequent agent check returned `fixture_root_absent=true` and
`cleanup=PASS_OPERATOR_REMOVAL_READONLY_CONFIRMED` for this same session. This closes
A1.7 local cleanup without another automated deletion attempt. Ordinary deletion
does not establish forensic erasure of SSD/pagefile/cache copies. Bitwarden was not
modified/deleted by the agent; the operator may separately remove only the TEST ONLY
block for this session manually. Do not reuse this key for a real backup.

**Final verdict: PASS for the independent, operator-attested phone-to-key synthetic
escrow/recovery drill and local cleanup.** This is not real-key escrow, independent
S3 backup, cold Bitwarden/MFA account recovery or complete machine-loss recovery.

Continuation checks: actual retained-session positive/negative tests and ACL audits
PASS; native Windows ACL suite 7 PASS; repository/CI contracts 19 PASS; Ruff PASS.
No full synthetic suite/session-creation rerun was performed in this continuation.
Source changes are limited to synthetic restore permission initialization, its native
Windows regression, this runbook and `docs/stage8c.md`. No commit/push.

New files: `src/recovery/s3_manual_drill.py`, `scripts/show_synthetic_escrow_key.py`,
`scripts/receive_synthetic_escrow_key.py`,
`tests/test_s3_manual_drill.py`, this runbook. `docs/stage8c.md` links this checkpoint.
Prior A1/A1.5/A1.6 WIP is preserved; nothing is staged/committed/pushed.
