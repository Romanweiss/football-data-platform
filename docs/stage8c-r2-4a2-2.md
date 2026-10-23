# R2.4-A2.2: manual production-key retrieval and pre-backup readiness

Baseline: `8ec15a2b60907b5639dabe9a1a2d4fad6ff1c273`, retaining local A2.1 work.
Stage 8C remains PARTIAL. No key regeneration, deletion, full S3 GET, archive
creation, cloud write, credential/IAM change or database recovery. The initial
no-commit boundary was subsequently amended by explicit operator approval on
2026-10-23: one local A2.1/A2.2 commit after successful checks, **without push**.

Key reference (not material):
`s3-recovery-20261022T204016Z-3e0f028ad7184961bb3b6b4377beeae9`.

The operator has confirmed saving the separate production Bitwarden note,
checking all 64 characters on the phone and closing the original key viewer.
This completes A2.1's manual-save checkpoint, NOT independent retrieval verification.

## Current checkpoint

**A2.2 readiness: READY**, based on the completed operator-attested phone comparison,
fresh bounded read-only source/lineage audit and current physical-media/path/space
checks below. **First live backup remains BLOCKED pending separate explicit approval
and a quiet collection window.** No archive exists and no collection was executed.

The operator updated the production note from the existing production viewer,
confirmed visibility on the phone and closed the viewer. Subsequent phone input
produced the actual MATCH receipt, and the operator confirmed PHONE/window closed.
Earlier mismatches/Key ID vs synthetic Session ID confusion were not bypassed;
the old note contents were never inspected programmatically or printed.

## Comparison implementation

`s3_key_escrow.begin_recovery` requires explicit saved/viewer-closed confirmation,
supported host, existing production register and private owner/protected file ACLs.
It keeps only a fresh UUID attempt ID and SHA-256 baseline in a repr-redacted
in-memory `KeyRecovery`. Original material is never used as the input default,
displayed, copied or deleted. No baseline digest is logged or persisted.

`confirm_recovered` requires the phone-source attestation and exactly 64 hex
characters. It checks that the original fingerprint has not changed since opening
the input window, then compares the supplied SHA-256 digest via `hmac.compare_digest`.
Malformed/wrong input cannot fall back to the original or write a success receipt.
No recovered `.key` file is written. The original remains unchanged.

Only after MATCH, an exclusive owner-only, protected-DACL receipt is written in
the existing private profile vault:

```text
<key_id>.recovery-<attempt_id>.json
```

It contains key/attempt IDs, UTC time, MATCH, method=MANUAL_PHONE_INPUT_SHA256_IN_MEMORY,
source=OPERATOR_ATTESTED_BITWARDEN_PHONE, original_preserved=true and
live_backup_executed=false. It contains NO key or fingerprint. A phone comparison
additionally records independent_route_verified=true (operator-attested route only).
An explicitly selected desktop diagnostic uses method=MANUAL_DESKTOP_INPUT_SHA256_IN_MEMORY,
source=OPERATOR_ATTESTED_DESKTOP_NOTE_DIAGNOSTIC_ONLY and independent_route_verified=false;
even MATCH in that mode does NOT satisfy independent recovery or authorize a source
preflight/backup. Never promote such a receipt to a phone-recovery PASS.
The creation-time
A2.1 register remains immutable; its pending state is historical, not a substitute
for this later event receipt. Existing receipts are never overwritten. A failed
receipt write/ACL audit is not accepted as successful readiness.

The evidence demonstrates a local cryptographic match and an operator-attested
phone route, not forensic proof of the input's origin, Bitwarden account/MFA recovery
after loss of all devices or recovery of an actual S3 archive. These receipts are
private operator records, not authenticated archive manifests or backup permission.

## Manual operator step

Keep the original key viewer and desktop Bitwarden view closed. Open ONLY the
production note `Football Platform | S3 Recovery | Production` on the phone.
Stop screen capture/sharing. Run locally from the project directory:

```powershell
& .\.venv\s3-recovery\Scripts\python.exe -B scripts/receive_s3_recovery_key.py `
  --key-id 's3-recovery-20261022T204016Z-3e0f028ad7184961bb3b6b4377beeae9' `
  --confirm-saved-and-viewer-closed
```

The user explicitly requested a usability revision on 2026-10-23: the field remains
masked by default, but Show entered key can reveal ONLY what the operator entered,
never the original file. A local length/hex-format counter does not echo characters
and distinguishes invalid characters/whitespace from a cryptographic mismatch.
Actual mismatches already passed the 64-hex format gate; their cause is not yet known.

Native Ctrl+C/Ctrl+V (and normal keyboard selection) are now permitted by that explicit
request. The script does not proactively read/write/clear the clipboard, access a
vault, export a key or send it anywhere. User-triggered native paste is the only
clipboard read. Clipboard history, cross-device sync and third-party clipboard
tools may retain/expose material; avoid them or review/clear their state manually.
Ordinary clearing is not guaranteed erasure. No screenshots, shell literals/history,
chat or plaintext export. Do not reveal the field on a shared/recorded screen.

Choose the real source explicitly; neither radio option is preselected:

- PHONE / independent retrieval: read from the phone. Any transfer/paste must
  genuinely originate from that independent route; its provenance remains an
  operator attestation, not an automatically verifiable claim.
- DESKTOP note: paste from the desktop note if needed for diagnosis. MATCH only
  proves equality, NOT phone/off-machine retrieval. Keep independent recovery BLOCKED.

Do not provide a master password, MFA or account recovery code. The original local
key file/viewer must never supply input for a claimed independent recovery.
Click Compare in memory. The field is cleared/remasked on success and cleared when
closing; no automatic clipboard manipulation is performed.
After the local MATCH message, close the window and report only MATCH/window closed.
Never send either the material or fingerprints. Do not delete the original key.

The receiver has no source-audit/backup command and never accesses Bitwarden APIs,
browser storage, extension state or application files. Unknown/Tk callback errors
have fixed non-secret messages. Host compromise,
screen capture, dumps/pagefile and secure memory erasure remain outside guarantees.

## Follow-up ONLY after MATCH and operator confirmation

1. Require a PHONE receipt with independent_route_verified=true, not a desktop
   diagnostic MATCH. Inspect the actual private receipt for the exact key/attempt, audit its ACL and
   original-file preservation. Do not confuse synthetic unit receipts with this event.
2. Run the existing Windows host read-only launcher with the existing ignored public
   CA bundle. It captures only allowlisted runtime parameters in memory and restores
   environment/logging. No dotenv/Bitwarden inspection, credentials in argv/files,
   TLS bypass, source modification or full object payload collection.
3. Confirm fresh complete root LIST/HEAD inventory, bounded JSON/range GET probes,
   before/after inventory and PostgreSQL/ClickHouse metadata fences, 22 build identities
   if still current, and both 43/106 and 9/281 contexts. Report observed counts/bytes,
   never substitute the historical 315-object baseline. 403 capability state is UNKNOWN.
4. Read-only audit K physical-device identity/health/NTFS/capacity, separation from
   C/F, archive/vault/record/key owner and protected ACLs, links/reparse points and
   current free space against `space_plan` of the fresh inventory.
5. Report readiness evidence and blockers; stop BEFORE create. A quiet collection
   window, fresh expected identity/inventory and separate live authorization remain
   necessary. No global atomic S3/metadata snapshot or USB/vault disaster immunity.

## Tests

`tests/test_s3_key_recovery.py` owns disposable synthetic temp keys only, blocks
network/Docker and never reads the actual production vault. It covers match and
wrong key, no original-input fallback, original retention/change detection, absent
attestations, malformed input/context, no receipt overwrite, unsafe ACL refusal,
masked-default GUI, reveal/hide/remask/clearing, native user-initiated paste,
honest phone-vs-desktop route evidence, secret-free errors/receipts and no backup.
Native Windows ACL/junction and existing recovery contracts remain required.

Local verification before opening the actual operator input window:

| Check | Result |
| --- | --- |
| Windows 3.12.10 phone-comparison/GUI simulations + actual ACL/junction suite | 16 PASS, no skips, 84.996s |
| Linux 3.10.12 / 3.12.14 full recovery and database compatibility, sockets blocked | 215 each, 7 Windows-only skips each |
| CI contracts / repository security contracts | 20 PASS / PASS |
| Explicit new/changed public-source secret-signature scan | PASS |
| Ruff / Windows compileall / Git diff checks | PASS |

The separate masked production input window was requested for the operator; no
production MATCH or receipt is assumed merely because that process starts. The
tests above used synthetic temp keys only. No fresh live source/media preflight
was executed before the manual comparison checkpoint. No commit/push.

2026-10-23 user-requested input UX revision: native Windows comparison/GUI suite
12 PASS (94.831s), followed by 2 latest-code desktop-evidence/visibility tests PASS;
Linux 3.10.12 and 3.12.14 each 218 recovery tests PASS (7 Windows-only skips).
Repository/CI contracts (20), Ruff, compileall and diff checks pass. These runs use
only synthetic test keys. The old input window was closed normally for the updated
GUI; no original key was replaced and no S3 preflight/backup was triggered.

## Completed live read-only acceptance (2026-10-23, Europe/Moscow)

This section supersedes the earlier pending-checkpoint descriptions, which remain
historical evidence. All source requests below followed the actual PHONE MATCH.

### Production key equivalence

- Private receipt attempt ID: `56845314e6744d67992cb872e64755ab`.
- Receipt time: `2026-10-22T22:28:11Z` (2026-10-23 01:28:11 MSK).
- Exact key ID/purpose/field set/attempt filename, MATCH, phone method/source and
  independent_route_verified=true were validated. Desktop-only evidence was not used.
- Receipt source is OPERATOR_ATTESTED_BITWARDEN_PHONE; no vault/browser/storage API
  access or forensic verification of the phone provenance occurred.
- Original 32-byte key remains present with one hardlink, correct owner and explicitly
  protected owner-only DACL. Register/receipt files pass the same protected-file audit.
  One original key file, one creation register and one MATCH receipt are present.
  No recovered-key copy, key deletion/regeneration or key/fingerprint output.
- Both known launcher/receiver processes are closed, matching the operator's reply.

### Fresh source/lineage audit

The existing `check_s3_host_readiness.py --check-source` completed with
PASS_HOST_READ_ONLY_AUDIT / PASS_READ_ONLY_DRY_RUN. Final local readiness checks
were completed by `2026-10-22T22:31:06Z` (2026-10-23 01:31:06 MSK).

| Layer | Objects | Bytes |
| --- | ---: | ---: |
| Bronze | 202 | 321,473,523 |
| Silver | 78 | 34,559,914 |
| Gold | 35 | 349,972 |
| Total | **315** | **356,383,409** |

- Source: `https://s3.ru-3.storage.selcloud.ru`, bucket
  `football-data-platform-dev-v1`, virtual addressing, verified TLS/hostname and
  existing host public CA. Ownership remains endpoint/bucket-bound; LIST did not
  expose an account-owner reference. No claim of independently verified account identity.
- 312 registered, 2 legacy and 1 test object remain observed/in scope.
  22 manifests, 22 published builds and 22 loaded builds reconcile with the
  PostgreSQL catalog/ClickHouse serving snapshot.
- World Cup 43/106: 64 matches; Bundesliga 9/281: 34 matches.
- Before/after full inventory and metadata digest fences PASS. Inventory SHA-256
  (NOT a key fingerprint):
  `1507a7676eed78b676ac8d82177fc451a4ca9a081f2aab5e5c6888abb2d931b6`.
- 630 HEAD, 3 LIST, 30 GET attempts, including 3 expected incorrect-validator 412s.
  Correct conditional probes pass for Bronze/Silver/Gold. Optional capability
  requests are additional to those adapter counters.
- Only **455,754 bytes** read: 24 small full lineage documents plus limited payload
  probes. No full Parquet GET or whole-bucket payload download. Full-byte SHA-256
  remains unverified for 291 objects, as expected for a read-only metadata preflight.
- Formats: 224 JSON, 47 Parquet, 22 directory markers, 22 extensionless markers.
  47 LIST/HEAD ETag differences remain observed; neither ETag is used as SHA-256.
- Versioning, Object Lock and ListObjectVersions each HTTP 403: **UNKNOWN / ACCESS
  DENIED**, not disabled or backed up. Historical-version recovery remains unverified.
- Temporary source variables were restored/removed, SDK session closed. A separate
  host presence-only check found all six S3/CA variables absent. Runtime credentials
  travelled only through the existing captured allowlisted pipe/process mechanism.

### Physical media, paths and capacity (read-only)

- K is Disk 4, StoreJet Transcend, USB, MBR, NTFS; disk and volume Healthy, online,
  not read-only. MediaType is reported **Unspecified**, not inferred as HDD/SSD.
  Disk size 1,000,204,886,016 bytes; volume size 1,000,202,039,296 bytes.
- C is Disk 1 and F is Disk 2 (NVMe SSD/GPT/NTFS). K is a separate physical disk.
- Current free K space: **131,061,084,160 bytes (122.06 GiB)**. Fresh source plan:
  archive upper bound 373,303,289 + reserve 93,325,823 = **466,629,112 bytes
  (445.01 MiB)** required; headroom 130,594,455,048 bytes. `check_space` PASS.
- The four existing archive/vault parent/leaf directories pass current safe-path,
  owner/protected-DACL and non-overlap checks. No symlink, reparse point or hardlink
  found in the checked paths/files. No existing ACL was modified.
- `K:\FootballPlatformBackups\s3` still has zero entries. Keys/register/receipt
  remain only in the private current-profile vault, outside Git/K.
- Host CPython 3.12.10 passes the existing runtime gate; boto3/cryptography present.
  No runtime/dependency/credential installation or change in this acceptance.

### Verdict and remaining boundary

**READY for A2.2 / a separately authorized first live attempt; execution remains
BLOCKED until that authorization and an actual quiet collection window. Stage 8C
remains PARTIAL.** The read-only launcher's generic backup_authorization=BLOCKED
is intentional: that helper never authorizes collection or independently evaluates
the separate key/media evidence. No gate/flag was changed to hide it.

Recheck fresh source identity/inventory, original key/receipt ACLs, medium identity,
capacity and quiet window at actual execution; a passed preflight can become stale.
No global atomic S3/PostgreSQL/ClickHouse snapshot is promised. Retain original key
and independent escrow mapping when the first actual session ID appears.

Independent S3 byte backup, actual archive verification/isolated restore, recovery
of vault/MFA after loss of all devices, runtime-secret restore and full machine-loss
recovery remain NOT VERIFIED. USB durability/BitLocker unlock recovery, ransomware,
theft, host/admin compromise and clipboard/history exposure remain separate risks.
The subsequent local checks passed repository/security contracts, 20 CI contracts,
ignore rules and Git diff checks. No new remote CI, commit/push or database drill.

## Repeated readiness audit and local source publication follow-up

On 2026-10-23 the operator requested another fresh read-only inventory/lineage
check, explicitly retained the existing MATCH/key and reconfirmed PHONE provenance.
The same original receipt/attempt was validated again; no new GUI, input, key or
MATCH event was created. Protected ACLs, the original 32-byte key's loader contract,
single-file link count and modification time not later than MATCH all pass.
The modification-time check is additional ordinary-change detection, not an
adversarial integrity proof or a persisted key fingerprint.

The repeated live audit again returned PASS_HOST_READ_ONLY_AUDIT and identical
315-object / 356,383,409-byte inventory and 22-build lineage. Both 43/106 (64) and
9/281 (34) remain present. Source is still the same endpoint/bucket resource ID;
TLS/host CA, virtual addressing, initial/final inventories and metadata fences pass.
Counts were observed again, not substituted from the prior run. This additional
audit read 455,754 bytes (24 small documents and probes; 630 HEAD / 3 LIST / 30 GET
attempts). No full object collection, S3 write, database restore or real archive.
47 LIST/HEAD ETag differences and 403/UNKNOWN optional capabilities remain unchanged.

K remains independent USB Disk 4 / NTFS / Healthy, separate from C Disk 1 and F Disk 2.
Four existing private directories, no links/reparse routing, three private vault
files, one original key and zero archive entries pass the repeated read-only audit.
Free K space is still 131,061,084,160 bytes versus 466,629,112 required. Host Python
3.12.10/dependencies pass; all six temporary source/CA variables are absent again.
Final live/media rechecks completed by `2026-10-22T22:39:23Z`
(2026-10-23 01:39:23 MSK). Readiness is READY; actual collection remains BLOCKED
pending its own explicit approval, quiet window and execution-time refresh.

For the separately authorized local commit, all A2.1/A2.2 sources, GUI scripts,
synthetic tests and runbooks are explicitly staged with README and completeness
contracts. The contract now requires the new public sources in the Git index and
rejects private vault/key/receipt paths. Existing synthetic CI discovery already
includes the new tests on Linux and Windows; no workflow gate was removed.
Keys, receipts, CA/venv, archives and runtime files are NOT staged. A local commit
does not publish this work or trigger a new GitHub CI run; push remains unauthorized.

The safe credential handoff tested here belongs to the bounded read-only launcher;
it intentionally leaves no host environment for a later `s3_backup.py create`.
Before actual collection the operator must approve/prepare a process-only handoff
for that separate gated command, without plaintext files, secret argv, logs or
unnecessary inheritance into metadata subprocesses. This follow-up did not add or
invoke a live-create credential wrapper. Read-only connectivity PASS is not proof
that an arbitrary subsequent shell already has the credentials needed by create.

Final source-publication checks ran from an isolated Git index snapshot containing
all 438 intended tracked files, not the working tree's ignored dependencies. The
existing recovery venv supplied only installed dependencies; imports/tests came
from that snapshot. Final report-only edits to this runbook do not alter tested
source/test/workflow bytes and are checked again before the local commit.

| Repeated local regression / publication check | Result |
| --- | --- |
| Native Windows CPython 3.12.10, full synthetic recovery/profile-v1 compatibility | **218 PASS**, no skips, 409.993s |
| Native owner/DACL/junction tests | All 7 PASS, included above |
| Linux 3.10.12 and 3.12.14 full recovery, network disabled | 218 each, 7 Windows-only skips each |
| Linux root regressions | 743 each, same 7 Windows-only skips |
| Application / CI contracts, both Linux versions | 30 / 21 each, PASS |
| Repository/private-artifact contracts and explicit public-source scan | PASS |
| Ruff / Linux and Windows compileall / actionlint / Git diff checks | PASS |

Tests use synthetic temp keys/fake transports only. The actual production key
was not supplied to a test/archive. The local commit contains public source/docs,
not the real key, private creation record, receipt, source credentials, CA bundle,
venv, S3 payloads, backup archives or database dumps. The existing requirements and
CI workflow gates remain unchanged; a new remote verdict requires a later push.

## Subsequent A2.3-F1 implementation

The missing process-only create bridge described above is addressed, with synthetic
tests only, in [A2.3-F1](stage8c-r2-4a2-3-f1.md). It adds an opt-in host route, not
backup authorization or a new live acceptance result. Stage 8C remains PARTIAL.
