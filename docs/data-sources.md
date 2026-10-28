# Data sources, coverage and interpretation

[Documentation index](README.md) · [Architecture](architecture.md)

## Implemented source

The loaded provider is [StatsBomb Open Data](https://github.com/hudl/open-data):
competition/season catalog, match JSON, event JSON and lineup JSON. StatsBomb xG
is supplied by the provider, not trained or recalculated by this project.
No football-data.org, API-Football, betting feed or current-season connector is
integrated. Provider 360 availability does not mean 360/tracking is loaded here.

## Verified platform coverage

These counts describe the audited immutable serving snapshot, not a new live
provider inventory or an assertion that all public StatsBomb competitions are loaded.

| Measure | World Cup 2022 `43/106` | Bundesliga 2023/24 `9/281` | Total |
| --- | ---: | ---: | ---: |
| Matches | 64 | 34 | 98 |
| Pass events | 68515 | 39214 | 107729 |
| Completed passes | 56346 | 33332 | 89678 |
| Failed passes | 11775 | 5747 | 17522 |
| Unknown passes | 394 | 135 | 529 |
| Coordinate-excluded passes in that audit | 0 | 0 | 0 |
| Normal shots, excluding shootout | 1453 | 916 | 2369 |

**Bundesliga coverage is Bayer Leverkusen matches only: 34/306 league fixtures.**
Opponents appear because they played those matches; their presence is not full
season coverage. Do not produce league-wide rankings, complete season totals or
freshness claims from this subset. **Season 2026/27 is not integrated.**
Evidence: [real coexistence totals](stage6b2.md#actual-observed-context-totals),
[98-match pass reconciliation](stage9b1.md#cd--verification-evidence-and-limits).

## Event semantics, not player movement

- Source coordinates use a StatsBomb 120×80 grid, top-left origin, X right and Y down.
  They are not a calibrated 120 m × 80 m physical pitch. Pass Map preserves full
  start/end values; the existing shot map uses its documented attacking window.
- Pass outcomes: both absent ID/name are the checked successful-pass default;
  known failure IDs 9/74/75/76 are failed; Unknown, unfamiliar IDs and name-only
  values remain unknown. Recipient presence does not prove completion.
- Missing, non-finite or out-of-bounds pass coordinates are explicitly counted,
  not silently repaired or sampled. API bounds are 5000 drawable rows / 4 MiB.
- Normal performance and xG exclude period 5; extra time in periods 3/4 remains.
  Official result/winner and shootout score are separate from shot goals and xG.
- Player rows follow squad membership, including zero-event players. No per90 or
  time-on-pitch rate is asserted without a playing-time model.
- An event heatmap/pass map describes observed events, not continuous movement,
  tracking speed, off-ball occupancy or a passing network already implemented.

Specification and implemented contract:
[official event documentation](https://github.com/hudl/open-data/tree/master/doc),
[Pass Map](stage9b1.md), [result/shootout semantics](stage4b.md).

## Attribution and licensing

Checked against the official repository and its agreement on **2026-10-29**:

- [StatsBomb repository terms](https://github.com/hudl/open-data#terms--conditions)
  ask published analysis to identify StatsBomb and use its brand logo.
- The [Public Data User Agreement](https://github.com/hudl/open-data/blob/master/LICENSE.pdf)
  covers research/analysis and restricts commercial exploitation and redistribution
  of source data. It is not a generic MIT, CC BY or public-domain data license.
- Before any different distribution/commercial use, review the agreement and
  obtain provider permission where required; this repository grants no extra rights.

The product READMEs use the official logo from the provider's
[image directory](https://github.com/hudl/open-data/tree/master/img); the
[media pack](https://statsbomb.com/media-pack/) is linked by the upstream README.
The documentation screenshot is derived match analysis, not a source JSON export.
No affiliation or endorsement by StatsBomb/Hudl, teams or competitions is claimed.

Data terms and software licensing are separate. This project currently has no
standalone software `LICENSE`; do not invent one by reusing a dependency's license.
Dependency/trademark rights remain with their owners. Provider terms may change;
this summary is a navigation aid, not a new license or legal clearance.
