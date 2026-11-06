# SUPERSET-UX-1: Match Analysis — диагностика и предложение UX-исправления

Дата проверки: **2026-11-06**. Baseline `master`:
`d3443f77c24445c3d2fb0978c10d0b57155561e8`.

**Диагностика и изолированная проверка config proposal: READY.**
**Live-применение: НЕ ВЫПОЛНЕНО; требуется отдельное разрешение и gates ниже.**
Новый dashboard не создавался. Live Superset metadata, ClickHouse, PostgreSQL,
Web/API, Airflow и OpenFootball ETL/Gold не изменялись. Stage 8C — PARTIAL,
PET-3D — NOT STARTED.

## 1. Причина технических подписей

Технический префикс намеренно введён действующим
[semantic contract](../src/analytics/superset_safety.py), а не получен из
повреждённых идентификаторов. Native Match filter использует calculated column
`match_identity` dataset 5 (`bi_match_overview`):

```sql
concat(toString(competition_id), '/', toString(season_id), '/',
       toString(match_id), ' | ', match_label)
```

`match_label` формируется в
[ClickHouse view](../infrastructure/clickhouse/migrations/012_create_match_analysis_views.sql):

```sql
concat(toString(r.match_date), ' | ', r.home_team_name, ' - ', r.away_team_name)
```

`r` — `football.match_results`; view соединяет его с `football.matches` по
**всем трём** полям competition/season/match. Состав подписи Сербия—Швейцария:

| Компонент | Источник / смысл |
| --- | --- |
| `43` | StatsBomb `competition_id`, ЧМ |
| `106` | StatsBomb `season_id`, контекст ЧМ-2022 |
| `3857256` | canonical `match_id`, Сербия—Швейцария |
| `/` | разделители составного ключа |
| ` | ` перед датой | разделитель identity и display label из calculated column |
| `2022-12-02` | `match_results.match_date`, ISO-представление Date |
| ` | Serbia - Switzerland` | исходные названия home/away teams, добавленные view |

Полное действующее значение:
`43/106/3857256 | 2022-12-02 | Serbia - Switzerland`.
Счёт в него **не включён**, хотя результат доступен отдельно.

Native filter targets dataset 5 / `match_identity`; scope — весь `ROOT_ID`,
`excluded=[]`, `chartsInScope=[9,10,11,12,13,14,15,16]`. Один выбор, без
creatable/multiSelect/inverseSelection. Default — Аргентина—Франция.
Восемь charts имеют постоянный Jinja guard: пустой, множественный или
некорректный выбор возвращает `0=1`; значение экранируется через `where_in`.
Удалять этот guard ради красивой подписи нельзя.

## 2. Проверенные матчи и причина пустых shootout charts

Read-only проверены фактические overview и period-5 записи
[shootout view](../infrastructure/clickhouse/migrations/013_create_match_visual_analysis_views.sql).

| Матч | Canonical scope | Итог игры | Shootout rows / итог серии | Классификация |
| --- | --- | --- | --- | --- |
| Сербия—Швейцария, 02.12.2022 | `43/106/3857256` | 2:3 | 0 / не было | NOT_APPLICABLE |
| Нидерланды—Эквадор, 25.11.2022 | `43/106/3857274` | 1:1 | 0 / не было | NOT_APPLICABLE |
| Аргентина—Франция, 18.12.2022 | `43/106/3869685` | 3:3 после игрового времени, включая ET | 8 / 4:2 | DATA_AVAILABLE |
| Bayer Leverkusen—RB Leipzig, 19.08.2023 | `9/281/3895052` | 3:2 | 0 / не было | NOT_APPLICABLE |

В финале: по 4 попытки каждой команды, 4 и 2 гола; все 8 записей имеют period 5.
По всему текущему контексту: **5 shootout matches / 41 попытка**, их counts
согласованы с overview. Среди 98 матчей **93 NOT_APPLICABLE**, **5 DATA_AVAILABLE**;
реальный NO_DATA в этой проверке не обнаружен.

Точные причины пустоты двух блоков:

- **Chart 13, Penalty Shootout**, dataset 11: источник содержит исключительно
  `is_shootout=1`, то есть period 5. Если серии не было, строк нет по определению.
- **Chart 14, Shootout Summary**, dataset 5: кроме Match guard сохранён явный
  SQL filter `result_method = 'PENALTIES'`. Он отсекает нормальные матчи,
  поэтому summary тоже пуст, хотя overview выбранного матча существует.

Это не повреждение IDs, потеря матчей или воспроизведённая SQL-ошибка. Текущая
пустота не объясняется в UI, а большие фиксированные размеры блоков усиливают
впечатление поломки. Старые высоты: Summary 20 и Penalty Shootout 43 grid units.

## 3. Читаемые названия без изменения identity

Проверенный формат предложения:

- `Serbia 2:3 Switzerland · 02.12.2022`
- `Netherlands 1:1 Ecuador · 25.11.2022`
- `Argentina 3:3 France · 18.12.2022 (pens 4:2)`

Названия сохранены **как в StatsBomb**, без fuzzy matching и автоматического
перевода. Русский вариант `Сербия 2:3 Швейцария · 02.12.2022` возможен через
отдельный явный team-ID dictionary; такой словарь для всех команд здесь не
добавлялся. Не следует выдавать русские примеры за уже локализованный Superset.

SQL display expression в candidate:

```sql
concat(
  home_team_name,
  if(isNull(home_score) OR isNull(away_score)
     OR result_method NOT IN ('REGULATION','DRAW','PENALTIES'),
     ' — ', concat(' ', toString(home_score), ':', toString(away_score), ' ')),
  away_team_name, ' · ', formatDateTime(match_date, '%d.%m.%Y'),
  if(result_method = 'PENALTIES',
     concat(' (pens ', toString(home_shootout_goals), ':',
            toString(away_shootout_goals), ')'),
     if(went_to_extra_time, ' (aet)', ''))
)
```

При NULL score или неизвестном result method счёт не выдумывается: проверенный
synthetic пример — `Home — Away · 01.01.2022`, в том числе при placeholder 0:0
и `result_method='UNKNOWN'`. Текущие 98 результатов используют три разрешённых
выше method values. Новый method потребует review, а не автоматического 0:0.
Игровой итог не выдаётся за отдельный 90-minute score; серия выделена суффиксом.

### Ограничение штатного native Select

В Superset 6.0.0 штатный Select строит option label из значения выбранного
столбца; простая подмена `verbose_name` переименует колонку, но не строки.
Произвольный независимый per-row label/value contract этим control panel не
предоставлен. Проверены первичные исходники тега 6.0.0:
[SelectFilterPlugin](https://github.com/apache/superset/blob/6.0.0/superset-frontend/src/filters/components/Select/SelectFilterPlugin.tsx#L281),
[controlPanel](https://github.com/apache/superset/blob/6.0.0/superset-frontend/src/filters/components/Select/controlPanel.ts).
Это обоснование предлагаемой mapping, а не заявление о невозможности написать
отдельный custom plugin. Custom plugin для этой задачи не предлагается.

## 4. Минимальный проверенный config proposal

Изменения подготовлены **только в изолированной DTO-копии**, не в ORM-объектах
живой metadata session. Полный field-level diff локален:
`.tmp/superset-ux-1/config-patch.json`. Он содержит **22 изменённых поля**:

| Объект | Изменение |
| --- | --- |
| Dataset 5 | Только Superset metadata: virtual SELECT поверх существующего overview с LEFT JOIN агрегата shootout; сохранить все `o.*`, добавить `match_display` и `shootout_status` |
| Native Match filter | Target `match_display` вместо `match_identity`, человекочитаемый default; тот же single-select и scope всех 8 charts |
| Charts 9–16 | Заменить только Match guard одновременно в params / saved query context / form_data |
| Chart 14 | Убрать только `result_method='PENALTIES'`; добавить status; без серии goals/winner показывать NULL, а не фиктивные 0:0 или победителя игры как победителя серии |
| Chart 13 | Сохранить реальные period-5 rows и их порядок; добавить описание нормального отсутствия серии |
| Dashboard 2 layout | Summary: height 20→12, width 8→12; kicks: height 43→20, width 8→12; короткая штатная Markdown-памятка перед Summary |

Другие 11 datasets, dashboard 1 и charts 1–8 в proposal **не изменены**.
Аналитические колонки/метрики charts 9–12 и 15–16 сохранены. Сама
`match_identity` column и исходные canonical IDs не изменены.

Минимальный структурный diff (сокращённый, **не исполняемый apply script**):

```diff
 dataset[5]:
-  sql: null
+  sql: SELECT o.*, <display SQL> AS match_display,
+              <reconciled status CASE> AS shootout_status
+       FROM football.bi_match_overview o
+       LEFT JOIN (<attempt/goal counts BY competition,season,match>
+                  FROM football.bi_match_shootout) s
+       USING (competition_id,season_id,match_id)
+  columns: [...unchanged..., match_display, shootout_status]
 native Match:
-  column: match_identity
+  column: match_display
 charts[9..16]:
-  guard: selected technical label IN escaped selection
+  guard: selected friendly label -> exact canonical key -> escaped key IN
 chart[14]:
-  where: result_method='PENALTIES' AND MatchGuard
+  where: MatchGuard
+  columns: shootout_status, home, nullable shootout goals, away, nullable winner
 dashboard[2]:
+  compact fixed-height shootout blocks + explanatory Markdown
```

### Почему именно такой guard

Установленный Superset отверг попытку подзапроса в **adhoc WHERE** по действующей
security policy. `ALLOW_ADHOC_SUBQUERY` и остальные защиты **не менялись**.
Поэтому trusted virtual datasource SQL выполняет status reconciliation, а
Jinja guard использует bounded **98-entry exact display→canonical-key map**.
Она построена из read-only SELECT и проверена на 98 уникальных значений.

Алгоритм guard: ровно один `IN` filter / одно string value из mapping → lookup
ключа `competition/season/match` → SQL `concat(...) IN ...|where_in`.
`get_filters('match_display', remove_filter=True)` потребляет display filter,
чтобы он не применялся как несуществующая physical column к другим datasets.
Пустой, неизвестный, inverse, multiple или повторённый filter → `0=1`.
Никакой поиск по похожему названию команды/матча не используется.

Mapping — **versioned snapshot**, не бесконечно актуальный справочник. Перед
будущим применением обязательны проверка source/mapping fingerprint,
однозначности и актуальности default. Новая дата/исправленный score или новый
матч требуют атомарной регенерации mapping/guards. Устаревшие display values
не должны разрешаться по fuzzy fallback. Старые bookmarks/filter-state могут
стать пустыми: нужно сбросить выбор, а не ослаблять guard.

Это больше, чем замена текста caption: штатный Select не отделяет display от
value. Более дешёвый вариант — оставить canonical suffix видимым после
человеческого названия; он не даёт полностью чистого предложенного формата.
Изменение ClickHouse views или новый frontend plugin для этого не требуется.

## 5. Семантика shootout state и размеры

| State | Условие / поведение |
| --- | --- |
| NOT_APPLICABLE | `went_to_penalties=false`, method не PENALTIES, фактических kicks нет |
| DATA_AVAILABLE | оба признака серии согласованы, kicks > 0, фактическое число попыток и goals обеих команд совпадают с overview |
| NO_DATA | ожидание серии/количество/голы/flags противоречат фактическим записям; не подменять нулями |
| QUERY_ERROR | ошибка выполнения запроса; сохранять error state Superset, не преобразовывать в пустой DataFrame/NOT_APPLICABLE |

Status рассчитывается из LEFT JOIN с агрегатом **реальных** kicks, не только из
флага overview. Synthetic records в production не создаются. Summary показывает
одну строку и для обычного матча. Для Penalty Shootout остаётся штатная пустая
таблица с постоянной понятной памяткой рядом.

**Условное скрытие charts по результату фильтра не подтверждено** и в solution
не используется. Размеры фиксированные, для длинной серии допустим scroll без
потери строк. Если владельцу нужен полностью отдельный сценарий просмотра,
Shootout dashboard/tab можно обсудить отдельно; сейчас новый dashboard не нужен.

## 6. Что проверено изолированно

Экспортированы безопасные domain config поля 16 charts / 12 datasets / двух
dashboards. Не экспортированы database URI, secrets, users, passwords, cookies
или полный Superset configuration. Экспорт — не штатный ZIP для слепого импорта.

Из DTO созданы **detached** SqlaTable/TableColumn/metric objects. Запросы
candidate прошли через **установленный compiler/executor Superset 6.0.0** и
настоящий configured ClickHouse reader. Это не только вручную написанный SQL.
Metadata transaction read-only; autoflush запрещён; theme startup sync и query
audit INSERTs отключены только в diagnostic process; session rollback в конце.
`session.dirty/new/deleted` пусты; ORM live objects не переписывались.

| Проверка | Результат |
| --- | --- |
| Options | 98 rows / 98 unique display labels, canonical scopes сохранены |
| 4 матча × 8 charts | 32 cases PASS, включая два требуемых обычных матча, финал и Bundesliga |
| Сравнение неизменённой аналитики | 24 DataFrame equality checks PASS для Header/Team/Player/Shots/xG/Shot Map |
| Invalid/empty/multiple/inverse/duplicate/injection-like selection × 7 datasets | 35 cases PASS, пусто, без leakage |
| Shootout status по 98 матчам | 93 NOT_APPLICABLE / 5 DATA_AVAILABLE, без потери матчей |
| Synthetic status cases | 7 PASS: normal/available/missing/partial/goal mismatch/stray kicks/flag mismatch |
| NULL score и UNKNOWN result с placeholder 0:0 | 2 PASS, score не отображается |
| Reverse config patch | точное равенство исходной DTO-копии, PASS |
| Текущий live semantic validator | 8 Overview chart cases / 40 Match cases / 2 native option cases PASS |
| Superset foundation/safety + documentation unit tests | 24 PASS, host Python 3.14.3 |
| Repository/workflow/private-artifact/secret-signature checks | PASS |

Фактические размеры результатов candidate:

| Match ID | Header | Team | Player rows | Shots | Kicks | Summary | xG series points | Shot Map |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3857256 | 1 | 2 | 49 | 26 | 0 | 1, NOT_APPLICABLE | 52 | 26 |
| 3857274 | 1 | 2 | 52 | 17 | 0 | 1, NOT_APPLICABLE | 34 | 17 |
| 3869685 | 1 | 2 | 50 | 30 | 8 | 1, DATA_AVAILABLE | 60 | 30 |
| 3895052 | 1 | 2 | 40 | 25 | 0 | 1, NOT_APPLICABLE | 50 | 25 |

Количество xG points не является количеством уникальных shots: existing series
формирует две командные траектории. Метрика и её семантика не менялись.

### Screenshots: важная граница доказательства

Получены **6 screenshots** — три матча × desktop 1440×1100 / mobile 390×844:
`.tmp/superset-ux-1/preview-<match_id>-<desktop|mobile>.png`.
Визуально просмотрены desktop финал и mobile Сербия—Швейцария.
Preview использует реальные результаты candidate SELECT и явно помечен
**ISOLATED CONFIGURATION PREVIEW — not the Superset UI**.

Chromium/Chrome запущен в новом временном context с отключёнными extensions;
обычный профиль/Bitwarden не использовался. Сетевые обращения preview запрещены:
0 HTTP requests. Проверены переключение матчей, keyboard и axe для шести
состояний: 0 axe violations, нет горизонтального page overflow.

Это **не screenshot реально импортированного dashboard** и не доказательство
визуальной приемки Superset native filter, layout, role permissions, stale
responses или error banner. Такие тесты в отдельном Superset UI окружении ещё
нужны перед live apply. UI для QUERY_ERROR здесь не воспроизводился: успешные
запросы не создавали ошибок, а ошибки диагностических экспериментов не
преобразовывались в нормальную пустоту.

## 7. Rollback и gates перед будущим live apply

До изолированной правки сохранён local non-secret export:
`.tmp/superset-ux-1/before.json`, SHA-256:
`37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86`.

Подготовлены:

- `candidate-config.json`, SHA-256
  `4f8f923deddb2bb3108b65145f565580ba78606f8105b156e5617a5996464514`;
- `config-patch.json`, SHA-256
  `7e030c99a6b1c82d1f7afa30dbd3a578f68d4319c0d56fc37473cf915a71851d`;
- `rollback-fields.json`, SHA-256
  `91e99eb42f9acc53a46d198842dd58e7516896e07dcbaa97862a26c151c82c34`.

Forward/reverse 22-field patch roundtrip проверен **на копии**, fingerprint
исходного содержимого восстановлен полностью. Файл rollback содержит before
значения и ожидаемые after значения для compare-and-swap; это план, **не
проверенный production restore metadata DB**. Не удалять эти ignored artifacts.

Перед применением требуются:

1. Отдельное разрешение и quiet window для редактирования Superset metadata;
   заново получить trusted export, сравнить все изменяемые поля с before.
2. Проверить source/label uniqueness и versioned mapping; запретить stale apply.
3. В отдельном Superset UI окружении проверить настоящий native filter,
   layout/Markdown, оба обычных матча, финал, empty/error/late responses и роли.
4. Минимально обновить semantic checker/tests **под новую версию контракта**:
   опубликованный checker требует прежний guard и physical dataset 5 и правильно
   отвергнет candidate. Не ослаблять проверки и **не запускать старый `--apply`**
   поверх нового config: он рассчитан на другой контракт. Эти исходники сейчас
   не изменены.
5. Подготовить проверенный транзакционный targeted writer/rollback: один commit
   metadata transaction, assert expected before, сохранить ID/UUID/owners,
   разрешить только 22 поля; никаких users/DB credentials/RBAC/import overwrite.
   Физические ClickHouse views/tables не трогать.
6. Проверить rollback в том же isolated metadata окружении с настоящим ORM
   writer. При конфликте after-state остановиться, не перезаписывать чужие edits.
   Откат: вернуть прежние chart params/query contexts/descriptions, filter/default/
   layout и physical dataset 5; убрать только два добавленных metadata columns.
   Затем повторить старый semantic validator. Нужен durable защищённый backup
   scoped configuration перед live change, не только временный путь из отчёта.

**Можно ли безопасно применять сейчас? Нет, не как готовый production apply.**
SQL/mapping и обратимость DTO доказаны, но настоящий isolated Superset UI
acceptance, transactional writer/rollback и новый semantic contract пока не
выполнены. Диагностика и предложение готовы к review; live repair не заявлен.

## 8. Сохранность данных и Git

Свежие production fingerprints до/после совпали полностью:
**98 analysis hashes / 12 ClickHouse physical tables, schemas и 22 build groups /
5 PostgreSQL catalogs**. Production Web/API identity также не изменилась.
Повторные `before.json` / `after.json` / `final.json` подтвердили равенство live
dashboard/chart/dataset metadata и domain source exports.

Application/ETL/semantic source code не изменён; migrations, ingestion, deployment,
staging, commit/push и Docker lifecycle операции не выполнялись. OpenFootball
Gold, S3, K: backup, внешний restore F: и recovery keys не открывались.
API tokens, Bitwarden и пользовательский browser profile не читались.

Новый документ этого этапа: `docs/superset-match-analysis-ux-review.md`, untracked.
Ignored helpers/exports/screenshots находятся в `.tmp`; не публиковать их
автоматически. Существующий `docs/infra-audit-2026-11.md`, planning documents и
shortcut сохранены. Staged по-прежнему только:

| Документ | Неизменённый blob ID |
| --- | --- |
| `docs/stage9c5-provider-comparison.md` | `fac8b0073dc67bab8f5341b4304036ea78d91e54` |
| `docs/stage9c5-provider-licensing-review.md` | `6fe2394c0dc11ded3199c5e7d75c173d96bc9ddd` |

Следующий минимальный этап — отдельный **SUPERSET-UX-2 isolated UI/config
acceptance и transactional patch preparation**, без изменения production до
прохождения gates и нового операторского разрешения.
