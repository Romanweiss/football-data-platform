# Stage 9C.4-A: Current Competitions UI prototype

Checked: 2026-11-02 (Europe/Moscow). Source baseline:
`29c057ee165eaf89d334c143eb1e0761d31b103b`.

**Synthetic local prototype: READY. Live integration: NOT IMPLEMENTED.**
Persistent onboarding remains **BLOCKED / LEGAL_REVIEW_REQUIRED**; Stage 8C remains
**PARTIAL**. The earlier real reconciliation report is preserved, not used as UI data.

## Routes and navigation

- Host dev index: `http://127.0.0.1:15175/competitions/current`.
- Host dev league: `http://127.0.0.1:15175/competitions/current/uefa-champions-league/2026`.
- Fixtures example: append `?round=3`.
- Table example: append `?view=standings`.
- Shared navigation connects Current Competitions and Historical Match Lab.
- Existing numeric competition/season/match and legacy match URLs remain intact.
- Unsupported paths under `/competitions/current/` get a local unavailable view,
  not a historical API request or fabricated context.

The existing History API router is extended, without a new routing library.
`view`, `round`, `team`, `from`, `to` filters live in URL query parameters. Back,
Forward and refresh restore the selection. EN/RU/ES uses the existing language
provider/localStorage preference; current-section strings are in a separately typed
message catalog. Document titles follow the selected section and language.

## What the prototype does

- League overview, calendar and results; inclusive UTC date, matchday and team filters.
- FINISHED/TIMED labels; future scores stay null and display an em dash.
- Fixture counts are explicit, with no sampling or hidden pagination.
- A 36-team standings table exposes position, played, W/D/L, GF/GA/GD and points.
- Positions 1–8, 9–24 and 25–36 have text legends and colour accents.
- Keyboard tabs support Left/Right, Home/End, Enter/Space; selects stay native.
- The table is a named, keyboard-focusable scroll region. Horizontal scrolling
  exposes all statistics on mobile; team/position stay pinned. No fields are removed.
- Loading, safe error/retry, empty results and invalid/inverted date states exist.
- Changing team only filters table rows: original positions and statistics remain.
  Date/matchday filters apply **only to fixtures**, not to a historical standings view.
- No shot/pass/pressure/xG/player-event visualization or Match Lab analysis link is
  rendered for synthetic fixtures.

## Synthetic data and arithmetic

[Factory](../frontend/src/current/synthetic.ts) returns a fresh deterministic object
for each call, default seed 7; no network, random clock or provider payload is used.

| Property | Demo value |
| --- | --- |
| Participants | 36 invented `Demo · …` teams; IDs `demo-team-01` through `demo-team-36` |
| Fixtures | 144 unique synthetic fixture IDs; eight matchdays, 18 games each |
| Schedule | Eight distinct opponents/team; four home/four away; one game/team/round |
| FINISHED / TIMED | 54 / 90, from three deliberately finished demo matchdays |
| Standings | 36 entries calculated from FINISHED fixture scores only |
| Zones | 8 / 16 / 12 teams |
| Demo as-of | Fixed `2026-10-15T00:00:00Z`, not provider freshness |
| Scope | League phase only, not the complete competition |

The bipartite synthetic draw is invented; it does not model UEFA pots or country
restrictions. Demo sorting is points, GD, GF, then demo ID, **not official UEFA
tie-breakers**. This synthetic 54/90 split is factory configuration, not a new
observation or copy of the real season. No real club emblems, photos or remote
fonts/images are used; team badges are plain CSS/text identifiers.

Every page displays **DEMO DATA — SYNTHETIC**, translated into Russian and Spanish,
plus a plain explanation that scores/teams are invented. Table captions, team names,
methodology, fixed clock and footer reinforce this distinction.

## DTO and source boundary

[types.ts](../frontend/src/current/types.ts) defines provider-neutral frontend DTOs:

- `CurrentCompetition`, `CurrentSeason`, `CurrentParticipant`, `CurrentFixture`.
- `CurrentStanding`, including immutable displayed position and explicit zone.
- `CurrentFreshness`, `CurrentCoverage`, `CurrentCapabilities`.
- `CurrentCompetitionCard` and the bounded `CurrentLeague` envelope (`schemaVersion=1`).

The prototype contract deliberately requires `dataKind='synthetic'`, a fixed demo
clock, `sourceRevision=null`, and false event/xG/lineup/player-stat capabilities.
Its string IDs are separate from StatsBomb and provider registry identifiers.

[source.ts](../frontend/src/current/source.ts) implements the injectable
`CurrentSource.catalog(signal)` / `league(slug, year, signal)` interface entirely
locally. Components never normalize vendor payloads or call vendor APIs. Historical
API loading is disabled while the Current Competitions section is active.

The existing `useResource` full-key/AbortSignal guard rejects late completions,
including transports that ignore cancellation. Locale or client-side filter changes
do not restart the source. Deferred-source unit tests prove cancellation/stale
response isolation during navigation; no production test-mode query flags were added.

### Future Django serving contract — proposal only

Potential separately approved routes, **not implemented or called here**:

```text
GET /api/v1/current/competitions
GET /api/v1/current/competitions/{slug}/seasons/{start_year}
```

They would supply a catalog and one bounded, internally consistent league envelope:
competition/season, participants, fixtures, authoritative serving standings,
freshness, coverage, capabilities and provenance. A Django adapter would validate
untrusted JSON/schema version and map serving field naming at the source boundary;
the page would not need provider parsing or a major rewrite.

Before accepting non-demo data, explicitly extend the provenance contract and banner
policy rather than labelling live scores synthetic. Resolve licensing, persistent
identity/version adoption, serving authorization, pagination/limits, corrections and
freshness first. This UI prototype does not provide that API, storage or permission.

## Checks and browser evidence

- Frontend unit: **96 PASS**, including data arithmetic, routes, filters, empty/error
  states, safe retry, deferred responses, dictionaries and Match Lab regression.
- TypeScript and Vite production build: **PASS**; no new npm dependencies.
- Synthetic Chromium CI suite: **10 PASS**, desktop **1440×900** and mobile **390×844**.
- New current-section scenarios run axe WCAG 2 A/AA checks on both views: **zero
  violations**, no page-level horizontal overflow; mobile table scroll exposes points.
- Browser checks include Back/Forward, deep-link reload, EN/RU/ES persistence,
  results-only capability boundaries and return to a synthetic historical shootout.
- Existing Chromium Pass Map, Pressure Heatmap and canonical-context scenarios remain
  in the same suite. Existing unit tests cover Shot Map/xG/shootout state transitions.
- The browser records **zero API calls on current-section pages** and permits only its
  local preview origin. Historical regression responses are intercepted synthetic data.
- Repository/security contracts include source completeness, transport isolation,
  synthetic provenance, localization and CI test discovery.
- Python 3.12.14: **55 CI/security contracts and 61 application/API tests PASS**;
  repository checker, Ruff and compileall PASS. No backend behavior was changed.

Full-page screenshots are generated at the specified viewport sizes:

```text
frontend/test-results/current-competitions-synth-1c9ab-ty-and-Match-Lab-regression-desktop/current-fixtures.png
frontend/test-results/current-competitions-synth-1c9ab-ty-and-Match-Lab-regression-desktop/current-standings.png
frontend/test-results/current-competitions-synth-1c9ab-ty-and-Match-Lab-regression-mobile/current-fixtures.png
frontend/test-results/current-competitions-synth-1c9ab-ty-and-Match-Lab-regression-mobile/current-standings.png
```

These are local ignored test artifacts, not committed documentation assets. They
contain only synthetic data and are reproducible, not evidence of live integration.

```powershell
cd frontend
npm test
npm run build
npm run test:ci-browser
```

The fixture-browser command uses isolated preview port 15174, not production or
the developer backend. It includes the new scenario through the existing config.
The existing container at port 15173 has no source bind mount and still serves its
previous image. It was not recreated. The current source is served by a separate
host Vite process on **15175**, without replacing containers or rebuilding 18090.
No frontend environment files were present; the repository environment file is
outside Vite's frontend root and was not loaded. The host process uses the public
local historical API origin `http://127.0.0.1:18000`; Current Competitions itself
does not call it. To restart this host-only dev session if it is stopped:

```powershell
cd frontend
$currentUiPreviousTarget = [Environment]::GetEnvironmentVariable('API_PROXY_TARGET', 'Process')
try {
  [Environment]::SetEnvironmentVariable('API_PROXY_TARGET', 'http://127.0.0.1:18000', 'Process')
  npm run dev -- --host 127.0.0.1 --port 15175 --strictPort
} finally {
  [Environment]::SetEnvironmentVariable('API_PROXY_TARGET', $currentUiPreviousTarget, 'Process')
}
```

Host dev browser evidence is also captured in ignored local files
`frontend/test-results/current-dev-desktop.png` and
`frontend/test-results/current-dev-mobile.png`. It is separate from the fixture
preview suite above; do not mistake the old 15173 image for the new prototype.

## Scope and next step

No authenticated provider call, ingestion, migration, database/S3 write, Silver/Gold
build, production deployment, credential read or backup/recovery operation occurred.
At the A checkpoint no staging, commit or push was performed. The prior local
reconciliation document and unrelated shortcut remain unchanged.

Next minimal step is a separate synthetic UX/publication review: inspect evidence,
audit exact source completeness and run a clean-checkout snapshot before publishing.
Live integration requires its own licensing/persistence/serving gates. No Europa
League, Nations League, team/player profiles or advanced event analytics are added.

## Stage 9C.4-B publication review checkpoint

Reviewed: 2026-11-02 (Europe/Moscow). The exact baseline, cached `origin/master`
and fresh remote master matched. Direct Git DNS failed; a read-only remote check
through the existing local system proxy succeeded. Its process-only environment
was restored; no system/Git proxy or DNS configuration changed.

The review found one small usability issue: breadcrumb height 16 px and filter
controls 40 px were smaller than the chosen 44 px touch target. Prototype-scoped
CSS raises breadcrumb, navigation, filter/retry/reset controls, brand/language and
method disclosure targets to at least 44 px. A real mobile Chromium assertion
guards their sizes; historical Match Lab controls are not restyled.

A second visual issue was confirmed at 390 px: automatic table sizing made the
sticky team column 266 px, leaving only 17.5 px for visible statistics. A fixed
table layout with a 180 px team column keeps more than 80 px available to numeric
columns, while retaining team/position pinning and all fields. Mobile Chromium
checks this usable width as well as keyboard scrolling and Points visibility.

Desktop hierarchy, date grouping, filters, table zones and contrast were reviewed.
Mobile keeps page-level overflow at zero, provides a horizontal-scroll hint and
pins team/position within the named scroll region; all numerical fields remain
available. ArrowRight and scrolling to Points are tested. Both EN/RU/ES demo
markers and invalid-filter/unknown-route behavior are covered. Axe/accessible-name
and keyboard checks are not a substitute for manual NVDA/VoiceOver testing, which
was not performed.

The intended publication bundle is the 16 A source/test/runbook files plus the
non-secret [real reconciliation report](stage9c3-real-reconciliation.md): **17 files**.
The report contains aggregate counts, timestamps, fingerprints and fixed codes,
not raw authenticated payloads or secret material. Images, probe scripts, local
dependencies, runtime files and the shortcut are outside the staged source bundle.
No commit, push or deployment is authorized by this checkpoint.
