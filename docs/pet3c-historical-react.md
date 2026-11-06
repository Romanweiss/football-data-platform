# PET-3C — Historical UEFA Champions League React integration

Implementation baseline: `8248abcd7de36abf4d3794c8058e3884b18e4583`.
Local development only; not deployed or committed. Publication review uses a separate temporary index; the main licensing index is not changed.
Stage 8C: PARTIAL. football-data.org persistent onboarding remains separately blocked.

## Routes and navigation

- `/competitions/historical`: same-origin historical dataset catalog.
- `/competitions/historical/uefa-champions-league/2024`: OpenFootball 2024/25 results-only page.
- Existing `/competitions/current/uefa-champions-league/2026` remains **DEMO DATA — SYNTHETIC**.
- Existing numeric StatsBomb Match Lab URLs are unchanged.

Workspace navigation and the current-competitions catalog link to the historical catalog without loading historical API data on synthetic routes. No public provider API is called by the browser.

## API integration and bounds

The separate `HistoricalSource` / DTO adapter reads published [PET-3B contracts](pet3b-historical-api.md), not the synthetic `CurrentLeague` DTO.
All requests use same-origin `/api/v1/competitions/historical`, reject redirects, request JSON, disable cache and accept an AbortSignal. Response bodies are streamed with a 1 MiB bound; rows are limited to 100. Invalid important fields, pagination, IDs, scores, duplicate fixtures or mixed provenance fail closed with a generic diagnostic.

The season loads overview, participants (limit 100) and coverage (limit 100) in three fixed requests. Metadata must be complete in those bounded pages and reconcile counts and provenance. The fixtures tab then loads **one** page (default 50, selectable 25/50/100). Quality is fetched only when selected, also one page at a time. No request per fixture or unbounded page-loading loop.

Published API detail: `/coverage` uses `coverage` for its row array, replacing the envelope metadata object of the same name. Its DTO models that actual response explicitly. Coverage badges come from the validated overview; identity/provenance and aggregate metadata counts are fenced across responses. This is not an API schema change.

`team_id`, `stage_id`, `round_id`, `view`, `limit` and `offset` live in the URL. IDs are provider-neutral `uefa:<kind>:<64 hex>`, never StatsBomb IDs. Duplicate, unrecognized, invalid or mutually inconsistent URL filters produce an explicit 400-style state. Stage changes clear the dependent round; other filter/view changes reset offset. Pagination uses the server's `next_offset`; displayed totals distinguish page rows from all matching source records.

## Source semantics and capability boundaries

Pinned source: OpenFootball `2024-25/uefa.cl.json`, commit `e6744429ee395bc86f247348c6184bb08d4eb361`, CC0-1.0.

| Property | Validated pinned dataset |
| --- | ---: |
| Fixtures / participants | 189 / 36 |
| Stage-round groups / stages | 14 / 3 |
| Source-reported FT / UNKNOWN result | 188 / 1 |
| Ambiguous ET/penalty fixtures | 2 |
| NON_FATAL DQ records | 394 |

The UI says **OpenFootball / HISTORICAL / 2024/25 / INCOMPLETE / RESULTS ONLY** (localized EN/RU/ES). Coverage remains source `UNKNOWN`, results `INCOMPLETE`, not a complete official UEFA competition claim.

- FT is **source-reported**, not verified regulation or confirmed 90-minute score.
- The unscored final remains UNKNOWN with dashes, not 0:0 or a score inferred from external knowledge. Unknown is not silently treated as scheduled.
- Original HT/FT/ET/P components are available in fixture details. Ambiguous ET/penalties do not produce canonical outcomes or winners.
- Match date is shown as a date only; UTC kickoff and observation time remain unknown.
- No inferred winners, points, standings, rankings, xG, shots, passes, player analytics or event-map links.
- `?view=standings` opens a capability explanation, not a fabricated standings table. Other unsupported query values fail closed.
- Participant navigation is alphabetical, not a ranking. Quality counters cover all matching rows; details remain paginated.
- Provenance includes upstream path/commit, source SHA-256, normalized fingerprint, batch and license; no credentials or private runtime paths.

Source SHA-256: `12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6`.
ETL batch: `ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc`.
Normalized fingerprint: `2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b`.

## Failure behavior and UX

Loading, empty, retry, malformed-response and invalid-URL states are explicit. HTTP 400, 404 and 503 have distinct localized explanations; 503 says “Historical dataset is not available in this environment.” No native backend errors or response bodies are exposed and there is no synthetic fallback. The default-disabled historical backend may correctly return 503 outside the isolated preview.

Resource keys include the full selection and pinned batch. Cleanup aborts old requests; late completions are ignored even if a transport disregards cancellation. New filters immediately stop displaying the old page. Back/Forward, direct URLs and reload restore selection. Tabs support arrows/Home/End, native selects support the keyboard, focus is visible and content is responsive without horizontal page overflow. Historical buttons have minimum 44×44 CSS-pixel targets. Pagination and participant/fixture-team navigation move focus into the persistent results panel rather than leaving it on a removed button or `body`; filter selects retain their focus.

## Local verification and screenshots

Verified locally on 2026-11-06. Synthetic test responses are deterministic artificial schedules, not copied upstream payloads and not a production source. They preserve the 189/36/394 shape solely to exercise API/UI reconciliation.

| Check | Result |
| --- | --- |
| Frontend unit | 119/119, including 23 historical adapter/UI tests |
| TypeScript / production asset build | PASS (build only, no deployment) |
| Synthetic Chromium desktop/mobile | 16/16, including six historical cases, axe, history/reload, EN/RU/ES, network errors, touch targets and stale responses |
| Real-Gold Chromium desktop/mobile | 2/2, actual published Django reader against isolated Gold |
| API/application regression | 79/79 on Python 3.10.12 and 3.12.14 |
| CI/documentation/security contracts | 78/78 on both Python versions |
| Full offline Python suite, 3.12.14 | 1089 run: 1080 passed, nine Windows-only cases skipped on Linux, not claimed as executed |
| Ruff / compileall / repository checks | PASS; cache and bytecode directed to disposable container `/tmp`, not source files |
| actionlint / public-placeholder Compose / diff checks | PASS |

The real-browser check read all four bounded fixture pages: 189 unique IDs, one missing result, two ambiguous fixtures, no overlap or omission. It also checked 144 league-phase records, participant/team navigation, 394 DQ records, source hash/batch, unknown final with four unknown score components, lack of fabricated standings, accessibility and localization. The first browser runs exposed an exact-label selector issue in the new test and a too-short default assertion deadline for the local relay; selectors now use accessible combobox roles. Only the opt-in local real-Gold config has a longer deadline. Synthetic CI retries remain zero and its 30-second test limit is unchanged. No backend contract was relaxed.

Local screenshots (ignored artifacts, not committed):

- `frontend/test-results/pet3c/desktop.png`: actual historical Gold overview and source-reported results.
- `frontend/test-results/pet3c/mobile.png`: actual responsive historical overview.
- `frontend/test-results/pet3c/mobile-unknown.png`: actual unknown final, no inferred result.
- `frontend/test-results/historical-synthetic-conte-*/historical-mocked-*.png`: explicitly artificial API-response screenshots from CI browser tests.

No screenshot is a claim of production deployment.

### Isolated preview used for acceptance

Dev page: `http://127.0.0.1:15176/competitions/historical/uefa-champions-league/2024`.

The local preview uses a new owned ClickHouse with tmpfs-only storage loaded from verified **existing** Gold, not a repeat of Bronze/Spark ingestion. Its `historical_reader` has SELECT-only grants and `readonly=1`. A separate Django container runs the unchanged published reader. Both use a newly created internal-only network, not any production network. Only `application/` and `src/` are mounted into the API, read-only; repository credentials and datasets are not mounted into that client.

Docker Desktop did not expose the API port on that internal-only network. Rather than attach it to a production or internet-enabled network, a temporary loopback GET-only relay forwards allowlisted historical paths into the owned API via `docker exec`. It does not alter Django responses or read production connections. Vite proxies same-origin `/api` to that relay. Its extra process-launch latency is not representative of a future normal serving deployment. All browser traffic remained loopback/same-origin; no OpenFootball or football-data.org HTTP request was made.

The two preparation helpers and non-secret resource receipt are local ignored files under `.tmp/pet3c*`, not publication files or required for synthetic CI. The preview is ephemeral: it is not a durable data service and is unavailable after its local processes/containers stop. Preparing a replacement requires verifying an isolated reader as described in [PET-3B](pet3b-historical-api.md), not falling back to production. Shut down only the receipt-identified PET-3C resources after use; do not stop the original PET-3A server or any Compose service.

Commands from `frontend/`:

```powershell
npm test
npm run build
npm run test:ci-browser
```

Optional real-Gold acceptance requires a separately prepared isolated Django reader; it does not start ingestion or deploy anything:

```powershell
$env:PET3C_ISOLATED_BROWSER = 'true'
npm exec playwright test -- --config playwright.historical.config.ts
Remove-Item Env:PET3C_ISOLATED_BROWSER
```

The opt-in browser config targets only `127.0.0.1:15176`; its spec is outside the default synthetic CI browser selection. No real dataset or raw response is needed for checkout-based CI. Screenshots are generated under ignored `frontend/test-results/`, not published assets or evidence of production deployment.

## Implementation file list and Git preservation

19 PET-3C files (five existing modified files, 14 new files):

```text
docs/pet3c-historical-react.md
frontend/playwright.ci.config.ts
frontend/playwright.historical.config.ts
frontend/tsconfig.json
frontend/src/App.tsx
frontend/src/current/CurrentCompetitions.tsx
frontend/src/historical/HistoricalCompetitions.tsx
frontend/src/historical/filters.ts
frontend/src/historical/historical.css
frontend/src/historical/messages.ts
frontend/src/historical/source.ts
frontend/src/historical/types.ts
frontend/src/routes.ts
frontend/tests/historical-fixtures.ts
frontend/tests/historical-live.spec.ts
frontend/tests/historical-source.test.ts
frontend/tests/historical.test.tsx
frontend/tests/smoke/historical.spec.ts
tests/ci/test_historical_react.py
```

No main-index staging, commit or push was performed. Publication review prepares only these 19 files in a separate temporary index and checks out its exact proposed tree into an isolated clone. The pre-existing licensing index tree remains `43b31d88dcecbf505b92ad6a754dee84371eef77`, with the same two staged document blobs. Their working-tree hashes and the planning document hashes were preserved. The unrelated shortcut remains untracked. Local `.tmp/pet3c*` helpers/receipts and screenshots are ignored, not publication dependencies.

### Publication review findings

Chromium review confirmed two small accessibility defects in the initial implementation: fixture-team buttons were about 26 px high (reset/pagination buttons 43 px), and pagination removed the focused button, returning focus to `body`. The scoped minimum target size and persistent-panel focus changes above fix both, without changing API/backend contracts or football semantics. Regression tests cover keyboard pagination/participant navigation, real element sizes, network-error retry, metadata cancellation when leaving history, streaming response-size limits and inconsistent score/filter responses.

Review viewports are exactly 1440×900 desktop and 390×844 mobile, including the opt-in real-Gold config. Review also found that the new gated Playwright config was outside the existing TypeScript include list; `frontend/tsconfig.json` now includes it, with a CI contract protecting that inclusion. No new workflow is needed: existing unit, build/typecheck, Chromium and Python CI jobs discover these tests. The clean snapshot installs frontend dependencies from the lockfile; it excludes source datasets, `.env`, venv/node_modules, screenshots, relay helpers and preview servers. Default CI still runs only artificial HTTP responses, including historical tests, using its own fresh local asset preview. The separately gated real-Gold check requires the explicit isolated runtime prerequisite; its absence never causes a synthetic fallback or a claim of live verification.

## Limits and next step

The page is a controlled historical source-only browser, not a live season product or a complete competition reconstruction. Runtime data availability is an explicit serving prerequisite; this stage does not add a production historical reader, migrate schemas, re-run PET-3A ingestion, or call football-data.org. Existing S3, PostgreSQL, production ClickHouse, Airflow, backups and recovery keys are outside scope.

Next: independent publication review of the frontend/API-contract snapshot, followed by separate authorization for publication. A later controlled serving deployment needs its own isolated/production connection review, immutable dataset availability, read-only identity, rollout and rollback plan. Do not repoint the current production reader or enable live onboarding implicitly.
