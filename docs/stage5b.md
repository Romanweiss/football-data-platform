# Stage 5B — React Match Analysis

Local frontend foundation, **not production deployment**. Superset remains the
BI/exploration layer; React is the application interface. No backend contract,
ClickHouse view, Gold dataset or analytical metric was changed.

## Inspection and API boundary

No frontend/package.json/Vite scaffold existed. Inspected Compose/networking,
Stage 5A code/docs, git/Docker ignores and actual live JSON before implementation.
DESCRIBE confirmed nullable winner ID/name, shot player ID/name, outcome name and
coordinates. Squad player fields are non-null in this serving contract. The
frontend interfaces reflect these distinctions instead of guessing response fields.

Browser -> same-origin `/api/v1/...` -> Vite dev proxy -> `football-api:8000` ->
existing ClickHouse BI views. React has no database client, SQL or credentials.
The browser never contacts ClickHouse, S3, PostgreSQL or an external data source.

Only two data requests are needed for a fresh page:

1. `/api/v1/competitions/43/seasons/106/matches` -> `{matches: [...]}`.
2. `/api/v1/matches/<id>/analysis` -> `{match, teams, players, shots, xg_race, shootout}`.

Changing match performs one composite request. Team filtering in the player table
is local. Each request owns an AbortController; effect cleanup aborts it and the
completion handler checks the signal before committing state. The displayed
resource is keyed by match ID so old data cannot appear under a new URL, even
before the next effect runs. Tests simulate a transport that ignores cancellation.

`api.ts` validates runtime object/array/nullable types, finite numbers and safe
integer IDs. It rejects wrong composite identity, missing teams and period-5
normal shot/race rows. It does not recreate backend DQ or calculate football
metrics. Error bodies are not shown verbatim to users.

## Stack, files and components

Runtime dependencies: React/React DOM 19.3.0 only. Development: TypeScript 7.0.2,
Vite 8.3.2 + React plugin, Vitest 5.0.3, Testing Library, jsdom 29.1.1,
Playwright and type declarations. Direct pins and `frontend/package-lock.json`
provide repeatable npm ci. jsdom 29 supports the existing Node 24.13.0 runtime;
the newer jsdom 30 requires a newer Node minor and is not selected.

No router library was needed for two route patterns. No chart library, Redux,
Tailwind, UI framework, SSR, auth or backend dependency was added.

```text
frontend/
  src/
    App.tsx                 routing, request lifecycle, composition
    api.ts                  relative HTTP calls and runtime validation
    types.ts                explicit Stage 5A interfaces
    visuals.ts              pure geometry/formatting/sorting
    styles.css              responsive dark layout; no external fonts/assets
    components/
      MatchSelector
      MatchHeader
      TeamComparison
      XgRace
      ShotMap
      PlayerTable
      ShootoutPanel
      States                LoadingState / ErrorState
  tests/                    synthetic API-shaped fixtures + offline tests
    smoke/live.spec.ts      explicit browser/live API checks
  vite.config.ts
  playwright.config.ts
  tsconfig.json
  package.json / package-lock.json
  index.html
docker/web/Dockerfile
```

Also updated Compose, .env.example (port only), README and ignores. node_modules,
dist, browser reports/screenshots and frontend-local environment files are
ignored. Docker context additionally excludes keys.txt; its contents were not read.

## Routing and states

`/` selects the first match in the API's deterministic chronological order using
replaceState; Argentina–France is not hardcoded as application state.
`/matches/<id>` is a shareable/deep-link URL. The native match selector displays
match_label; selection uses pushState and popstate restores Back/Forward.
Vite SPA fallback supports refresh/deep links. Invalid routes/IDs show not-found
UI. Production hosting must supply the same SPA fallback for non-API routes.

Loading is explicit and announced with role=status. 404 shows “Match not found”;
503 shows “Data service temporarily unavailable”; network, invalid-response and
other failures show a generic retry state. A failed list has its own retry;
failed match analysis retries just that resource. An empty match list is explicit.
The development proxy also converts upstream connection failure into safe JSON
503. No raw JSON, SQL or stack traces are rendered.

## Display semantics

MatchHeader uses API display_score/result_method verbatim (only underscores in
the latter become spaces). No winner or score reconstruction. TeamComparison
shows supplied goals, shots, xG, pass attempts, under-pressure and counterpress
counts. Player rows retain zero-activity squad members and sort by shot_xg DESC,
shot_count DESC, event_count DESC, then team/player IDs for deterministic ties.

Formatting is centralized: xG two decimals, counts integer text, source dates
formatted in UTC without changing the calendar date, seconds zero-padded.
Formatting does not round the stored numbers used for SVG geometry. Colors are
home teal `#64d9c0` and away amber `#ffb46b` everywhere, never inferred from nation.
Legends identify teams, race lines also use solid/dashed strokes, goals use white
rings and shootout outcomes use text/symbols as well as color.

## SVG pitch: verified geometry and exact transform

Source geometry was checked against the provider's
[StatsBomb specification, Appendix 2](https://github.com/statsbomb/open-data/blob/master/doc/StatsBomb%20Open%20Data%20Specification%20v1.1.pdf):
grid 120 by 80, top-left origin, Y increasing downward; halfway x=60; attacking
penalty area x=102..120/y=18..62; six-yard box x=114..120/y=30..50; goal opening
x=120/y=36..44; penalty spot (108,40). This is a normalized source grid, not a
claim that every stadium has those physical dimensions. The radius-10 penalty
arc is consistent with the source's yard-style layout and the
[IFAB field markings](https://theifab.com/laws/latest/the-field-of-play/#the-penalty-area).
Its visible outside-box segment intersects x=102 at y=32 and y=48. The goal's
two-unit net depth is schematic decoration, not a source event coordinate.

Existing Stage 4E evidence and a fresh API inspection of all **1453 normal shots
across 64 matches** found x=59..120, y=0.7..79.2, no missing starts and no period 5.
Two shots start left of x=60. Therefore the visual shows the attacking half plus
a narrow **x=55..60 context strip**, rather than silently discarding them. The
halfway line remains at x=60. These current source values support a common goal
at x=120 without team/period-specific reorientation; no team-name inference.

The SVG viewBox is `0 0 370 432`. For each valid displayed shot:

```text
x_svg = 16 + (start_x - 55) * 5
y_svg = 16 + start_y * 5
```

The pitch lines use precisely the same translation/scale. Both axes scale equally;
SVG preserves aspect ratio on resize. **Neither X nor Y is inverted.** Source
Y-down already matches SVG's Y-down convention. Raw backend coordinates remain
untouched. Null, non-finite or outside-display coordinates are not clipped or
replaced; the panel reports how many shots could not be plotted. None are omitted
for the current tournament.

Marker radius (SVG units) is `3 + 8 * sqrt(clamp(xG, 0, 1))`: minimum 3, maximum
11. This is a bounded visual size encoding, not an exact xG-proportional area
claim. A white ring distinguishes goals. Hover, keyboard focus, Enter/Space or
tap reveals player, team, minute:second, xG, outcome and human-readable shot_label;
UUID is only a React identity, not the visible primary text. Missing nullable
names use explicit display fallbacks. Escape dismisses the detail. The detail
area is announced for keyboard users. Overlapping shots are not jittered.

## SVG xG race and shootout

Race consumes the supplied long-form states. Within each team, points are sorted
by event_order. SVG path starts at the first actual state, then uses `H` to the
next event_order and `V` to its supplied cumulative_xg. No interpolation, no xG
summation, no fabricated kickoff/end anchors. X is explicitly **ordered normal
shots, not elapsed minutes**. Source periods 1–4 include extra time; period 5 is
rejected at the boundary. Each legend displays that team's last supplied state.
Axes, final values, two-team legend and responsive viewBox are included.

ShootoutPanel returns null when went_to_penalties is false. Otherwise it orders
attempts by shootout_order and displays supplied player/team/outcome/running
home-away score. Goal, Saved and missed outcomes are visually/textually distinct.
No winning team or final result is inferred from attempts.

## Development networking and exact PowerShell commands

`football-web` uses Node 24.13.0, runs as user node, and copies only frontend files.
Host port **127.0.0.1:15173 -> 5173**, configurable with WEB_HOST_PORT. It was free
before startup. No whole-repository bind mount and no credentials/env_file are
passed. The only server-side setting is API_PROXY_TARGET; it is not VITE_* and
does not enter the browser bundle. The Vite file-serving allowlist is the frontend
directory, never its parent. No root .env is loaded by the frontend.

The [Vite proxy](https://vite.dev/config/server-options#server-proxy) preserves
`/api` paths and changes the upstream Host to football-api:8000 for Django's
existing ALLOWED_HOSTS. No django-cors-headers or wildcard CORS. Vite's normal
development HMR transport is tooling only; no application WebSocket feature was
added. This Vite dev server is not a production hosting configuration.

With existing ClickHouse running:

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose config -q
docker compose build football-api football-web
docker compose up -d --no-deps football-api football-web

# Open: http://127.0.0.1:15173/
# Deep link: http://127.0.0.1:15173/matches/3869685
Invoke-RestMethod http://127.0.0.1:15173/api/v1/health
docker compose logs football-web
docker compose logs football-api
```

The task reused the already-running API and started only football-web. Both are
left available for manual review; other existing services were not recreated.
The image copies source at build time: after source edits, rebuild and restart
only football-web. For host-side hot reload instead (Node 24):

```powershell
Set-Location F:\Learning_projects\football-data-platform\frontend
npm.cmd ci --no-audit --no-fund
$env:API_PROXY_TARGET = 'http://127.0.0.1:18000'
npm.cmd run dev -- --host 127.0.0.1
# Host-side URL: http://127.0.0.1:5173/
```

## Tests and live smoke

Tests need no internet after dependency/image installation. Fixtures are small
synthetic data with inspected API shapes, clearly not complete real matches.
No test fetches StatsBomb/S3. Browser live tests are a separate explicit command.

```powershell
Set-Location F:\Learning_projects\football-data-platform
docker compose run --rm --no-deps football-web npm test
docker compose run --rm --no-deps football-web npm run build
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'test_*.py'
docker compose run --rm --no-deps football-api python scripts/check_application_api.py
docker compose config -q
git diff --check

Set-Location .\frontend
npm.cmd ci --no-audit --no-fund
npm.cmd test
npm.cmd run build
npm.cmd run test:smoke
```

Windows smoke tests default to the existing installed Edge (`msedge`), headless.
No browser download was needed here. Elsewhere, install a supported browser once
and select PLAYWRIGHT_CHANNEL as appropriate; the web image intentionally does
not contain a browser. WEB_BASE_URL can override the test origin. Playwright
does not start services implicitly and only the local frontend/API are used.

Verified results:

- **26 frontend unit/component tests PASS**, on Windows and in the web container:
  parsing/nullability, transforms, marker sizes, step paths, formatting/sorting,
  selector/history, cancellation/late responses, filtering, shootout visibility,
  focus details and loading/404/503/generic-error states.
- TypeScript strict check and Vite build PASS on host and in Docker.
- **2 real-browser smoke tests PASS**, including all four requested matches:
  Argentina–France, Netherlands–Argentina, Mexico–Poland, Croatia–Morocco.
- Final: 30 plotted normal shots, xG labels 2.76/2.27 (raw API values retained),
  8 shootout attempts and API display_score. Mexico–Poland: no shootout block.
- Switching, Back, root initial selection, deep-link refresh, live 404, mocked
  503 + retry, no period-5 pitch markers and no page JavaScript errors PASS.
- Browser XHR/fetch traffic stays on the frontend origin under /api/v1; filtering
  players adds no requests. Mobile 390px width has no page-level horizontal
  overflow; the player table has its own horizontal scroll.
- Screenshots inspected at desktop and mobile sizes; generated artifacts stay
  ignored in frontend/test-results, not committed.
- **19 API unit tests PASS** and the Stage 5A read-only validator PASS after the
  frontend changes. All-64-match coordinate inspection confirmed coverage above.
- **416 previous Python unit tests PASS**. Compose config -q, tracked/new-file
  whitespace checks and PowerShell documentation syntax checks also passed.

## Limits and suggested Stage 5C

WC2022 only, English UI, two fixed home/away colors, no official crests/colors,
no caching/prefetch/pagination, no server rendering or authentication. Dense
overlapping shots can obscure one another visually; keyboard focus still exposes
each marker. All squad rows remain available in a long scrollable table. There
is no event playback, pass network or heatmap. Date formatting uses the source
calendar date; no invented venue/browser timezone conversion.

The API snapshot consists of separate read-only queries, not an atomic serving
transaction. Current IDs are safe JavaScript integers; the parser rejects unsafe
IDs rather than silently losing precision. No production deployment, performance
SLA or comprehensive accessibility audit is claimed. Production reverse proxy,
TLS/static delivery and rate/security hardening remain separate work.

Recommended Stage 5C: a focused usability/accessibility pass with match search,
documented source attribution and synchronized shot selection between race,
pitch and a detail list; keep existing API semantics and avoid recalculating xG.
Review before adding endpoints or analytical features.

Not executed: ClickHouse writes/view changes, migrations, Superset changes,
S3/Gold publish, secret inspection, Git commit/push, Docker down/prune, or adding
new backend frameworks/infrastructure.
