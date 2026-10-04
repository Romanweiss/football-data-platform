# Stage 6B-2 — Second-context onboarding attempt

Attempt date: 2026-10-04 (Europe/Moscow).
Status: **Source connectivity diagnosed and strict container preflight PASS.**
Onboarding remains paused before any remote writes; Stage 6B-2 is not complete.

The Stage 6B-1 runbook was read before execution. The target supplied by the task
is competition `9`, season `281`: the previously inspected Bundesliga 2023/2024
subset of 34 Bayer Leverkusen matches. The original attempt used prior expectations
from [Stage 6B-1](stage6b1.md); the follow-up below reconfirms the authoritative
identity and complete available source inventory from the pipeline container.

## Original source preflight failure

The exact documented command ran inside the intended Python pipeline container:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_statsbomb_source.py --competition-id 9 --season-id 281
```

Exit code: `1`.
Safe diagnostic:

```text
Public source preflight failed: exception=URLError
```

`URLError` is the reported source-access failure class. The formatter does not
expose its nested cause, so this run does not establish whether the cause was
TLS, DNS, a connection failure or another URL transport error. No raw exception
text or credentials were printed. TLS verification was not changed or bypassed.

The original task required immediate STOP if this preflight failed. That attempt
stopped without retries, source substitution or later onboarding steps. The next
task explicitly authorized diagnosis and a bounded preflight transport fix.

## Connectivity diagnosis

All diagnostics used the same `football-python-tools` service/image as ingestion,
with verified TLS and without persistent source downloads or database/S3 clients.

The actual script uses Python standard-library `urllib.request.urlopen`:
GET catalog/matches goes through `src/common/http.py:download_bytes`, while child
availability uses HEAD in `scripts/check_statsbomb_source.py`. Both use a 30-second
socket-operation timeout, not an overall preflight deadline. urllib's standard
redirect handling remains enabled. HEAD checks run with four worker threads.
The canonical URL is already `hudl/open-data`; no source URL/identity changed.

The historical log cannot establish the exact failed URL retrospectively. An
instrumented reproduction exposed these concrete failures:

| Method | Exact failing URL | Hostname | Safe reason |
| --- | --- | --- | --- |
| HEAD | `https://raw.githubusercontent.com/hudl/open-data/master/data/events/3895292.json` | `raw.githubusercontent.com` | `URLError.reason=SSLEOFError`, `UNEXPECTED_EOF_WHILE_READING` |
| HEAD | `https://raw.githubusercontent.com/hudl/open-data/master/data/events/3895134.json` | `raw.githubusercontent.com` | `URLError.reason=SSLEOFError`, `UNEXPECTED_EOF_WHILE_READING` |

The observed failure is an intermittent premature TLS connection close on the
container's outbound source requests. It is not an observed certificate-validation
or DNS error. The evidence does not identify which upstream peer/network component
closes the connection, so attributing it specifically to GitHub, Docker or a VPN
would be unsupported. No global DNS/network/proxy settings were changed.

Host/container comparison:

- Windows GET to the exact catalog and matches URLs: HTTP 200, respectively 34887
  and 63079 response bytes. Windows HEAD to both reproduced child URLs: HTTP 200.
- Container Python GET to the same catalog/matches URLs: HTTP 200; 256-byte samples
  read in memory; no redirect for either request. Both simple HTTPS probes pass,
  while the original full project preflight fails intermittently on child HEAD.
- Container `socket.getaddrinfo` succeeds for `raw.githubusercontent.com`
  (185.199.108.133 through 185.199.111.133) and `github.com` (140.82.121.3).
  No DNS failure warranted changing Docker DNS or reading unrelated network config.
- Container OpenSSL: `OpenSSL 3.0.20 7 Apr 2026`; default Python context has
  `CERT_REQUIRED` and `check_hostname=True`. Default CA paths are
  `/usr/lib/ssl/cert.pem` and `/usr/lib/ssl/certs`; the OS bundle
  `/etc/ssl/certs/ca-certificates.crt` exists. certifi is installed at
  `/usr/local/lib/python3.12/site-packages/certifi/cacert.pem`; urllib uses its
  normal Python/OpenSSL trust configuration, not a newly selected certifi override.
- The existing `python:3.12.14-slim-bookworm` Dockerfile installs OS
  `ca-certificates` and GlobalSign Root R6. No image rebuild or CA change was needed.
- HTTP_PROXY/HTTPS_PROXY/NO_PROXY and lowercase counterparts are all unset on host
  and container. Container `urllib.request.getproxies()` is empty; host Python's
  urllib discovers `ftp/http/https` proxy entries despite those environment variables
  being unset. Thus host urllib has OS-level proxy discovery absent in the container;
  identical routing cannot be assumed. Proxy values/credentials were not printed
  or copied into Docker. This difference alone does not prove the cause of TLS EOF.

## Targeted fix and strictness

Only `scripts/check_statsbomb_source.py` changed at runtime:

- GET and HEAD preflight requests now have at most three attempts with 1s/2s
  exponential backoff, each retaining the original 30-second timeout/default TLS.
- Retries apply to TLS EOF, timeout/reset/aborted/broken connections, incomplete
  responses, temporary DNS (`EAI_AGAIN`), and HTTP 429/500/502/503/504.
- Certificate verification failures, other TLS protocol errors, permanent DNS,
  HTTP 404/other permanent status, invalid content and catalog/context mismatches
  are not retried. Source parsing/identity checks still run outside the retry loop.
- Failure/retry output includes method, public URL/hostname, exception/reason
  classes, safe category and attempt count. URL userinfo/query/fragment and
  arbitrary exception text are excluded. Wrapped downloader causes are unwrapped.
- The catalog, matches membership and every required events/lineups HEAD check
  remain mandatory. Exhausted failures still produce a nonzero exit code.

This is preflight-only transport handling. Bronze downloader behavior, source
identities, existing WC2022 lineage, data architecture and Docker configuration
remain unchanged.

## Successful original-command rerun

The exact command from the original runbook was rerun after the fix:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_statsbomb_source.py --competition-id 9 --season-id 281
```

Exit code: **0**. Actual authoritative output:

```text
competition_id: 9
season_id: 281
competition_name: 1. Bundesliga
season_name: 2023/2024
match_count: 34
team_count: 18
events_available: 34
lineups_available: 34
catalog_sha256: e6cd42f5d8956d6aa30fb917ce8d4c3b3df1879a93f02f8feba820930a6971fa
matches_sha256: 13dff90f126d9f73da410ae3292b2773744657d3ba968a2b7a9c02135033581c
```

The hashes agree with the prior inspected source evidence. Four child HEADs
(`lineups/3895320.json`, `events/3895340.json`, `events/3895134.json`,
`events/3895258.json`) reported TLS EOF on attempt 1 and succeeded on attempt 2.
All 68 required child checks completed; no failure was ignored or substituted.
TLS certificate and hostname verification remained enabled throughout.

## Focused verification

New `tests/test_statsbomb_source_preflight.py`: 10 focused tests passed, covering
retry classification/backoff/exhaustion, certificate/404/content/context rejection,
safe diagnostics, complete child inventory and unchanged default-TLS HEAD behavior.
The existing inexpensive offline suite also passed: **438 tests**. No Spark,
serving load or expensive pipeline run was needed for this transport-only fix.

```powershell
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_statsbomb_source_preflight.py'
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
docker compose run --rm --no-deps football-python-tools python -m compileall -q scripts/check_statsbomb_source.py tests/test_statsbomb_source_preflight.py
docker compose config -q
git diff --check
```

All listed checks passed. Changed files: the preflight script, its focused tests
and this report. README remains unchanged because live data state did not change.

## Execution and partial state

- No S3 publication or object mutation was attempted.
- No PostgreSQL registration or ClickHouse load/DDL was attempted.
- WC2022 baseline capture, Bronze ingestion/validation, Silver and Gold builds,
  load preflights, real loads and idempotency reruns were not started.
- No new Silver/Gold build IDs, row counts or metric totals were produced.
- Two-context serving, WC before/after comparisons, API/frontend acceptance and
  the Superset dashboard semantic audit remain unexecuted.
- The original STOP attempt did not run the broader test suite. The authorized
  connectivity follow-up ran only the tests/static checks listed above.
- No secrets files were opened; no commit, push, destructive database operation
  or Docker cleanup was performed.

There are no new ingestion/build/load artifacts from this attempt. Existing
remote data state was not inspected after the stop; no claim is made about
artifacts potentially created by other runs. README is unchanged because this
attempt did not change the platform's live data state.

## Resume point

The container source preflight now passes. At the user's requested boundary,
execution stops before ingestion and returns control. No architectural/source
identity change was required. Intermittent transport errors remain possible;
bounded retries improve tolerance but do not guarantee future network availability.

When Stage 6B-2 is resumed, begin with the same exact preflight command above to
establish current source availability. After its PASS, the next read-only baseline
command is:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_match_visuals.py
```

Capture WC catalog/served build IDs and API baseline as specified in Stage 6B-1
before continuing A–M with exact pins. No ingestion command was executed by this
connectivity follow-up.
