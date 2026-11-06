# SUPERSET-UX-3 — measured layout revision and real browser acceptance

Дата: **2026-11-06**. Published HEAD / branch:
`d3443f77c24445c3d2fb0978c10d0b57155561e8` / `master`.

**Вердикт: BLOCKED для безоговорочной mobile acceptance.** Candidate-specific
clipping и новый serious `scrollable-region-focusable` устранены в **ux3-r2**.
Revision готова к review, но обычный mobile URL всё ещё имеет framework overflow
418/390 px; baseline axe findings остаются. Это не mobile/axe PASS и не
разрешение на live apply.

Live Superset `18088` и production Web/API `18090` не изменены. PET-3D — NOT
STARTED; Stage 8C — PARTIAL. Production PostgreSQL writer не активировался,
durable backup live metadata не создавался.

## 1. Продолжение UX-2, не новая диагностика данных

Использованы [UX-1](superset-match-analysis-ux-review.md),
[UX-2](superset-match-analysis-ux-acceptance.md) и
[infra audit](infra-audit-2026-11.md). Четыре original UX-1 bundle hashes до и
после этапа совпали с прежними pins. Старые файлы/reports не перезаписаны.

Проверены существующие isolated instances:

| Instance | Port | Contract при preflight |
| --- | --- | --- |
| `football-superset-ux2-20261106` | 18089 | UX-1 candidate |
| `football-superset-ux2-v2-20261106` | 18091 | old |

Оба running; immutable image одинаковый:
`sha256:fe90eca2116e101b8a34a3bbfbfde881014e34857490faec75873f60d0ca8fe8`,
Superset **6.0.0**, Linux Python **3.10.19**. На candidate state новый patch не
накладывался. Эти экземпляры использованы для read-only UI baseline measurements.

Для двух UX-3 trials созданы отдельные чистые metadata copies того же образа:
`football-superset-ux3-r1-20261106` / `18092` и
`football-superset-ux3-r2-20261106` / `18093`.
Каждая — собственная SQLite DB `/tmp/superset-ux3.sqlite` в своём контейнере,
без persistent volumes и без production metadata PostgreSQL backend.
Metadata schema и synthetic permission fixtures подготовлены как в UX-2;
migrations, ETL и основной Compose не запускались/не менялись.

Аналитика использует прежний SELECT-only reader (`readonly=1`) через проверенный
process-only handoff; credentials не сохранялись в plaintext, CLI, отчёт или Git.
Connections в test metadata шифруются штатно Superset. Session/encryption key
тестового процесса не является recovery key и не выводился.

## 2. Измерения и revision history

### Точные причины UX-2 findings

- Summary inner box **64 px**, header+data rows около **59 px**, не считая
  chart header; data row выходила за box. Наличие status в API не помогало UI.
- Новый `scrollable-region-focusable` указывал конкретно на **Markdown note**,
  а не на потерянные kicks: его auto-scroll container не имел focusable content.
- Старый dashboard без UX-1 candidate на mobile тоже давал **614 px** page width
  при viewport **390 px**. Открытый vertical filter sidebar оставлял слишком
  мало места grid; поэтому не всё следует приписывать candidate.

### Отдельные revisions

| Настройка | UX-2 candidate | UX3-r1 (trial) | UX3-r2 (review candidate) |
| --- | --- | --- | --- |
| Summary grid height | 12 | 20 | 20 |
| Markdown grid height | 6 | 12 | 20 |
| Kicks grid height | 20 | 36 | 44 |
| Filter orientation | vertical/default | native HORIZONTAL | native HORIZONTAL |
| Kicks pagination | auto | 5 rows/page | 5 rows/page |
| Kicks column widths | auto | auto | player 320 / team 140 / outcome 110 px |

`r1` устранил desktop clipping, но mobile note требовала **150 px** при
доступных **96 px**. Для `r2` выбрано **160 px**, не CSS-маскировка overflow.
В `r1` пять mobile kick rows из-за переноса имён требовали 259 px при viewport
таблицы 100 px. В `r2` штатные column widths сократили переносы; измеренный
mobile tbody — **148 px clientHeight / 148 px scrollHeight** для пяти строк.
Все пять rows первой страницы помещаются; остальные три доступны на второй.

Настройки pagination/column widths являются штатными table controls Superset
6.0.0: [control panel](https://github.com/apache/superset/blob/6.0.0/superset-frontend/plugins/plugin-chart-table/src/controlPanel.tsx),
[column configuration types](https://github.com/apache/superset/blob/6.0.0/superset-frontend/plugins/plugin-chart-table/src/types.ts).
Pagination client-side: backend row_limit не уменьшался. Для финала API
возвращает все 8 attempts, UI показывает **5+3 / 8 unique attempts**.

Ни conditional chart hiding, ни custom frontend plugin не добавлены. Global
Superset CSS не менялся; dashboard CSS также не добавлялся. Existing library
overflow styles не использовались для маскировки: проверено полное помещение
Markdown/status cell в реальные bounds. Единая фиксированная высота note даёт
дополнительное desktop whitespace — осознанный компромисс ради mobile текста.
Для обычных матчей fixed kicks panel сохраняет пустое состояние; динамическое
скрытие не заявляется поддержанным или реализованным.

## 3. Trusted hashes и воспроизводимость

Папки revisions — `.tmp/superset-ux-3/r1/` и `r2/`. Обе immutable после создания.
В каждой: `before.json`, candidate, 22-field patch, inverse patch, manifest и
`revision-diff.json` относительно исходного UX-2 candidate.

| Файл | ux3-r2 SHA-256 |
| --- | --- |
| `before.json` | `37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86` |
| `candidate-config.json` | `d741625a585e12a96f786994e18df92b04ce5d1a2ecae91881938da530ec3555` |
| `config-patch.json` | `3d6d2c5037c7c1a9e3f8cd7c1f2ef3e5441ae7ae43cdc89358cb8b2cd18c2a6c` |
| `rollback-fields.json` | `35652191f52c20cfa9a0329a06df9a28936435cfa5383925608bc0490c78a22e` |

Trial r1 candidate hash:
`e4108a79dffa0985a8ca41e1674eca82b713b9225c3c9799deb1795cffa5695d`.
Полные r1 hashes также pinned в protocol и его local manifest; r1 не выдан за
прошедший mobile trial.

Добавлен [offline builder](../scripts/build_superset_ux_layout.py). Он принимает
только original trusted UX-1 bundle, проверяет hashes до parsing, создаёт новый
output directory, отказывает при overwrite и выдаёт строго pinned revision.
Независимая генерация в `reproduced-r2/` дала **те же четыре hashes**.

```powershell
# Только offline generation; не запускает Superset, SQL или live apply.
python scripts/build_superset_ux_layout.py --bundle-dir .tmp/superset-ux-1 --output <new-directory> --revision ux3-r2
```

Старый default `load_bundle(raw)` остаётся UX-1. Новые pins выбираются только
явным `ux3-r1` / `ux3-r2`; неизвестная revision отклоняется. `--contract old`
и UX-2 validation сохранены. Не следует нормализовать CRLF/LF в original bundle:
trust распространяется на bytes, не на эквивалентный JSON после переписывания.

## 4. Source identity и reconciliation

В сравнении с UX-2 **без изменений**:

- все 12 datasets, включая trusted virtual SQL dataset 5;
- query-context `queries`, SQL guards и analytical filters всех charts;
- native Match ID, single-value selection, default, scope charts 9–16;
- 98-entry exact display→canonical mapping, без fuzzy matching;
- dashboard 1; metric expressions, результаты матчей, physical tables/views.

Новый semantic check выполнен на каждой isolated revision; для r2:
**98 unique labels / 98 unique canonical keys, 32 chart cases, 35 negative
selection cases; 93 NOT_APPLICABLE / 5 DATA_AVAILABLE — PASS**.
Никакие synthetic records в источники не записывались.

| Реальный матч | Player rows | Shots | Summary | Kicks |
| --- | --- | --- | --- | --- |
| Serbia—Switzerland | 49 | 26 | NOT_APPLICABLE | 0 |
| Netherlands—Ecuador | 52 | 17 | NOT_APPLICABLE | 0 |
| Argentina—France | 50 | 30 | DATA_AVAILABLE | 8, серия 4:2 |
| Bayer Leverkusen—RB Leipzig | 40 | 25 | NOT_APPLICABLE | 0 |

Player Stats, Shots, xG Race и Shot Map получили успешные real chart responses.
Не повторялось полное исследование SQL/PET-3A ETL и full-table hash scan. Fresh
read-only live Superset metadata + bounded domain export совпал с UX-2 export.
Свежая проверка 98 analysis hashes / всех physical tables этим этапом отдельно
не заявляется: их последний полный PASS относится к UX-2.

## 5. Real browser acceptance

Использован настоящий Superset 6.0.0 и Playwright/Chrome, свежий browser context
на каждый viewport: **1440×900** / **390×844**. Не HTML-preview. Network browser
ограничен isolated origin; user profile/Bitwarden не использовались.
Role — synthetic Admin, штатно допущенный к draft dashboard; public/Gamma
acceptance не заявляется и publish/owners ради неё не менялись.

Для каждого из четырёх матчей дожидались всех восьми chart responses и правильного
Header. Summary проверялся по **собственной status cell**, её bounding rectangle
внутри chart, а не по слову в постоянной Markdown-памятке.

- **8/8 viewport/match cases:** status cell полностью видима, Markdown complete.
- Summary inner height **128 px**, data row входит в box.
- Note **160 px client / 160 px scroll** на обоих viewports, без auto-scroll.
- Финал: UI pagination 5+3, все 8 attempt numbers уникальны; source/API не обрезан.
- Mobile table body: horizontal scroll внутри области; focus и ArrowRight
  изменяли `scrollLeft` 0→40. Дополнительно настоящий Tab дошёл до ячейки Summary
  и ArrowRight дал 0→200 **без добавления tabindex или иной DOM mutation**.
- Tab chain длинная: **585 stops** через существующие интерактивные таблицы.
  Ранний bounded trial 180 stops не достиг Summary; он не считается доказательством
  недоступности. Длинная цепочка — оставшееся usability limitation.
- Native mobile More filters → Match selector работает. Измеренные размеры:
  selector **224×32 px**, More filters около **165×32 px**. Это geometry/browser
  viewport test, не сертификация физических touch devices/Safari.

### Mobile overflow: отделить dashboard от chrome приложения

| Режим | Page width / viewport | Статус |
| --- | --- | --- |
| Old dashboard, vertical sidebar | 614 / 390 | baseline limitation |
| UX3-r2, normal URL | 418 / 390 | **NOT PASS**: верхний main-nav выходит до x=418 |
| UX3-r2, native `?standalone=1` | 390 / 390 | width check PASS только для этого presentation profile |

В r2 dashboard content имеет ровно **390 px**, grid **358 px**; tables scroll
внутри. Оставшиеся 28 px страницы связаны с штатной навигацией Superset, а не
увеличением ширины chart. Никакой `overflow:hidden` для всей страницы не вводился.
Native standalone — отдельный просмотр без main nav, не исправление normal URL
и не автоматически выбранная production/mobile policy.

### Axe desktop/mobile — без отключения rules

**`scrollable-region-focusable` отсутствует во всех 8 r2 cases.** Подтверждённый
новый serious defect UX-2 исправлен. Remaining rule IDs в normal UI:

| Rule | Classification |
| --- | --- |
| `aria-allowed-role` / `#main-menu` | baseline Superset navigation |
| `html-has-lang` | baseline document shell |
| `page-has-heading-one` | baseline document structure |
| `color-contrast` | native theme/chrome controls, не объявлены исправленными |

Для финала desktop contrast nodes: Draft tag **3.07:1**, Edit dashboard control
**2.37:1**, то же, что baseline. В mobile/presentation states число nodes
варьируется; в частности, native horizontal Clear All также получает **2.37:1**.
Его нельзя спрятать общим утверждением «всё baseline/PASS»: это открытое
ограничение выбранного штатного control. В standalone main-menu rule исчезает
из-за отсутствия main nav, но contrast/lang/heading findings остаются.
**Overall axe PASS не заявляется.** Global theme/styles или frontend plugin ради
обхода findings не менялись.

### States, history и keyboard

Повторены именно UI checks для новой orientation/revision:

- reload и Back/Forward между dashboard 2 и 1 — PASS (реальные UI transitions);
- selection клавиатурой Enter и Apply — PASS;
- задержан настоящий response Serbia, затем выбран Netherlands: после release
  старый response не переписал актуальный Header — PASS;
- browser-only HTTP 500 у одного chart показан как error, не NOT_APPLICABLE;
- Clear All в horizontal bar не использовался как доказательство empty source:
  наблюдалось возвращение default Argentina Header;
- отдельно из одного настоящего isolated chart request удалён selected match:
  backend guard вернул **HTTP 200 / success / 0 rows**, настоящий UI показал
  `No results were returned for this query`. Fake source rows не добавлялись.

Error/latency injection относится только к browser transport теста, не к
production SQL. После states выполнен rollback; после дополнительного
Tab/empty test — ещё один подтверждённый rollback.

### Screenshots и evidence

Основные файлы — `.tmp/superset-ux-3/r2-evidence/`:

- `real-<3857256|3857274|3869685|3895052>-<desktop|mobile>.png` — 8 real screenshots;
- `native-standalone1-mobile.png` — отдельно маркированный native profile;
- `real-loading.png`, `real-query-error.png`, `real-empty-guard.png`;
- `acceptance.json`, `real-state-results.json`, `keyboard-empty.json`, `history.json`.

Raw DOM measurements baseline/trials: `old-measurements.json`,
`ux2-measurements.json`, `r1-fresh-measurements.json`, `r2-fresh-measurements.json`.
Resizing trials сохранены отдельно; финальная проверка использовала fresh
contexts, чтобы не принять stale desktop table widths за initial mobile layout.
Screenshots/локальные fixtures не staged и не публикуются автоматически.

## 6. CAS, apply/rollback и тесты

Сохранён UX-2 protocol: ровно **22 field paths**, strict CAS всех semantic fields,
единственное узкое сохранение runtime `shared_label_colors`. Новый список hashes
не принимает произвольный manifest как authority. IDs/UUID/owners/original
columns сохраняются; no credential/RBAC/full-dashboard writer.

| Операция | r1 | r2 |
| --- | --- | --- |
| Clean old → apply | PASS, 1 commit | PASS, 1 commit |
| New validator | PASS | PASS, 98/32/35 |
| Repeated apply | ожидаемый CAS_CONFLICT | ожидаемый CAS_CONFLICT |
| Rollback | PASS, 1 commit | PASS, 1 commit |
| Old validator после rollback | PASS, 8 Overview / 40 Match | PASS, 8 Overview / 40 Match |

R2 дополнительно прошёл apply→states→rollback, apply→Tab/empty→rollback и
apply→reload/Back/Forward→rollback. Последний отдельный history test подтвердил
сохранение выбранного Netherlands после reload/Back, возврат на dashboard 1
через Forward и old validator после rollback (8 Overview / 40 Match cases).
Конечный metadata contract **обоих UX-3 instances — old**, 16 charts / 12 datasets.
Production PostgreSQL gate не снят: adapter разрешает только точные isolated
SQLite paths UX-2/UX-3; никакого live activation не было.

- **43 offline tests PASS** на Windows Python **3.12.10**, отдельно 43 PASS на
  host **3.14.3**. Включены legacy/new CAS tests и visual-revision invariants.
- Real Superset backend: Linux Python **3.10.19**, не CI matrix 3.10.12/3.12.14.
- Ruff, compileall, repository/security contracts, documentation links и diff
  checks — PASS. Никакие skipped/непроверенные mobile criteria за PASS не выданы.
- Unchanged SQL/query/guard/dataset assertions и byte-reproduction r2 — PASS.

## 7. Изменённые repository files и Git

Изменения именно относительно локального UX-2 состояния:

1. `src/analytics/superset_ux.py` — отдельные pinned revision hashes; old default сохранён.
2. `scripts/superset_ux_metadata.py` — ещё один exact isolated SQLite path, не PostgreSQL.
3. `scripts/superset_semantic_safety.py` — явные validate-only `ux3-r1` / `ux3-r2`.
4. `scripts/build_superset_ux_layout.py` — новый offline reproducible builder.
5. `tests/test_superset_ux.py` — revision registry / immutable visual transformation tests.
6. `docs/superset-match-analysis-ux3.md` — этот новый отчёт.

UX-2 validator implementation и старые UX-1/UX-2 reports не переписаны.
Ignored harnesses `.tmp/superset_ux3_*` и bundles/evidence не являются staged
publication set. Полный worktree содержит также предыдущие UX-2 files/docs.

Index по-прежнему содержит только два licensing-документа:

| File | Unchanged blob ID |
| --- | --- |
| `docs/stage9c5-provider-comparison.md` | `fac8b0073dc67bab8f5341b4304036ea78d91e54` |
| `docs/stage9c5-provider-licensing-review.md` | `6fe2394c0dc11ded3199c5e7d75c173d96bc9ddd` |

Planning docs и shortcut сохранены. Worktree ожидаемо не чистый; staging,
commit/push, reset/clean не выполнялись. Source data, K: backups, внешний restore
F: и recovery keys не читались/не менялись. SQL-query logs/cache test instances
являются isolated operational state, не production dataset writes.

## 8. Docker lifecycle recommendation — НЕ выполнено

Все четыре test containers оставлены running. Shared image — тот же Superset
image, который нужен live; его удаление не предлагается. Exact IDs:

| Name / port | ID prefix | Конечный semantic state |
| --- | --- | --- |
| `football-superset-ux2-20261106` / 18089 | `a12f5c742199` | original candidate, forensic instance |
| `football-superset-ux2-v2-20261106` / 18091 | `39e76ad6ea41` | old |
| `football-superset-ux3-r1-20261106` / 18092 | `08d7d2c5d0b` | old, trial evidence |
| `football-superset-ux3-r2-20261106` / 18093 | `7f2a753eabc9` | old, final rollback verified |

**После успешного принятия UX-3/limitations и отдельного cleanup-разрешения**:
сначала сохранить non-secret bundles, hashes, screenshots/receipts вне временной
области и проверить отсутствие активных тестов; сверить exact IDs/labels/mounts.
Затем можно поимённо остановить и удалить только эти четыре test instances,
сохранив r2 последним при необходимости review. Их SQLite operational state
эфемерен; новый экземпляр воспроизводится через trusted bundle/handoff, а не
через обещание restart с прежним process-only encryption key.

```powershell
# FUTURE PROPOSAL ONLY — requires separate approval; not executed.
docker stop football-superset-ux2-20261106 football-superset-ux2-v2-20261106 football-superset-ux3-r1-20261106 football-superset-ux3-r2-20261106
docker rm football-superset-ux2-20261106 football-superset-ux2-v2-20261106 football-superset-ux3-r1-20261106 football-superset-ux3-r2-20261106
```

Без `-f`, `-v`, prune, network/volume removal или image removal. Не включать live
`football-superset`, его PostgreSQL, production API/Web или другие проекты.
Сейчас никакая часть этой cleanup-последовательности не выполнялась.

## 9. Минимальное следующее действие

Согласовать **mobile policy**: Superset desktop-first с явным ограничением
обычного mobile URL и optional native standalone profile либо отдельная
разрешённая работа с framework shell/контрастностью. Native global findings
нельзя исправлять скрытием axe rules или CSS clipping.

После этого — отдельный publication/config review `ux3-r2`, затем отдельно
разрешённые production PostgreSQL writer tests и durable scoped backup этап.
Текущий шаг их не запускал. **Normal mobile и overall axe остаются NOT PASS;
live apply автоматически не разрешён.**
