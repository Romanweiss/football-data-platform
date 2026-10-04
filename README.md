# Football Data Platform

## Stage 6B-2 — Real multi-context onboarding

WC2022 (`43/106`) and StatsBomb Bundesliga 2023/2024 (`9/281`) now coexist in
Bronze/Silver/Gold, the approved ClickHouse serving tables and API/React catalogs.
9/281 is the **34 available Bayer Leverkusen matches**, not the complete league:
18 teams, 460 players, 137765 events, 39214 passes, 916 normal shots,
110 shot goals and xG 100.5025969706; no extra time or shootout.

All seven Silver and three Gold builds passed DQ and explicit-input validation.
All ten loads registered, then repeated as `UNCHANGED / ALREADY_LOADED` without
row/catalog growth. WC2022 counts, served build IDs and all 64 analysis-response
hashes are unchanged. Real 9/281 frontend navigation/interactions and mobile/
desktop acceptance passed; no backend/frontend runtime semantics changed.

Bronze GET uses three transient-only attempts with 1s/2s backoff and verified TLS;
resume verifies/reuses cataloged immutable children rather than downloading their
source again. Full evidence, exact build IDs and runbook pins:
[Stage 6B-2](docs/stage6b2.md).

**Immediate BI follow-up:** World Cup 2022 Overview's eight Superset charts lack
fixed 43/106 filters and can now mix both contexts (98 unfiltered matches).
Match Analysis also needs an enforced selected-match guard. Superset was audited
read-only and not modified; its WC dashboard is not certified semantically safe.

## Stage 6B-1 — Context-explicit ETL preparation

Bronze/Silver/Gold orchestration and loaders now require explicit competition/season
and immutable input references. WC2022 remains the pinned golden regression.
At the end of 6B-1 no second context had been published or loaded; real coexistence
has since been verified in Stage 6B-2 above.

The selected context was StatsBomb 1. Bundesliga 2023/2024 (`9/281`), the 34
available Bayer Leverkusen matches, **not** the complete league season.
Public source preflight found all 34 events and 34 lineups files.
Container connectivity has been intermittent; the runbook requires a successful
fresh source preflight before any Stage 6B-2 write.

See [Stage 6B-1 audit, evidence and exact Stage 6B-2 runbook](docs/stage6b1.md).
That runbook supersedes historical ETL/load commands below: new invocations need
`--competition-id`, `--season-id`, exact parent/build pins and (for Bronze children)
`--bronze-max-id`. Historical stage sections retain their original verification context.

## Stage 6A — Multi-competition / multi-season foundation

Application context is now explicit: competition → season → match. Catalogs come
from available `football.bi_match_overview` rows, not a hardcoded WC2022 registry.
The serving schema currently has IDs but no authoritative competition/season
names, so the UI uses localized ID labels.

Canonical frontend URL: `/competitions/43/seasons/106/matches/3869685`.
The API adds `/api/v1` and supports all existing match sections, including
`/analysis`. Legacy `/matches/<id>` links resolve only unambiguous IDs.
The root selects the first catalog competition/season and chronologically first
match; it does not assume 43/106. Search stays local to the selected context.

Generic validators now require `--competition-id` and `--season-id`.
WC2022 remains a named golden regression, not a universal count rule.
Stage 6A live verification covered 43/106 only; 9/281 is now verified in 6B-2.
The original Bronze/Silver/Gold blockers are addressed in Stage 6B-1;
real second-context onboarding and proof are recorded in Stage 6B-2 above.

See [Stage 6A](docs/stage6a.md) for contracts, compatibility, context audit,
verification results, manual commands and the Stage 6B onboarding checklist.

Учебный production-like Data Engineering проект для поэтапного построения платформы футбольных данных. На первом этапе репозиторий содержит только локальную инфраструктуру и основу структуры исходного кода: PostgreSQL, ClickHouse и одноразовый Python-контейнер для безопасной проверки подключения к внешнему Selectel S3.

## Компоненты и их роли

### PostgreSQL

PostgreSQL — операционная база `football_metadata`. В ней будут храниться:

- метаданные;
- конфигурация;
- сопоставления сущностей из разных источников;
- позднее — данные backend/application-части.

При первом создании локального volume init-скрипт создаёт пустую схему `metadata`. Таблиц предметной области на этом этапе нет.

Stage 1C добавляет каталог `metadata.ingestion_objects` отдельной ручной миграцией.
Он хранит успешно обнаруженные immutable S3 artifacts, а не историю запусков ingestion.

### ClickHouse

ClickHouse — аналитическая база `football`. В следующих этапах она будет хранить:

- матчи;
- события матчей;
- статистику игроков;
- статистику команд;
- аналитические агрегаты.

При первом создании локального volume init-скрипт гарантирует наличие базы `football`. Таблиц пока нет.

### Selectel S3

Внешний S3-compatible Object Storage Selectel играет роль Data Lake. Локальный S3-сервер не запускается. Планируемый поток данных:

```text
Source -> S3 Bronze -> processing -> S3 Silver -> ClickHouse / Gold
```

Уровни озера:

- `bronze` — исходные данные без бизнес-преобразований;
- `silver` — очищенные и нормализованные данные;
- `gold` — подготовленные аналитические наборы и агрегаты.

Планируемая структура объектов:

```text
s3://<bucket>/football/
    bronze/
        kaggle/
        statsbomb/
        api_football/

    silver/
        matches/
        teams/
        players/
        events/

    gold/
        team_statistics/
        player_statistics/
        standings/
```

Эта структура документирует convention и не создаётся автоматически. Проверка `check_s3.py` выполняет только read-only запрос. По ручным командам roundtrip-тест записывает один тестовый объект, а StatsBomb ingestion сохраняет два исходных JSON в существующий bucket.

### Docker Compose

Docker Compose описывает и изолирует локальные сервисы проекта:

- `football-postgres` — PostgreSQL 17;
- `football-clickhouse` — ClickHouse Server;
- `football-python-tools` — одноразовый Python 3.12 tools-контейнер.

PostgreSQL и ClickHouse используют restart policy `unless-stopped` и healthcheck без искусственных задержек. Python tools не является постоянно работающим сервисом: он запускается только на время команды через `docker compose run --rm` и удаляется после завершения.

Все контейнеры подключены к bridge-сети `football-network`. Постоянные локальные данные хранятся в named volumes `football_postgres_data` и `football_clickhouse_data`.

## HOST port и CONTAINER port

`CONTAINER port` — порт процесса внутри Docker-сети. Другие контейнеры обращаются к сервису по имени и этому порту, например `football-postgres:5432`.

`HOST port` — порт Windows-компьютера, перенаправленный в контейнер. Он нужен клиентам, запущенным на хосте, например DBeaver. HOST-порты вынесены в `.env`, чтобы их можно было поменять без редактирования `compose.yaml`.

| Сервис | HOST port по умолчанию | CONTAINER port | Назначение |
|---|---:|---:|---|
| PostgreSQL | `15436` | `5432` | PostgreSQL protocol |
| ClickHouse | `18124` | `8123` | HTTP interface |
| ClickHouse | `19001` | `9000` | Native protocol |

## Настройка окружения

В репозитории хранится только `.env.example` с placeholders. Создайте локальный `.env` и замените `change_me`, `<pool>` и остальные значения на реальные. Файл `.env` игнорируется Git; не добавляйте в репозиторий пароли и S3-ключи.

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Значение `S3_REGION` не обязано быть `ru-1`: используйте pool/region, выданный для вашего Selectel S3. Endpoint также должен соответствовать этому pool.

## Команды

Проверить Compose-конфигурацию без вывода значений credentials:

```bash
docker compose config -q
```

Собрать образ одноразовых Python-инструментов:

```bash
docker compose build football-python-tools
```

Запустить PostgreSQL и ClickHouse:

```bash
docker compose up -d football-postgres football-clickhouse
```

Проверить состояние и healthcheck сервисов:

```bash
docker compose ps
```

Посмотреть общие логи:

```bash
docker compose logs
```

Посмотреть логи отдельного сервиса:

```bash
docker compose logs football-postgres
docker compose logs football-clickhouse
```

Проверить доступ к существующему Selectel S3 bucket безопасной read-only операцией `head_bucket`:

```bash
docker compose run --rm football-python-tools python scripts/check_s3.py
```

Скрипт получает настройки только из environment variables, не выводит ключи и ничего не создаёт, не изменяет и не удаляет. Успех означает, что указанный bucket доступен данным credentials. При ошибке команда возвращает ненулевой exit code.

Остановить и удалить контейнеры и сеть текущего Compose-проекта, сохранив локальные данные в volumes:

```bash
docker compose down
```

Полностью удалить контейнеры, сеть и **локальные данные PostgreSQL и ClickHouse**:

```bash
docker compose down -v
```

> **Осторожно:** `docker compose down -v` безвозвратно удаляет named volumes `football_postgres_data` и `football_clickhouse_data`. Команда не удаляет и не изменяет данные во внешнем Selectel S3.

## S3 Bronze roundtrip test

Минимальный тест проверяет полный путь данных:

```text
data/samples/sample_match.json (исходные bytes)
    -> put_object -> Selectel S3 Bronze -> get_object
    -> скачанные bytes -> сравнение SHA-256
```

Bucket — контейнер объектов в S3; его имя берётся из `S3_BUCKET`.
Object key — имя объекта внутри bucket. Для этого теста оно фиксировано:
`football/bronze/_tests/s3_roundtrip/sample_match.json`. Имя bucket не входит в key.
Часть `football/bronze/...` — это prefix object key, а не настоящая директория S3:
символ `/` используется для удобной группировки объектов.

Скрипт читает небольшой JSON с вымышленным матчем как bytes и передаёт их без
повторной сериализации через `put_object`. Объект получает
`ContentType="application/json"` и metadata `source=local-sample`, `layer=bronze`.
После `get_object` скрипт сравнивает SHA-256 исходных и скачанных bytes.
Совпадение хэшей подтверждает, что данные прошли этот путь без изменения;
при несовпадении команда завершается с ненулевым exit code.

RAW/Bronze слой должен сохранять исходные данные, чтобы можно было повторить
обработку, исправить ошибки преобразования и сверить результат с источником.
Поэтому этот тест не нормализует JSON и не меняет его форматирование.

Запускать вручную из корня проекта при настроенных S3 environment variables:

```bash
docker compose run --rm football-python-tools python scripts/test_s3_roundtrip.py
```

Нужны права на запись и чтение этого test object в существующем bucket.
При успехе выводятся `S3 roundtrip successful`, bucket, key, размер в bytes и SHA-256.
Объект остаётся в S3; повторный запуск перезаписывает тот же key. Скрипт не удаляет
объекты, не создаёт bucket и не меняет Bucket Policy или IAM.
TLS-проверка и `AWS_CA_BUNDLE` сохраняются; общий S3 helper использует SigV4
и virtual hosted addressing. `scripts/check_s3.py` остаётся read-only проверкой
доступности bucket через `head_bucket`.

## StatsBomb Bronze ingestion

Первый ingestion реальных данных сохраняет два файла StatsBomb Open Data:

- [competitions.json](https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json)
  → `football/bronze/statsbomb/competitions/sha256=<FULL_SHA256>/competitions.json`.
- [FIFA World Cup 2022 matches](https://raw.githubusercontent.com/hudl/open-data/master/data/matches/43/106.json)
  (`competition_id=43`, `season_id=106`)
  → `football/bronze/statsbomb/matches/competition_id=43/season_id=106/sha256=<FULL_SHA256>/matches.json`.

```text
Source -> HTTP download -> raw bytes -> SHA-256 -> immutable S3 Bronze object
    -> confirmed object -> PostgreSQL metadata catalog
```

HTTP helper использует стандартный `urllib.request`, User-Agent проекта,
таймаут 30 секунд и включённую TLS-проверку. Ответ должен иметь статус `200`.
Скрипт не парсит JSON, не меняет пробелы или кодировку и не сериализует данные
заново: в `put_object` передаются ровно те bytes, которые получены по HTTP.
RAW/Bronze сохраняет оригинал для повторной обработки и сверки с источником.

Bucket берётся из `S3_BUCKET`; его имя не добавляется в object key.
Используется существующий общий S3 helper с SigV4, virtual hosted addressing
и настроенным `AWS_CA_BUNDLE`.
Объект получает `ContentType="application/json"` и metadata:
`source=statsbomb`, `layer=bronze`, `sha256=<checksum>`, `source_url=<source URL>`,
`dataset=competitions` или `dataset=world_cup_2022_matches`.
Все metadata keys — lowercase ASCII; два фиксированных source URL также ASCII
и достаточно короткие для S3 metadata.

### Stage 1C: immutable / versioned Bronze

Версия определяется полным lowercase SHA-256 исходных bytes (64 hex-символа),
а не временем запуска. Helper `build_versioned_key()` добавляет `sha256=<checksum>`
перед именем файла и нормализует разделители `/`.

Idempotency: повторный запуск тех же данных получает тот же key, проверяет
metadata и выводит `UNCHANGED: <key>` без новой копии в S3 и без дубля в каталоге.
Immutable Bronze: если исходные bytes изменились, checksum и key станут другими;
создаётся новая версия, а старая остаётся. Оба source-файла по-прежнему скачиваются
при каждом запуске для расчёта актуальных checksums.

Перед записью `head_object` проверяет именно versioned key. Для существующего
объекта metadata `sha256` обязана совпадать с checksum источника и сегментом key.
Отсутствующая или отличающаяся metadata — ошибка integrity: объект нельзя
перезаписывать или автоматически исправлять. Его metadata также сохраняется.
Для отсутствующего объекта выполняется `put_object` и выводится `UPLOADED: <key>`.

Запись использует `IfNoneMatch="*"`, чтобы исключить перезапись, если другой запуск
успел создать объект между HEAD и PUT. При `412` выполняется повторный HEAD и
integrity check. Другие ошибки, включая `409`, завершают запуск с ошибкой;
безусловного повторного PUT нет. Поддержка условной записи описана в
[документации Selectel](https://docs.selectel.ru/s3/objects/conditional-requests/).

Старые keys без `sha256=...` остаются нетронутыми: новый ingestion их не читает,
не переносит, не удаляет и не перезаписывает. S3 versioning автоматически не включается.
Отдельный тест в `football/bronze/_tests/` сохраняет прежнее поведение roundtrip.

Ответ об отсутствии объекта (`404` / `NoSuchKey` / `NotFound`) допускает первую
запись. Ошибки доступа, отсутствующего bucket и остальные ошибки S3 не считаются
отсутствием объекта: скрипт завершается с ненулевым exit code. Для S3 ClientError
выводятся HTTP status и код ошибки, без полного сообщения с потенциальными credentials.

S3 хранит RAW bytes. PostgreSQL хранит metadata/catalog: источник, dataset,
source URL, bucket, key, checksum, размер и `first_seen_at`. ClickHouse позднее
будет хранить аналитически подготовленные данные; этот ingestion в него не пишет.

После успешного PUT или HEAD с корректной integrity выполняется параметризованный
`INSERT ... ON CONFLICT (s3_bucket, object_key) DO NOTHING` в `metadata.ingestion_objects`.
Одна immutable версия соответствует одной строке. Каждая регистрация фиксируется
отдельной транзакцией; повторная регистрация не меняет `first_seen_at` или другие поля.
Выводится `REGISTERED: <key>` либо `ALREADY_REGISTERED: <key>`.

Если S3 upload прошёл, а запись или commit PostgreSQL не удались, pipeline завершится
с ошибкой и оставит S3 object. При следующем запуске существующая версия пройдёт
integrity check, после чего недостающая запись каталога будет добавлена без повторного
upload. Уже зафиксированные строки других artifacts сохраняются. Каталог не является
`ingestion_runs`: историю запусков на этом этапе не ведём.

### Ручная подготовка Stage 1C

Python tools подключается к PostgreSQL по Docker-адресу `football-postgres:5432`.
HOST port `15436` применяется только для клиентов на хосте. Compose передаёт
`POSTGRES_HOST`, `POSTGRES_PORT` и существующие `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`; менять `.env` для этого этапа не требуется.

Пересоберите tools-образ с закреплённым `psycopg[binary]==3.3.6`:

```bash
docker compose build football-python-tools
```

В PostgreSQL добавлен read-only mount `/migrations`. Чтобы новый mount появился
в уже запущенном контейнере, вручную примените конфигурацию только этого сервиса:

```bash
docker compose up -d --no-deps --wait football-postgres
```

Compose пересоздаст контейнер PostgreSQL при изменении конфигурации, сохранив его
named volume. ClickHouse эта команда не пересоздаёт. После готовности PostgreSQL
примените SQL-миграцию вручную (ни запуск контейнера, ни ingestion её не выполняют).
Пример для стандартных имени пользователя и базы из `.env.example`:

```bash
docker compose exec football-postgres \
  psql -v ON_ERROR_STOP=1 -U football_user -d football_metadata \
  -f /migrations/001_create_ingestion_objects.sql
```

PowerShell, одной строкой:

```powershell
docker compose exec football-postgres psql -v ON_ERROR_STOP=1 -U football_user -d football_metadata -f /migrations/001_create_ingestion_objects.sql
```

Если имя пользователя или базы отличается, замените только аргументы `-U` и `-d`.
Миграция создаёт таблицу с UNIQUE по `(s3_bucket, object_key)`, CHECK для SHA-256
и размера, а также индекс `(source, dataset)`. `CREATE TABLE IF NOT EXISTS` и
`CREATE INDEX IF NOT EXISTS` позволяют повторный запуск. Старый init SQL не изменён:
он не применяется повторно к существующему volume.

Ручной запуск из корня проекта (одинаково для PowerShell и Linux/macOS):

```bash
docker compose run --rm football-python-tools python scripts/ingest_statsbomb_bronze.py
```

Для каждого объекта выводятся key, размер в bytes и SHA-256. При завершении:
`StatsBomb Bronze ingestion complete`, `Downloaded: 2`, `Uploaded: N`, `Unchanged: N`,
`Registered: N`, `Already registered: N`.
Скрипт не удаляет объекты, не создаёт bucket и не меняет Bucket Policy или IAM.
Его единственная запись в PostgreSQL — регистрация подтверждённых artifacts.

Проверки после сборки tools-образа, без реального HTTP/S3/PostgreSQL ingestion:

```bash
docker compose run --rm --no-deps football-python-tools python -m compileall src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose config -q
```

Unit-тесты используют стандартный `unittest` и mocks для HTTP, S3 и PostgreSQL.
Миграция при тестах не применяется.

## StatsBomb match fan-out ingestion

Stage 1D использует уже сохранённый parent dataset `world_cup_2022_matches`.
Источник списка матчей находится внутри платформы:

```text
PostgreSQL catalog: latest world_cup_2022_matches
    -> S3 parent object -> SHA-256 verification -> matches JSON -> unique match_id
    -> for each match: events -> S3 Bronze -> catalog
                      lineups -> S3 Bronze -> catalog
```

Fan-out ingestion означает, что один parent artifact содержит N match_id и порождает
по две дочерние задачи на матч. Child datasets: `match_events` и `match_lineups`.
Обработка последовательная: сначала events и lineups первого матча, затем второго.

Parent выбирается из `metadata.ingestion_objects` по `source=statsbomb` и
`dataset=world_cup_2022_matches` с `ORDER BY first_seen_at DESC, id DESC LIMIT 1`.
Это последняя зарегистрированная версия. На один запуск выбирается один parent;
его bucket, key и SHA-256 выводятся в логе. Bucket и key берутся из каталога,
а не из захардкоженного пути или настройки целевого bucket.
Запрос к каталогу завершает свою транзакцию до сетевого чтения.

Parent скачивается через S3 `get_object`, StreamingBody обязательно закрывается,
а SHA-256 полученных bytes сравнивается с каталогом до JSON parsing. При отсутствии
parent или нарушении integrity pipeline останавливается до загрузки children.
Matches JSON декодируется как UTF-8; root должен быть list, каждый элемент — object
с integer `match_id` (boolean не допускается). Дубликаты удаляются с сохранением
порядка первого появления. Исходные bytes parent не изменяются.

Файл `matches/43/106.json` не скачивается из GitHub повторно. Так происхождение
списка дочерних загрузок привязано к конкретному проверенному Bronze parent artifact.
Новая таблица связей или история запусков на этом этапе не добавляется.

По HTTP запрашиваются только:

- `https://raw.githubusercontent.com/hudl/open-data/master/data/events/<match_id>.json`;
- `https://raw.githubusercontent.com/hudl/open-data/master/data/lineups/<match_id>.json`.

Children сохраняются в настроенный `S3_BUCKET` без JSON parsing или повторной
сериализации. Используются общий `build_versioned_key()` и единственная реализация
`put_immutable_object()` в `src/common/bronze.py`, общая со Stage 1C:

```text
football/bronze/statsbomb/events/match_id=<id>/sha256=<FULL_SHA256>/events.json
football/bronze/statsbomb/lineups/match_id=<id>/sha256=<FULL_SHA256>/lineups.json
```

Metadata содержит `source=statsbomb`, `layer=bronze`, `dataset=match_events` или
`match_lineups`, `match_id` как строку, `sha256` и конкретный `source_url`.
После успешного immutable PUT или проверки существующего объекта вызывается
`register_ingestion_object()`. Каждая регистрация фиксируется отдельно.

При ошибке download/upload/registration выполнение останавливается; ранее
сохранённые объекты и зафиксированные строки остаются. Повторный запуск снова
проверяет источники: неизменённые children получают `UNCHANGED` и
`ALREADY_REGISTERED`. Если PUT прошёл, а registration нет, повторный запуск
добавит недостающую запись каталога без перезаписи S3 object.

Ограниченный ручной запуск — первые два уникальных match_id, до четырёх children:

```powershell
docker compose run --rm football-python-tools python scripts/ingest_statsbomb_match_data.py --limit 2
```

`--limit` принимает только integer > 0. Это реальный ingestion с записью объектов
и metadata, ограниченный числом матчей. Без `--limit` обрабатывается весь список:

```powershell
docker compose run --rm football-python-tools python scripts/ingest_statsbomb_match_data.py
```

Вывод включает `EVENTS/LINEUPS UPLOADED/UNCHANGED: match_id=<id>`, key, размер,
SHA-256 и `REGISTERED/ALREADY_REGISTERED`. Полный JSON и credentials не печатаются.
`Matches discovered` — число уникальных match_id в parent до применения limit.
Счётчики `Objects downloaded/uploaded/unchanged/registered/already registered`
относятся только к children; чтение parent в них не включается.

Текущей схемы PostgreSQL и зависимостей достаточно: новые миграции и пересборка
образа для Stage 1D не нужны. Тесты reader, parser, catalog lookup и fan-out
используют `unittest` и mocks без реальных обращений к GitHub, S3 или PostgreSQL.

## Stage 2A - Spark Bronze to Silver preview

Stage 2A добавляет `football-spark` на официальном образе `spark:4.2.0-python3`.
Это отдельный processing runtime, а не master/worker cluster. `spark-submit --master "local[2]"`
выполняет Spark job в одном контейнере с двумя локальными потоками. Для учебного preview
этого достаточно; дополнительные сервисы, host ports и Spark UI не нужны.

Поток данных на этом этапе:

```text
PostgreSQL: latest match_events (по одному artifact на source_url)
                         |
Selectel S3 Bronze -> boto3 + SHA-256 verification
                         |
data/work/bronze_events/match_id=<id>.json (исходные bytes)
                         |
Spark local[2] -> explicit schema -> event_core -> DQ
                         |
data/work/silver/event_core/ (локальный Snappy Parquet)
```

Bronze — raw immutable JSON: исходные bytes и дополнительные поля сохраняются без изменений.
Silver — типизированная, нормализованная структура для аналитики. На этом этапе это только
локальный disposable preview, не опубликованный Silver dataset. Parquet — колоночный формат:
для аналитических scan workloads можно читать нужные столбцы, эффективно сжимать данные
и использовать статистику файлов. JSON удобен для сохранения исходного документа, но обычно
требует большего объёма чтения и повторного parsing для таких запросов.

### Каталог, staging и схема

`find_latest_ingestion_objects()` выбирает `source=statsbomb`, `dataset=match_events`.
`DISTINCT ON (source_url)` оставляет последнюю зарегистрированную версию по
`first_seen_at DESC, id DESC`; итоговый порядок — `source_url ASC`.
`--limit N` берёт первые N artifacts в этом стабильном лексикографическом порядке.
Все URL и отсутствие дубликатов logical source проверяются **до** применения limit.

Текущий Stage 1D наполняет `match_events` только матчами World Cup 2022: job явно передаёт
`competition_id=43`, `season_id=106` в transformation. Сам SQL не фильтрует competition/season:
до расширения Bronze на другие турниры потребуется отдельный выбор соответствующего набора
artifacts. Значения контекста не спрятаны внутри `transform_event_core()`.

`match_id` определяется строгим canonical URL
`https://raw.githubusercontent.com/hudl/open-data/master/data/events/<id>.json`,
не содержимым event. Существующий `read_bronze_object()` скачивает bytes по bucket/key из
каталога, закрывает S3 Body и проверяет фактический SHA-256 против catalog checksum.
Только после этого bytes без JSON reserialization записываются в staging.
Spark получает `match_id` из имени файла через `input_file_name()`, `regexp_extract()` и
`try_cast()`; Python UDF не используются.

`data/work/` явно исключён из Git и виден с Windows host через bind mount `.:/app`.
Рабочая директория создаётся job при необходимости; пустые директории Git не хранит.
Старые staging-файлы не удаляются: Spark читает точный список выбранных файлов, а не wildcard.
Повторный запуск заменяет только выбранные staging-копии и локальный `event_core` preview.
Не запускайте два preview job одновременно: они используют общий disposable workspace.

Explicit `StructType` фиксирует контракт полей и типов, делает результат воспроизводимым
при пропущенных полях и не требует inference по содержимому каждого запуска.
JSON читается с `multiLine=true`, `mode=FAILFAST`: повреждённые/несовместимые записи не должны
молча исчезать из результата. Дополнительные `pass`, `shot`, `tactics` и другие event-specific
структуры игнорируются в Silver, но остаются в Bronze.

`event_core` содержит:

```text
competition_id, season_id, match_id, event_id, event_index,
period, timestamp, minute, second, type_id, type_name, possession,
possession_team_id, possession_team_name, play_pattern_id, play_pattern_name,
team_id, team_name, player_id, player_name, position_id, position_name,
location_x, location_y, duration, under_pressure, counterpress
```

`event_id` и `event_index` берутся из `id` и `index`. `timestamp` остаётся строкой:
это время внутри периода, а не календарная дата. `location` имеет тип `array<double>`;
`location_x/y` — элементы 0/1. Nullable player, position, location, duration и flags
остаются NULL; даже короткий location не вызывает ошибку индекса и не заполняется нулями.

### DQ и локальная запись

Перед записью job выводит агрегированные counts и требует:

- `row_count > 0`;
- отсутствие NULL в `match_id`, `event_id`, `event_index`, `type_id`, `team_id`;
- отсутствие повторяющихся пар `(match_id, event_id)`;
- наличие событий для каждого выбранного матча.

`duplicate_keys` — число повторяющихся пар, не число лишних строк.
На driver возвращаются только маленькие агрегаты, не весь dataset.
При нарушении DQ job завершается с ненулевым кодом **до записи**. Ранее созданный preview
при такой ошибке может остаться на диске, но не является результатом нового запуска.
Сообщение `Silver event_core build complete` появляется только после успешной записи.
Summary содержит выбранные artifacts, обработанные матчи, events read/written,
output partitions, путь и Spark version. Spark parser stack traces отключены, поскольку
могут содержать raw JSON; CLI выводит безопасный этап/тип ошибки или DQ counts.

Перед записью используется `repartition(4)`, формат Parquet, `compression=snappy`,
`mode=overwrite`. Это 4 Spark output partitions, а не директории по матчам;
на очень маленьком fixture число непустых файлов может быть меньше.
`partitionBy("match_id")` для 64 небольших матчей создавал бы много маленьких файлов:
накладные расходы на listing/open/scheduling стали бы непропорциональны объёму данных.
`coalesce(1)` тоже не используется: не сводим всю запись к одной task.

Spark image переиспользует pinned `requirements/tools.txt` и минимальную CA setup для
GlobalSign Root R6 из python-tools. boto3 использует системный bundle через `AWS_CA_BUNDLE`,
AWS Signature v4 и virtual-hosted addressing. TLS verification включена; credentials
поступают через существующие environment variables и не печатаются.
Java S3A truststore и Hadoop S3A packages пока не настраиваются.

### Проверки и ручной запуск Stage 2A

Сборка и проверки без чтения реальных Bronze artifacts:

```powershell
docker compose config -q
docker compose build football-spark
docker compose run --rm football-spark spark-submit --version
docker compose run --rm football-spark python3 -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm football-python-tools python -m unittest discover -s tests -v
docker compose run --rm football-spark spark-submit --master "local[2]" tests/spark/test_event_core.py
```

Обычные unit tests используют mocks для PostgreSQL/S3/Spark orchestration. Spark suite
использует только `tests/fixtures/statsbomb_events.json`, временные локальные файлы и
`unittest`; отдельный запуск не требует PySpark в python-tools. Проверяются explicit schema,
flatten, nullable/короткий location, filename identity, required columns, DQ failures,
отсутствие записи при DQ failure и Snappy Parquet roundtrip/overwrite.
Generated JSON/Parquet тестов находятся внутри отдельной temporary directory в `data/work/`
и удаляются при завершении теста; никакие S3 objects не затрагиваются.

Первый **ручной** build на двух реальных Bronze artifacts (PostgreSQL должен уже работать):

```powershell
docker compose run --rm football-spark spark-submit --master "local[2]" scripts/build_silver_event_core.py --limit 2
```

После проверки результата — все доступные World Cup 2022 event artifacts:

```powershell
docker compose run --rm football-spark spark-submit --master "local[2]" scripts/build_silver_event_core.py
```

Оба запуска читают реальные Bronze objects, но записывают только локальные файлы.
Нет загрузки Silver в S3, регистрации Silver в PostgreSQL, ClickHouse writes, изменения
Bronze, преобразования lineups или event-specific Silver tables.

Stage 2B реализован отдельно ниже: Spark S3A direct access и persistent versioned Silver
в Selectel. Stage 2A остаётся независимым local preview.

## Stage 2B - Direct S3A and immutable Silver builds

Stage 2A (`scripts/build_silver_event_core.py`) по-прежнему читает verified local staging
и записывает только локальный preview. Новый `scripts/publish_silver_event_core.py`
читает events непосредственно из Selectel через Spark S3A и публикует immutable Silver build.
Spark остаётся `local[2]`; новых сервисов, UI ports и ClickHouse writes нет.

```text
PostgreSQL catalog -> verified small World Cup parent -> exact event membership
                         |
                    boto3 HEAD preflight (без event bodies)
                         |
                   Spark S3A: exact immutable event keys
                         |
                   EVENT_SCHEMA -> transform_event_core -> DQ
                         |
              deterministic build identity -> inspect exact output prefix
                         |
       new prefix: directory committer / existing prefix: validate, never rewrite
                         |
                _SUCCESS + parts -> S3A read-back -> _manifest.json
                         |
                     metadata.silver_builds
```

### Runtime, TLS и credentials

В текущем образе фактически проверены Spark **4.2.0**, Hadoop **3.5.0**, Scala **2.13.18**.
В `docker/spark/Dockerfile` закреплён S3A-набор из dependency contract опубликованного
`org.apache.spark:spark-hadoop-cloud_2.13:4.2.0`:

| JAR | Версия |
| --- | --- |
| spark-hadoop-cloud_2.13 | 4.2.0 |
| hadoop-aws | 3.5.0 |
| AWS SDK v2 bundle | 2.35.4 |
| analyticsaccelerator-s3 | 1.3.1 |
| wildfly-openssl | 2.2.5.Final |
| jackson-dataformat-cbor | 2.21.2 |

JAR-файлы скачиваются по versioned Maven Central URLs только при Docker build и находятся
в `/opt/spark/jars`. Hadoop client, Jackson core/databind, HTTP client и SLF4J уже есть
в закреплённом Spark image. Ненужные Azure/GCS connectors не добавляются.
Runtime-команды не используют `--packages`, Ivy download или другую загрузку dependencies.

boto3 — Python SDK для небольшого parent JSON, HEAD metadata и manifest. S3A — Hadoop
filesystem connector: URI `s3a://bucket/key` позволяет Spark/JVM читать и писать object storage.
Event bodies в Stage 2B читает только Spark; `data/work/bronze_events/` не создаётся.
HEAD preflight сверяет catalog SHA-256, immutable key SHA-256 и S3 metadata SHA-256.
Это проверка согласованности metadata, **не повторное вычисление SHA-256 всех event bytes**,
как в Stage 2A. S3A чтение доверяет неизменности опубликованных Bronze objects.

Python использует прежний `AWS_CA_BUNDLE`. JVM использует свой `cacerts`: GlobalSign Root R6
уже присутствует; Docker build проверяет его SHA-256 fingerprint, не импортирует дубликат
и не заменяет truststore. Реальный Java TLS handshake с Selectel проверяется только ручным
smoke test. TLS verification не отключается.

Только `football-spark` дополнительно получает `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
из тех же Compose substitutions, что и `S3_ACCESS_KEY`/`S3_SECRET_KEY` для boto3.
`configure_s3a()` использует
`software.amazon.awssdk.auth.credentials.EnvironmentVariableCredentialsProvider`.
Секреты не записываются в source, SparkConf, Hadoop Configuration или XML/conf-файлы.
Endpoint/region берутся из `S3_ENDPOINT`/`S3_REGION`; virtual-hosted addressing включён
через `fs.s3a.path.style.access=false`, SSL — через `fs.s3a.connection.ssl.enabled=true`.

### Почему S3A directory committer

S3 — не POSIX filesystem: директории являются prefixes, а переименование набора objects
не является атомарным directory rename. Классический rename-based commit может превратиться
в дорогие copy/delete операции и оставить промежуточное состояние.

Для S3 настроены `S3ACommitterFactory`, `PathOutputCommitProtocol` и
`BindingParquetOutputCommitter`. Directory committer подходит для нашего целиком нового
неpartitioned dataset prefix: Parquet tasks используют локальные временные файлы и
multipart uploads с отложенным завершением. Pending-upload metadata хранится в локальном
`file:///tmp/football-s3a-commits`, buffer — `/tmp/football-s3a-buffer`; это не staging Bronze.
Внутренний FileOutputCommitter обслуживает только локальную служебную информацию,
не выполняет classic S3 rename publication.

Конфигурация:

```text
mapreduce.outputcommitter.factory.scheme.s3a=org.apache.hadoop.fs.s3a.commit.S3ACommitterFactory
fs.s3a.committer.name=directory
fs.s3a.committer.staging.conflict-mode=fail
fs.s3a.committer.staging.unique-filenames=true
fs.s3a.committer.abort.pending.uploads=true
fs.s3a.multipart.purge=false
spark.sql.sources.commitProtocolClass=org.apache.spark.internal.io.cloud.PathOutputCommitProtocol
spark.sql.parquet.output.committer.class=org.apache.spark.internal.io.cloud.BindingParquetOutputCommitter
```

Запись использует `mode("errorifexists")`, `repartition(4)`, Snappy Parquet, без
`partitionBy(match_id)`. `conflict-mode=fail` запрещает replace/append существующего build.
Bucket-wide multipart purge выключен; abort pending uploads относится к текущему destination.
Запускайте только **одного publisher для одного build_id**: S3 prefix не является
транзакционной блокировкой, а directory committer не даёт атомарного compare-and-swap каталога.

### Lineage, fingerprints и manifest

Job читает latest `world_cup_2022_matches` parent через существующий SHA-verified reader.
Из parent извлекаются match ids. Для каждого требуется ровно один latest `match_events`
artifact; missing/duplicate — ошибка, artifacts других турниров игнорируются.
Весь membership проверяется до `--limit`. Текущий полный parent содержит 64 матча.
Дополнительно URL match id сверяется с match id в immutable key.

Spark читает точный список URI, а не wildcard. Используется существующий `EVENT_SCHEMA`,
`multiLine=true`, `mode=FAILFAST`. Built-in regexp извлекает match id из строгого suffix
`/match_id=<positive integer>/sha256=<64 lowercase hex>/events.json`.
Transformation и DQ общие со Stage 2A; competition=43 и season=106 передаются явно.

- **Input fingerprint:** SHA-256 canonical UTF-8 JSON списка inputs, отсортированного по
  match id. Поля: `match_id`, `source_url`, `s3_bucket`, `object_key`, `sha256`.
- **Schema fingerprint:** SHA-256 UTF-8 строки `transformed_df.schema.json()`, без данных.
- **Build ID:** SHA-256 canonical build specification: source/layer/dataset,
  competition/season, `TRANSFORM_VERSION="event_core_v1"`, input fingerprint и schema hash.
  Время, UUID, Git commit, имя машины и временные пути не участвуют.
- **Transform version:** при изменении смысла transformation нужно явно перейти на v2;
  Git commit не заменяет эту версию контракта.

Bronze object version определяется bytes одного исходного документа.
Silver dataset build version определяется всем выбранным набором Bronze inputs,
выходной схемой и версией transformation. Поэтому одинаковые inputs/schema/version
дают тот же build prefix независимо от порядка Python list.

```text
football/silver/statsbomb/event_core/competition_id=43/season_id=106/build_id=<64hex>/
├── part-....snappy.parquet
├── ...
├── _SUCCESS
└── _manifest.json
```

После записи проверяются `_SUCCESS`, непустой inventory part files, read-back row count,
match count и схема. Parquet reader расширяет nullability, поэтому при сравнении обе схемы
приводятся к nullable; имена, порядок, типы и metadata должны совпадать.
Fingerprint при этом остаётся hash исходной transformed schema.

`_manifest.json` содержит build specification, build_id, row/match/file counts, canonical
inputs и file inventory (keys, sizes, ETags). ETag используется как идентификатор inventory,
не объявляется SHA-256 содержимого Parquet. Manifest создаётся с `IfNoneMatch="*"`, metadata
`build_id` и `sha256`; существующий документ должен совпасть, перезапись запрещена.
Только после read-back и подтверждённого manifest выполняется registration в PostgreSQL.

### Recovery и ограничения без DeleteObject

| Состояние exact prefix | Поведение повторного запуска |
| --- | --- |
| Отсутствует, записи каталога нет | Новый Spark write, validation, manifest, registration |
| `_SUCCESS` + Parquet + manifest + catalog | Read-back validation, `UNCHANGED / ALREADY_BUILT`, без записи |
| Complete output + manifest, catalog отсутствует | Validation и повторная registration, без Spark write |
| Complete output + `_SUCCESS`, manifest/catalog отсутствуют | Validation, conditional manifest create, registration |
| Нет `_SUCCESS`, неверный manifest/inventory/schema/counts | `SilverIntegrityError`, никаких изменений |
| Catalog существует, output или manifest исчез | `SilverIntegrityError`, автоматическое восстановление bytes запрещено |

При сбое PostgreSQL после публикации S3 данные сохраняются. Повторный запуск вычисляет
тот же build_id. `ON CONFLICT ... DO NOTHING RETURNING id` не меняет existing catalog row;
конфликтующая запись дополнительно сравнивается с ожидаемым контрактом.

Python-код не вызывает DeleteObject/DeleteObjects, IAM и bucket policy не меняются.
Но directory committer **нельзя считать библиотекой без каких-либо delete-paths**:
в Hadoop 3.5.0 setup проверяет/удаляет старый `<build-prefix>/_SUCCESS`, cleanup проверяет
`<build-prefix>/_temporary/`. Для отсутствующих путей `S3AFileSystem.delete()` сначала
делает status probe и возвращает false без S3 DELETE. Наш publisher запускает write
только для отсутствующего prefix; Hadoop 3.5 сохраняет directory markers.

При ошибке после частичного завершения multipart commit внутренний rollback Hadoop может
вызвать DeleteObject для уже завершённых объектов по адресу
`s3a://<bucket>/football/silver/statsbomb/event_core/competition_id=43/season_id=106/build_id=<hash>/part-<actual-name>.snappy.parquet`.
Это требует DeleteObject; текущая IAM policy должна отказать. Частичный prefix останется
для ручного разбора, следующий запуск завершится ошибкой. Код не подавляет проблему
путём смены IAM/committer, удаления данных или принудительного overwrite.
Для успешного нового build по анализу кода удалять существующие objects не требуется;
реальный Selectel write/permissions пока не проверен. При DELETE/403 в ручном запуске
остановитесь: не добавляйте широкие Delete-права и не очищайте prefix автоматически.
Устранение внутренних rollback-delete путей потребовало бы отдельно согласованного
изменения committer; в этот этап такой обход не входит.

Основание: исходники Hadoop 3.5.0
[AbstractS3ACommitter](https://github.com/apache/hadoop/blob/rel/release-3.5.0/hadoop-tools/hadoop-aws/src/main/java/org/apache/hadoop/fs/s3a/commit/AbstractS3ACommitter.java),
[StagingCommitter](https://github.com/apache/hadoop/blob/rel/release-3.5.0/hadoop-tools/hadoop-aws/src/main/java/org/apache/hadoop/fs/s3a/commit/staging/StagingCommitter.java),
[S3AFileSystem](https://github.com/apache/hadoop/blob/rel/release-3.5.0/hadoop-tools/hadoop-aws/src/main/java/org/apache/hadoop/fs/s3a/S3AFileSystem.java).

### Проверки и ручной запуск Stage 2B

Offline-проверки, без Selectel/PostgreSQL calls и без применения migration:

```powershell
docker compose config -q
docker compose build football-spark
docker compose run --rm football-spark spark-submit --version
docker compose run --rm football-spark java -cp "/opt/spark/jars/*" org.apache.hadoop.util.VersionInfo
docker compose run --rm football-spark python3 -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm football-python-tools python -m unittest discover -s tests
docker compose run --rm football-spark spark-submit --master "local[2]" tests/spark/test_event_core.py
docker compose run --rm football-spark spark-submit --master "local[2]" tests/spark/test_s3a_event_core.py
```

Следующие команды — **только ручные**, уже обращаются к реальным сервисам.
Сначала read-only S3A smoke и двухматчевый check:

```powershell
docker compose run --rm football-spark spark-submit --master "local[2]" scripts/check_s3a.py
docker compose run --rm football-spark spark-submit --master "local[2]" scripts/publish_silver_event_core.py --limit 2 --check-only
```

`--check-only` печатает версии, filesystem class, parent/selected/processed counts, DQ,
input/schema hashes и calculated build_id, затем `CHECK ONLY - nothing published`.
Он не пишет Silver и не обращается к таблице `silver_builds`. `--limit` без `--check-only`
запрещён до любого IO. Без limit check-only проверяет полный parent.

Перед первой публикацией вручную примените новую migration; старые migrations не менялись:

```powershell
docker compose exec football-postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/002_create_silver_builds.sql'
```

Migration использует `CREATE TABLE/INDEX IF NOT EXISTS`, hash/count checks и две UNIQUE
constraints. Повтор безопасен для той же схемы, но не исправляет вручную изменённую таблицу.

Полная публикация и повтор для проверки идемпотентности/recovery:

```powershell
docker compose run --rm football-spark spark-submit --master "local[2]" scripts/publish_silver_event_core.py
docker compose run --rm football-spark spark-submit --master "local[2]" scripts/publish_silver_event_core.py
```

Это команды с реальной записью S3/metadata; автоматически они не выполняются.
Ожидаемый текущий full build: 64 матча, 234637 events, 4 part files, если inputs не изменились.
Stage 2A local preview, Bronze, lineups и ClickHouse остаются без изменений.

## Stage 2C - Event domain Silver

Stage 2C добавляет два независимых persistent Silver datasets:
`pass_events` (`pass_events_v1`) и `shot_events` (`shot_events_v1`).
Они читают исходные immutable `match_events` JSON через S3A. Существующий
`event_core` содержит общие поля всех событий и сохраняет свой контракт/build.
Pass/shot не извлекаются из `event_core`: вложенные поля передач и ударов есть в Bronze.

Логическая связь трёх datasets — `(match_id, event_id)`. Для сопоставления builds
используйте одинаковый `input_fingerprint`: он подтверждает один набор версий Bronze.
Имена datasets, transform versions и схемы различаются, поэтому `build_id` различается.

Мы разделяем данные по смыслу футбольного события. Сверхширокая таблица
`event_core + pass + shot + goalkeeper + duel + ...` содержала бы множество почти
всегда пустых columns и объединяла бы разные правила заполнения. Отдельные datasets
упрощают DQ, аналитические запросы и последующее моделирование ClickHouse.
Это логическое разделение доменов, а не OLTP-style third normal form.

### Общий pipeline и lineage

`src/silver/job.py` содержит вынесенную из Stage 2B orchestration:
parent catalog → GET/SHA-256 → membership → child HEAD → exact S3A paths →
Spark/S3A setup → dataset read/transform/DQ → fingerprints → publication.
Оба CLI используют этот pipeline; каждый передаёт только свою функцию подготовки DataFrame.

Parent выбирается как `source=statsbomb, dataset=world_cup_2022_matches`.
Из него берутся match IDs (для текущего World Cup parent — 64), затем latest
`source=statsbomb, dataset=match_events` для каждого ID. Другие турниры исключаются;
пропущенный или дублированный match artifact останавливает job ещё до Spark.
Полнота parent проверяется до применения `--limit`.

`src/silver/publish.py`, `src/silver/manifest.py` и PostgreSQL helpers переиспользуются:
exact-prefix inventory, `_SUCCESS`, read-back схемы/числа строк/матчей, conditional
manifest publication, `find_silver_build`, `register_silver_build` и recovery.
В `build_specification` добавлен dataset с прежним default `event_core`.
Алгоритм canonical inputs/fingerprints/build ID остался прежним.

### Schemas и transformations

`src/silver/statsbomb/event_domains.py` определяет `PASS_SCHEMA`, `SHOT_SCHEMA`
и `DOMAIN_EVENT_SCHEMA = core fields + pass + shot`. Все вложенные поля nullable;
именованные сущности имеют `id: long, name: string`, координаты — `array<double>`,
числа length/angle/xG — `double`, флаги — `boolean`, `key_pass_id` — `string`.
Schema inference не используется, лишние RAW структуры игнорируются.
Исходный `EVENT_SCHEMA` для event_core не расширяется и не мутируется.

`transform_pass_events` оставляет `type.name == "Pass" AND pass IS NOT NULL`;
`transform_shot_events` — `type.name == "Shot" AND shot IS NOT NULL`.
Обе функции получают competition/season параметрами и используют встроенные Spark
выражения. Они сохраняют отсутствующие поля как NULL, включая outcome успешной
передачи и неуказанные boolean flags: никаких придуманных default values.

Общие выходные поля: competition/season, match/event IDs, event index, period,
timestamp/minute/second, team/player IDs и names, `start_x`, `start_y`.
Pass дополняет их recipient, length/angle, end x/y, height, body part, pass type,
outcome, technique и флагами cross/cut_back/switch/shot_assist/goal_assist/aerial_won/through_ball.
Shot содержит xG, end x/y/z, key_pass_id, body part, shot type, technique,
outcome и first_time/open_goal/one_on_one/aerial_won/deflected.
`F.get` возвращает NULL для коротких/пустых/null массивов и работает при ANSI mode;
у shot без третьей координаты `end_z = NULL`.

### Data quality

Оба validator используют небольшие агрегаты, не собирая весь dataset в Python.
Для каждого домена проверяются nonempty output, уникальность `(match_id, event_id)`
и обязательные `match_id`, `event_id`, `event_index`, `team_id`.
Проверяются точное множество выбранных match IDs и отсутствие чужих матчей.
Как и в Stage 2B, текущий publish contract требует представленность каждого
выбранного матча в output; отсутствие доменных событий для одного из них вызывает DQ failure.

Для pass отрицательный `pass_length` вызывает ошибку. NULL в остальных optional
полях допустим; отдельно печатаются informational NULL counts для `player_id`,
`recipient_id`, `outcome_id`, `body_part_id`, `technique_id`.

Для shot дополнительно обязательны `statsbomb_xg` и `outcome_id`.
xG должен находиться в `[0, 1]`; NaN также вызывает ошибку. Informational NULL counts:
`player_id`, `key_pass_id`, `body_part_id`, `technique_id`, `end_z`.

Expected count вычисляется из RAW по тем же условиям type + non-null struct,
после чего сравнивается с числом domain rows. Потеря событий при transformation
вызывает DQ failure. Конкретные World Cup pass/shot counts в коде не зашиты.

### Layout, manifest и recovery

```text
football/silver/statsbomb/{pass_events|shot_events}/
  competition_id=43/season_id=106/build_id=<sha256>/
    part-*.snappy.parquet
    _SUCCESS
    _manifest.json
```

Writer использует `repartition(4)`, Snappy и `errorifexists`; `partitionBy(match_id)`
и `coalesce(1)` не используются. На очень маленьких synthetic datasets число физических
part files может быть меньше четырёх из-за пустых partitions.

Manifest сохраняет Stage 2B contract: source/layer/dataset, competition/season,
transform_version, input_fingerprint, schema_sha256, build_id, row_count,
match_count, file_count, exact input artifacts и output inventory.
Full pass/shot build включает все event artifacts parent (сейчас 64).
В PostgreSQL используется существующая `metadata.silver_builds`; новой migration нет.

Повторный identical publish проверяет output и возвращает
`UNCHANGED / ALREADY_BUILT` и `ALREADY_REGISTERED`, не переписывая Parquet.
После DB failure повтор восстанавливает регистрацию для того же build ID.
При валидном Parquet + `_SUCCESS` без manifest и catalog восстанавливается manifest.
Если запись catalog уже существует, исчезнувший manifest считается нарушением
целостности, как в Stage 2B. Partial/corrupt prefix даёт `SilverIntegrityError`.
Автоматическая очистка S3 не выполняется; ограничения IAM/committer Stage 2B сохраняются.

### Проверки и ручной запуск Stage 2C

Offline-проверки используют mocks и локальный synthetic JSON с pass/shot событиями:

```powershell
docker compose config -q
docker compose run --rm --no-deps football-spark python3 -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_event_core.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_s3a_event_core.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_event_domains.py
git diff --check
```

Docker/dependencies не менялись; код подключён bind mount, rebuild для Stage 2C не нужен.

Следующие команды запускаются вручную и обращаются к реальному Selectel/PostgreSQL.
Двухматчевые проверки выполняют read/transform/DQ, печатают версии, Dataset,
Transform version, Parent matches, Bronze artifacts selected, Matches processed,
Input events, Domain events, DQ, fingerprints и Build ID, затем
`CHECK ONLY - nothing published`. Silver и PostgreSQL registration не записываются.

```powershell
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_event_domains.py --dataset passes --limit 2 --check-only
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_event_domains.py --dataset shots --limit 2 --check-only
```

Для проверки всего parent без публикации уберите `--limit 2`.
`--limit` разрешён только с `--check-only`. `--dataset` обязателен и принимает
только `passes` или `shots`.

Полная публикация — отдельная команда для каждого dataset, с независимым recovery:

```powershell
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_event_domains.py --dataset passes
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_event_domains.py --dataset shots
```

Повторите каждую команду для проверки `UNCHANGED / ALREADY_BUILT` и `ALREADY_REGISTERED`.
Публикация `event_core` для этого этапа не требуется.

## Stage 2D - Lineups domain Silver

Stage 2D читает existing Bronze `source=statsbomb, dataset=match_lineups` и создаёт
три competition-season scoped datasets:

| Dataset | Смысл | Ключ | Transform version | Output partitions |
| --- | --- | --- | --- | --- |
| `teams` | Команды из выбранных составов турнира | `team_id` | `teams_v1` | 1 |
| `players` | Игроки из выбранных составов турнира | `player_id` | `players_v1` | 2 |
| `match_squads` | Связь match ↔ team ↔ player | `(match_id, team_id, player_id)` | `match_squads_v1` | 2 |

`team_id` и `player_id` — **StatsBomb source IDs**, а не canonical platform-wide IDs.
Будущая поддержка нескольких источников потребует отдельного entity-resolution layer:
StatsBomb player/team ↔ API-Football ↔ Kaggle ↔ другие источники.
Canonical IDs на этом этапе не создаются.

`players` не содержит `team_id`: identity игрока и его принадлежность команде в
конкретном матче — разные сущности. Эта принадлежность хранится в `match_squads`.
Состав не называется `starting_lineup`; выбранные поля не доказывают старт, капитанство,
роль запасного или позицию. Эти признаки не выводятся из косвенных данных.
Более богатые RAW поля остаются в Bronze для последующего расширения Silver.

### Lineage, input schema и transformations

Используется тот же parent `source=statsbomb, dataset=world_cup_2022_matches`.
Из каталога выбирается ровно один latest lineup artifact для каждого parent match.
Для текущего World Cup это 64 матча и 64 inputs. Другие матчи игнорируются;
missing/duplicate logical match identity вызывает ошибку до Spark.
Проверяется весь parent даже при `--limit N --check-only`.

`src/statsbomb/lineups.py` принимает только canonical URL
`https://raw.githubusercontent.com/hudl/open-data/master/data/lineups/<positive-bigint>.json`.
URL, match ID в immutable key и catalog SHA-256 сверяются до HEAD preflight.
Metadata SHA-256 проверяется существующим Bronze helper.

Небольшой parent JSON читается verified Bronze reader с GET/SHA-256.
Lineup bulk JSON читает только Spark S3A по списку exact immutable paths:

```text
s3a://<bucket>/football/bronze/statsbomb/lineups/
  match_id=<id>/sha256=<64-lowercase-hex>/lineups.json
```

`match_id` получается из `input_file_name()` через regex и `try_cast("long")`.
Некорректный путь, нулевой ID или BIGINT overflow дают NULL и DQ failure.

`src/silver/statsbomb/lineups.py` задаёт explicit `LINEUP_SCHEMA`:

```text
team_id: long
team_name: string
lineup: array<struct<
  player_id: long,
  player_name: string,
  player_nickname: string,
  jersey_number: int,
  country: struct<id: long, name: string>
>>
```

Поля nullable на входе, обязательность проверяется DQ. Schema inference не используется.
Неиспользуемые поля, включая positions/cards, игнорируются Spark.
Контракт проверен на synthetic fixtures; real cloud reads выполняются вручную.

`transform_match_squads` использует built-in `explode(lineup)` и сохраняет team/player
identity, nickname, jersey и country. Competition/season передаются параметрами;
NULL не заменяется значениями `Unknown`, `-1` или `0`.

`transform_teams` и `transform_players` используют текущий lineup-derived squad frame,
не читают event_core или опубликованные dimensions. Для команд остаётся hard invariant
`team_id → team_name`: два distinct non-null имени вызывают `LineupQualityError`.
NULL + одно известное имя не конфликтуют; после проверки используется `min`.

StatsBomb `player_id` — source identity. Описательные player_name/player_nickname/country
могут различаться между source artifacts (например, Phil Foden / Philip Foden).
`match_squads` сохраняет исходные match-level значения имени, nickname, country и jersey
для `(match_id, team_id, player_id)` без канонизации.
`players` — детерминированная competition/season-level проекция: одна строка на player_id.
Имя и nickname выбираются из non-null значений по `frequency DESC, length DESC, value ASC`
через Spark groupBy/Window, без Python UDF и недетерминированного first/last.
Если известного nickname нет, сохраняется NULL; отсутствие player_name по-прежнему
нарушает hard DQ. Перестановка строк/partitions не меняет выбор.

Country рассматривается только как пара `(country_id, country_name)`, где оба поля non-null.
Одна distinct полная пара сохраняется; нет полной пары или их несколько — оба поля NULL.
Частично заполненные пары не используются и никогда не объединяются друг с другом.
Например, Belgium / Morocco для player_id=131037 остаются в match_squads,
но в players country_id/country_name намеренно NULL, а не произвольно выбранная страна.
Выводятся только три агрегата: `player_name_variant_ids`, `player_nickname_variant_ids`,
`country_pair_variant_ids`. Их ненулевые значения информационные и сами по себе не
останавливают build; полные datasets не собираются в Python.
Будущий entity-resolution/canonical profile слой сможет решать более сложную
cross-source идентификацию; этот этап такой слой не вводит.

Версии `teams_v1`, `players_v1`, `match_squads_v1` сохранены: по подтверждению владельца
проекта persistent Silver builds этих datasets ещё не публиковались. Изменение
неопубликованной реализации не требует bump. Если выяснится, что старый players build
уже опубликован, перед публикацией изменённой семантики потребуется новая версия;
immutable build нельзя переиспользовать с другим содержимым. Удалённое состояние
каталога при этой правке не проверялось.

### DQ и referential integrity

Match squads должны быть непустыми; обязательны match/team/player IDs и team/player names.
Дубликаты `(match_id, team_id, player_id)` запрещены. Проверяются exact parent membership,
две distinct teams в каждом матче, непустой состав каждой match/team пары и число
explode rows относительно RAW arrays. Пустые/null lineup arrays проверяются также
до их исчезновения при `explode`, включая лишнюю пустую третью team.
Размер состава не зашит в код.

Для teams/players проверяются nonempty output, уникальные IDs, обязательные ID/name.
Информационно выводятся actual row/entity counts и NULL counts nickname/jersey/country.
Количество команд и игроков не хардкодится.

`validate_references` выполняет Spark `left_anti` joins и считает отсутствующие ссылки:
`match_squads.team_id ⊆ teams.team_id`, `match_squads.player_id ⊆ players.player_id`.
Полные наборы IDs не собираются в Python.
Каждый запуск строит и проверяет все три связанных представления текущих inputs,
но публикует только выбранный dataset. Поэтому referential DQ не зависит от порядка
публикации teams/players/match_squads и наличия предыдущих builds в S3.

### Общая публикация и manifest

Stage 2D расширяет существующие `job.py`, membership, build identity и publisher.
Все три datasets используют один canonical fingerprint exact lineup inputs:
match_id/source_url/s3_bucket/object_key/sha256, отсортированные по match ID.
Build IDs различаются за счёт dataset, transform version и schema SHA-256.
Для event_core/pass_events/shot_events прежние inputs, fingerprints и defaults сохранены.

```text
football/silver/statsbomb/{teams|players|match_squads}/
  competition_id=43/season_id=106/build_id=<sha256>/
    part-*.snappy.parquet
    _SUCCESS
    _manifest.json
```

Writer использует `repartition(1)` для teams, `repartition(2)` для players/match_squads,
Snappy и `errorifexists`. По entity IDs partitioning не выполняется.
Прежние event datasets сохраняют четыре output partitions.

Manifest переиспользует source/layer/dataset, context, version, hashes, build_id,
row_count/file_count, inputs и file inventory. У match_squads есть `match_count`.
У teams/players этот показатель неприменим к output и не записывается; `row_count`
равен entity count. Полнота входных матчей проверяется отдельно по `input_match_count`
до создания manifest; полный lineup lineage сохраняется в `inputs`.
Не вводятся дополнительные произвольные metadata fields.
Read-back проверяет schema/row_count, а match_count — у datasets с match rows.

`metadata.silver_builds`, generic SQL helpers и recovery остаются общими.
Complete identical build даёт `UNCHANGED / ALREADY_BUILT` и `ALREADY_REGISTERED`.
После DB failure повтор регистрирует тот же build без Parquet rewrite.
Валидный unregistered output без manifest восстанавливает manifest.
Partial/corrupt prefix даёт `SilverIntegrityError`; автоматической очистки S3 нет.
Новые migrations, IAM permissions и Docker services не требуются.

### Проверки и ручные команды Stage 2D

Offline/synthetic проверки:

```powershell
docker compose config -q
docker compose run --rm --no-deps football-spark python3 -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_event_core.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_s3a_event_core.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_event_domains.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_lineup_domains.py
git diff --check
```

Следующие команды обращаются к реальным сервисам и выполняются вручную:

```powershell
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_lineup_domains.py --dataset teams --limit 2 --check-only
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_lineup_domains.py --dataset players --limit 2 --check-only
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_lineup_domains.py --dataset match-squads --limit 2 --check-only
```

Check-only печатает Dataset, Transform version, Parent matches, Bronze artifacts selected,
Matches processed, Raw lineup team rows, Raw lineup player rows, Output rows, DQ,
Input fingerprint, Schema SHA256, Build ID и `CHECK ONLY - nothing published`.
S3 output и PostgreSQL registration не записываются. Для полного check-only уберите
`--limit 2`. Limit без check-only запрещён до IO.

Независимые full publishes:

```powershell
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_lineup_domains.py --dataset teams
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_lineup_domains.py --dataset players
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_lineup_domains.py --dataset match-squads
```

Повтор каждой команды проверяет идемпотентность/registration recovery.
Rebuild Docker для изменений Python-кода не нужен: проект подключён bind mount.
Пересоздавать event_core/pass_events/shot_events для Stage 2D не требуется.

## Stage 3A - ClickHouse analytics foundation

Stage 3A загружает **только `event_core`** из зарегистрированного immutable Silver build.
S3 Silver остаётся source of truth: проверяемым, воспроизводимым batch snapshot.
ClickHouse — serving/analytical storage для быстрых SQL-запросов, а не новый источник
истины и не замена PostgreSQL metadata catalog. Остальные Silver datasets пока не загружаются.

Поток: PostgreSQL `metadata.silver_builds` → exact build → manifest/checksum/inventory
→ ClickHouse `s3()` читает Parquet напрямую → `football.event_core` → target validation
→ PostgreSQL `metadata.clickhouse_loads`. Python читает только небольшой manifest;
Parquet не скачивается через boto3, Spark в загрузке не участвует.

### Конфигурация и совместимость

Используется прежний ClickHouse `25.8.23.13-alpine` и pinned официальный Python-клиент
`clickhouse-connect==0.15.0`. Python-tools подключается к `football-clickhouse:8123`,
не к `localhost:18124`. Переменные CLICKHOUSE_DB/USER/PASSWORD передаются из environment.
Существующие переменные PostgreSQL/S3 сохранены.

`infrastructure/clickhouse/config.d/10_selectel_s3.xml` задаёт named collection
`selectel_s3`: access_key_id/secret_access_key берутся через `from_env` из
S3_ACCESS_KEY/S3_SECRET_KEY. Значения не попадают в Git, SQL или application diagnostics.
Не выводите содержимое named collection или полный `docker compose config`.
Named collection скрывает credentials из SQL, но не заменяет контроль доступа:
администраторам доступен серверный config; произвольные SQL и URL от недоверенных
пользователей в этом stage не поддерживаются.

Поддерживаемый синтаксис проверен по исходникам/документации точного тега:

- [S3 named collection whitelist, v25.8.23.13-lts](https://github.com/ClickHouse/ClickHouse/blob/v25.8.23.13-lts/src/Storages/ObjectStorage/S3/Configuration.cpp)
- [Named collections XML](https://github.com/ClickHouse/ClickHouse/blob/v25.8.23.13-lts/docs/en/operations/named-collections.md)
- [Config from_env](https://github.com/ClickHouse/ClickHouse/blob/v25.8.23.13-lts/docs/en/operations/configuration-files.md)
- [MergeTree deduplication setting](https://github.com/ClickHouse/ClickHouse/blob/v25.8.23.13-lts/src/Storages/MergeTree/MergeTreeSettings.cpp)
- [clickhouse-connect 0.15.0 command/settings](https://github.com/ClickHouse/clickhouse-connect/blob/v0.15.0/clickhouse_connect/driver/httpclient.py)

`region` отсутствует в whitelist параметров S3 named collection этой версии, поэтому
в XML его **нет**. S3_REGION передаётся контейнеру, но выдуманный setting не добавляется.
URL передаётся отдельно: `https://<S3_BUCKET>.s3.<pool>.storage.selcloud.ru/<key>`.
Helper принимает только generic Selectel HTTPS endpoint без credentials, port,
path, query и fragment; bucket/key валидируются. Bucket с точками отклоняется из-за
wildcard TLS certificate. Префикс обязан совпадать с resolved build identity.
Единственный wildcard добавляется кодом: `part-*.parquet` внутри exact build prefix;
manifest, `_SUCCESS`, соседние builds и вложенные каталоги не читаются как Parquet.

ClickHouse использует собственный системный CA trust, не JVM/S3A truststore и не
AWS_CA_BUNDLE Python-контейнера. TLS verification не отключается. Если ручной cloud
smoke выявит certificate error, нужно отдельно исправить CA trust, не обходить TLS.

Mount всей `config.d` скрывает `docker_related_config.xml` из образа. Поэтому
`00_docker_network.xml` сохраняет его исходные listen_host `::`/`0.0.0.0` и listen_try=1.
Init directory сохранён; ClickHouse migrations подключены отдельно, read-only.

### MergeTree, схема и ключи

Исходная схема находится в `infrastructure/clickhouse/migrations/001_create_event_core.sql`;
уже применённая migration 001 не изменяется. Migration `002_event_core_float64_metrics.sql`
расширяет только location_x/location_y/duration до `Nullable(Float64)`.
Silver Spark хранит эти поля как Double/Float64, поэтому ClickHouse сохраняет Float64,
чтобы избежать потери точности. INSERT сохраняет `accurateCast(..., 'Nullable(Float64)')`.
Используется обычная `MergeTree`: данные хранятся отсортированными parts и объединяются
фоновыми merges. LowCardinality используется только для type_name/team_name.
Необязательные player/position/location/duration/flags остаются Nullable; NULL не
заменяется нулями или пустыми строками. INSERT содержит явные колонки и casts;
`accurateCast` дополнительно отклоняет переполнение unsigned integer вместо wraparound.

`ORDER BY (competition_id, season_id, match_id, period, event_index, event_id)`
группирует события турнира/матча и сохраняет удобный порядок внутри матча.
Без отдельного PRIMARY KEY этот sorting key используется также для sparse primary
index: индекс хранит отметки для гранул, а не отдельную запись на каждую строку.
**ClickHouse PRIMARY KEY не обеспечивает уникальность.** Уникальность пары
(match_id, event_id) внутри build проверяет загрузчик через uniqExact.

`PARTITION BY (competition_id, season_id)` — lifecycle-oriented граница турнира/сезона,
не замена sorting key и не partition-per-match. Secondary indexes, projections,
materialized views не добавлены. ReplacingMergeTree не нужен: это immutable batch
snapshots, не CDC/row-level updates; merge-дедупликация не должна скрывать ошибки loader.

`silver_build_id` даёт lineage каждой строки до Silver manifest/catalog. Разные builds
могут содержать одни и те же события: аналитические запросы должны выбирать один build.
`scripts/clickhouse_smoke_queries.sql` требует build_id parameter и содержит пять
read-only запросов: общее число событий, top matches, event types, teams и события
одного детерминированно выбранного матча.

### Проверки, идемпотентность и recovery

Latest build разрешается один раз по source=statsbomb, dataset=event_core,
competition_id=43, season_id=106; порядок `created_at DESC, id DESC`.
`--build-id` использует существующий exact lookup с тем же контекстом. Поддерживается
только `event_core_v1`; arbitrary S3 prefix через CLI не принимается.

Перед INSERT проверяются manifest checksum, build identity, input fingerprint,
dataset/context/version/schema hash, row/file counts и match_count по lineage inputs.
Проверяются `_SUCCESS`, точный inventory Parquet (keys/sizes/ETags) и число файлов;
Parquet bodies не скачиваются. Затем DESCRIBE проверяет весь target column/type contract,
loaded_at default, а system.tables — engine/keys/dedup setting. Auto-ALTER отсутствует.

Source через `s3()` и target по silver_build_id проверяются по count, uniqExact(match_id),
uniqExact(tuple(match_id,event_id)), min/max competition_id и season_id.
Ожидаемые counts берутся из manifest, не из констант 234637/64.

- В target 0 строк и отсутствует load registration: один логический INSERT SELECT.
- В target ровно expected rows: полная validation, без INSERT; можно восстановить
  отсутствующую PostgreSQL registration после timeout/DB failure.
- Частичный/избыточный target, отсутствующий зарегистрированный target или конфликт
  metadata: ClickHouseIntegrityError; никаких DELETE, reload, ALTER или cleanup.
- Регистрация выполняется только после target validation: ON CONFLICT DO NOTHING
  RETURNING id, затем проверка совпадения metadata. Идентичный повтор даёт
  `UNCHANGED / ALREADY_LOADED`, `ALREADY_REGISTERED`.

Защита повторов: `non_replicated_deduplication_window=1000` и
`client.command(..., settings={"insert_deduplication_token": build_id, ...})`.
INSERT SELECT имеет ORDER BY ALL и фиксированный single-thread execution для
воспроизводимого порядка; loaded_at вычисляется DEFAULT. Dedup window — дополнительная
ограниченная защита, не гарантия уникальности и не замена проверкам target/catalog.
Ручных retry loops нет. Session advisory lock PostgreSQL сериализует экземпляры этого
loader, не удерживая длинную SQL transaction во время удалённого IO. Он не защищает
от ручных INSERT, которые обходят loader.

При timeout серверный INSERT может ещё выполняться: дождитесь завершения запроса
перед повтором. Автоматической отмены/удаления/перезагрузки нет. Следующий запуск
проверит target и восстановит только недостающую регистрацию, если build полный.
Diagnostics показывают stage/operation/exception class, но не raw exception text.

`--check-only` выполняет resolution, manifest/table/source/target/catalog checks,
показывает Would load и не выполняет INSERT или registration. S3 smoke не требует
target table: он проверяет latest build, named collection и direct source read.

### Локальные проверки Stage 3A

```powershell
docker compose config -q
docker compose build football-python-tools
docker compose run --rm --no-deps football-python-tools python -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_local.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_event_core.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_s3a_event_core.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_event_domains.py
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_lineup_domains.py
git diff --check
```

Offline tests используют fake S3/ClickHouse/PostgreSQL и не обращаются в облако.
Opt-in local integration test требует запущенный football-clickhouse, создаёт только
уникальные TEMPORARY session tables с synthetic rows. Они автоматически исчезают
после expiry HTTP session (60 секунд); DROP/DELETE/TRUNCATE не выполняются.
Migration в football.event_core этот тест не применяет, PostgreSQL/S3 не использует.

### Ручной запуск Stage 3A

Следующие команды **не выполняются автоматически**. Запускать из корня проекта
в PowerShell. Сначала обновить только ClickHouse service, сохранив существующий volume:

```powershell
docker compose config -q
docker compose build football-python-tools
docker compose up -d --no-deps football-clickhouse
```

При первоначальной установке применить PostgreSQL migration 003 и ClickHouse migrations
001, затем 002. Если 001 уже применена, для исправления типов выполнить только ClickHouse
migration 002 ниже. Here-string передаёт shell script через
stdin, поэтому PowerShell не раскрывает переменные credentials; значения не печатаются:

```powershell
@'
exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/003_create_clickhouse_loads.sql
'@ | docker compose exec -T football-postgres sh

@'
exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery < /migrations/001_create_event_core.sql
'@ | docker compose exec -T football-clickhouse sh

@'
exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery < /migrations/002_event_core_float64_metrics.sql
'@ | docker compose exec -T football-clickhouse sh
```

Cloud smoke, затем check-only, загрузка и идентичный повтор:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_s3.py
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_event_core.py --check-only

$silverBuildId = Read-Host 'Введите Silver build ID из успешного check-only (64 lowercase hex)'
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_event_core.py --build-id $silverBuildId
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_event_core.py --build-id $silverBuildId
```

Без --build-id loader выбирает latest; для воспроизводимого повторного теста выше
зафиксирован один ID. Также поддерживается `--build-id $silverBuildId --check-only`.
После загрузки выполнить read-only smoke SQL через официальный клиент:

```powershell
docker compose run --rm --no-deps football-python-tools python -c "import sys; from pathlib import Path; from src.common.clickhouse import create_clickhouse_client; c=create_clickhouse_client(); sql=Path('scripts/clickhouse_smoke_queries.sql').read_text(); [print(c.query(q, parameters={'build_id':sys.argv[1]}).result_rows) for q in sql.split(';') if q.strip()]; c.close()" $silverBuildId
```

Rebuild Spark, повторная публикация Silver, изменение IAM и удаление объектов не нужны.
Stage 3B в этот этап не входит.

## Stage 3B - Complete ClickHouse Silver model

Stage 3B материализует оставшиеся Silver datasets через тот же direct `s3()` pipeline.
ClickHouse остаётся serving storage; immutable Silver в S3 — source of truth.
Никакие Spark/Bronze/Silver transforms, build identity, IAM или credentials не меняются.

### Спецификации и общий loader

`src/analytics/specs.py` содержит frozen dataclass `DatasetSpec` и шесть явных specs:
dataset/version, database/table, schema, source→target SELECT expressions, identity,
context/partition/sorting columns и небольшие настройки validation.
`loader.py` реализует единственный load/recovery state machine, `validation.py` —
aggregate checks. `silver_input.py` переиспользует существующие manifest checksum,
input fingerprint, `_SUCCESS` и exact part inventory checks; Python Parquet не скачивает.
`event_core.py` — compatibility exports, а прежний `load_clickhouse_event_core.py`
продолжает вызывать общий job с event_core по умолчанию.

| CLI dataset | Silver / ClickHouse table | Transform version | Уникальный ключ внутри build |
|---|---|---|---|
| event-core | event_core | event_core_v1 | match_id, event_id |
| passes | pass_events | pass_events_v1 | match_id, event_id |
| shots | shot_events | shot_events_v1 | match_id, event_id |
| teams | teams | teams_v1 | team_id |
| players | players | players_v1 | player_id |
| match-squads | match_squads | match_squads_v1 | match_id, team_id, player_id |

Fact-like tables: event_core/pass_events/shot_events. Dimension-like: teams/players.
Bridge match_squads описывает membership игрока в команде конкретного матча; team_id
не хранится в players. Идентификаторы остаются StatsBomb source identities, не глобальной
cross-source моделью сущностей. Все шесть таблиц — материализации отдельных immutable builds.
Loader не зависит от порядка загрузки; межтабличные проверки выполняются отдельно.

### ClickHouse schemas и точность

`003_create_remaining_silver_tables.sql` создаёт пять новых таблиц через IF NOT EXISTS.
Применённые 001/002 не изменяются; PostgreSQL migration 004 не нужна.
Все таблицы используют plain MergeTree, partition (competition_id, season_id),
non_replicated_deduplication_window=1000, lineage silver_build_id FixedString(64)
и loaded_at DateTime64(3, 'UTC') DEFAULT now64(3).

Полные пять schemas находятся в migration 003 и сверяются тестами со specs.
Fact sorting: competition_id, season_id, match_id, period, event_index, event_id.
Teams/players sorting: competition_id, season_id, entity ID.
Squads sorting: competition_id, season_id, match_id, team_id, player_id.

Исходные типы проверены по Stage 2C/2D code/tests: координаты/length/angle/xG —
DoubleType, key_pass_id — nullable String, идентификаторы — Long, jersey_number — Integer.
Source→target projections перечисляют все колонки явно, без SELECT *:

- числовые ID/context → `accurateCast(column, 'UInt32'/'UInt64'/'UInt16'/...)`;
- необязательные ID/числа/строки/flags → accurateCast в соответствующий Nullable type;
- location/start/end coordinates, pass_length/pass_angle/duration → Nullable(Float64);
- statsbomb_xg → Float64; сужений до Float32 нет;
- event_id → toUUID(event_id);
- nullable key_pass_id → toUUID(key_pass_id): NULL остаётся NULL, неверная non-null
  строка отклоняется. В 25.8 accurateCast в Nullable(UUID) может скрыть неверную строку
  как NULL, поэтому для UUID он не используется;
- LowCardinality strings → явный CAST в заданный LowCardinality type.

Важная синтаксическая корректировка: `players.country_name` использует
`LowCardinality(Nullable(String))`. Обратная вложенность `Nullable(LowCardinality(String))`
не поддерживается ClickHouse 25.8.23.13; это проверено локально. Смысл сохраняется:
nullable dictionary-encoded string. NULL не заменяется на sentinel/zero UUID.

Source и target проверяются по manifest row_count, уникальному ключу, context min/max
и обязательным полям. Для facts и squads также сравнивается manifest match_count;
для teams/players он не придумывается. Для shots xG должен быть finite и в [0,1],
outcome_id — non-null. Для squads проверяются две разные команды на каждый матч,
без предположения о размере состава. Ожидаемые World Cup counts не захардкожены.

### Один build на dataset/context

Начиная со Stage 3B ClickHouse поддерживает **ровно один materialized Silver build**
на dataset + competition_id + season_id. Это ужесточает историческую политику Stage 3A:
два snapshot одного контекста больше не могут автоматически сосуществовать в serving table.

Перед INSERT loader получает только агрегаты target context: count, uniqExact(build_id),
count строк с другим build_id. Проверка выполняется и в check-only:

- 0 строк → разрешена первая загрузка, если нет конфликтующей регистрации;
- полный запрошенный build → DQ, ALREADY_LOADED, без повторного INSERT;
- другой build или смесь builds → ClickHouseBuildConflictError;
- partial/excessive target → ClickHouseIntegrityError.

Замены, DELETE, DROP PARTITION и append второго snapshot нет. Старые Silver builds
остаются в S3 и metadata.silver_builds для lineage/reproducibility. Отдельный replacement
workflow (validation, переключение snapshot и каталогов) будет спроектирован позже.
Это предотвращает двойной счёт в аналитике. Другой competition/season не конфликтует.

Сохранены insert_deduplication_token=build_id, ORDER BY ALL и прежние insert settings.
Общий PostgreSQL advisory lock использует прежний namespace и сериализует старый
и новый CLI. Он не защищает от ручных INSERT в обход loader.
После успешного INSERT и timeout/сбоя регистрации следующий запуск проверяет target,
не повторяет INSERT для полного build и восстанавливает metadata.clickhouse_loads.
После timeout сначала дождитесь завершения серверного запроса; автоматических retries
или cleanup нет. Registration выполняется только после post-load validation.

### Read-only model check и аналитика

`scripts/check_clickhouse_model.py` разрешает **текущие builds из ClickHouse**, а не
latest Silver. Для каждой из шести таблиц требует один непустой build в контексте,
matching Silver/load catalog records и совпадение row_count. Затем выполняет SQL
LEFT ANTI JOIN с фильтрами context + текущий build с каждой стороны:

- squads.team_id → teams.team_id;
- squads.player_id → players.player_id;
- event_core.match_id → match_squads.match_id;
- passes/shot event keys → event_core event keys.

Это hard checks. Player/team orphan row counts в трёх fact tables выводятся INFO:
NULL player IDs не считаются orphan, а non-null отсутствующие ссылки пока не являются
hard failure. Все ID не собираются в Python. Между запросами нет распределённого
snapshot isolation: запускать после загрузок; в конце current builds проверяются повторно.

`scripts/clickhouse_model_smoke_queries.sql` добавляет десять read-only запросов:
passes по командам/outcome, shots/xG по командам и игрокам, squads, joins facts→dimensions
и timeline одного матча. Они фильтруют context и требуют успешный model check с
one-build policy. Прежний `clickhouse_smoke_queries.sql` Stage 3A сохранён.
NULL pass outcome трактуется как normally complete только в StatsBomb semantics,
уже описанной в Stage 2C README, а не как универсальное правило для NULL.

### Проверки Stage 3B без облака

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_local.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_datasets.py
git diff --check
```

Local tests создают только TEMPORARY session tables с synthetic rows (включая 0.1 для
проверки Float64, nullable/invalid UUID, конфликты builds и orphan references).
Migration 003 не применяется к football; production data, S3 и PostgreSQL не используются.
Session tables автоматически истекают через 60 секунд после последнего запроса.
Image rebuild и новые зависимости не нужны.

### Ручные команды Stage 3B

Следующие команды Codex автоматически не выполняет. Из корня проекта в PowerShell.
Миграция 003 создаёт только пять новых таблиц; event_core не перезагружается:

```powershell
docker compose config -q
@'
exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery < /migrations/003_create_remaining_silver_tables.sql
'@ | docker compose exec -T football-clickhouse sh
```

Read-only совместимость event_core через оба CLI (обращаются к S3):

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_event_core.py --check-only
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset event-core --check-only
```

Для остальных datasets recommended order: teams → players → match-squads → passes → shots.
Цикл ниже останавливается при первой ошибке. Для каждого dataset: сначала check-only,
затем вручную скопировать его build ID, загрузить и повторить **тот же ID** для проверки
ALREADY_LOADED / ALREADY_REGISTERED:

```powershell
foreach ($dataset in @('teams', 'players', 'match-squads', 'passes', 'shots')) {
    docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset $dataset --check-only
    if ($LASTEXITCODE -ne 0) { throw "Check-only failed: $dataset" }
    $silverBuildId = Read-Host "Введите build ID из успешного check-only для $dataset"
    docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset $dataset --build-id $silverBuildId
    if ($LASTEXITCODE -ne 0) { throw "Load failed: $dataset" }
    docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset $dataset --build-id $silverBuildId
    if ($LASTEXITCODE -ne 0) { throw "Repeat failed: $dataset" }
}
```

После всех загрузок:

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_model.py --competition-id 43 --season-id 106
```

Только после успешного model check выполнить аналитические запросы:

```powershell
docker compose run --rm --no-deps football-python-tools python -c "from pathlib import Path; from src.common.clickhouse import create_clickhouse_client; c=create_clickhouse_client(); sql=Path('scripts/clickhouse_model_smoke_queries.sql').read_text(); [print(c.query(q, parameters={'competition_id':43,'season_id':106}).result_rows) for q in sql.split(';') if q.strip()]; c.close()"
```

No replacement workflow, Stage 3C, marts, BI, API или orchestration в этот этап не входят.

## Stage 3C - Gold Match Analytics

Gold — business-oriented analytical datasets; Silver остаётся нормализованным,
source-aligned immutable слоем. Цепочка: Bronze → Silver S3 → Gold S3 → ClickHouse.
В Stage 3C ClickHouse **не читается и не записывается**: materialization Gold относится
к будущему Stage 3D. BI, API и orchestration здесь не добавляются.

### Входы, grain и метрики

Оба Gold datasets используют ровно четыре latest зарегистрированных Silver build:
`event_core`, `pass_events`, `shot_events`, `match_squads`, для StatsBomb / 43 / 106.
Latest определяется PostgreSQL `created_at DESC, id DESC` один раз для каждого input;
далее используются только зафиксированные build IDs и exact immutable parts.
`teams` и `players` не нужны этим расчётам: имена уже есть в match_squads.
Не нужно переиздавать Silver или зависеть от состояния serving tables.

| Gold dataset | Grain внутри competition/season | Версия | Output partitions |
|---|---|---|---:|
| team_match_stats | match_id, team_id | team_match_stats_v1 | 1 |
| player_match_stats | match_id, team_id, player_id | player_match_stats_v1 | 2 |

Base grain получается только из match_squads. Team base — distinct match/team/name;
player base сохраняет source match-level team_name/player_name, а не representative
имя из competition-level players. Игрок без событий и команда без ударов остаются в output.

Каждый fact агрегируется **отдельно** до нужного grain, затем агрегаты присоединяются
к base через left joins. Raw events/passes/shots друг с другом не соединяются:
это предотвращает many-to-many размножение строк и завышение метрик.

Общие метрики: `event_count`, `pass_attempts`, `shot_count`, `shot_xg`, `shot_goals`,
`under_pressure_events`, `counterpress_events`. У teams также есть
`players_with_events = countDistinct(player_id)`, игнорирующий NULL.
Player aggregates исключают NULL player_id; team aggregates учитывают эти события.
Отсутствующие после joins count metrics становятся long 0, xG — double 0.0;
identity/name поля не заменяются sentinels. Для флагов учитывается только true.

`shot_goals` считает только shot_events.outcome_id=97 (`Goal`), как в существующем
`tests/fixtures/statsbomb_event_domains.json`. Это **не** итоговый счёт матча:
own-goal events не переосмысляются как обычные shot goals. Pass completion пока нет.
`shot_xg` суммирует Double values в детерминированном порядке: Spark sort_array +
collect_list внутри каждой группы + встроенный aggregate. Это не Python UDF/driver collect
и не lossy Decimal/Float32 cast; порядок floating-point сложения не зависит от partitions.
Для текущих небольших матчевых групп такой in-group массив приемлем.
Minutes/per90 отсутствуют: интервалы игрового времени ещё не смоделированы.

### Проверки и lineage

До Spark проверяются Silver catalog context/version/bucket/exact prefix, manifest identity,
checksum metadata, input fingerprint, `_SUCCESS`, exact part inventory и file_count.
Наборы входных матчей у выбранных Silver builds должны совпадать.
Python GET используется только для manifests; Parquet читает Spark S3A по exact file paths
из inventory с recursiveFileLookup, без partition inference из build_id/context paths.
Manifest и _SUCCESS не попадают в Parquet reader. Проверяются фактические row/match counts
и competition/season входного Parquet.

Для каждого event/pass/shot агрегата Spark left_anti проверяет наличие всех metric keys
в base. Non-null player keys вне squads — hard failure, даже если orphan counts были
информационными в Stage 3B. Gold не должен молча терять метрики; исправление такого
расхождения потребует отдельного решения по source semantics, не автоматического удаления.

Output DQ: непустой frame, обязательные context/identity/name поля, unique grain,
неотрицательные non-null метрики, finite nonnegative xG, shot_goals <= shot_count.
Для teams — ровно две строки на матч. Дополнительно проверяется равенство row_count
base и результата joins. Числа 64/128/32/3244 не зашиты в Gold DQ.
`pass_attempts <= event_count` не вводится как независимый invariant: этот этап не доказывает
event-key membership между произвольно выбранными immutable snapshots.

`src/gold/build_identity.py` сортирует inputs по dataset, оставляя только dataset,
build_id, transform_version, schema_sha256, s3_bucket, s3_prefix. Input fingerprint —
SHA-256 canonical JSON этого списка. Build ID — SHA-256 canonical JSON specification:
layer=gold, source, dataset, competition_id, season_id, transform_version,
input_fingerprint, schema_sha256. Schema SHA считается от Spark output schema JSON.
DB IDs, created_at, runtime timestamp, machine и случайные UUID не входят в identity.

Lineage: Gold manifest → exact Silver build IDs/locations → Silver manifests → Bronze.
Gold остаётся воспроизводимым analytical artifact/source of truth для будущего serving слоя.

### Immutable publish и каталог

`004_create_gold_builds.sql` создаёт metadata.gold_builds с identity PK, source/dataset/context,
transform version, тремя SHA-256 hashes, S3 location, row/file counts и created_at.
Hash CHECKs требуют lowercase 64 hex; counts > 0. Unique keys: dataset/context/build_id
и bucket/prefix; lookup index: source/dataset/context. Silver catalog не меняется.
`find_gold_build`, `find_latest_gold_build`, `register_gold_build` используют параметризованный
SQL; регистрация — ON CONFLICT DO NOTHING RETURNING id, затем проверка существующей записи.

```text
football/gold/statsbomb/{team_match_stats|player_match_stats}/
  competition_id=43/season_id=106/build_id=<sha256>/
    part-*.snappy.parquet
    _SUCCESS
    _manifest.json
```

Gold package переиспользует только generic части Silver: canonical JSON/SHA checks,
immutable inventory/manifest transport и writer errorifexists/Snappy с прежним S3A committer.
Gold identity/manifest/publisher отдельные; большого рефакторинга Silver нет.
Manifest содержит спецификацию, build_id, counts, exact inputs и sorted part inventory.
Manifest создаётся условным PUT IfNoneMatch="*" с build_id/SHA-256 metadata.
Overwrite и DeleteObject не используются; запускать один publisher за раз.

Первый запуск: CREATED / REGISTERED. Повтор: UNCHANGED / ALREADY_BUILT и ALREADY_REGISTERED.
Перед registration читаются exact Gold parts и сравниваются schema и **все логические строки**
с детерминированным rebuild через Spark exceptAll в обе стороны, без driver collect.
Это также защищает recovery после успешных Parquet/_SUCCESS и сбоя manifest/catalog:
совпадающие данные не переписываются, восстанавливаются только отсутствующие metadata.
Partial/corrupt prefix либо missing output/manifest у зарегистрированного build — integrity error.
Автоматической очистки нет. После timeout дождаться завершения прежнего server job перед повтором.
Произвольный raw exception text не печатается; diagnostics содержат stage/operation/dataset/class.

### Проверки Stage 3C и ручные команды

Offline checks:

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_gold_match_stats.py
git diff --check
```

Также сохраняются все предыдущие Spark suites из Stage 2D и offline Stage 3A/3B tests.
Новые Gold synthetic fixtures содержат два матча, две команды/матч, игрока без событий,
passes без shots, goal/xG, nullable flags, orphan keys и zero-metric строки.

Следующие команды **ручные**, Codex их не запускает. Сначала применить только migration 004:

```powershell
@'
exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/004_create_gold_builds.sql
'@ | docker compose exec -T football-postgres sh
```

Затем полный read/transform/DQ check-only обоих datasets (обращается к реальным S3/PostgreSQL):

```powershell
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/build_gold_match_stats.py --dataset team-match-stats --check-only
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/build_gold_match_stats.py --dataset player-match-stats --check-only
```

Печатаются selected Silver datasets/short build IDs, transform version, input fingerprint,
schema SHA, build ID, matches, output rows, DQ и CHECK ONLY - nothing published.
Нет S3 writes и PostgreSQL registration. CLI не принимает --limit/--build-id.

Только после успешных check-only — publish и повтор для проверки идемпотентности:

```powershell
foreach ($dataset in @('team-match-stats', 'player-match-stats')) {
    docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/build_gold_match_stats.py --dataset $dataset
    if ($LASTEXITCODE -ne 0) { throw "Gold publish failed: $dataset" }
    docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/build_gold_match_stats.py --dataset $dataset
    if ($LASTEXITCODE -ne 0) { throw "Gold repeat failed: $dataset" }
}
```

Для одинакового build ID между запусками не публикуйте новые Silver inputs.
Новые Docker services/dependencies, IAM changes и Gold → ClickHouse в этот этап не входят.

## Stage 3D - Gold Serving in ClickHouse

Gold S3 остаётся воспроизводимым аналитическим артефактом/source of truth.
ClickHouse `football.team_match_stats` и `football.player_match_stats` — serving copies
готовых Gold Parquet, без повторного расчёта business metrics. Они убирают повторяющиеся
joins сырых Silver events для обычной аналитики и будущего BI. BI/Superset/API пока нет.
Per90 не рассчитывается до появления отдельной модели игрового времени.

```text
metadata.gold_builds → exact registered Gold build → manifest/_SUCCESS/inventory
    → ClickHouse s3(selectel_s3, exact-build/part-*.parquet)
    → explicit INSERT SELECT → MergeTree → target DQ → metadata.clickhouse_gold_loads
```

### Контракты и миграции

Новые миграции выполняются вручную: PostgreSQL
`005_create_clickhouse_gold_loads.sql` и ClickHouse `004_create_gold_match_stats.sql`.
Ранее применённые миграции, Silver loaders и Gold business calculations не меняются.
Gold catalog использует `gold_build_id`, а не `silver_build_id`: три SHA-256 checks,
`row_count > 0`, UNIQUE `(clickhouse_database, clickhouse_table, gold_build_id)` и индекс
`(source, dataset, competition_id, season_id)`. Registration параметризован,
`ON CONFLICT DO NOTHING RETURNING id`. Существующие exact/latest Gold helpers переиспользуются;
latest определяется `ORDER BY created_at DESC, id DESC`.

Обе serving tables — обычный MergeTree, partition `(competition_id, season_id)`.
Team grain: `(match_id, team_id)`; player grain: `(match_id, team_id, player_id)`.
ORDER BY содержит context, затем соответствующий grain.

| Поля | ClickHouse type | Dataset |
| --- | --- | --- |
| competition_id, season_id, team_id | UInt32 | оба |
| match_id | UInt64 | оба |
| team_name | LowCardinality(String) | оба |
| player_id / player_name | UInt32 / String | player |
| event_count, pass_attempts, shot_count, shot_goals | UInt64 | оба |
| under_pressure_events, counterpress_events | UInt64 | оба |
| players_with_events | UInt64 | team |
| shot_xg | Float64 | оба |
| gold_build_id | FixedString(64) | оба |
| loaded_at | DateTime64(3, 'UTC') DEFAULT now64(3) | оба |

`src/analytics/gold_specs.py` задаёт frozen contracts с явными колонками/casts.
Spark Double xG сохраняется как Float64; numeric conversions используют `accurateCast`.
Нет Float32 narrowing, `SELECT *` или credentials в SQL. Named collection `selectel_s3`
и существующая virtual-hosted URL configuration переиспользуются без изменения IAM.

### Resolver, проверки и восстановление

`gold_input.py` разрешает только registered builds для statsbomb/43/106 и версий
`team_match_stats_v1` / `player_match_stats_v1`. CLI принимает latest или точный
`--build-id <64 lowercase hex>`, но не произвольный S3 prefix.
До любого ClickHouse access проверяются catalog, manifest checksum/identity/inputs,
`_SUCCESS` и точный part inventory/file_count. Python читает только metadata,
Parquet bodies читает ClickHouse напрямую.

Source и target DQ проверяют row_count из manifest, unique grain, match_count,
context min/max, обязательные поля и metrics без NULL, неотрицательные metrics,
finite xG и `shot_goals <= shot_count`. У team каждый матч содержит ровно две команды.
Ожидания не захардкожены как 128/3244.

Serving policy: один Gold build на dataset/competition/season.

- Пустой target: один INSERT, DQ, затем registration.
- Полный тот же build: `UNCHANGED / ALREADY_LOADED`, INSERT пропускается.
- Полный build без load catalog после timeout/PG failure: DQ и только registration.
- Partial/excess/missing registered rows: integrity error, без auto cleanup.
- Другой или смешанный build: `GoldBuildConflictError`, без append/delete/replace.

Полные loaders используют существующий общий PostgreSQL advisory writer lock.
`insert_deduplication_token=gold_build_id`, deterministic ordering и MergeTree dedup window
1000 — дополнительная защита, а не замена проверки состояния target. Не запускать
некооперирующих writers. После INSERT timeout сначала дождаться окончания запроса на сервере,
затем повторить тот же build. Check-only lock/INSERT/registration не выполняет:
он читает реальный Gold через S3, проверяет схему/DQ/конфликт и печатает expected/source rows,
files, existing target/build и `Would load`, затем `CHECK ONLY - nothing loaded`.
Diagnostics содержат stage/operation/exception class, но не raw exception text/credentials.

`scripts/check_clickhouse_gold_model.py` — read-only, без S3. Он берёт фактически
загруженные Gold/Silver build IDs, проверяет их catalogs и соответствие Gold input fingerprint
загруженному Silver. Проверяет grain keys в обе стороны относительно match_squads,
team event/pass/shot sums, player sums только для Silver `player_id IS NOT NULL`,
player row count против squad grain и team xG sum против Silver xG
(`math.isclose`, relative/absolute tolerance `1e-9`). Все 12 проверок hard;
context/build IDs ограничивают каждую сторону сравнения. Повторная проверка build state
обнаруживает смену snapshot, но это не распределённая транзакция: запускать после writers.

`scripts/clickhouse_gold_smoke_queries.sql` содержит 8 read-only запросов: team totals,
team-match xG, player totals, top xG, top shots, average team xG, squad players без событий,
pressure activity. Totals группируются по ID, `min(name)` — только deterministic display
label при вариациях имени между матчами, не entity resolution.

### Проверки Stage 3D

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_local.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_datasets.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_gold.py
git diff --check
```

Integration suites используют только session TEMPORARY tables и synthetic rows, без S3
и без применения миграций к `football`. Таблицы исчезают при истечении тестовой сессии
(session_timeout=60), DROP не выполняется. Offline cases покрывают оба datasets,
resolver/manifest, schema/SQL, first/repeat/check-only, partial/conflict, timeout recovery,
catalog failure, DQ и отсутствие секретов в diagnostics.
Предыдущие пять Spark synthetic suites также остаются обязательной регрессией.

### Ручная проверка Stage 3D

Следующие команды изменяют локальные persistent databases и/или читают реальный Selectel.
Codex их не выполняет. Из корня проекта сначала применить только новые миграции:

```powershell
@'
exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /migrations/005_create_clickhouse_gold_loads.sql
'@ | docker compose exec -T football-postgres sh
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL migration failed' }

@'
exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery < /migrations/004_create_gold_match_stats.sql
'@ | docker compose exec -T football-clickhouse sh
if ($LASTEXITCODE -ne 0) { throw 'ClickHouse migration failed' }
```

Проверить каждый dataset отдельно (без загрузки):

```powershell
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset team-match-stats --check-only
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset player-match-stats --check-only
```

После успешных check-only скопировать соответствующие `Gold build ID` в prompts ниже.
Каждый dataset — отдельная команда и recovery boundary. После любой ошибки остановиться,
не запускать следующий dataset до выяснения причины.

```powershell
$teamGoldBuild = Read-Host 'Gold build ID from team check-only'
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset team-match-stats --build-id $teamGoldBuild
if ($LASTEXITCODE -ne 0) { throw 'Team load failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset team-match-stats --build-id $teamGoldBuild
if ($LASTEXITCODE -ne 0) { throw 'Team repeat failed' }

$playerGoldBuild = Read-Host 'Gold build ID from player check-only'
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset player-match-stats --build-id $playerGoldBuild
if ($LASTEXITCODE -ne 0) { throw 'Player load failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_gold.py --dataset player-match-stats --build-id $playerGoldBuild
if ($LASTEXITCODE -ne 0) { throw 'Player repeat failed' }

docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_gold_model.py --competition-id 43 --season-id 106
if ($LASTEXITCODE -ne 0) { throw 'Gold model check failed' }
```

Первый load ожидает `LOADED / REGISTERED`, повтор —
`UNCHANGED / ALREADY_LOADED` и `ALREADY_REGISTERED`. После успешной model check
выполнить все восемь analytical queries (read-only, без S3):

```powershell
@'
from contextlib import closing
from pathlib import Path
from src.common.clickhouse import create_clickhouse_client
with closing(create_clickhouse_client()) as client:
    queries = Path('scripts/clickhouse_gold_smoke_queries.sql').read_text().split(';')
    for index, query in enumerate((q for q in queries if q.strip()), 1):
        result = client.query(query, parameters={'competition_id': 43, 'season_id': 106})
        print('Query', index, result.column_names)
        for row in result.result_rows:
            print(row)
'@ | docker compose run --rm --no-deps -T football-python-tools python -
```

## Stage 3E - Match dimension

Silver `matches` (`matches_v1`) — source-aligned измерение матчей StatsBomb, одна строка
на `match_id`. Дата, kickoff, стадия, участники, счёт, стадион и судья отделены от event
facts: BI/API сможет показывать понятный матч вместо одного raw ID. Superset/API не добавлены.

```text
matches 1 → many event_core / pass_events / shot_events / match_squads
matches 1 → 2 team_match_stats rows (именно home и away)
matches 1 → many player_match_stats rows
```

### Источник, схема и DQ

Parent разрешается через `metadata.ingestion_objects`: statsbomb/world_cup_2022_matches,
latest по `first_seen_at DESC, id DESC`. Key и SHA не захардкожены. Existing Bronze reader
проверяет metadata, SHA-256 скачанных bytes и размер. PostgreSQL helper теперь также
возвращает source/dataset/source_url для lineage, прежние поля и selection semantics сохранены.

Форма nested-полей сверена с [публичным StatsBomb matches source](https://raw.githubusercontent.com/statsbomb/open-data/master/data/matches/43/106.json).
`competition.competition_id`, `season.season_id`, `home_team.home_team_id/home_team_name`,
`away_team.away_team_id/away_team_name`, `competition_stage.id/name`, `stadium.id/name`,
`referee.id/name` проецируются явно. Runtime читает только зарегистрированный immutable
Bronze, а не новую версию GitHub. Synthetic fixture `tests/fixtures/statsbomb_matches.json`
содержит два матча, три команды, разные даты/стадии и отсутствующие optional attributes.

| Silver поле | Spark type | ClickHouse type |
| --- | --- | --- |
| competition_id, season_id | Long | UInt32 |
| match_id | Long | UInt64 |
| match_date | Date | Date |
| kick_off | String, nullable | String |
| match_week | Integer, nullable | Nullable(UInt16) |
| competition_stage_id | Long | UInt16 |
| competition_stage_name | String | LowCardinality(String) |
| home_team_id, away_team_id | Long | UInt32 |
| home_team_name, away_team_name | String | LowCardinality(String) |
| home_score, away_score | Integer | UInt16 |
| stadium_id, referee_id | Long, nullable | Nullable(UInt32) |
| stadium_name, referee_name | String, nullable | Nullable(String) |

Явные raw/output schemas находятся в `src/silver/statsbomb/matches.py`, без inferSchema.
`kick_off` — строка исходного времени, timezone не назначается. Silver сохраняет NULL.
На serving boundary NULL kickoff явно заменяется на `''`, поскольку запрошенный
ClickHouse contract — non-null String; другие optional NULL остаются NULL.
Дата преобразуется безопасно через проверку epoch days как UInt16: простой
`accurateCast(Date32, Date)` может ограничивать значение диапазоном вместо ошибки.
Для nullable integer fields ненулевые overflow также вызывают ошибку, не превращаются в NULL.

Hard DQ: непустой output; unique/non-null match_id; required date/stage/team IDs/names/scores;
правильный context; home != away; scores >= 0. Aggregate informational NULL counts печатаются
для stadium/referee/kick_off/match_week. Никакого ожидания ровно 64 строк в коде.
Team IDs остаются StatsBomb-native, без canonical platform IDs.

Перед DQ разрешается один текущий registered Silver `teams` build: проверяются catalog,
manifest/_SUCCESS/inventory, затем Spark читает exact Parquet parts и проверяет schema,
row count, unique team IDs и context. Home/away references проверяются Spark `left_anti`
joins по team ID в том же competition/season. На driver возвращаются только counts.
Teams build — reference-validation prerequisite, не источник output attributes: его ID
печатается в diagnostics, но не изменяет заданную Bronze-only identity `matches`.

### Identity и публикация

Fingerprint — SHA-256 canonical JSON с единственным Bronze input и полями:
`source, dataset, source_url, s3_bucket, object_key, sha256`. Не включает timestamps,
credentials или local paths. Проверяются source URL context 43/106 и SHA format.
Build specification использует прежний Silver machinery:
`layer=silver/source=statsbomb/dataset=matches/competition_id=43/season_id=106`,
`transform_version=matches_v1`, input fingerprint и hash явной Spark schema.

```text
football/silver/statsbomb/matches/competition_id=43/season_id=106/build_id=<hash>/
  part-*.snappy.parquet       (1 output partition, без partitionBy(match_id))
  _SUCCESS
  _manifest.json
```

Общий `publish_build` переиспользует errorifexists/Snappy writer, exact readback
schema/counts, conditional manifest creation и `metadata.silver_builds` registration.
У matches один input artifact содержит много матчей: manifest match_count == row_count,
а не число input artifacts. Existing events/lineups manifest rules не меняются.
Первый запуск — CREATED / REGISTERED, повтор — UNCHANGED / ALREADY_BUILT / ALREADY_REGISTERED.
После metadata failure полный output не переписывается; partial/corrupt output hard-fails.
Ни overwrite, ни DeleteObject, ни новая PostgreSQL migration не нужны.

### ClickHouse serving и модель

Новая migration `infrastructure/clickhouse/migrations/005_create_matches.sql` создаёт
`football.matches`: plain MergeTree, partition `(competition_id, season_id)`, ORDER BY
`(competition_id, season_id, match_date, match_id)`, `silver_build_id FixedString(64)` и
`loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)`. Старые миграции не меняются.

Существующий `load_clickhouse_silver.py --dataset matches` использует новый DatasetSpec,
но прежний loader/state machine, named collection, explicit projection, source/target DQ,
dedup token и `metadata.clickhouse_loads`. One-build-per-context policy и recovery прежние:
полный тот же build не INSERT-ится снова; partial или другой build не очищается/не заменяется.
Check-only читает real S3 через ClickHouse, но не INSERT-ит и не регистрирует load.

`check_clickhouse_model.py` теперь требует семь Silver и обе Gold serving tables.
Прежние hard/informational checks сохранены; добавлены 11 hard aggregate SQL checks:
match references от event_core/pass_events/shot_events/match_squads/обоих Gold datasets,
home/away references к teams, Gold team pairs против home/away в обе стороны и ровно
две уникальные team rows на матч. Каждая сторона ограничена context и фактически
загруженным build ID. Проверка повторно читает serving snapshot; запускать без active writers.
`check_clickhouse_gold_model.py` по-прежнему проверяет Gold metric/lineage consistency.

Девятый запрос в `scripts/clickhouse_gold_smoke_queries.sql` соединяет team_match_stats
с matches: дата, kickoff, stage, home/away, score, team metrics. Это обычный read-only join,
не materialized view и не денормализация Gold. Старые восемь запросов сохранены.

### Проверки и ручной запуск Stage 3E

Разрешённые offline/local checks:

```powershell
docker compose config -q
docker compose run --rm --no-deps football-python-tools python -X pycache_prefix=/tmp/football-pycache -m compileall -q src scripts tests
docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" tests/spark/test_matches.py
docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_matches.py
git diff --check
```

Также выполняются прежние пять Spark и три ClickHouse synthetic suites. Local ClickHouse
tests используют только session TEMPORARY tables, без persistent migrations и real S3.

Следующие команды выполняются **вручную**, не Codex. Уже должен существовать registered
Silver teams build. Сначала read/transform/DQ check-only, затем publish и повтор:

```powershell
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_matches.py --check-only
if ($LASTEXITCODE -ne 0) { throw 'Matches check-only failed' }
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_matches.py
if ($LASTEXITCODE -ne 0) { throw 'Matches publish failed' }
docker compose run --rm --no-deps football-spark spark-submit --master "local[2]" scripts/publish_silver_matches.py
if ($LASTEXITCODE -ne 0) { throw 'Matches repeat failed' }
```

Между повторами не изменять Bronze parent. `--limit` не поддерживается. Check-only
печатает DQ/counts/fingerprints/build ID, ничего не публикует и не регистрирует.
Затем применить только новую ClickHouse migration и проверить загрузку:

```powershell
@'
exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery < /migrations/005_create_matches.sql
'@ | docker compose exec -T football-clickhouse sh
if ($LASTEXITCODE -ne 0) { throw 'Matches migration failed' }

$matchesBuild = Read-Host 'Build ID printed by matches publish'
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset matches --build-id $matchesBuild --check-only
if ($LASTEXITCODE -ne 0) { throw 'Matches load check failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset matches --build-id $matchesBuild
if ($LASTEXITCODE -ne 0) { throw 'Matches load failed' }
docker compose run --rm --no-deps football-python-tools python scripts/load_clickhouse_silver.py --dataset matches --build-id $matchesBuild
if ($LASTEXITCODE -ne 0) { throw 'Matches load repeat failed' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_model.py --competition-id 43 --season-id 106
if ($LASTEXITCODE -ne 0) { throw 'Cross-model check failed' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_gold_model.py --competition-id 43 --season-id 106
```

Для smoke SQL используйте PowerShell/Python-команду из Stage 3D: она теперь выполнит
девять запросов, включая join с matches. После INSERT timeout дождаться завершения
серверного запроса, затем повторить тот же build. Automatic cleanup нет.

## Stage 4A - Superset BI foundation

Это **local/dev Docker Compose deployment, не production deployment**. Приложение
доступно только на loopback `http://localhost:${SUPERSET_HOST_PORT}`, по примеру
`http://localhost:18088`. Для production нужны отдельный security review, TLS/reverse
proxy, secret management, backups и эксплуатационные ограничения. Не открывайте
существующие ClickHouse host ports в Интернет.

```text
Gold/Silver ClickHouse tables → ordinary BI views → superset_reader (read-only)
    → Superset → World Cup 2022 Overview (создаётся вручную в UI)

Superset → football-superset-db → football_superset_db_data
           только users/charts/dashboards/datasource definitions
```

`football_metadata` остаётся platform catalog. Superset получает собственный PostgreSQL
service/database/volume: внутренние миграции BI-инструмента не смешиваются с нашей
ingestion/build metadata. Аналитические данные остаются в ClickHouse; воспроизводимые
Gold artifacts остаются в S3. BI views лишь присоединяют match metadata, не переписывая
Gold, не создавая новые S3 artifacts или materialized views.

### Образ, конфигурация и init

`docker/superset/Dockerfile` основан на official `apache/superset:6.0.0`, дополнительно
закреплённом digest. Полный source repository не клонируется. Python packages ставятся
в `/app/.venv` с constraints из release image и `uv pip check`:

- `clickhouse-connect==0.15.0` — тот же pin, что в `requirements/tools.txt`;
- `psycopg2-binary==2.9.6` — точный PostgreSQL extra Superset 6.0.0;
- `lz4==4.4.5`, `zstandard==0.23.0` — compression dependencies (zstandard согласован с base constraints).

Совместимость сверена с [Superset 6.0.0 dependency contract](https://github.com/apache/superset/blob/6.0.0/pyproject.toml)
и [clickhouse-connect 0.15.0](https://github.com/ClickHouse/clickhouse-connect/blob/v0.15.0/setup.py).
Legacy clickhouse-sqlalchemy не устанавливается. Runtime работает как non-root `superset`.

`infrastructure/superset/superset_config.py` требует непустые env values. SECRET_KEY
не имеет default и должен быть случайным, длиной минимум 32 символа. Metadata URI
строится с URL-encoding username/password; database name — простой PostgreSQL identifier.
Запрещены SQLite и `football_metadata`. Host задаётся Compose как `football-superset-db`.
Talisman HTTPS enforcement выключен только для local loopback HTTP, CSRF сохранён.
Нет Redis/Celery workers, alerts/reports, global async queries или загрузки examples.

`football-superset-init` использует тот же образ и последовательно выполняет:
`superset db upgrade` → проверку/создание admin через security manager → `superset init`.
Повторный запуск не меняет пароль существующего active Admin. Если username принадлежит
не-Admin/inactive user или создание не удалось, init завершается с ошибкой, а не `|| true`.
Admin credentials не передаются в CLI arguments. Framework output перехватывается:
в init logs попадают только stage/status/exception class, не raw exceptions/passwords.
Не запускайте одновременно несколько init. Смена env password не сбрасывает пароль
существующего admin или уже инициализированного PostgreSQL — это отдельная ручная операция.

App ждёт healthy metadata DB и successful one-shot init. Healthcheck использует Python
urllib и `http://localhost:8088/health`, без предположений о curl/wget.
Metadata PostgreSQL не публикует host port. App не получает S3 credentials, platform
PostgreSQL password, ClickHouse admin password или Superset admin password.

### Секреты и ClickHouse reader

Добавьте новые переменные из `.env.example` в свой gitignored `.env` **вручную**.
SECRET_KEY, metadata DB password, admin password и reader password должны быть отдельными
секретами, не значением `football_user` и не `admin/admin`. Сгенерируйте их в password
manager; не сохраняйте в README/SQL/exports/скриншотах. Не заменяйте `.env` целиком.
Не меняйте SECRET_KEY после создания datasources без процедуры Superset key rotation:
он используется в том числе для шифрования сохранённых datasource credentials.

`SUPERSET_CLICKHOUSE_USER=superset_reader` — фиксированное имя XML-пользователя, не
переименование через Compose. Пароль берётся из `SUPERSET_CLICKHOUSE_PASSWORD` через
ClickHouse `from_env`. Compose требует непустое значение **до запуска любого сервиса**,
чтобы пустой placeholder не создавал reader без пароля. Поэтому до добавления новой
переменной старые Compose-команды тоже будут fail-fast. `.env.example` содержит только
пустые secret placeholders, а не работоспособные default credentials.

`20_superset_reader.xml` монтируется отдельным файлом users.d. Существующий
`10_named_collection_access.xml`, entrypoint-managed files и platform user не заменяются.
Для reader задан профиль `readonly=1` и ровно один явный grant:

```sql
GRANT SELECT ON football.*
```

В ClickHouse 25.8 SELECT включает scoped SHOW COLUMNS → SHOW TABLES → SHOW DATABASES;
дополнительный глобальный SHOW или SELECT ON *.* не нужен. Драйвер использует SHOW
DATABASES/TABLES, DESCRIBE и metadata tables. Доступ к необходимым system metadata
предусмотрен сервером; tables/columns/databases фильтруются по правам пользователя.
Основание: [ClickHouse 25.8 ContextAccess](https://github.com/ClickHouse/ClickHouse/blob/v25.8.23.13-lts/src/Access/ContextAccess.cpp)
и [driver introspection](https://github.com/ClickHouse/clickhouse-connect/blob/v0.15.0/clickhouse_connect/cc_sqlalchemy/inspector.py).
XML `grants` — явный allowlist. Нет INSERT/ALTER/CREATE/DROP/TRUNCATE/SYSTEM/S3,
NAMED COLLECTION, access management, grant/admin options. Views используют
`SQL SECURITY INVOKER`, не права создавшего их администратора. Reader может SELECT
любые football objects по заданному ТЗ, но обычные dashboard charts используют только
три рекомендованных datasets ниже.

### BI views и проверки

Migration `006_create_bi_views.sql` добавляет две ordinary VIEW через IF NOT EXISTS:

- `bi_team_match_stats`: Gold team grain + дата/kickoff/week/stage/home/away/score,
  is_home/opponent, goals_for/goals_against, signed goal_difference и match_result W/D/L;
- `bi_player_match_stats`: Gold player grain + match metadata/is_home/opponent.

Join в обоих случаях по competition_id, season_id, match_id. Goals/result выводятся из
официального match score, не shot_goals и не xG. Match result не означает tournament
advancement; penalty shoot-out/правила турнира отдельно не моделируются. Per90 нет.
Views не выбирают второй snapshot: прежняя one-build-per-context policy и успешные
Stage 3D/3E model checks — prerequisite. IF NOT EXISTS не обновляет ранее созданную
view при изменении её определения: дальнейшие изменения требуют новой migration.

`scripts/check_clickhouse_bi_views.sql` содержит семь read-only checks с `throwIf`:
непустые и равные source/view counts, unique team/player grain, opponent validity,
signed difference/result, сверка goals/opponent/result с matches. Context задаётся
query parameters. Любое нарушение завершает проверку с ошибкой.

### Ручной запуск Stage 4A (PowerShell)

Codex не выполняет эти команды с настоящими секретами. Сначала заполните `.env`,
остановите запуск publishers/loaders на время пересоздания ClickHouse, затем:

```powershell
git check-ignore .env
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose config failed' }
docker compose build football-superset
if ($LASTEXITCODE -ne 0) { throw 'Superset build failed' }

# Только этот ClickHouse service: подключить новый env и отдельный users.d mount.
# Existing named volumes сохраняются, будет краткий перерыв доступности ClickHouse.
docker compose up -d --no-deps --force-recreate --wait football-clickhouse
if ($LASTEXITCODE -ne 0) { throw 'ClickHouse health failed' }

@'
exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery < /migrations/006_create_bi_views.sql
'@ | docker compose exec -T football-clickhouse sh
if ($LASTEXITCODE -ne 0) { throw 'BI migration failed' }

docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_model.py --competition-id 43 --season-id 106
if ($LASTEXITCODE -ne 0) { throw 'Cross-model check failed' }
docker compose run --rm --no-deps football-python-tools python scripts/check_clickhouse_gold_model.py --competition-id 43 --season-id 106
if ($LASTEXITCODE -ne 0) { throw 'Gold model check failed' }
```

Выполнить семь BI assertions (read-only, без S3):

```powershell
@'
from pathlib import Path
from contextlib import closing
from src.common.clickhouse import create_clickhouse_client
with closing(create_clickhouse_client()) as client:
    for sql in Path('scripts/check_clickhouse_bi_views.sql').read_text().split(';'):
        if sql.strip():
            print(client.query(sql, parameters={'competition_id': 43, 'season_id': 106}).result_rows)
'@ | docker compose run --rm --no-deps -T football-python-tools python -
if ($LASTEXITCODE -ne 0) { throw 'BI view validation failed' }
```

Проверить reader **до подключения Superset**, без пробных write-команд:

```powershell
@'
exec clickhouse-client --user superset_reader --password "$SUPERSET_CLICKHOUSE_PASSWORD" --multiquery <<'SQL'
SELECT currentUser(), getSetting('readonly');
SHOW DATABASES;
SHOW TABLES FROM football;
DESCRIBE TABLE football.bi_team_match_stats;
SELECT count() FROM football.bi_team_match_stats;
CHECK GRANT SELECT ON football.*;
CHECK GRANT INSERT ON football.*;
CHECK GRANT ALTER ON football.*;
CHECK GRANT CREATE TABLE ON football.*;
CHECK GRANT DROP TABLE ON football.*;
CHECK GRANT TRUNCATE ON football.*;
CHECK GRANT SYSTEM ON *.*;
CHECK GRANT S3 ON *.*;
CHECK GRANT NAMED COLLECTION ON selectel_s3;
CHECK GRANT ACCESS MANAGEMENT ON *.*;
SQL
'@ | docker compose exec -T football-clickhouse sh
```

Ожидания: user=superset_reader, readonly=1, metadata/SELECT успешны; CHECK GRANT SELECT
возвращает 1, все остальные перечисленные CHECK GRANT — 0. Если не так, не подключайте BI.
Затем metadata DB, one-shot init и app:

```powershell
docker compose up -d --wait football-superset-db
if ($LASTEXITCODE -ne 0) { throw 'Superset DB health failed' }
docker compose up --no-deps --abort-on-container-exit --exit-code-from football-superset-init football-superset-init
if ($LASTEXITCODE -ne 0) { throw 'Superset initialization failed' }
docker compose up -d --wait football-superset
if ($LASTEXITCODE -ne 0) { throw 'Superset app health failed' }
docker compose ps football-superset football-superset-db football-superset-init
```

Повторный init допустим: admin EXISTS, пароль не переписывается. App dependency может
снова запустить init при Compose up; он идемпотентен. Не использовать down -v/prune.
Откройте `http://localhost:18088` (или свой SUPERSET_HOST_PORT), войдите созданным admin.

### Ручное подключение ClickHouse и datasets

В Settings → Database Connections → + Database выберите **ClickHouse Connect (Superset)**.
Используйте host `football-clickhouse`, port `8123`, database `football`, user
`superset_reader`, отдельный reader password. Для текущего Docker HTTP выключите
Encryption; `localhost:18124` внутри Superset — неверный адрес.
Если выбран режим SQLAlchemy URI, формат:

```text
clickhousedb://superset_reader:<URL-encoded-reader-password>@football-clickhouse:8123/football
```

Предпочтительнее отдельное password field в connection form, чтобы не ошибиться с URL
encoding специальных символов. Test Connection → Connect. Не включайте DML, CTAS/CVAS,
file uploads или asynchronous execution. Настоящая защита — ClickHouse grants, а не UI.
Не используйте football_user. Сохранённые datasource credentials зашифрованы SECRET_KEY
в отдельной metadata DB; ни URI, ни export с секретами не коммитить.

Datasets → + Dataset: выбрать connection, schema `football`, добавить:

1. `matches`;
2. `bi_team_match_stats`;
3. `bi_player_match_stats`.

В каждом dataset отметить `match_date` temporal и выбрать его default time column.
Views могут показываться в общем списке tables драйвера, это нормально. Raw Silver
event tables для обычных charts пока не добавлять. Если datasource содержит и другие
contexts, установить на charts фильтры competition_id=43 и season_id=106.

### Dashboard: World Cup 2022 Overview

Создавайте каждый chart через Charts → + Chart, сохраняйте и добавляйте в новый dashboard
**World Cup 2022 Overview**. Initial time range — No filter либо полный диапазон турнира.

| Chart | Dataset | Настройка |
| --- | --- | --- |
| Matches, Big Number | matches | COUNT(DISTINCT match_id) |
| Team total xG, Bar | bi_team_match_stats | team_name; SUM(shot_xg); descending |
| Team shots, Bar | bi_team_match_stats | team_name; SUM(shot_count); descending |
| Team passing volume, Bar | bi_team_match_stats | team_name; SUM(pass_attempts); descending |
| Shots vs xG by team, Scatter | bi_team_match_stats | entity team_name; X SUM(shot_count); Y SUM(shot_xg) |
| Top players by xG, Bar | bi_player_match_stats | player_name; SUM(shot_xg); descending; top 20 |
| Top players by shots, Bar | bi_player_match_stats | player_name; SUM(shot_count); descending; top 20 |
| Matches, Table (raw records) | matches | match_date, competition_stage_name, home_team_name, away_team_name, home_score, away_score; date ascending |

В Superset 6.0.0 scatter-визуализация доступна как **Bubble Chart**: для обычного
Shots vs xG scatter задайте Size metric `MAX(1)` (одинаковые точки), Entity `team_name`,
X/Y как в таблице; Series при необходимости также `team_name`.

Для каждого chart выберите `match_date` как time column. Не используйте COUNT(*) для
числа матчей в team/player views: их grain шире. При совпадениях/вариациях player_name
можно дополнительно группировать по player_id, не придумывая canonical identity.
Per90/minutes и advanced dashboards в Stage 4A не входят.

В dashboard Edit → native filters добавьте:

- `competition_stage_name`: Select filter; источник bi_team_match_stats, scope явно
  включает все подходящие team/player/matches charts с одноимённой колонкой;
- `match_date`: Time range filter; scope всех charts, у каждого temporal column match_date;
- `team_name`: Select filter из bi_team_match_stats; scope явно включает team и player
  charts. Matches Big Number и Matches Table **исключены**: у matches нет team_name,
  только home_team_name/away_team_name. Подпишите это поведение в dashboard description.

Фильтр из team dataset не обязан автоматически влиять на player dataset. Проверьте
native filter scope для каждого chart и совместимость колонок; после выбора команды
откройте View query у team/player charts и убедитесь в наличии team_name predicate.
Stage/date также проверить на всех datasets. Cross-filtering кликом по chart — отдельная
настройка, не замена explicit native filter scope. Нельзя обещать общий filter state
без этой проверки. Dashboard JSON и внутренние IDs автоматически не создаются.

### Offline/local checks Stage 4A

Проверки без live secrets используют process-only синтетический reader password,
чтобы пройти fail-closed Compose interpolation. Значение не сохраняется в `.env`
и не применяется к работающему ClickHouse. Не используйте его для запуска BI services.

```powershell
$previousReader = $env:SUPERSET_CLICKHOUSE_PASSWORD
try {
    $env:SUPERSET_CLICKHOUSE_PASSWORD = 'static-check-only-not-a-live-password'
    docker compose config -q
    docker compose run --rm --no-deps football-python-tools python -m unittest discover -s tests
    docker compose run --rm --no-deps football-python-tools python tests/integration/test_clickhouse_bi.py
} finally {
    $env:SUPERSET_CLICKHOUSE_PASSWORD = $previousReader
}
git diff --check
```

Новые ClickHouse tests выполняют только SELECT с synthetic CTEs и readonly=1 — даже
TEMPORARY tables не создаются. Они проверяют обе реальные view projections, signed
goal difference, W/D/L, official scores, дубликаты и все семь validation statements.
Offline tests проверяют config/URI, missing secrets, init idempotency/errors, XML grant
allowlist, Compose isolation/healthchecks и SQL structure. Built-image tests в
`tests/superset/test_image.py` запускаются с `--network none`, без Superset app/server
и реальных credentials. Reader runtime permissions и dashboard остаются ручной проверкой.

## Stage 4B - Match result semantics and penalty shootouts

Подготовлены immutable Gold `match_results_v1`, ClickHouse migration `007`, BI migration
`008` и явно выбираемые `team_match_stats_v2` / `player_match_stats_v2`.
**Миграции, публикация и v1→v2 serving cutover автоматически не выполнялись.**

Read-only аудит текущего WC2022 подтвердил: Gold v1 включает period=5 —
41 лишний для обычной match-performance аналитики shot, 26 shot goals, 32.1235 xG.
Затронуты 10 team-строк и 41 player-строка по shots; с учётом event_count — 53 player-строки.
Extra time (period 3/4) остаётся в v2. Официальный счёт не суммируется с shootout score.

- [Полный аудит: exact build IDs и все построчные различия](docs/stage4b_shot_audit.json).
- [Контракт, DQ, schema, controlled cutover plan и точные ручные команды](docs/stage4b.md).

Для Superset Match Table источник `football.match_results` даёт одну строку на матч,
`display_score` вроде `3-3 (4-2 pens)` и `result_method=PENALTIES`.
`match_date` остаётся Date; Table D3 format: **`%Y-%m-%d`**, без преобразования в String.
После migration 008 team `match_result` учитывает shootout winner; проверка результата
теперь `scripts/check_clickhouse_match_results.py --bi`, а не прежний Stage 4A W/D/L SQL.
Match Analysis dashboard пока не создаётся.

## Stage 4C - Safe stats v2 shadow serving cutover

Реализован безопасный путь загрузки stats v2 в отдельные
`football.team_match_stats_v2` / `football.player_match_stats_v2`.
v1-таблицы и история каталога сохраняются. Mapping закрытый, для v2 обязательны
точный Gold build ID и четыре Silver build ID из аудита Stage 4B.

Миграция 009 создаёт shadow-таблицы; 010 переключает только два публичных BI view,
сохраняя все колонки и authoritative `match_results`; 011 предназначена **только
для явного rollback**, не для последовательного применения после 010.
Добавлены проверки всех grain/metric deltas по аудиту, lineage, схем и BI coverage.
Superset datasets не переименовываются и не дублируются.

**Live cutover не выполнен.** Точные ручные PowerShell-команды, STOP/check points,
DDL backup, maintenance window, smoke tests и rollback: [docs/stage4c.md](docs/stage4c.md).
Два view заменяются неатомарно; нельзя открывать BI до проверки обоих.

## Stage 4D - Match Analysis foundation

Подготовлены четыре отдельные ordinary BI views для анализа одного матча:
`bi_match_overview`, `bi_match_team_stats`, `bi_match_player_stats`, `bi_match_shots`.
Они сохраняют существующие метрики и единый `match_label` из overview;
`match_results` остаётся источником результата. Shot view сохраняет все удары,
включая period=5: обычные performance charts обязаны фильтровать `is_shootout=0`.
Period 3/4 остаётся в обычной статистике, координаты сохраняются как `start_x/start_y`.

Существующие World Cup Overview datasets/views не изменены. Миграция 012 и
Superset dashboard **не применены автоматически**. Архитектура, проверки,
точные PowerShell-команды и ручной дизайн Match Analysis: [docs/stage4d.md](docs/stage4d.md).
Для проверки SELECT-проекций до миграции:
`python scripts/check_clickhouse_match_analysis.py --candidate` внутри python-tools.

## Stage 4E - Match Visual Analytics

Подготовлена additive migration 013: `bi_match_xg_race`, `bi_match_shot_map`,
`bi_match_shootout`. Первые два view содержат только обычные удары, включая extra
time; третий — упорядоченные попытки серии пенальти с промежуточным счётом.
Накопления xG проверяются по каждому событию и сверяются с team stats. Координаты
и nullable-поля сохраняются без разворота/замены. Stage 4D и World Cup Overview
не изменяются, новых Gold/S3 artifacts нет.

**Миграция и Superset изменения не выполняются автоматически.** Представление xG
race, ограничения часовой оси/shot scatter, проверенные Step/Bubble plugins,
точные ручные команды и настройки charts: [docs/stage4e.md](docs/stage4e.md).
SELECT-only preview до установки 013:
`python scripts/check_clickhouse_match_visuals.py --candidate` внутри python-tools.

## Stage 5A — read-only Django application API

Добавлен минимальный Django API для будущего React-приложения; Superset остаётся
BI-слоем. API читает существующие ClickHouse views без пересчёта метрик и без S3 /
PostgreSQL в request handlers. Локальный адрес: `http://127.0.0.1:18000/api/v1/`.
Сервис использует существующий read-only ClickHouse-профиль, не ingestion user.

```powershell
docker compose build football-api
docker compose run --rm --no-deps football-api python manage.py check
docker compose run --rm --no-deps football-api python scripts/check_application_api.py --competition-id 43 --season-id 106 --wc2022-regression
docker compose up -d --no-deps football-api
Invoke-RestMethod http://127.0.0.1:18000/api/v1/matches/3869685/analysis
```

Маршруты: health, ClickHouse health, список 64 матчей, overview, teams, players
с фильтром team_id, normal shots, xG race, shootout и composite analysis.
Контракты, Docker/test-команды, query count, измерения latency и ограничения:
[docs/stage5a.md](docs/stage5a.md). Это dev foundation, не production deployment;
новых миграций и автоматических изменений Superset нет.

## Stage 5B — React Match Analysis

React + TypeScript + Vite приложение читает только Django `/api/v1` через
same-origin dev proxy. Страница: выбор матча, официальный результат, команды,
SVG xG race и карта ударов на поле, squad-таблица и серия пенальти при наличии.
Superset остаётся BI-слоем; метрики в React не пересчитываются.

```powershell
docker compose build football-api football-web
docker compose up -d --no-deps football-api football-web
# http://127.0.0.1:15173/
docker compose logs football-web
docker compose logs football-api
```

Deep link: `http://127.0.0.1:15173/matches/3869685`. Root выбирает первый матч
из хронологического списка API, а не фиксированный финал. SVG сохраняет исходные
координаты; область x=55..120 включает удары немного левее центральной линии.
Frontend не получает DB/S3 credentials. Архитектура, точная геометрия, тесты,
smoke-проверки и ограничения: [docs/stage5b.md](docs/stage5b.md).
Это local development foundation, не production deployment.

## Stage 5C — интерактивность, поиск и EN/RU/ES

Поиск матчей работает локально по командам, стадии и дате; стрелки/Enter/Escape
управляют combobox, Back/Forward сохраняет навигацию. xG race и карта поля
синхронизируют hover/выбор по event_id и показывают общий блок деталей удара.
Язык EN/RU/ES сохраняется в localStorage; смена языка не перезагружает данные.
Добавлены локальные фильтры игроков: по умолчанию игроки с событиями, полный состав
доступен отдельной опцией.
Метрики, API и ClickHouse не изменены.

```powershell
docker compose build football-web
docker compose up -d --no-deps football-web
# http://127.0.0.1:15173/
Set-Location .\frontend
npm.cmd test
npm.cmd run build
npm.cmd run test:smoke
```

Поведение поиска, клавиатуры, локализации, адаптивности, тесты и ограничения:
[docs/stage5c.md](docs/stage5c.md).

## Инициализация баз

Файлы из `infrastructure/*/init/` выполняются entrypoint-скриптами образов только при первом создании пустого volume. Изменение init SQL не переинициализирует уже существующую базу автоматически. Для повторной чистой инициализации пришлось бы удалить соответствующий локальный volume, что уничтожит его данные.
