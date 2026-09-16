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

Эта структура сейчас только документирует convention. Скрипты проекта не создают bucket, префиксы или объекты и не изменяют существующие данные.

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

Проверить итоговую Compose-конфигурацию:

```bash
docker compose config
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

## Инициализация баз

Файлы из `infrastructure/*/init/` выполняются entrypoint-скриптами образов только при первом создании пустого volume. Изменение init SQL не переинициализирует уже существующую базу автоматически. Для повторной чистой инициализации пришлось бы удалить соответствующий локальный volume, что уничтожит его данные.
