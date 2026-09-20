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

## Инициализация баз

Файлы из `infrastructure/*/init/` выполняются entrypoint-скриптами образов только при первом создании пустого volume. Изменение init SQL не переинициализирует уже существующую базу автоматически. Для повторной чистой инициализации пришлось бы удалить соответствующий локальный volume, что уничтожит его данные.
