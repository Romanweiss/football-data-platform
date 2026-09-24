"""Aggregate-only ClickHouse schema, context and dataset checks."""

import re

from src.analytics.specs import EVENT_CORE

S3_SOURCE = "s3(selectel_s3, url=%(url)s, format='Parquet')"
READ_SETTINGS = {"input_format_null_as_default": 0}


class ClickHouseIntegrityError(RuntimeError):
    """Invalid source, target or catalog. No automatic repair of data."""


class ClickHouseBuildConflictError(ClickHouseIntegrityError):
    """Another snapshot already occupies this dataset/context."""


def verify_named_collection(client):
    count = client.query(
        "SELECT count() FROM system.named_collections WHERE name = %(name)s",
        parameters={"name": "selectel_s3"},
    ).result_rows[0][0]
    if count != 1:
        raise ClickHouseIntegrityError("Required selectel_s3 named collection is unavailable.")


def validate_table_schema(client, *, spec=EVENT_CORE):
    rows = client.query(f"DESCRIBE TABLE {spec.target}").result_rows
    if tuple((row[0], row[1]) for row in rows) != spec.target_columns:
        raise ClickHouseIntegrityError("ClickHouse columns/types differ from dataset specification.")
    if tuple(rows[-1][2:4]) != ("DEFAULT", "now64(3)"):
        raise ClickHouseIntegrityError("ClickHouse loaded_at default differs from specification.")
    info = client.query(
        "SELECT engine, create_table_query FROM system.tables "
        "WHERE database = %(database)s AND name = %(table)s",
        parameters={"database": spec.clickhouse_database, "table": spec.clickhouse_table},
    ).result_rows
    if len(info) != 1:
        raise ClickHouseIntegrityError("ClickHouse target table is missing.")
    engine, ddl = info[0]
    ddl = re.sub(r"\s+", " ", ddl.replace("`", ""))
    if (
        engine != "MergeTree" or f"PARTITION BY ({', '.join(spec.context_columns)})" not in ddl
        or f"ORDER BY ({', '.join(spec.order_by)})" not in ddl
        or not re.search(r"\bnon_replicated_deduplication_window\s*=\s*1000\b", ddl)
    ):
        raise ClickHouseIntegrityError("ClickHouse engine/keys/deduplication settings differ from specification.")


def metric_expressions(spec):
    expressions = ["count()"]
    if spec.has_match_count:
        expressions.append("uniqExact(match_id)")
    expressions.append(f"uniqExact(tuple({', '.join(spec.identity_columns)}))")
    expressions.extend(f"{operation}({column})" for column in spec.context_columns for operation in ("min", "max"))
    expressions.extend(f"countIf(isNull(`{column}`))" for column in spec.required_columns)
    expressions.extend(f"countIf({predicate})" for predicate in spec.invalid_predicates)
    return ", ".join(expressions)


def source_metrics(client, url, *, spec=EVENT_CORE):
    return tuple(client.query(
        f"SELECT {metric_expressions(spec)} FROM {S3_SOURCE}",
        parameters={"url": url}, settings=READ_SETTINGS,
    ).result_rows[0])


def target_metrics(client, build_id, *, spec=EVENT_CORE):
    return tuple(client.query(
        f"SELECT {metric_expressions(spec)} FROM {spec.target} WHERE silver_build_id = %(build_id)s",
        parameters={"build_id": build_id},
    ).result_rows[0])


def expected_metrics(manifest, spec):
    expected = [manifest["row_count"]]
    if spec.has_match_count:
        expected.append(manifest["match_count"])
    expected.append(manifest["row_count"])
    expected.extend(manifest[column] for column in spec.context_columns for _ in range(2))
    expected.extend(0 for _ in (*spec.required_columns, *spec.invalid_predicates))
    return tuple(expected)


def validate_metrics(metrics, manifest, *, spec=EVENT_CORE):
    if metrics != expected_metrics(manifest, spec):
        raise ClickHouseIntegrityError("Row/match counts, identity, context, required fields or domain values differ.")


def validate_extra(client, relation, parameters, *, spec=EVENT_CORE):
    if spec.two_teams_per_match:
        count = client.query(
            f"SELECT count() FROM (SELECT match_id FROM {relation} "
            "GROUP BY match_id HAVING uniqExact(team_id) != 2)",
            parameters=parameters, settings=READ_SETTINGS,
        ).result_rows[0][0]
        if count:
            raise ClickHouseIntegrityError("Each squad match must have exactly two teams.")


def inspect_context(client, build, *, spec=EVENT_CORE):
    """Bounded aggregate result; never retrieve every build ID or target row."""
    rows, distinct, other, _ = client.query(
        f"SELECT count(), uniqExact(silver_build_id), countIf(silver_build_id != %(build_id)s), "
        f"min(toString(silver_build_id)) FROM {spec.target} "
        "WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s",
        parameters={name: build[name] for name in ("build_id", "competition_id", "season_id")},
    ).result_rows[0]
    if other or distinct > 1:
        raise ClickHouseBuildConflictError("Another Silver build exists in this dataset/context; replacement is not supported.")
    if (rows == 0 and distinct != 0) or (rows > 0 and distinct != 1):
        raise ClickHouseIntegrityError("Inconsistent target build aggregates.")
    return rows
