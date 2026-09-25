"""Read-only Gold/Silver serving consistency. Aggregate results only, no S3 calls."""

import math

from src.analytics.gold_loader import (
    GoldBuildConflictError, load_record, target_metrics, validate_gold_metrics, validate_record,
)
from src.analytics.gold_specs import SPECS
from src.analytics.model import current_builds as current_silver_builds
from src.analytics.specs import SPECS as SILVER_SPECS
from src.analytics.validation import ClickHouseIntegrityError, validate_extra, validate_table_schema
from src.common.postgres import find_clickhouse_gold_load, find_gold_build, find_silver_build
from src.gold.build_identity import REQUIRED_INPUTS, input_fingerprint, require_sha256

XG_REL_TOL = 1e-9
XG_ABS_TOL = 1e-9
INPUT_SPECS = {name: SILVER_SPECS[name] for name in REQUIRED_INPUTS}


def current_gold_builds(client, connection, *, competition_id=43, season_id=106, specs=SPECS):
    records = {}
    for dataset, spec in specs.items():
        validate_table_schema(client, spec=spec)
        count, distinct, build_id = client.query(
            f"SELECT count(), uniqExact(gold_build_id), min(toString(gold_build_id)) FROM {spec.target} "
            "WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s",
            parameters={"competition_id": competition_id, "season_id": season_id},
        ).result_rows[0]
        if distinct > 1:
            raise GoldBuildConflictError("Multiple Gold builds in the serving context.")
        if count <= 0 or distinct != 1:
            raise ClickHouseIntegrityError("Both Gold datasets must be materialized.")
        require_sha256(build_id)
        record = find_gold_build(connection, dataset=dataset, competition_id=competition_id, season_id=season_id, build_id=build_id)
        if (record is None or record["build_id"] != build_id or record["source"] != "statsbomb"
                or record["dataset"] != dataset or record["competition_id"] != competition_id or record["season_id"] != season_id
                or record["transform_version"] != spec.transform_version or record["row_count"] != count):
            raise ClickHouseIntegrityError("Loaded Gold differs from registered artifact.")
        validate_record(find_clickhouse_gold_load(connection, clickhouse_database=spec.clickhouse_database,
                                                 clickhouse_table=spec.clickhouse_table, gold_build_id=build_id), load_record(record, spec=spec))
        validate_gold_metrics(target_metrics(client, build_id, spec=spec), record, spec=spec)
        validate_extra(client, f"{spec.target} WHERE gold_build_id = %(build_id)s", {"build_id": build_id}, spec=spec)
        records[dataset] = record
    return records


def model_queries(*, gold_specs=SPECS, silver_specs=INPUT_SPECS):
    """All comparisons are scoped by context AND the currently loaded build IDs."""
    def scope(dataset):
        gold = dataset in gold_specs
        spec = (gold_specs if gold else silver_specs)[dataset]
        column = "gold_build_id" if gold else "silver_build_id"
        return (f"{spec.target} WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s "
                f"AND {column} = %({dataset}_build_id)s")

    def scalar(dataset, expression, *, player=False):
        return f"(SELECT {expression} FROM {scope(dataset)}" + (" AND player_id IS NOT NULL" if player else "") + ")"

    queries = []
    for dataset, spec in gold_specs.items():
        keys = spec.identity_columns
        columns = ", ".join(keys)
        for child, parent, name in ((dataset, "match_squads", dataset + "_orphan_keys"),
                                    ("match_squads", dataset, dataset + "_missing_keys")):
            sql = (f"SELECT count() FROM (SELECT DISTINCT {columns} FROM {scope(child)}) AS child "
                   f"LEFT ANTI JOIN (SELECT DISTINCT {columns} FROM {scope(parent)}) AS parent ON "
                   + " AND ".join(f"child.{key} = parent.{key}" for key in keys))
            queries.append((name, sql, "zero"))
    for gold, player in (("team_match_stats", False), ("player_match_stats", True)):
        for metric, silver in (("event_count", "event_core"), ("pass_attempts", "pass_events"), ("shot_count", "shot_events")):
            sql = f"SELECT {scalar(gold, f'sum({metric})')}, {scalar(silver, 'count()', player=player)}"
            queries.append((gold + "_" + metric, sql, "equal"))
    queries.append(("team_shot_xg", f"SELECT {scalar('team_match_stats', 'sum(shot_xg)')}, "
                    f"{scalar('shot_events', 'sum(statsbomb_xg)')}", "close"))
    queries.append(("player_grain_rows", f"SELECT {scalar('player_match_stats', 'count()')}, "
                    f"{scalar('match_squads', 'uniqExact(tuple(match_id, team_id, player_id))')}", "equal"))
    return queries


def validate_model_metrics(client, gold_builds, silver_builds, *, competition_id=43, season_id=106,
                           gold_specs=SPECS, silver_specs=INPUT_SPECS):
    parameters = {"competition_id": competition_id, "season_id": season_id,
                  **{name + "_build_id": value for name, value in {**gold_builds, **silver_builds}.items()}}
    failures = []
    results = {}
    for name, sql, rule in model_queries(gold_specs=gold_specs, silver_specs=silver_specs):
        row = client.query(sql, parameters=parameters).result_rows[0]
        actual, expected = (row[0], 0) if rule == "zero" else row
        valid = (math.isclose(actual, expected, rel_tol=XG_REL_TOL, abs_tol=XG_ABS_TOL)
                 and math.isfinite(actual) and math.isfinite(expected)) if rule == "close" else actual == expected
        tolerance = f" rel_tol={XG_REL_TOL} abs_tol={XG_ABS_TOL}" if rule == "close" else ""
        print(f"{'PASS' if valid else 'FAIL'} {name}: Gold={actual} expected={expected}{tolerance}")
        results[name] = (actual, expected)
        if not valid:
            failures.append(name)
    if failures:
        raise ClickHouseIntegrityError("Gold model grain/metric checks failed.")
    return results


def check_model(client, connection, *, competition_id=43, season_id=106, gold_specs=SPECS, silver_specs=INPUT_SPECS):
    context = {"competition_id": competition_id, "season_id": season_id}
    gold = current_gold_builds(client, connection, specs=gold_specs, **context)
    silver = current_silver_builds(client, connection, specs=silver_specs, **context)
    upstream = [find_silver_build(connection, dataset=name, build_id=build_id, **context) for name, build_id in silver.items()]
    if any(record is None for record in upstream):
        raise ClickHouseIntegrityError("Loaded Silver lineage is missing from the catalog.")
    fingerprint = input_fingerprint(upstream)
    if any(record["input_fingerprint"] != fingerprint for record in gold.values()):
        raise ClickHouseIntegrityError("Gold lineage differs from the currently loaded Silver builds.")
    gold_ids = {name: record["build_id"] for name, record in gold.items()}
    result = validate_model_metrics(client, gold_ids, silver, gold_specs=gold_specs, silver_specs=silver_specs, **context)
    if (gold != current_gold_builds(client, connection, specs=gold_specs, **context)
            or silver != current_silver_builds(client, connection, specs=silver_specs, **context)):
        raise ClickHouseIntegrityError("Serving model changed during validation; repeat after writers finish.")
    print("CLICKHOUSE GOLD MODEL CHECK PASSED")
    return result
