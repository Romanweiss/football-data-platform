"""Gold-only materialization state machine; shared pure validation, separate lineage."""

from src.common.postgres import find_clickhouse_gold_load, register_clickhouse_gold_load
from src.analytics.loader import INSERT_SETTINGS
from src.analytics.validation import (
    ClickHouseIntegrityError, S3_SOURCE, metric_expressions, source_metrics,
    validate_extra, validate_metrics, validate_table_schema,
)


class GoldBuildConflictError(ClickHouseIntegrityError):
    """A different Gold snapshot occupies this serving dataset/context."""


def load_record(build, *, spec):
    fields = ("source", "dataset", "competition_id", "season_id", "input_fingerprint", "schema_sha256", "s3_bucket", "s3_prefix", "row_count")
    return {**{field: build[field] for field in fields}, "gold_build_id": build["build_id"],
            "clickhouse_database": spec.clickhouse_database, "clickhouse_table": spec.clickhouse_table}


def validate_record(actual, expected):
    if actual is None or any(actual.get(field) != value for field, value in expected.items()):
        raise ClickHouseIntegrityError("Gold load catalog conflicts with verified build.")


def insert_sql(*, spec):
    columns = ", ".join(f"`{name}`" for name, _ in spec.columns)
    expressions = (*spec.select_expressions, "CAST(%(build_id)s, 'FixedString(64)') AS gold_build_id")
    return (f"INSERT INTO {spec.target} ({columns}, gold_build_id)\nSELECT\n    "
            + ",\n    ".join(expressions) + f"\nFROM {S3_SOURCE}\nORDER BY ALL")


def target_metrics(client, build_id, *, spec):
    return tuple(client.query(f"SELECT {metric_expressions(spec)} FROM {spec.target} WHERE gold_build_id = %(build_id)s",
                              parameters={"build_id": build_id}).result_rows[0])


def validate_gold_metrics(metrics, expected, *, spec):
    # The v1 manifest includes match_count; catalog-only model checks can derive it.
    if not 0 < metrics[1] <= expected["row_count"]:
        raise ClickHouseIntegrityError("Gold requires a positive meaningful match count.")
    validate_metrics(metrics, {"match_count": metrics[1], **expected}, spec=spec)


def inspect_context(client, build, *, spec):
    rows, distinct, other = client.query(
        f"SELECT count(), uniqExact(gold_build_id), countIf(gold_build_id != %(build_id)s) FROM {spec.target} "
        "WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s",
        parameters={field: build[field] for field in ("build_id", "competition_id", "season_id")},
    ).result_rows[0]
    if other or distinct > 1:
        raise GoldBuildConflictError("Another Gold build exists in this dataset/context; replacement is not supported.")
    if (rows == 0 and distinct != 0) or (rows > 0 and distinct != 1):
        raise ClickHouseIntegrityError("Inconsistent Gold target context aggregates.")
    return rows


def load_gold(client, connection, build, manifest, url, *, spec, check_only, diagnostics):
    diagnostics.set("Gold table schema", "DESCRIBE")
    validate_table_schema(client, spec=spec)
    diagnostics.set("ClickHouse Gold S3 read", "source_metrics")
    source = source_metrics(client, url, spec=spec)
    validate_gold_metrics(source, manifest, spec=spec)
    validate_extra(client, S3_SOURCE, {"url": url}, spec=spec)
    record = load_record(build, spec=spec)
    identity = {field: record[field] for field in ("clickhouse_database", "clickhouse_table", "gold_build_id")}
    diagnostics.set("Gold load catalog", "find_clickhouse_gold_load")
    existing = find_clickhouse_gold_load(connection, **identity)
    if existing is not None:
        validate_record(existing, record)
    diagnostics.set("Gold build conflict", "inspect_context")
    context_rows = inspect_context(client, build, spec=spec)
    diagnostics.set("Gold target preflight", "target_metrics")
    target = target_metrics(client, build["build_id"], spec=spec)
    if (target[0] not in (0, manifest["row_count"]) or context_rows != target[0]
            or (target[0] == 0 and existing is not None)):
        raise ClickHouseIntegrityError("Gold target is partial, excessive, outside context or missing despite registration.")
    already_loaded = target[0] == manifest["row_count"]
    relation = f"{spec.target} WHERE gold_build_id = %(build_id)s"
    if already_loaded:
        validate_gold_metrics(target, manifest, spec=spec)
        validate_extra(client, relation, {"build_id": build["build_id"]}, spec=spec)
    for label, value in (("Dataset", spec.dataset), ("Transform version", spec.transform_version), ("Gold build ID", build["build_id"]),
                         ("Expected rows", manifest["row_count"]), ("Source rows", source[0]), ("Expected files", manifest["file_count"]),
                         ("Existing target rows", target[0]), ("Existing build ID", build["build_id"] if context_rows else "none"),
                         ("Would load", "no" if already_loaded else "yes")):
        print(f"{label}: {value}")
    if check_only:
        print("CHECK ONLY - nothing loaded")
        return {"check_only": True, "already_loaded": already_loaded}
    if not already_loaded:
        diagnostics.set("ClickHouse Gold INSERT", "insert_select")
        client.command(insert_sql(spec=spec), parameters={"url": url, "build_id": build["build_id"]},
                       settings={**INSERT_SETTINGS, "insert_deduplication_token": build["build_id"]})
    diagnostics.set("Gold target validation", "target_metrics")
    validate_gold_metrics(target_metrics(client, build["build_id"], spec=spec), manifest, spec=spec)
    validate_extra(client, relation, {"build_id": build["build_id"]}, spec=spec)
    if inspect_context(client, build, spec=spec) != manifest["row_count"]:
        raise ClickHouseIntegrityError("Gold context changed during load.")
    registered = False
    if existing is None:
        diagnostics.set("PostgreSQL Gold registration", "register_clickhouse_gold_load")
        registered = register_clickhouse_gold_load(connection, **record)
        validate_record(find_clickhouse_gold_load(connection, **identity), record)
    result = {"output_status": "UNCHANGED / ALREADY_LOADED" if already_loaded else "LOADED",
              "catalog": "REGISTERED" if registered else "ALREADY_REGISTERED"}
    print(f"Output status: {result['output_status']}")
    print(f"Catalog: {result['catalog']}")
    return result
