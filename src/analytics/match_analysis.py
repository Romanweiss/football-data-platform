"""Read-only Stage 4D contracts; small WC2022 BI relations, no event lake/S3 reads."""

import math
from collections import Counter
from pathlib import Path

from src.analytics.gold_specs import RESULTS
from src.analytics.specs import MATCHES, SHOTS
from src.analytics.stats_cutover import close, require, rows_by_key

MIGRATION = Path(__file__).resolve().parents[2] / "infrastructure/clickhouse/migrations/012_create_match_analysis_views.sql"
MATCH_KEY = ("competition_id", "season_id", "match_id")
GRAINS = {
    "overview": MATCH_KEY,
    "team_stats": (*MATCH_KEY, "team_id"),
    "player_stats": (*MATCH_KEY, "team_id", "player_id"),
    "shots": (*MATCH_KEY, "event_id"),
}
SOURCE_TABLES = {
    "matches": "football.matches", "results": "football.match_results",
    "team_stats": "football.bi_team_match_stats", "player_stats": "football.bi_player_match_stats",
    "shots": "football.shot_events",
}
METADATA_FIELDS = ("match_week", "stadium_id", "stadium_name", "referee_id", "referee_name")
SHOT_CONTEXT = ("match_label", "match_date", "competition_stage_name", "display_score", "result_method",
                "went_to_extra_time", "went_to_penalties", "winner_team_id", "winner_team_name")
WC2022 = {
    "overview": 64, "team_stats": 128, "player_stats": 3244, "shots": 1494,
    "normal_shots": 1453, "shootout_shots": 41, "extra_time_shots": 45,
    "normal_xg": 155.8985419302, "shootout_xg": 32.1235, "raw_xg": 188.0220419302,
    "shootout_matches": frozenset((3869219, 3869220, 3869321, 3869420, 3869685)),
}


def view_selects():
    """Read only SELECT bodies of the four fixed reviewed views, never execute DDL."""
    statements = [sql.strip() for sql in MIGRATION.read_text(encoding="utf-8").split(";") if sql.strip()]
    require(len(statements) == 4, "Unexpected migration view count.")
    result = {}
    for name, statement in zip(GRAINS, statements, strict=True):
        require(f"CREATE VIEW IF NOT EXISTS football.bi_match_{name}\nSQL SECURITY INVOKER\nAS\n" in statement,
                "Unexpected migration view contract.")
        result[name] = statement.split("\nAS\n", 1)[1]
    return result


def candidate_relations():
    """Virtual SELECT-only equivalents, usable before 012 is applied."""
    bodies = view_selects()
    overview = bodies["overview"]
    return {name: "(" + body.replace("football.bi_match_overview", "(" + overview + ")") + ")"
            for name, body in bodies.items()}


def match_label(row):
    # Independent check of the SQL expression, not a source for BI labels.
    return f"{row['match_date'].isoformat()} | {row['home_team_name']} - {row['away_team_name']}"


def key_of(row):
    return tuple(row[name] for name in MATCH_KEY)


def equal_projection(actual, expected, keys, columns):
    """Exact preservation, including Float64 values and NULL vs empty/zero."""
    left, right = rows_by_key(actual, keys), rows_by_key(expected, keys)
    require(left.keys() == right.keys(), "Source/view grain mismatch.")
    for key, row in left.items():
        for field in columns:
            require(row[field] == right[key][field], f"Source preservation failed: column={field}.")


def validate_rows(views, sources, *, expected=WC2022):
    indexed = {name: rows_by_key(rows, GRAINS[name]) for name, rows in views.items()}
    results = rows_by_key(sources["results"], MATCH_KEY)
    matches = rows_by_key(sources["matches"], MATCH_KEY)
    overview = indexed["overview"]
    require(overview.keys() == results.keys() == matches.keys(), "Match coverage differs from authoritative sources.")
    equal_projection(views["overview"], sources["results"], MATCH_KEY, [name for name, _ in RESULTS.columns])
    equal_projection(views["overview"], sources["matches"], MATCH_KEY, METADATA_FIELDS)
    labels = set()
    for row in views["overview"]:
        require(row["match_label"] == match_label(results[key_of(row)]), "Non-deterministic match label.")
        label_key = (row["competition_id"], row["season_id"], row["match_label"])
        require(label_key not in labels, "Ambiguous Match filter label within context.")
        labels.add(label_key)
    for name, rows in views.items():
        require(len(rows) == expected[name], f"Unexpected row count: view={name}.")
        require({key_of(row) for row in rows} == overview.keys(), f"Missing/orphan match coverage: view={name}.")
        for row in rows:
            parent = overview[key_of(row)]
            require(bool(row["match_label"]) and row["match_label"] == parent["match_label"], "Inconsistent match label across views.")
            if name != "overview":
                require(row["team_id"] in (parent["home_team_id"], parent["away_team_id"]), "Orphan team relative to match.")
    for name in ("team_stats", "player_stats"):
        equal_projection(views[name], sources[name], GRAINS[name], sources[name][0].keys())
    require(all(count == 2 for count in Counter(key_of(row) for row in views["team_stats"]).values()),
            "Expected exactly two teams per match.")
    equal_projection(views["shots"], sources["shots"], GRAINS["shots"], [name for name, _ in SHOTS.columns])
    normal, shootout, extra = [], [], []
    for row in views["shots"]:
        require(row["period"] in (1, 2, 3, 4, 5), "Unexpected shot period.")
        require(row["is_shootout"] == int(row["period"] == 5), "Incorrect shootout flag.")
        require(row["is_extra_time"] == int(row["period"] in (3, 4)), "Incorrect extra-time flag.")
        require(math.isfinite(row["statsbomb_xg"]) and 0 <= row["statsbomb_xg"] <= 1, "Invalid shot xG.")
        for field in SHOT_CONTEXT:
            require(row[field] == overview[key_of(row)][field], f"Shot match context differs: column={field}.")
        (shootout if row["is_shootout"] else normal).append(row)
        if row["is_extra_time"]:
            extra.append(row)
    require(len(normal) == expected["normal_shots"] and len(shootout) == expected["shootout_shots"], "Normal/shootout counts differ.")
    require(len(extra) == expected["extra_time_shots"], "Extra-time shots lost or misclassified.")
    for name, rows in (("normal", normal), ("shootout", shootout), ("raw", views["shots"])):
        require(close(math.fsum(row["statsbomb_xg"] for row in rows), expected[name + "_xg"]), f"Unexpected {name} xG total.")
    shootout_ids = {row["match_id"] for row in shootout}
    result_ids = {row["match_id"] for row in sources["results"] if row["went_to_penalties"]}
    require(shootout_ids == result_ids == expected["shootout_matches"], "Shootout match set differs from match_results.")
    # Stable goal ID 97 is the existing project contract, never outcome_name text.
    for parent in results.values():
        for side in ("home", "away"):
            rows = [row for row in shootout if key_of(row) == key_of(parent) and row["team_id"] == parent[side + "_team_id"]]
            require(len(rows) == parent[side + "_shootout_attempts"], "Shootout attempts differ from match_results.")
            require(sum(row["outcome_id"] == 97 for row in rows) == parent[side + "_shootout_goals"], "Shootout goals differ from match_results.")
    return {"rows": {name: len(rows) for name, rows in views.items()}, "normal_shots": len(normal),
            "shootout_shots": len(shootout), "shootout_matches": len(shootout_ids), "extra_time_shots": len(extra),
            "normal_xg": math.fsum(row["statsbomb_xg"] for row in normal),
            "shootout_xg": math.fsum(row["statsbomb_xg"] for row in shootout)}


def read_relation(client, relation, columns="*"):
    # Context fixed to audited WC2022. Bound driver memory if source cardinality regresses.
    result = client.query(f"SELECT {columns} FROM {relation} WHERE competition_id=43 AND season_id=106 LIMIT 10001",
                          settings={"readonly": 1})
    require(len(result.result_rows) <= 10000, "Relation exceeds WC2022 diagnostic row bound.")
    schema = tuple(zip(result.column_names, (kind.name for kind in result.column_types)))
    require(len(dict(schema)) == len(schema), "Duplicate result columns.")
    return schema, [dict(zip(result.column_names, row)) for row in result.result_rows]


def read_sources(client):
    specs = {"matches": MATCHES, "results": RESULTS, "shots": SHOTS}
    return {name: read_relation(client, table, ", ".join(n for n, _ in specs[name].columns) if name in specs else "*")
            for name, table in SOURCE_TABLES.items()}


def expected_schemas(sources):
    schemas = {name: result[0] for name, result in sources.items()}
    match_types = dict(schemas["matches"])
    overview = (*schemas["results"], *((name, match_types[name]) for name in METADATA_FIELDS), ("match_label", "String"))
    overview_types = dict(overview)
    return {
        "overview": overview,
        "team_stats": (*schemas["team_stats"], ("match_label", "String")),
        "player_stats": (*schemas["player_stats"], ("match_label", "String")),
        "shots": (*schemas["shots"], ("is_shootout", "UInt8"), ("is_extra_time", "UInt8"),
                  *((name, overview_types[name]) for name in SHOT_CONTEXT)),
    }


def check_analysis(client, *, candidate=False):
    before = read_sources(client)
    schemas = expected_schemas(before)
    relations = candidate_relations() if candidate else {name: "football.bi_match_" + name for name in GRAINS}
    views = {}
    for name, relation in relations.items():
        schema, views[name] = read_relation(client, relation)
        require(schema == schemas[name], f"Public column/type/nullability contract changed: view={name}.")
    summary = validate_rows(views, {name: result[1] for name, result in before.items()})
    after = read_sources(client)
    for name in before:
        require(before[name][0] == after[name][0], "Source schema changed during validation.")
        keys = MATCH_KEY if name in ("matches", "results") else GRAINS[name]
        equal_projection(before[name][1], after[name][1], keys, dict(before[name][0]))
    return summary
