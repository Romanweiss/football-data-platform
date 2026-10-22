# Stage 8C-R2.4-A1.6: recovery key escrow readiness

Date: 2026-10-22 (Europe/Moscow). Baseline HEAD:
`bea3d8dd94f87f1e3f683c13541d77db361fc423`, preserving local A1/A1.5 WIP.

**Local synthetic key recovery: PASS. External escrow: BLOCKED / NOT VERIFIED.**
**Real key generation and first live backup: BLOCKED. Stage 8C: PARTIAL.**

No independent store has been selected/connected. No real recovery key, S3 request,
cloud write, backup, ETL, database/volume/credential change, commit or push in A1.6.
The [A1.5 read-only acceptance](stage8c-r2-4a1-5.md) is historical evidence, not a
new source inventory or backup in this stage.

## Store comparison and conditional recommendation

| Option | Survives loss of Windows profile/workstation only if… | Main risks / recovery check |
| --- | --- | --- |
| Existing encrypted password-manager vault | A vault copy and unlock/recovery credentials are accessible on another device without this Windows login | A local-only/DPAPI-bound copy is insufficient. Test fresh-device login or offline unlock, MFA/recovery and binary attachment export; avoid plaintext exports, clipboard/history and screenshots |
| Separate disconnectable encrypted medium | It is not K, not an internal C/F partition, is physically stored separately and its unlock material is independently recoverable | Theft, loss, media degradation and shared physical disaster. Prove decryption/export on the intended recovery device, then disconnect; a new drive letter alone proves nothing |
| Specialized protected cloud store | A separately administered account, unlock/MFA recovery route and supported export survive workstation/source-account loss | Provider/account lockout, compromised admin, unavailable service/export and retained versions. Test the exact 32-byte export; a non-exportable KMS key is not a drop-in replacement for this archive API |

Conditional first choice: the operator's **existing encrypted password manager**, if
it already supports a proven independent recovery device and exact binary-key export.
Otherwise use a separately protected offline medium. This is a recommendation, not
selection of a provider or proof of either route. No software, vault or external
service was installed/connected. Account/region availability and a specific product's
features remain operator/provider checks, not assumed facts.

Independence requires the archive, key and vault/medium unlock recovery not to share
one failure boundary. A synced vault whose sole unlock/MFA recovery is on this PC
does not qualify. Neither does a key copied to another C folder or onto K beside
the archive. Key backup and compromise planning follow the principles in
[NIST SP 800-57 Part 1 Rev. 5](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final);
the concrete procedure below is this project's design, not a certification.

## Key lifecycle (future real operations, NOT executed)

1. **Prepare the route first.** Select a store/custodian/recovery device and prove
   its unlock/recovery without the original PC using a synthetic fixture. Archive
   encryption must not depend on a vault unlock secret stored only in that archive.
2. **Allocate an opaque key reference.** Keep it in the operator's private recovery
   register. The archive session ID does not exist until `S3ArchiveWriter` starts:
   do not invent one or confuse it with an ETL build ID.
3. **Create only after separate authorization.** Existing `generate_key` uses OS
   randomness for exactly 32 bytes, exclusive create, fsync and owner/ACL audit.
   Use the existing private profile `FootballRecoveryVault/s3`, outside Git and K.
   Do not derive the key from S3 credentials/passwords or pass it on the command line.
4. **Escrow exact bytes.** The operator places that key in the chosen encrypted
   store using its approved protected interface. Prefer binary attachment/export;
   if a store requires encoding, document reversible encoding and verify the decoded
   32 bytes in memory. Encoding is not encryption. No shell literal, print, clipboard
   log, plaintext export, Git/CI artifact or automatic upload.
5. **Retrieve before collection.** On the intended recovery device/route, retrieve
   a separate copy into a newly created private directory. Check length, owner,
   protected DACL, links and exact equality in memory, never log key bytes/digests.
   A synthetic route PASS alone does not prove the eventual real key was escrowed.
6. **Bind to actual session IDs.** Record `key_ref -> session_id` for each actual
   attempt in the private register and encrypted escrow entry once known; keep the
   mapping retrievable independently of C. The authenticated manifest binds session
   ID, salt, scope and index to the key. Prefer a fresh key for each new generation;
   keep necessary mappings for aborted sessions, never overwrite/resume them.
7. **Offline recovery verification.** Recover matching source/runtime and archive
   independently. Retrieve the key through the route, not the original host file.
   Existing offline `verify` authenticates manifest/index/chunks and checks plaintext
   SHA-256. Only after verification plan an isolated restore; no live cloud restore
   adapter is introduced here. Compare restored bytes/counts where restore is supported.
8. **Retain and retire deliberately.** Keep recoverable key copies for every retained
   dependent archive. Recheck the recovery route after vault/MFA/device changes and
   periodically with an operator-approved schedule; no job/deletion is installed.
   Delete/retire only after dependency/retention review and separate authorization.

Loss of every usable key copy makes the encrypted archive unrecoverable; neither
session/build IDs nor runtime credentials reconstruct it. If compromise is suspected,
stop using that key, identify affected sessions, preserve evidence, and arrange a
new trusted environment/key/escrow/verified backup under separate approval. Rotating
S3 credentials does not re-encrypt old archives; re-encryption cannot undo exposure
of an already copied ciphertext/key. A stolen master key also permits forgery of
archive authentication, not merely decryption. No automatic destructive response.

Cryptography remains unchanged: AES-256-GCM, existing nonces/AAD, per-session random
salt and HKDF-SHA256 separation for data/index/manifest MAC. Database profile v1 and
the schema-2 S3 archive remain compatible.

## Local synthetic evidence, NOT independent escrow

Recorded only:

```json
{"status":"PASS","session_id":"20261021T233230Z-014870e53dc94aa78b4da236c5b1bb90"}
```

The session timestamp is UTC; the local date is 2026-10-22. The drill in
`tests/test_s3_escrow.py:local_synthetic_drill`:

- Uses a fresh system-temp tree, private fixture directories, a random **synthetic**
  32-byte key and tiny JSON/binary/empty payloads. No existing archive/key is opened.
- Creates/seals the existing encrypted archive with session permission guards.
- Copies the synthetic key to `LOCAL-NOT-INDEPENDENT` within that temp tree, deletes
  its original fixture file, retrieves into another private test directory, then
  deletes the local-copy fixture file. No original writer is used for recovery.
- Authenticates/verifies offline, restores into a new temp destination and compares
  each payload's SHA-256. A wrong key fails manifest authentication before any
  plaintext destination is created.
- Returns only PASS/session ID, not payloads, keys, key fingerprints, file paths or
  decrypted index. The temporary test tree is cleaned up by its owning test context.

All paths are local on the same machine. Simulated removal of an original copy is
not a test of loss of Windows profile, device, password manager, MFA or machine.
No fixture key is retained for later external upload; an external drill requires a
new synthetic session after store selection. K and the actual private key directory
were not used for fixtures. There is no escrow upload adapter or production drill CLI.

## External drill operator checklist (unexecuted)

- [ ] Name the existing vault or separate medium; identify custodian and recovery device.
- [ ] Prove vault/medium unlock and MFA/account recovery without this PC/profile.
- [ ] Agree a test-only private fixture location outside Git, K and the real key directory.
- [ ] Create a fresh synthetic key/archive, labelled TEST ONLY; do not invoke live `create`.
- [ ] Manually place only the test key in the approved encrypted store; record its session mapping.
- [ ] Make the original test key unavailable to the recovery attempt without deleting real data.
- [ ] Retrieve through the independent route/device; validate a new private key location.
- [ ] Verify the archive and perform isolated synthetic restore; compare all SHA-256/counts.
- [ ] Record only PASS/FAIL and session ID as drill evidence; no key/hash/export contents.
- [ ] Remove only the explicitly identified test copies through approved store procedures.
- [ ] Separately approve any future real key generation; escrow/retrieve the actual key
  before attesting key recoverability for the first backup.

The checklist is a plan, not evidence. A checked boolean or two paths on C cannot
make external escrow PASS. No external route or service is selected automatically.

## Existing gates and limits

- `locations` rejects overlapping archive/key trees in either direction. It does
  **not** prove different physical disks or forbid every sibling directory on K.
  Operator procedure requires the real working key outside K, and escrow outside
  the workstation; these physical/administrative checks remain explicit gates.
- Private owner/protected DACL and no extra allowed principals are audited; unsafe
  existing directories/files are refused, not silently repaired. Links and hardlinks
  are refused. Tests include actual broad Windows directory **and key-file** grants.
- Live `create` rejects absent `key_recoverable` confirmation before runtime, key or
  source access. It also needs independent-media/quiet-window/user confirmations.
  These are attestations, not automatic validation of a third-party vault.
- `keygen` separately requires explicit generation confirmation; it does not itself
  prove escrow and returns `key_recovery_verified=False`. This stage's BLOCKED key
  decision is an operator boundary; do not claim the software prevents every manual
  generation before escrow. No bypass of any existing guard was added.
- No automatic vault/cloud upload, export, key rotation or retention deletion exists.
  Key bytes are never a report/log/argument; host/admin compromise, memory dumps and
  secure deletion on SSD/pagefile are outside these process/ACL guarantees.

## A1.5 failure diagnosis and future safe codes

The first A1.5 failure's cause remains **UNKNOWN**. Its anonymized result contains no
retained SDK type; a later successful audit cannot retrospectively establish TLS or
timeout as the cause. No real S3 call was repeated here to manufacture a diagnosis.

`s3_diagnostics.py` now classifies actual exception types and allowlisted provider
codes, never searches/prints raw messages. The host launcher retains its existing
top-level failure code/stage and adds safe `diagnostic` fields:

| Category | Example code / operation |
| --- | --- |
| TLS_FAILURE | S3_READ_TLS_FAILED / head_object |
| TIMEOUT | S3_READ_TIMEOUT / list_objects_v2 |
| CREDENTIAL_FAILURE | S3_READ_CREDENTIALS_FAILED, or legacy S3_READ_HTTP_403 for explicit credential rejection |
| ACCESS_DENIED | S3_READ_HTTP_403 without an explicit known credential-rejection code |
| METADATA_INCONSISTENCY | S3_METADATA_BASELINE_CHANGED / reconcile_metadata, plus exact known lineage codes |
| UNKNOWN | S3_HOST_READINESS_FAILED; unknown messages/attributes are suppressed |

Generic 403 cannot prove whether a key is invalid or permission is missing. Metadata
query/unknown errors are not falsely diagnosed as catalog inconsistency. TLS_FAILURE
does not claim every SSL failure is certificate validation. Stream failures preserve
`S3_STREAM_READ_FAILED` with safe timeout/TLS category and operation `read_body`.
Existing 403/404/412 exception strings and optional-capability UNKNOWN semantics are
unchanged; no retries, timeouts, budget, TLS setting or DQ/lineage rule was weakened.

## Tests

Synthetic tests have no real cloud credentials/network or production archive/key;
Windows ACL modifications apply only to newly created disposable fixture paths.

| Check | Result |
| --- | --- |
| Native Windows 3.12.10: escrow, ACL, diagnostics, host, read-only suites | **58 PASS**, no skips, 54.336s |
| Real Windows directory/key-file ACL, owner and junction cases | **6 PASS**, included above |
| Native Windows: S3 archive + database-v1 recovery compatibility | **62 PASS**, 24.497s; no real database restore |
| Linux 3.10.12 and 3.12.14, network disabled: full recovery gate | **186 each**, PASS; 6 Windows-only skips each |
| Linux 3.12.14 root unit regression | **711**, PASS; same 6 Windows-only skips |
| Repository/CI contracts | **19 PASS** |
| Repository security / ignore contracts, Ruff, compileall, Git diff check | PASS |
| Changed/untracked public-source signature and whitespace audit | PASS; staging empty |

No full native Windows recovery rerun or real DB drill was needed: targeted native
Windows suites above cover the changed transport/diagnostic and key/ACL paths, while
the full operator/workflow regressions also run on both offline Linux versions.
No new remote CI result is claimed for these uncommitted changes.

Reproduce the targeted local tests (no source connection or operator backup command):

```powershell
$python = '.\.venv\s3-recovery\Scripts\python.exe'
& $python -B -m unittest tests.test_s3_escrow tests.test_s3_windows_acl tests.test_s3_diagnostics tests.test_s3_host tests.test_s3_readonly -q
& $python -B -m unittest tests.test_s3_archive tests.test_recovery -q
python -B ci/check_repository.py
python -B -m unittest discover -s tests/ci -q
git diff --check
```

Changed in A1.6:

- New `src/recovery/s3_diagnostics.py`, `tests/test_s3_diagnostics.py`,
  `tests/test_s3_escrow.py` and this document.
- Updated `src/recovery/s3_readonly.py` to retain typed safe diagnostics,
  `scripts/check_s3_host_readiness.py` to expose only the allowlisted details,
  `tests/test_s3_windows_acl.py` and `docs/stage8c.md`.

Existing A1/A1.5 changes are retained, not staged or committed. Archive cryptography,
`s3_archive.py`, `s3_safety.py`, dependencies and the actual key/backup CLI gates
were not changed in this stage.

## Decision

**BLOCKED for a real recovery key and first live backup.** Required from the operator:
chosen store, separate recovery device/identity, independently recoverable unlock/MFA
route, and an external synthetic retrieval/restore drill. Later, the real key must
itself be escrowed/retrieved and separately authorized before backup. Independent S3
copy, remote S3 restore, secret recovery and full machine-loss recovery remain unverified.
