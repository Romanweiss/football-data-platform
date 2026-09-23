"""Stage 3A SQL contract and load/recovery state machine. No cleanup operations."""

import re

from src.common.postgres import find_clickhouse_load, register_clickhouse_load

DATABASE = "football"
TABLE = "event_core"
TARGET = "football.event_core"
EVENT_COLUMNS = (
    ("competition_id", "UInt32"), ("season_id", "UInt32"), ("match_id", "UInt64"),
    ("event_id", "UUID"), ("event_index", "UInt32"), ("period", "UInt8"),
    ("timestamp", "String"), ("minute", "UInt16"), ("second", "UInt8"),
    ("type_id", "UInt16"), ("type_name", "LowCardinality(String)"), ("possession", "UInt16"),
    ("possession_team_id", "Nullable(UInt32)"), ("possession_team_name", "Nullable(String)"),
    ("play_pattern_id", "Nullable(UInt16)"), ("play_pattern_name", "Nullable(String)"),
    ("team_id", "UInt32"), ("team_name", "LowCardinality(String)"),
    ("player_id", "Nullable(UInt32)"), ("player_name", "Nullable(String)"),
    ("position_id", "Nullable(UInt16)"), ("position_name", "Nullable(String)"),
    ("location_x", "Nullable(Float64)"), ("location_y", "Nullable(Float64)"),
    ("duration", "Nullable(Float64)"), ("under_pressure", "Nullable(Bool)"),
    ("counterpress", "Nullable(Bool)"),
)
TARGET_COLUMNS = (*EVENT_COLUMNS, ("silver_build_id", "FixedString(64)"), ("loaded_at", "DateTime64(3, 'UTC')"))
S3_SOURCE = "s3(selectel_s3, url=%(url)s, format='Parquet')"
METRICS = (
    "count(), uniqExact(match_id), uniqExact(tuple(match_id, event_id)), "
    "min(competition_id), max(competition_id), min(season_id), max(season_id)"
)
READ_SETTINGS = {"input_format_null_as_default": 0}
INSERT_SETTINGS = {
    **READ_SETTINGS, "insert_null_as_default": 0, "insert_deduplicate": 1,
    "async_insert": 0, "max_threads": 1, "max_insert_threads": 1,
}


class ClickHouseIntegrityError(RuntimeError):
    """Target/source/catalog mismatch; never auto-delete, reload or ALTER."""


def verify_named_collection(client) -> None:
    # Never select collection contents: even system tables can expose credentials.
    count = client.query(
        "SELECT count() FROM system.named_collections WHERE name = %(name)s",
        parameters={"name": "selectel_s3"},
    ).result_rows[0][0]
    if count != 1:
        raise ClickHouseIntegrityError("Required selectel_s3 named collection is unavailable.")


def validate_table_schema(client) -> None:
    rows = client.query(f"DESCRIBE TABLE {TARGET}").result_rows
    if tuple((row[0], row[1]) for row in rows) != TARGET_COLUMNS:
        raise ClickHouseIntegrityError("ClickHouse event_core columns/types differ from Stage 3A.")
    if rows[-1][2:4] not in (("DEFAULT", "now64(3)"), ["DEFAULT", "now64(3)"]):
        raise ClickHouseIntegrityError("ClickHouse loaded_at default differs from Stage 3A.")
    info = client.query(
        "SELECT engine, create_table_query FROM system.tables "
        "WHERE database = %(database)s AND name = %(table)s",
        parameters={"database": DATABASE, "table": TABLE},
    ).result_rows
    if len(info) != 1:
        raise ClickHouseIntegrityError("ClickHouse target table is missing.")
    engine, ddl = info[0]
    ddl = re.sub(r"\s+", " ", ddl.replace("`", ""))
    if (
        engine != "MergeTree" or "PARTITION BY (competition_id, season_id)" not in ddl
        or "ORDER BY (competition_id, season_id, match_id, period, event_index, event_id)" not in ddl
        or not re.search(r"\bnon_replicated_deduplication_window\s*=\s*1000\b", ddl)
    ):
        raise ClickHouseIntegrityError("ClickHouse engine/keys/deduplication settings differ from Stage 3A.")


def source_metrics(client, url: str) -> tuple:
    return tuple(client.query(
        f"SELECT {METRICS} FROM {S3_SOURCE}", parameters={"url": url}, settings=READ_SETTINGS,
    ).result_rows[0])


def target_metrics(client, build_id: str) -> tuple:
    return tuple(client.query(
        f"SELECT {METRICS} FROM {TARGET} WHERE silver_build_id = %(build_id)s",
        parameters={"build_id": build_id},
    ).result_rows[0])


def validate_metrics(metrics: tuple, manifest: dict) -> None:
    expected = (
        manifest["row_count"], manifest["match_count"], manifest["row_count"],
        manifest["competition_id"], manifest["competition_id"],
        manifest["season_id"], manifest["season_id"],
    )
    if metrics != expected:
        raise ClickHouseIntegrityError("Row/match counts, event uniqueness or competition/season differ.")


def insert_sql() -> str:
    columns = ", ".join(f"`{name}`" for name, _ in EVENT_COLUMNS)
    expressions = []
    for name, kind in EVENT_COLUMNS:
        if kind == "UUID":
            expression = f"toUUID(`{name}`)"
        elif kind.startswith("LowCardinality"):
            expression = f"CAST(`{name}`, '{kind}')"
        else:
            # Unlike toUInt*, accurateCast rejects integer overflow/negative IDs.
            # Nullable destination types retain NULL; no sentinel/default values.
            expression = f"accurateCast(`{name}`, '{kind}')"
        expressions.append(f"{expression} AS `{name}`")
    expressions.append("CAST(%(build_id)s, 'FixedString(64)') AS silver_build_id")
    return (
        f"INSERT INTO {TARGET} ({columns}, silver_build_id)\nSELECT\n    "
        + ",\n    ".join(expressions) + f"\nFROM {S3_SOURCE}\nORDER BY ALL"
    )


def load_record(build: dict) -> dict:
    record = {name: build[name] for name in (
        "source", "dataset", "competition_id", "season_id", "input_fingerprint",
        "schema_sha256", "s3_bucket", "s3_prefix", "row_count",
    )}
    return {**record, "silver_build_id": build["build_id"], "clickhouse_database": DATABASE, "clickhouse_table": TABLE}


def validate_load_record(actual: dict, expected: dict) -> None:
    if actual is None or any(actual.get(name) != value for name, value in expected.items()):
        raise ClickHouseIntegrityError("ClickHouse load catalog conflicts with verified Silver build.")


def load_event_core(client, connection, build: dict, manifest: dict, url: str, *, check_only: bool, diagnostics) -> dict:
    """Caller holds the writer lock for full loads; check-only is read-only."""
    diagnostics.set("table schema", "DESCRIBE")
    validate_table_schema(client)
    diagnostics.set("ClickHouse S3 read", "source_metrics")
    source = source_metrics(client, url)
    validate_metrics(source, manifest)
    record = load_record(build)
    identity = {name: record[name] for name in ("clickhouse_database", "clickhouse_table", "silver_build_id")}
    diagnostics.set("load catalog", "find_clickhouse_load")
    existing = find_clickhouse_load(connection, **identity)
    if existing is not None:
        validate_load_record(existing, record)
    diagnostics.set("target preflight", "target_metrics")
    target = target_metrics(client, build["build_id"])
    if target[0] not in (0, manifest["row_count"]) or (target[0] == 0 and existing is not None):
        raise ClickHouseIntegrityError("Target is partial, excessive or missing despite load registration.")
    already_loaded = target[0] == manifest["row_count"]
    if already_loaded:
        validate_metrics(target, manifest)
    print("Dataset: event_core")
    print(f"Silver build ID: {build['build_id']}")
    print(f"Expected rows: {manifest['row_count']}")
    print(f"ClickHouse source rows: {source[0]}")
    print(f"Expected files: {manifest['file_count']}")
    print(f"Existing target rows for build_id: {target[0]}")
    print(f"Would load: {'no' if already_loaded else 'yes'}")
    if check_only:
        print("CHECK ONLY - nothing loaded")
        return {"already_loaded": already_loaded, "check_only": True}
    if not already_loaded:
        diagnostics.set("ClickHouse INSERT", "insert_select")
        # ONE command, no manual retry. Ambiguous commit is inspected on the next run.
        client.command(
            insert_sql(), parameters={"url": url, "build_id": build["build_id"]},
            settings={**INSERT_SETTINGS, "insert_deduplication_token": build["build_id"]},
        )
    diagnostics.set("target validation", "target_metrics")
    validate_metrics(target_metrics(client, build["build_id"]), manifest)
    diagnostics.set("PostgreSQL registration", "register_clickhouse_load")
    registered = False
    if existing is None:
        registered = register_clickhouse_load(connection, **record)
        validate_load_record(find_clickhouse_load(connection, **identity), record)
    result = {
        "output_status": "UNCHANGED / ALREADY_LOADED" if already_loaded else "LOADED",
        "catalog": "REGISTERED" if registered else "ALREADY_REGISTERED",
    }
    print(f"Output status: {result['output_status']}")
    print(f"Catalog: {result['catalog']}")
    return result
