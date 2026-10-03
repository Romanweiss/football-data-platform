# Stage 5C — Interactive Match UX, search and i18n

Presentation-only follow-up to Stage 5B. The existing Django API, ClickHouse views,
Gold/Silver/S3 datasets and analytical contracts remain unchanged. No new runtime
dependency or service. Superset remains the BI layer.

## Search and navigation

`MatchSelector` is an editable combobox over the already-loaded tournament list.
It searches home/away names, raw match_label, raw and localized stage, and ISO date.
Search is partial, case-insensitive and accent-insensitive; whitespace-separated
terms must all match. Input order is preserved (API chronological order).
Examples: `arg`, `fran`, `final`, `2022-12-18`.

Click/focus opens an empty search field ready for typing. Current match_label stays
visible below it, including while searching. Rows show teams, locale-formatted
date, localized stage and authoritative display_score. The dropdown scrolls
internally and announces result count / localized empty state.

- Arrow Down/Up moves the active option; Enter selects (first result if none active).
- Escape closes without navigation; Tab leaves; outside pointer or focus closes.
- DOM focus stays in the input; listbox/options use aria-activedescendant.
- Selection pushes /matches/<id>; popstate restores Back/Forward.
- Search does not request data. Selecting a different match requests its composite
  analysis once. Existing AbortController and stale-response guards are retained.

Keyboard pattern follows the
[WAI-ARIA combobox guidance](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/).

## Shared shot interaction

`Analysis` owns `useShotInteraction`: hoveredShotId and selectedShotId keyed by
event_id, never array position. Hover/focus previews temporarily; click/tap,
Enter or Space selects persistently. Hover takes precedence in details without
discarding selection; leaving restores selected details. Escape within analysis
or the clear button clears both. Selecting another match resets shot state;
changing language does not. Reload intentionally resets shot selection.

Race and pitch use the same events and state. Both show a solid hover ring and
a larger dashed selected ring; goal rings on the pitch remain separate. Team
colors are unchanged (teal home, orange away); state is not color-only.
SVG controls have meaningful localized labels, focus styles and aria-pressed.
Race hit circles have radius 12 SVG units without changing the visible point or
line geometry.

The long-form race contains two team states at every event. Both series remain
drawn using every state, but only the shooting team's point has a visible marker
and shot control. An opponent plateau
is not presented as a second shot. Join uses event_id AND team_id; no accumulation
is recomputed. ShotDetails is shared below the charts and shows player/team,
minute:second, shot xG, outcome, the shooting team's cumulative xG, period and
extra-time indication. Missing cumulative state displays an em dash. No primary
UUID label. No additional request on hover, selection or language switch.

X axis still means shot order, not elapsed minutes. Extra time stays included;
period-5 shootout stays excluded from normal shots/race. Source coordinates,
marker-radius formula, SVG step paths and raw numeric precision are unchanged.

## I18n ownership and formatting

`locales.ts` contains static typed EN/RU/ES dictionaries; missing keys are compile
errors. Tests check key and interpolation-placeholder parity. `i18n.tsx` supplies
a small React context and typed translation/formatting helpers; no runtime i18n
package, network translation or duplicated language-specific JSX trees.

All application-owned headings, labels, instructions, accessible descriptions,
loading/error/retry/empty states and footer are translated. Stable stage,
result-method and shot-outcome values have frontend display maps; unknown values
fall back to source text. Team/player names, IDs, match_label and display_score
remain source data, including the API's embedded “pens” abbreviation. They are
not rewritten or blindly translated.

| EN | RU | ES |
| --- | --- | --- |
| Match analysis | Анализ матча | Análisis del partido |
| Shots | Удары | Tiros |
| Expected goals | Ожидаемые голы | Goles esperados |
| Penalty shootout | Серия пенальти | Tanda de penaltis |

Initial locale: valid localStorage `touchline.language` preference, else first
supported navigator.languages base language, else English. EN/RU/ES header select
persists explicit choice and updates document lang/title. Unavailable storage
still permits in-memory switching. No navigation, fetch restart or loss of current
match/error/selection on language change.

Intl uses en-GB, ru-RU and es-ES. xG is displayed with exactly two decimals (2.76 /
2,76); raw values feed geometry unchanged. Dates format the source calendar date
in UTC, not an invented venue timezone. Event minute:second remains a football
clock, including extra time.

## Player table and responsive layout

Local player-name search, existing team filter and all-squad/activity selector.
Players with events is the default; activity means the existing event_count > 0.
Full squad, including zero-activity players, remains explicitly selectable.
Filtering does not mutate or delete source rows and
does not call the API. Sorting is unchanged. Table retains caption, column/row
headers and a keyboard-focusable internally scrollable region.

Existing Touchline dark/editorial styling retained. At <=1100px the secondary
brand text hides; <=900px charts stack; <=600px header/search/details/filters
reflow, team names wrap and footer stacks. No browser zoom tricks.

Native language/team/activity selects share appearance:none and CSS-background
chevrons with reserved right padding. The chevron cannot intercept clicks;
native semantics and visible keyboard focus are retained.

Browser checks cover actual 1440x900, 1024x768, 768x1024 and 390x844, each in all
three languages. They check page overflow, dropdown usability, selected details,
table scrolling and accessible names. Screenshots are ignored test artifacts in
frontend/test-results. Desktop RU and mobile ES screenshots were inspected.

## Verification and manual commands

From PowerShell, project root:

```powershell
Set-Location F:\Learning_projects\football-data-platform
# Existing API must be running; update only the frontend.
docker compose build football-web
docker compose up -d --no-deps football-web
docker compose config -q
docker compose run --rm --no-deps football-web npm test
docker compose run --rm --no-deps football-web npm run build
docker compose run --rm --no-deps -v "${PWD}/tests/application:/app/tests/application:ro" football-api python -m unittest discover -s tests/application -p 'test_*.py'
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests -p 'test_*.py'
git diff --check

Set-Location .\frontend
# Only needed when installing/updating dependencies:
npm.cmd ci --no-audit --no-fund
npm.cmd test
npm.cmd run build
npm.cmd run test:smoke
```

Open http://127.0.0.1:15173/ and search “arg”; select Argentina–France final.
Hover/select an xG point and observe its pitch marker and shared details. Switch
RU (same match and selection), reload (RU persists), then ES. Select Mexico–Poland
and inspect Robert Lewandowski at 57:23: his saved match-time penalty stays in
normal pitch/race; no shootout panel. Test Back/Forward and Escape.

Unit/component tests are fully synthetic/offline; browser tests require local
frontend/API/data, not internet access. Browser default on Windows is installed
Edge; WEB_BASE_URL / PLAYWRIGHT_CHANNEL can override the existing defaults.
Only dev dependency added: pinned @axe-core/playwright (and its axe-core transitive
dependency) for automated accessibility checks; bundled runtime is unchanged.

Verified: 40 frontend tests, TypeScript/Vite build, 19 API tests and 416 previous
Python tests pass. All 11 live browser tests pass, including mobile touch and
browser-language fallback. There are 24 passing full-page axe scans (four
viewports x three languages x open-search/selected-shot states), with zero
reported violations. Compose config and tracked/new-file whitespace checks pass. Axe
checks full pages with open search and selected shots across languages/viewports,
including color contrast; no rules are disabled. This is not a WCAG compliance
claim or a screen-reader audit.

## Changed files

- New: frontend/src/locales.ts, i18n.tsx, search.ts, shotInteraction.ts and
  components/ShotDetails.tsx.
- Updated: frontend/src/App.tsx, visuals.ts, styles.css and components/
  MatchSelector.tsx, MatchHeader.tsx, TeamComparison.tsx, XgRace.tsx, ShotMap.tsx,
  PlayerTable.tsx, ShootoutPanel.tsx, States.tsx.
- New tests: frontend/tests/search.test.tsx, i18n.test.tsx, interaction.test.tsx.
  Updated app.test.tsx, components.test.tsx, setup.ts and smoke/live.spec.ts.
- frontend/package.json and package-lock.json: development-only axe dependency.
- README.md and this document.

## Limitations and proposed Stage 5D

- WC2022 scope, no backend search/pagination/cache/auth/SSR.
- Dense overlapping pitch markers remain at exact source coordinates; keyboard
  focus accesses obscured markers. Race transparent hit targets can overlap on
  narrow screens; keyboard selection remains available.
- Details are one shared panel below the charts, not a floating tooltip. On
  stacked/mobile layout it can be below the viewport; active control labels and
  polite live-region details remain available to assistive technology.
- Browser tests use Chromium/Edge; Safari/Firefox and real assistive-technology
  testing remain separate. Static translations are not a professional linguistic
  audit. Full squad table is intentionally long.

Recommended Stage 5D: production-delivery readiness (static hosting/reverse proxy,
SPA fallback, security headers, automated CI unit/browser/a11y gates) plus manual
keyboard/screen-reader and cross-browser review, without changing analytics.

No ClickHouse/migration, API metric/schema, Superset, S3/Gold, IAM or credential
changes; no Git commit/push or destructive Docker operation performed.
