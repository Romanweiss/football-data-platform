"""SELECT-only WC2022 shadow/BI validation. No S3, DDL or repair path."""

import math
import re
from pathlib import Path

from src.analytics.gold_model import (
    current_gold_builds, check_model, XG_ABS_TOL, XG_REL_TOL,
)
from src.analytics.gold_specs import SPECS, V2_SPECS
from src.analytics.model import current_builds
from src.analytics.specs import SPECS as SILVER_SPECS
from src.analytics.validation import ClickHouseIntegrityError
from src.common.postgres import find_silver_build
from src.gold.build_identity import input_fingerprint
from src.gold.stats_snapshot import PINNED_STATS_INPUTS

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = {"competition_id": 43, "season_id": 106}
DELTA_METRICS = {
    "event_count": "delta_events", "pass_attempts": "delta_passes", "shot_count": "delta_shots",
    "shot_xg": "delta_xg", "shot_goals": "delta_goals", "under_pressure_events": "delta_pressure",
    "counterpress_events": "delta_counterpress", "players_with_events": "delta_players_with_events",
}


def close(actual, expected):
    return (math.isfinite(actual) and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=XG_REL_TOL, abs_tol=XG_ABS_TOL))


def require(condition, message):
    if not condition:
        raise ClickHouseIntegrityError(message)


def rows_by_key(rows, keys):
    result = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        require(key not in result and all(value is not None for value in key), "Duplicate/null grain in validation input.")
        result[key] = row
    return result


def compare_rows(actual, expected, *, keys, columns):
    left, right = rows_by_key(actual, keys), rows_by_key(expected, keys)
    require(left.keys() == right.keys(), "Serving keys differ; missing/orphan/zero-activity rows.")
    for key, row in left.items():
        for name in columns:
            valid = close(row[name], right[key][name]) if name == "shot_xg" else row[name] == right[key][name]
            require(valid, f"Serving value mismatch: key={key}, column={name}.")


def validate_deltas(v1, v2, *, spec, audit):
    """All keys/metrics, including zero deltas outside the recorded affected set."""
    old, new = rows_by_key(v1, spec.identity_columns), rows_by_key(v2, spec.identity_columns)
    expected = rows_by_key(audit[spec.dataset]["differences"], spec.identity_columns)
    require(old.keys() == new.keys(), "Shadow grain differs from rollback table.")
    require(len(new) == audit[spec.dataset]["rows"], "Unexpected shadow row count.")
    metrics = {name: delta for name, delta in DELTA_METRICS.items() if name in dict(spec.columns)}
    affected = set()
    for key, row in old.items():
        recorded = expected.get(key)
        for name, _ in spec.columns:
            if name not in metrics:
                require(row[name] == new[key][name], f"Shadow identity/name changed: key={key}, column={name}.")
        for name, delta_name in metrics.items():
            delta = row[name] - new[key][name]  # Python signed integers; never UInt underflow.
            wanted = recorded[delta_name] if recorded else 0
            require(close(delta, wanted) if name == "shot_xg" else delta == wanted,
                    f"Audit delta mismatch: key={key}, metric={name}.")
            changed = not close(delta, 0) if name == "shot_xg" else delta != 0
            if changed:
                affected.add(key)
        if recorded:
            # The audit also records before/after shots; detect shifted baselines.
            for name, after in (("shot_count", "normal_shots"), ("shot_goals", "normal_goals"), ("shot_xg", "normal_xg")):
                require(close(row[name], recorded[name]) if name == "shot_xg" else row[name] == recorded[name],
                        "Rollback values differ from the recorded audit baseline.")
                require(close(new[key][name], recorded[after]) if name == "shot_xg" else new[key][name] == recorded[after],
                        "Shadow shot values differ from the recorded audit.")
    require(affected == expected.keys(), "Unexpected or missing affected grain keys.")
    require(len(affected) == audit[spec.dataset]["affected_rows"], "Affected grain count mismatch.")
    for metric, delta_name in metrics.items():
        values = [old[key][metric] - new[key][metric] for key in old]
        actual = math.fsum(values) if metric == "shot_xg" else sum(values)
        wanted = audit[spec.dataset]["totals"][delta_name]
        require(close(actual, wanted) if metric == "shot_xg" else actual == wanted, "Audit total delta mismatch.")
    return len(affected)


def validate_wc_totals(v2):
    require(len({row["match_id"] for row in v2}) == 64, "Shadow must cover 64 matches.")
    for metric, expected_total in (("shot_count", 1453), ("shot_goals", 169), ("shot_xg", 155.8985419302)):
        total = math.fsum(row[metric] for row in v2) if metric == "shot_xg" else sum(row[metric] for row in v2)
        require(close(total, expected_total) if metric == "shot_xg" else total == expected_total, "Unexpected WC2022 normal shot totals.")


def query_rows(client, sql, parameters):
    result = client.query(sql, parameters=parameters, settings={"readonly": 1})
    return [dict(zip((name.split(".")[-1] for name in result.column_names), row)) for row in result.result_rows]


def performance_query(spec):
    """Independent per-grain reconstruction from pinned Silver, retaining period 3/4."""
    keys = ", ".join(spec.identity_columns)
    player = "player_id" in spec.identity_columns
    identity = [name for name, _ in spec.columns if name not in DELTA_METRICS]
    ctes = []
    for dataset in PINNED_STATS_INPUTS:
        ctes.append(f"{dataset} AS (SELECT * FROM football.{dataset} WHERE competition_id=43 AND season_id=106 "
                    f"AND silver_build_id=%({dataset}_build_id)s)")
    event_key = "competition_id,season_id,match_id,event_id"
    for dataset, alias in (("shot_events", "shots"), ("pass_events", "passes")):
        ctes.append(f"{alias} AS (SELECT s.* FROM {dataset} s INNER JOIN event_core e USING ({event_key}) WHERE e.period!=5)")
    optional = " AND player_id IS NOT NULL" if player else ""
    ctes += [
        f"base AS (SELECT DISTINCT {', '.join(identity)} FROM match_squads)",
        f"events AS (SELECT {keys},count() event_count,countIf(under_pressure) under_pressure_events,"
        f"countIf(counterpress) counterpress_events,uniqExact(player_id) players_with_events "
        f"FROM event_core WHERE period!=5{optional} GROUP BY {keys})",
        f"pass_stats AS (SELECT {keys},count() pass_attempts FROM passes WHERE 1{optional} GROUP BY {keys})",
        f"shot_stats AS (SELECT {keys},count() shot_count,countIf(outcome_id=97) shot_goals,"
        f"arraySum(arraySort(groupArray(statsbomb_xg))) shot_xg FROM shots WHERE 1{optional} GROUP BY {keys})",
    ]
    columns = [f"b.{name} AS {name}" for name in identity]
    for metric in DELTA_METRICS:
        if metric not in dict(spec.columns):
            continue
        alias = "p" if metric == "pass_attempts" else "s" if metric.startswith("shot_") else "e"
        columns.append(f"coalesce({alias}.{metric},0) AS {metric}")
    return ("WITH " + ",\n".join(ctes) + " SELECT " + ", ".join(columns)
            + f" FROM base b LEFT JOIN events e USING ({keys}) LEFT JOIN pass_stats p USING ({keys})"
            + f" LEFT JOIN shot_stats s USING ({keys})")


def audited_state(client, connection, audit, *, shadow):
    silver_specs = {name: SILVER_SPECS[name] for name in (*PINNED_STATS_INPUTS, "matches", "teams", "players")}
    silver = current_builds(client, connection, **CONTEXT, specs=silver_specs)
    require(all(silver[name] == value for name, value in PINNED_STATS_INPUTS.items()), "Serving Silver differs from pinned audit snapshot.")
    require(silver["matches"] == audit["builds"]["matches"], "Matches snapshot changed since audit.")
    upstream = [find_silver_build(connection, dataset=name, build_id=silver[name], **CONTEXT) for name in PINNED_STATS_INPUTS]
    require(all(row is not None for row in upstream), "Pinned Silver catalog record missing.")
    fingerprint = input_fingerprint(upstream)
    old = current_gold_builds(client, connection, **CONTEXT, specs=SPECS)
    new = current_gold_builds(client, connection, **CONTEXT, specs=V2_SPECS) if shadow else {}
    require(all(record["build_id"] == audit["builds"][name] for name, record in old.items()), "Rollback Gold differs from audit snapshot.")
    require(all(record["input_fingerprint"] == fingerprint for record in (*old.values(), *new.values())), "Gold lineage differs from pinned Silver.")
    return silver, old, new


def validate_shadow(client, connection, audit):
    initial = audited_state(client, connection, audit, shadow=True)
    silver, old, new = initial
    check_model(client, connection, **CONTEXT, gold_specs=V2_SPECS)
    parameters = {name + "_build_id": value for name, value in silver.items()}
    for name, spec in V2_SPECS.items():
        columns = [column for column, _ in spec.columns]
        def fetch(target, build_id):
            return query_rows(client, f"SELECT {', '.join(columns)} FROM {target} WHERE competition_id=43 AND season_id=106 AND gold_build_id=%(build_id)s", {"build_id": build_id})
        v1, v2 = fetch(SPECS[name].target, old[name]["build_id"]), fetch(spec.target, new[name]["build_id"])
        expected = query_rows(client, performance_query(spec), parameters)
        compare_rows(v2, expected, keys=spec.identity_columns, columns=columns)
        references = [("match_id", "matches"), ("team_id", "teams")]
        if name == "player_match_stats":
            references.append(("player_id", "players"))
        for field, parent in references:
            count = client.query(f"SELECT count() FROM (SELECT {field} FROM {spec.target} WHERE competition_id=43 AND season_id=106 AND gold_build_id=%(build_id)s) c "
                f"LEFT ANTI JOIN (SELECT {field} FROM football.{parent} WHERE competition_id=43 AND season_id=106 AND silver_build_id=%(parent_id)s) p USING ({field})",
                parameters={"build_id": new[name]["build_id"], "parent_id": silver[parent]}, settings={"readonly": 1}).result_rows[0][0]
            require(count == 0, "Orphan shadow match/team/player reference.")
        affected = validate_deltas(v1, v2, spec=spec, audit=audit)
        validate_wc_totals(v2)
        print(f"PASS {spec.target}: rows={len(v2)} matches=64 exact_affected_keys={affected}; all per-grain metrics match Silver period!=5")
    require(initial == audited_state(client, connection, audit, shadow=True), "Serving state changed during validation.")
    print("SHADOW V2 VALIDATION PASSED")


def view_bodies(version):
    names = {"v1": "011_rollback_bi_views_to_stats_v1.sql", "v2": "010_switch_bi_views_to_stats_v2.sql"}
    source = (ROOT / "infrastructure/clickhouse/migrations" / names[version]).read_text(encoding="utf-8")
    return [sql.split("\nAS\n", 1)[1].strip() for sql in source.split(";") if sql.strip()]


def validate_bi(client, *, version):
    specs = SPECS if version == "v1" else V2_SPECS
    for (name, spec), body in zip(specs.items(), view_bodies(version), strict=True):
        view = "football.bi_" + name
        ddl = client.query(f"SHOW CREATE TABLE {view}", settings={"readonly": 1}).result_rows[0][0]
        normalized = re.sub(r"\s+", " ", ddl.replace("`", ""))
        require(re.search(r"\bFROM " + re.escape(spec.target) + r"\s+AS\b", normalized) is not None,
                "BI view points to the wrong serving version.")
        require("SQL SECURITY INVOKER" in normalized and "JOIN football.match_results AS r" in normalized,
                "BI security/result source changed.")
        actual_schema = client.query(f"DESCRIBE TABLE {view}", settings={"readonly": 1}).result_rows
        expected_schema = client.query(f"DESCRIBE TABLE ({body})", settings={"readonly": 1}).result_rows
        require([(r[0], r[1]) for r in actual_schema] == [(r[0], r[1]) for r in expected_schema], "Public BI column/type contract changed.")
        actual = query_rows(client, f"SELECT * FROM {view} WHERE competition_id=43 AND season_id=106", {})
        expected = query_rows(client, f"SELECT * FROM ({body}) WHERE competition_id=43 AND season_id=106", {})
        target_count = client.query(f"SELECT count() FROM {spec.target} WHERE competition_id=43 AND season_id=106", settings={"readonly": 1}).result_rows[0][0]
        require(len(actual) == target_count and target_count > 0, "BI joins changed serving coverage.")
        compare_rows(actual, expected, keys=spec.identity_columns, columns=[r[0] for r in expected_schema])
        print(f"PASS {view}: source={spec.target}, full public schema and all values preserved")
