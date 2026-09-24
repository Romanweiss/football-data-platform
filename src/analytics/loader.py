"""One Silver -> ClickHouse load/recovery state machine for all specifications."""

from src.common.postgres import find_clickhouse_load, register_clickhouse_load
from src.analytics.specs import EVENT_CORE
from src.analytics.validation import (
    ClickHouseIntegrityError, READ_SETTINGS, S3_SOURCE, inspect_context,
    source_metrics, target_metrics, validate_extra, validate_metrics, validate_table_schema,
)

INSERT_SETTINGS = {
    **READ_SETTINGS, "insert_null_as_default": 0, "insert_deduplicate": 1,
    "async_insert": 0, "max_threads": 1, "max_insert_threads": 1,
}


def insert_sql(*, spec=EVENT_CORE):
    columns = ", ".join(f"`{name}`" for name, _ in spec.columns)
    expressions = (*spec.select_expressions, "CAST(%(build_id)s, 'FixedString(64)') AS silver_build_id")
    return (
        f"INSERT INTO {spec.target} ({columns}, silver_build_id)\nSELECT\n    "
        + ",\n    ".join(expressions) + f"\nFROM {S3_SOURCE}\nORDER BY ALL"
    )


def load_record(build, *, spec=EVENT_CORE):
    record = {name: build[name] for name in (
        "source", "dataset", "competition_id", "season_id", "input_fingerprint",
        "schema_sha256", "s3_bucket", "s3_prefix", "row_count",
    )}
    return {**record, "silver_build_id": build["build_id"],
            "clickhouse_database": spec.clickhouse_database, "clickhouse_table": spec.clickhouse_table}


def validate_load_record(actual, expected):
    if actual is None or any(actual.get(name) != value for name, value in expected.items()):
        raise ClickHouseIntegrityError("ClickHouse load catalog conflicts with verified Silver build.")


def load_dataset(client, connection, build, manifest, url, *, check_only, diagnostics, spec=EVENT_CORE):
    """Caller holds the shared writer lock for full loads. No INSERT retries/cleanup."""
    diagnostics.set("table schema", "DESCRIBE")
    validate_table_schema(client, spec=spec)
    diagnostics.set("ClickHouse S3 read", "source_metrics")
    source = source_metrics(client, url, spec=spec)
    validate_metrics(source, manifest, spec=spec)
    validate_extra(client, S3_SOURCE, {"url": url}, spec=spec)
    record = load_record(build, spec=spec)
    identity = {name: record[name] for name in ("clickhouse_database", "clickhouse_table", "silver_build_id")}
    diagnostics.set("load catalog", "find_clickhouse_load")
    existing = find_clickhouse_load(connection, **identity)
    if existing is not None:
        validate_load_record(existing, record)
    diagnostics.set("build conflict", "inspect_context")
    context_rows = inspect_context(client, build, spec=spec)
    diagnostics.set("target preflight", "target_metrics")
    target = target_metrics(client, build["build_id"], spec=spec)
    if (target[0] not in (0, manifest["row_count"]) or context_rows != target[0]
            or (target[0] == 0 and existing is not None)):
        raise ClickHouseIntegrityError("Target is partial, excessive, outside context or missing despite registration.")
    already_loaded = target[0] == manifest["row_count"]
    relation = f"{spec.target} WHERE silver_build_id = %(build_id)s"
    if already_loaded:
        validate_metrics(target, manifest, spec=spec)
        validate_extra(client, relation, {"build_id": build["build_id"]}, spec=spec)
    print(f"Dataset: {spec.dataset}")
    print(f"Transform version: {spec.transform_version}")
    print(f"Silver build ID: {build['build_id']}")
    print(f"Expected rows: {manifest['row_count']}")
    print(f"Source rows: {source[0]}")
    print(f"Expected files: {manifest['file_count']}")
    print(f"Existing target rows: {target[0]}")
    print(f"Existing build: {build['build_id'] if context_rows else 'none'}")
    print(f"Would load: {'no' if already_loaded else 'yes'}")
    if check_only:
        print("CHECK ONLY - nothing loaded")
        return {"already_loaded": already_loaded, "check_only": True}
    if not already_loaded:
        diagnostics.set("ClickHouse INSERT", "insert_select")
        client.command(
            insert_sql(spec=spec), parameters={"url": url, "build_id": build["build_id"]},
            settings={**INSERT_SETTINGS, "insert_deduplication_token": build["build_id"]},
        )
    diagnostics.set("target validation", "target_metrics")
    validate_metrics(target_metrics(client, build["build_id"], spec=spec), manifest, spec=spec)
    validate_extra(client, relation, {"build_id": build["build_id"]}, spec=spec)
    if inspect_context(client, build, spec=spec) != manifest["row_count"]:
        raise ClickHouseIntegrityError("Context changed during load.")
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
