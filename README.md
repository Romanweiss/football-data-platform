# Football Data Platform

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

Stage 2B — будущий отдельный этап: Spark S3A direct access и persistent versioned Silver
в Selectel. В Stage 2A это не реализовано.

## Инициализация баз

Файлы из `infrastructure/*/init/` выполняются entrypoint-скриптами образов только при первом создании пустого volume. Изменение init SQL не переинициализирует уже существующую базу автоматически. Для повторной чистой инициализации пришлось бы удалить соответствующий локальный volume, что уничтожит его данные.
