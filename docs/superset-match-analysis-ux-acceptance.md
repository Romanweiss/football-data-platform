# SUPERSET-UX-2 — real isolated Superset acceptance

Дата: **2026-11-06**. HEAD `master`:
`d3443f77c24445c3d2fb0978c10d0b57155561e8`.

**Вердикт для live apply: BLOCKED.** Изолированные SQL/semantic checks и
transactional writer/rollback прошли. Настоящий UI выявил clipping и
accessibility regression; mobile имеет horizontal overflow. Исходный UX-1
candidate не заменён и не объявляется принятым.

Live Superset `18088`, production Web/API, ClickHouse/PostgreSQL данные,
Airflow, ETL и recovery materials не менялись. PET-3D — NOT STARTED,
Stage 8C — PARTIAL.

## 1. Проверенный вход и сохранность

Использованы [UX-1 review](superset-match-analysis-ux-review.md) и
[infra audit](infra-audit-2026-11.md). Четыре файла проверены до работы и повторно
в конце; SHA-256 совпали:

| Файл в `.tmp/superset-ux-1/` | SHA-256 |
| --- | --- |
| `before.json` | `37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86` |
| `candidate-config.json` | `4f8f923deddb2bb3108b65145f565580ba78606f8105b156e5617a5996464514` |
| `config-patch.json` | `7e030c99a6b1c82d1f7afa30dbd3a578f68d4319c0d56fc37473cf915a71851d` |
| `rollback-fields.json` | `91e99eb42f9acc53a46d198842dd58e7516896e07dcbaa97862a26c151c82c34` |

Ни mapping, ни геометрия утверждённого candidate не переписывались.
Использованы ровно 22 согласованных field paths. Full upstream datasets,
planning/licensing документы и shortcut не переносились в тестовый Superset.

## 2. Настоящее isolated окружение

Использован существующий локальный образ `football-superset:6.0.0`
(image ID prefix `fe90eca2116e`), Apache Superset **6.0.0**, Linux Python
**3.10.19**. Это настоящий backend/frontend Superset, не HTML-preview UX-1.

| Тестовый контейнер | Loopback URL | Назначение / конечное состояние |
| --- | --- | --- |
| `football-superset-ux2-20261106` | `http://127.0.0.1:18089` | первый диагностический экземпляр; retained candidate и evidence первоначального CAS conflict |
| `football-superset-ux2-v2-20261106` | `http://127.0.0.1:18091` | проверка исправленного protocol; после тестов возвращён **старый metadata contract** |

Оба созданы этим этапом и оставлены для review; существовавшие до этапа
контейнеры не останавливались, не удалялись и не пересоздавались. Новые test
instances не являются production и требуют отдельного решения о завершении
их lifecycle. Не использовать первый экземпляр как рабочий dashboard.

Каждый имеет **свою** SQLite metadata DB `/tmp/superset-ux2.sqlite` внутри
собственного writable layer. Это разные файлы в разных контейнерах. Schema
создана через SQLAlchemy metadata `create_all` исключительно в пустой isolated
DB; Alembic/Superset migrations и `superset init` не запускались. Persistent
dataset writes не выполнялись. Production metadata PostgreSQL не является
metadata backend ни одного тестового приложения.

Оба контейнера используют `football-network` для доступа к существующему
ClickHouse reader; это **не air gap**. Credentials production PostgreSQL им
не предоставлялись. Reader проверен с `readonly=1`; аналитические операции —
SELECT. Новый аналитический writer/Gold build не создавался.

Reader URI передан из проверенного live Superset process в память launcher и
stdin нового process, без CLI arguments, plaintext-файлов или вывода значений.
В isolated metadata connection material хранится штатно зашифрованным Superset;
test session/encryption secret генерируется в памяти нового процесса, не
копируется из live. Он не является Stage 8C recovery key. Test instances
эфемерны: после остановки не следует ожидать восстановления подключения простым
restart без отдельной контролируемой подготовки.

Mounts — только readonly analytics source и файл metadata adapter. Ни `.env`,
ни project data, recovery directories или пользовательский browser profile не
монтировались. Named/anonymous volumes для этих экземпляров не создавались.

Созданы только синтетические Admin/Gamma users. Для пустой metadata DB отдельно
инициализированы стандартные UI permission fixtures: 301 permission pairs
Admin/Gamma без live users, их membership, passwords и datasource grants.
Из live прочитаны лишь штатные определения permissions; его RBAC не изменён.
Gamma дополнительно получил доступ только к 12 isolated datasource references.
Это fixture setup, не часть 22-field writer.

Первые bootstrap ошибки были ошибками подготовки нового окружения: inherited
live-specific config, порядок FAB/model initialization и отсутствие standard
UI permissions. Они не трактуются как дефект production Superset. Live-specific
config не использовался для подключения тестовой metadata DB.

## 3. Semantic checker old/new

Существующий [validator](../scripts/superset_semantic_safety.py) сохранён:
default contract — `old`; прежняя функция `validate` не изменена. Добавлены
`--contract ux2 --bundle-dir <trusted-bundle>` для SELECT-only проверки нового
контракта. `--contract ux2` с apply/audit вместо validate отклоняется.

Новая реализация: [superset_ux_validate.py](../scripts/superset_ux_validate.py).
В isolated environment обе функции запускались через authenticated test-only
management endpoint внутри того же Superset process, не через другой bootstrap
с чужим encryption key. Standalone CLI в ephemeral SQLite environment отдельно
не сертифицирован.

Новый validator проверяет:

- fingerprint всего approved bundle до JSON parsing; bounded input;
- exact approved SQL/guards/columns/native scope/layout;
- **98 rows / 98 unique display labels / 98 unique canonical keys**;
- свежую display→canonical mapping, без fuzzy matching;
- реальные 32 chart cases для четырёх матчей;
- 35 empty/invalid/multiple/inverse/duplicate/injection-like checks;
- 93 NOT_APPLICABLE и 5 DATA_AVAILABLE; source state не подменяется synthetic rows.

Геометрия candidate проверяется как approved config, но это **не означает**, что
геометрия хороша: visual acceptance — отдельный gate и здесь он failed.

| Проверка в isolated Superset | Результат |
| --- | --- |
| Старый validator до apply | PASS: 8 Overview / 40 Match cases |
| Новый validator после apply | PASS: 98 labels, 32 chart cases, 35 negative cases |
| Старый validator после rollback | PASS: 8 Overview / 40 Match cases |
| Dataset-query checks нового checker с synthetic Gamma | PASS; не равнозначно browser-доступу к unpublished dashboard |

Security policies, включая запрет adhoc subqueries, не отключались.

## 4. Real UI: результаты и найденные дефекты

Chromium/установленный Chrome запускался через Playwright в новом context,
extensions отключены. Обычный Chrome profile, Bitwarden и реальные browser
cookies не использовались. Разрешены только запросы к нужному isolated origin.

Реальная UI acceptance выполнена с **synthetic Admin**, имеющим штатное право
на draft dashboard. Gamma не получил доступ к unpublished dashboard: UI показал
Not found/access denied. Это ожидаемая граница роли, не доказательство поломки
Match selector. Не заявляется public/Gamma browser acceptance. Dashboard не
публиковался и owners не менялись ради обхода этой проверки.

Все восемь charts 9–16 реально получали успешные HTTP chart-data responses для
каждого выбранного матча, а не только выводили постоянную Markdown-памятку:

| Матч / ID | Player rows | Shots | Summary | Shootout rows |
| --- | --- | --- | --- | --- |
| Serbia—Switzerland / 3857256 | 49 | 26 | 1, NOT_APPLICABLE | 0 |
| Netherlands—Ecuador / 3857274 | 52 | 17 | 1, NOT_APPLICABLE | 0 |
| Argentina—France / 3869685 | 50 | 30 | 1, DATA_AVAILABLE | 8 |
| Bayer Leverkusen—RB Leipzig / 3895052 | 40 | 25 | 1, NOT_APPLICABLE | 0 |

Читаемые labels и exact selection работают; штатных SQL errors в этих случаях
не было. Финал содержит серию 4:2. Player Stats, Shots, Shot Map и xG Race
загружаются. xG chart-data API использует штатное post-processing серии; число
строк API после него не следует сравнивать с числом long-form SQL points.

### Screenshots именно настоящего Superset

В `.tmp/superset-ux-2/v2/` сохранены:

- `real-3857256-desktop.png` / `real-3857256-mobile.png`;
- `real-3857274-desktop.png` / `real-3857274-mobile.png`;
- `real-3869685-desktop.png` / `real-3869685-mobile.png`;
- `real-3895052-desktop.png` / `real-3895052-mobile.png`;
- `real-loading.png`, `real-query-error.png`, `real-empty.png`;
- `real-rollback-old.png`.

Это не UX-1 preview. Данные для screenshots ожидались по завершению chart
responses и соответствию Header выбранному матчу. Ранние диагностические
screenshots первого экземпляра включали loading; они не используются как
доказательство завершённой acceptance. Артефакты не staged и не предназначены
для автоматической публикации.

### Блокирующие UX findings

1. **Summary height 12 не вмещает data row.** Измеренный inner box — 64 px;
   header row начинается около y=970.5, data row около y=1001, тогда как box
   заканчивается около y=998. Контейнер таблицы имеет clientHeight 28 при
   scrollHeight 59. Статус есть в API/DOM, но строка обрезана в реальном UI.
   Следовательно, наличие слова NOT_APPLICABLE в общей Markdown не считается
   успешным отображением Summary.
2. **Markdown height 6 тоже тесен:** explanatory text обрезается. Отдельный
   preview UX-1 не мог обнаружить точный layout Superset.
3. **Mobile 390×844 имеет horizontal page overflow во всех четырёх случаях.**
   Selector существует, screenshots получены, но полноценная responsive
   acceptance не пройдена.
4. **Новый accessibility defect:** `scrollable-region-focusable`, serious,
   наблюдался в candidate, отсутствовал в baseline старого dashboard. Compact
   scroll area нельзя считать keyboard-accessible лишь по доступности selector.

Прочие axe findings также не скрыты:

| axe rule | Старый dashboard | Candidate (Serbia case) |
| --- | --- | --- |
| `aria-allowed-role` | minor, 1 node | minor, 1 node |
| `color-contrast` | serious, 2 nodes | serious, 4 nodes |
| `html-has-lang` | serious, 1 node | serious, 1 node |
| `page-has-heading-one` | moderate, 1 node | moderate, 1 node |
| `scrollable-region-focusable` | не обнаружен | serious, 1 node |

Наличие четырёх rule IDs в baseline не оправдывает новые проблемы; увеличение
числа contrast nodes и новая scroll regression требуют review. Не заявляется
«axe PASS» для настоящего Superset. Axe запускался на desktop states; для mobile
здесь выполнены screenshots/overflow checks, не отдельная полная axe acceptance.

### Навигация, keyboard и transport states

| Сценарий | Фактически проверено |
| --- | --- |
| Reload | выбранный Bayer Leverkusen match восстановился |
| Back/Forward | переход Dashboard 2 → Dashboard 1 → Back → Forward работает |
| Dashboard 1 | Overview открывается; его charts отвечают успешно |
| Keyboard | native option выбран Enter, Apply активирован Enter, Header подтвердил Serbia |
| Loading | задержан настоящий chart response; реальный loading UI снят |
| Late response | удержан ответ Serbia, затем выбран Netherlands; после release старого ответа Header остался Netherlands |
| Error | Playwright вернул synthetic HTTP 500 только одному isolated chart request; настоящий UI показал error, не NOT_APPLICABLE |
| Clear all / empty | required selector отключает Apply; Header сохраняет последний applied match. Новый empty chart request этим действием не отправлен |

Error injection — browser-only transport fault, **не ошибка production SQL** и
не изменение исходных данных. Empty guard на backend проверен негативными
semantic cases, но UI Clear all не выдаётся за демонстрацию empty DataFrame:
pending required selection и applied state различаются. Это дополнительная
UX-оговорка, если ожидается немедленная очистка charts.

## 5. Transactional writer, CAS и rollback

Реализованы [protocol](../src/analytics/superset_ux.py) и
[SQLAlchemy adapter](../scripts/superset_ux_metadata.py).

- Четыре trusted hashes проверяются **до** разбора JSON; scope — ровно 22 paths.
- Для SQLite writer lock `BEGIN IMMEDIATE` берётся до CAS reads.
- Все expected before-state проверки выполняются до первого write.
- IDs/UUID/owners всех charts/datasets/dashboards и IDs исходных columns
  проверяются до/после flush. Это сохранность относительно isolated fixture,
  не перенос production users/owners в тестовый экземпляр.
- Исходные columns не пересоздаются; добавляются/удаляются только два новых
  metadata columns. Нет full dashboard import, credential/RBAC writer или
  перезаписи database connection.
- Один commit на apply или rollback; ошибка — rollback всей своей транзакции.
  Чужая уже открытая transaction отклоняется без её rollback.
- Повторный apply отказал **HTTP 409 / CAS_CONFLICT**, без повторного commit.

### Важный реальный CAS finding и узкая политика runtime colors

При первом strict rollback обнаружено, что Superset **сам** изменил
`dashboard[2].metadata.shared_label_colors` после обычного просмотра.
Первый writer корректно отказал с CAS conflict; force overwrite не выполнялся.

В проверенной второй версии protocol ровно этот один runtime cache key исключён
из semantic CAS projection **и сохраняется неизменённым при write**. Bundle
проверяется на то, что before/after не пытаются менять этот cache. Все остальные
keys, SQL, filters и layout остаются строгими CAS; никаких общих «ignore
metadata differences» нет. Runtime cache принадлежит Superset, не UX-патчу.

Это явная политика writer, не изменение approved candidate. Она покрыта unit
тестами: cache drift сохраняется, изменение native config по-прежнему блокирует
apply. VERIFY после write сравнивает полное фактическое значение, включая
сохранённый runtime cache. Перед live использованием эту политику нужно принять
как часть review; raw byte equality всей metadata JSON после UI не обещается.

| Real isolated operation, экземпляр v2 | Результат |
| --- | --- |
| Apply approved 22 fields | PASS, 1 commit |
| New semantic validator | PASS |
| Duplicate apply | CAS_CONFLICT, ожидаемый отказ |
| Rollback после настоящего UI browsing | PASS, 1 commit |
| Старый native selector / chart guards | восстановлены; старый validator PASS |
| Повторный apply → latency/error/empty/keyboard tests → rollback | PASS, по 1 commit на операцию |
| Fresh old UI после rollback | canonical labels и Argentina Header восстановлены, screenshot сохранён |

Первый экземпляр оставлен как evidence conflict; он не выдаётся за успешно
откаченный. Второй заканчивает этап в old-contract state, не в candidate state.

**Adapter намеренно gated только на isolated SQLite path.** Он отказывает при
production PostgreSQL URL или другом SQLite path. Это не готовая live CLI
команда: PostgreSQL adapter с target authorization/row locks потребует
отдельной проверки перед будущим разрешением. Снимать gate простым удалением
проверки нельзя.

## 6. Mapping drift и сравнение canonical suffix

Exact map пригодна для текущего frozen StatsBomb контекста, но хрупка для
изменяющихся feeds. Unit tests показали: rename, date correction или score
correction требуют **STALE_DISPLAY_MAPPING**, duplicate key/label и reassignment
не принимаются. Source не изменялся для этих тестов.

Новый checker выполняет freshness fence при проверке. Сам query guard не
обновляет map автоматически и **не является постоянным монитором**: если source
поменяется после apply, уже сохранённый старый selection может ещё разрешаться
в прежний canonical key, а новые options — не совпасть с map. Нельзя обещать
полную runtime drift safety без frozen-source policy/повторной проверки.

| Вариант | Плюсы | Ограничения |
| --- | --- | --- |
| Approved clean label + 98-entry map | чистая подпись, exact identity, проверен реальный UI | versioned lookup требует регенерации guards при corrections; длинный guard |
| Friendly text + видимый `[competition/season/match]` suffix | canonical reference видна; guard может разбирать только строгий canonical suffix, не зависеть от текста | нужен новый reviewed guard и escaping/validation tests; stale display selection всё равно требует UX handling; ID остаётся видимым |

Для долгоживущего изменяющегося источника стоит согласовать более простой
suffix-вариант либо настоящий отдельный label/value plugin. **Ни один не
подставлен автоматически** вместо approved candidate. Для frozen historical
выборки exact-map вариант допустим только при явном source/mapping gate.

## 7. Тесты и границы результата

- **41 tests PASS** на Windows Python **3.12.10**, отдельно 41 PASS на host
  Python **3.14.3**: new protocol/adapter, legacy safety/foundation, documentation.
- Real Superset validators/ORM/browser работают на Linux Python **3.10.19**.
  Это не заявление о выполнении Python 3.10.12 или 3.12.14 CI matrix.
- Tested: scope, conflicts по всем 22 paths, replay, partial failure rollback,
  protected identity, runtime color merge, отказ production target, transaction
  ownership, lock failure, mapping corrections. Никаких skips за PASS не выдано.
- Ruff, compileall, existing repository/security/workflow contracts — PASS.
- Documentation links, local secret-signature scan и diff checks — PASS.
- **UI quality gate — FAIL/BLOCKED**, несмотря на успешный SQL и rollback.

Новые scripts/modules/tests ещё не staged. CI публикационная полнота и GitHub
CI этого snapshot не заявляются выполненными.

## 8. Minimal future live application plan — НЕ выполнялся

1. Исправить/согласовать **новую** candidate revision отдельно от четырёх UX-1
   файлов: высота Summary/Markdown, pagination/focus для kicks, mobile policy и
   contrast. Не лечить это снижением quality gates или скрытием axes findings.
2. Выбрать exact-map с frozen-source policy либо reviewed canonical suffix.
   Повторить real UI acceptance обновлённой версии и выдать новые hashes.
3. Подготовить/протестировать PostgreSQL adapter в отдельной test metadata DB:
   row locks/CAS, pinned target identity, explicit authorization, один commit,
   inverse patch и отказ на concurrent operator edits.
4. **До live write** создать durable scoped backup вне `.tmp`/контейнера:
   например отдельный private operations directory
   `%LOCALAPPDATA%\FootballOperationsVault\superset\<change-id>` с owner-only ACL,
   no-overwrite и SHA-256 manifest. Он не должен быть recovery-key directory.
   Сохранить scoped config и protected identity manifest без connection secrets/
   users/passwords; проверить чтение и восстановление в isolated DB. Вторую
   защищённую копию и retention согласовать с оператором. Сейчас такой каталог
   и backup не создавались; temporary export не считается достаточным.
5. Получить отдельное операторское разрешение и metadata editing quiet window;
   заново проверить live before-state, source mapping, reader permissions и
   integrity baseline. Не выполнять force apply при конфликте.
6. Применить только утверждённые fields, сохранить runtime cache по принятой
   политике, прогнать validators и UI smoke; при rollback вернуть versioned
   old fields и проверить old validator. Не менять identities, credentials,
   IAM, source tables или остальные dashboards.

## 9. Git, изменённые файлы и production preservation

Изменены/созданы этим этапом ровно следующие repository files:

1. `scripts/superset_semantic_safety.py` — modified, backward-compatible CLI.
2. `scripts/superset_ux_validate.py` — new validator.
3. `scripts/superset_ux_metadata.py` — isolated-only adapter.
4. `src/analytics/superset_ux.py` — pinned bundle/CAS protocol.
5. `tests/test_superset_ux.py` — offline protocol/adapter tests.
6. `docs/superset-match-analysis-ux-acceptance.md` — этот отчёт.

Ignored launchers, fixtures и browser evidence — `.tmp/superset-ux-2/` и
`.tmp/superset_ux2_*`; не публиковать автоматически. Scoped bundle остаётся
в `.tmp/superset-ux-1/`; четыре original hashes сохранены.

Свежая read-only проверка live Superset config/domain export совпала с UX-1
`before.json`. Свежие **98 analysis hashes, 12 ClickHouse physical tables /
22 build groups, 5 PostgreSQL catalogs** совпали с сохранённым baseline.
Production Web/API identity не изменилась. OpenFootball source/Gold,
backup K:, restore directory F: и recovery keys не открывались.

В index по-прежнему только два licensing documents:

| Документ | Blob ID |
| --- | --- |
| `docs/stage9c5-provider-comparison.md` | `fac8b0073dc67bab8f5341b4304036ea78d91e54` |
| `docs/stage9c5-provider-licensing-review.md` | `6fe2394c0dc11ded3199c5e7d75c173d96bc9ddd` |

Planning docs, оба предыдущих audit/review отчёта и unrelated shortcut
сохранены. Staging/commit/push не выполнялись. Git worktree **не чистое**:
это ожидаемые local changes плюс прежние staged/untracked документы.

**Итог: BLOCKED для live apply.** Изолированный proof получен, writer/rollback
проверен, но UX defects и недостающий production-adapter/durable-backup gate
не позволяют честно объявить live readiness. Остановлено до live изменений.
