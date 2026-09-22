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
не читают event_core или опубликованные dimensions. До dedup проверяются distinct
non-null attributes по source ID. Для team это `team_name`; для player —
`player_name`, `player_nickname`, `country_id`, `country_name`.
Два известных различных значения вызывают DQ failure. NULL + одно известное значение
не конфликтуют. После доказанной consistency используется детерминированный `min`,
который сохраняет известное значение либо NULL, если известных значений нет.

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

## Инициализация баз

Файлы из `infrastructure/*/init/` выполняются entrypoint-скриптами образов только при первом создании пустого volume. Изменение init SQL не переинициализирует уже существующую базу автоматически. Для повторной чистой инициализации пришлось бы удалить соответствующий локальный volume, что уничтожит его данные.
