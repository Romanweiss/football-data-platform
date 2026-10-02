"""Independent, read-only validation of Stage 4E shot-level visual contracts."""

import math
from collections import defaultdict
from pathlib import Path

from src.analytics.match_analysis import MATCH_KEY, equal_projection, key_of, read_relation
from src.analytics.stats_cutover import close, require, rows_by_key

MIGRATION = Path(__file__).resolve().parents[2] / "infrastructure/clickhouse/migrations/013_create_match_visual_analysis_views.sql"
VIEWS = ("xg_race", "shot_map", "shootout")
SHOT_KEY = (*MATCH_KEY, "event_id")
BASE_FIELDS = tuple("competition_id season_id match_id match_label match_date event_id event_index team_id team_name player_id player_name period minute second statsbomb_xg outcome_id outcome_name is_shootout is_extra_time".split())
COORDINATES = ("start_x", "start_y", "end_x", "end_y", "end_z")
TEAM_CONTEXT = ("home_team_id", "home_team_name", "away_team_id", "away_team_name")
ORDER = ("period", "minute", "second", "event_index")
EXPECTED = {"normal": 1453, "shootout": 41, "shootout_matches": 5, "extra_time": 45,
            "normal_xg": 155.8985419302}
# Current WC2022 review bounds, not universal constraints on every StatsBomb dataset.
# In particular z is ball height, not bounded by the goal crossbar (observed max 7.6).
COORDINATE_MAX = {"start_x": 120.0, "end_x": 120.0, "start_y": 80.0, "end_y": 80.0, "end_z": 7.6}


def view_selects():
    statements = [s.strip() for s in MIGRATION.read_text(encoding="utf-8").split(";") if s.strip()]
    require(len(statements) == 3, "Unexpected visual migration view count.")
    bodies = {}
    for name, sql in zip(VIEWS, statements, strict=True):
        require(f"CREATE VIEW IF NOT EXISTS football.bi_match_{name}\nSQL SECURITY INVOKER\nAS\n" in sql,
                "Unexpected visual migration contract.")
        bodies[name] = sql.split("\nAS\n", 1)[1]
    return bodies


def validate_coordinates(row):
    for field, upper in COORDINATE_MAX.items():
        value = row[field]
        require(value is None or (math.isfinite(value) and 0 <= value <= upper),
                f"Coordinate outside reviewed WC2022 domain: column={field}.")


def validate_visuals(views, shots, overview, team_stats, *, expected=EXPECTED):
    parents = rows_by_key(overview, MATCH_KEY)
    teams = rows_by_key(team_stats, (*MATCH_KEY, "team_id"))
    rows_by_key(shots, SHOT_KEY)
    # A unique source index makes event_index the final deterministic tie breaker.
    rows_by_key(shots, (*MATCH_KEY, "event_index"))
    normal = [r for r in shots if r["is_shootout"] == 0]
    penalties = [r for r in shots if r["is_shootout"] == 1]
    require(len(normal) == expected["normal"] and len(penalties) == expected["shootout"], "Unexpected source shot counts.")
    for row in shots:
        require(row["period"] in (1, 2, 3, 4, 5) and row["is_shootout"] == int(row["period"] == 5)
                and row["is_extra_time"] == int(row["period"] in (3, 4)), "Invalid source period flags.")
        require(math.isfinite(row["statsbomb_xg"]) and 0 <= row["statsbomb_xg"] <= 1, "Invalid source shot xG.")
        require(key_of(row) in parents and (*key_of(row), row["team_id"]) in teams, "Orphan shot match/team.")
        require(row["match_label"] == parents[key_of(row)]["match_label"], "Shot label differs from overview.")
    require(sum(r["is_extra_time"] for r in normal) == expected["extra_time"], "Extra-time coverage changed.")
    require(close(math.fsum(r["statsbomb_xg"] for r in normal), expected["normal_xg"]), "Normal xG total changed.")
    for name in VIEWS:
        source = penalties if name == "shootout" else normal
        fields = (*BASE_FIELDS, *COORDINATES) if name == "shot_map" else BASE_FIELDS
        equal_projection(views[name], source, SHOT_KEY, fields)
        for row in views[name]:
            if name != "shot_map":
                require(all(row[f] == parents[key_of(row)][f] for f in TEAM_CONTEXT), "Home/away identity changed.")
            if name != "xg_race":
                require(row["is_goal"] == (row["outcome_id"] == 97), "Goal flag differs from stable outcome ID.")
            else:
                require(row["event_time_seconds"] == row["minute"] * 60 + row["second"], "Source event clock changed.")
            if name == "shot_map":
                validate_coordinates(row)

    matches = defaultdict(list)
    for row in views["xg_race"]:
        matches[key_of(row)].append(row)
    final_xg = {}
    for match, rows in matches.items():
        parent = parents[match]
        values = {parent["home_team_id"]: [], parent["away_team_id"]: []}
        previous = {team: 0.0 for team in values}
        for order, row in enumerate(sorted(rows, key=lambda r: tuple(r[f] for f in ORDER)), 1):
            require(row["event_order"] == order, "Incorrect canonical race order.")
            require(row["team_id"] in values, "Shot team is not a match participant.")
            values[row["team_id"]].append(row["statsbomb_xg"])
            for side in ("home", "away"):
                team = parent[side + "_team_id"]
                wanted = math.fsum(values[team])
                actual = row[side + "_cumulative_xg"]
                require(close(actual, wanted) and (actual >= previous[team] or close(actual, previous[team])),
                        "Non-monotonic or incorrect running xG.")
                previous[team] = actual
            require(close(row["team_cumulative_xg"], math.fsum(values[row["team_id"]])), "Shooting-team cumulative xG differs.")
        for team, values_ in values.items():
            final_xg[(*match, team)] = math.fsum(values_)
    # Teams with no normal shots legitimately have no own race events and zero xG.
    for key, row in teams.items():
        require(close(final_xg.get(key, 0.0), row["shot_xg"]), "Final cumulative xG differs from team stats.")

    matches = defaultdict(list)
    for row in views["shootout"]:
        matches[key_of(row)].append(row)
    required = {key for key, parent in parents.items() if parent["went_to_penalties"]}
    require(matches.keys() == required and len(matches) == expected["shootout_matches"], "Shootout match coverage differs.")
    for match, rows in matches.items():
        parent = parents[match]
        attempts = defaultdict(int)
        goals = {parent["home_team_id"]: 0, parent["away_team_id"]: 0}
        for order, row in enumerate(sorted(rows, key=lambda r: r["event_index"]), 1):
            team = row["team_id"]
            require(team in goals, "Shootout team is not a match participant.")
            attempts[team] += 1
            goals[team] += int(row["outcome_id"] == 97)
            require(row["shootout_order"] == order and row["team_attempt_number"] == attempts[team], "Non-contiguous shootout/attempt order.")
            for side in ("home", "away"):
                require(row[side + "_shootout_goals_after"] == goals[parent[side + "_team_id"]], "Incorrect running shootout score.")
        for side in ("home", "away"):
            team = parent[side + "_team_id"]
            require(goals[team] == parent[side + "_shootout_goals"] and attempts[team] == parent[side + "_shootout_attempts"],
                    "Final shootout score/attempt count differs from overview.")
    return {"xg_race": len(normal), "shot_map": len(normal), "shootout": len(penalties),
            "shootout_matches": len(matches), "normal_xg": math.fsum(r["statsbomb_xg"] for r in normal),
            "extra_time_shots": sum(r["is_extra_time"] for r in normal)}


def read_sources(client):
    return {name: read_relation(client, "football.bi_match_" + name) for name in ("shots", "overview", "team_stats")}


def expected_schemas(sources):
    shot_schema = dict(sources["shots"][0])
    parent_schema = dict(sources["overview"][0])
    base = tuple((f, shot_schema[f]) for f in BASE_FIELDS)
    context = tuple((f, parent_schema[f]) for f in TEAM_CONTEXT)
    return {
        "xg_race": (*base, *context, ("event_time_seconds", "UInt64"), ("event_order", "UInt64"),
                    ("team_cumulative_xg", "Float64"), ("home_cumulative_xg", "Float64"), ("away_cumulative_xg", "Float64")),
        "shot_map": (*base, *((f, shot_schema[f]) for f in COORDINATES), ("is_goal", "Bool"), ("shot_label", "String")),
        "shootout": (*base, *context, ("shootout_order", "UInt64"), ("team_attempt_number", "UInt64"), ("is_goal", "Bool"),
                     ("home_shootout_goals_after", "UInt64"), ("away_shootout_goals_after", "UInt64")),
    }


def check_visuals(client, *, candidate=False, candidate_shot_map=False):
    before = read_sources(client)
    schemas = expected_schemas(before)
    relations = {n: "(" + sql + ")" for n, sql in view_selects().items()} if candidate else {n: "football.bi_match_" + n for n in VIEWS}
    if candidate or candidate_shot_map:
        relations["shot_map"] = "(" + shot_map_select() + ")"
    views = {}
    for name, relation in relations.items():
        schema, views[name] = read_relation(client, relation)
        require(schema == schemas[name], f"Visual schema/nullability mismatch: view={name}.")
    result = validate_visuals(views, *(before[n][1] for n in ("shots", "overview", "team_stats")))
    validate_shot_labels(views["shot_map"])
    result["unique_shot_labels"] = len(views["shot_map"])
    after = read_sources(client)
    for name in before:
        require(before[name][0] == after[name][0], "Source schema changed during check.")
        keys = SHOT_KEY if name == "shots" else (*MATCH_KEY, "team_id") if name == "team_stats" else MATCH_KEY
        equal_projection(before[name][1], after[name][1], keys, dict(before[name][0]))
    return result


SHOT_MAP_MIGRATION = MIGRATION.with_name("015_enrich_match_shot_map.sql")


def shot_map_select():
    sql = SHOT_MAP_MIGRATION.read_text(encoding="utf-8").strip()
    require("CREATE OR REPLACE VIEW football.bi_match_shot_map\nSQL SECURITY INVOKER\nAS\n" in sql,
            "Unexpected enriched shot-map migration contract.")
    return sql.split("\nAS\n", 1)[1].removesuffix(";")


def expected_shot_label(row):
    player = "Unknown player" if row["player_name"] is None else row["player_name"]
    outcome = "Unknown outcome" if row["outcome_name"] is None else row["outcome_name"]
    return f"{player} | {row['minute']}:{row['second']:02d} | {outcome} | #{row['event_index']}"


def validate_shot_labels(rows):
    rows_by_key(rows, SHOT_KEY)
    rows_by_key(rows, (*MATCH_KEY, "event_index"))
    rows_by_key(rows, (*MATCH_KEY, "shot_label"))
    for row in rows:
        label = row["shot_label"]
        require(isinstance(label, str) and bool(label.strip()) and label == expected_shot_label(row),
                "Invalid or non-deterministic shot label.")


SERIES_MIGRATION = MIGRATION.with_name("014_create_match_xg_race_series_view.sql")
SERIES_EVENT_FIELDS = (*MATCH_KEY, "match_label", "event_order", "event_id", "event_index", "period", "minute", "second")
SERIES_FIELDS = (*SERIES_EVENT_FIELDS, "team_id", "team_name", "is_home", "cumulative_xg")


def series_select():
    sql = SERIES_MIGRATION.read_text(encoding="utf-8").strip()
    require("CREATE VIEW IF NOT EXISTS football.bi_match_xg_race_series\nSQL SECURITY INVOKER\nAS\n" in sql,
            "Unexpected xG series migration contract.")
    return sql.split("\nAS\n", 1)[1].removesuffix(";")


def validate_race_series(series, race, team_stats, *, expected_rows=2906):
    """Two exact team states per source event, independent of the shooting team."""
    event_key = (*MATCH_KEY, "event_order")
    rows_by_key(race, event_key)
    rows_by_key(race, SHOT_KEY)
    rows_by_key(series, (*event_key, "team_id"))
    require(len(series) == expected_rows == 2 * len(race), "Unexpected long-form xG row count.")
    expected = []
    for row in race:
        require(row["home_team_id"] != row["away_team_id"], "Race home/away teams must differ.")
        require(row["period"] in (1, 2, 3, 4) and row["is_shootout"] == 0, "Non-normal source race event.")
        for side, flag in (("home", 1), ("away", 0)):
            value = row[side + "_cumulative_xg"]
            require(math.isfinite(value) and value >= 0, "Invalid source cumulative xG.")
            expected.append({**{f: row[f] for f in SERIES_EVENT_FIELDS},
                             "team_id": row[side + "_team_id"], "team_name": row[side + "_team_name"],
                             "is_home": flag, "cumulative_xg": value})
    # Keys include the side: this proves exactly one home and one away per event,
    # and exact values/identity (no tolerance for an altered source projection).
    equal_projection(series, expected, (*event_key, "is_home"), SERIES_FIELDS)
    finals = {}
    for row in series:
        key = (*key_of(row), row["team_id"])
        if key not in finals or row["event_order"] > finals[key]["event_order"]:
            finals[key] = row
    teams = rows_by_key(team_stats, (*MATCH_KEY, "team_id"))
    require(finals.keys() == teams.keys(), "Final series team coverage differs from team stats.")
    for key, row in finals.items():
        require(row["team_name"] == teams[key]["team_name"] and close(row["cumulative_xg"], teams[key]["shot_xg"]),
                "Final long-form cumulative xG differs from team stats.")
    return {"xg_race_series": len(series), "team_final_states": len(finals)}


def check_race_series(client, *, candidate=False, race_relation="football.bi_match_xg_race"):
    schema, race = read_relation(client, race_relation)
    team_schema, teams = read_relation(client, "football.bi_match_team_stats")
    types = dict(schema)
    expected_schema = (*((f, types[f]) for f in SERIES_EVENT_FIELDS),
                       ("team_id", types["home_team_id"]), ("team_name", types["home_team_name"]),
                       ("is_home", "UInt8"), ("cumulative_xg", "Float64"))
    relation = "(" + series_select().replace("football.bi_match_xg_race", race_relation) + ")" if candidate else "football.bi_match_xg_race_series"
    actual_schema, series = read_relation(client, relation)
    require(actual_schema == expected_schema, "Long-form xG schema contract changed.")
    result = validate_race_series(series, race, teams)
    after_schema, after_race = read_relation(client, race_relation)
    after_team_schema, after_teams = read_relation(client, "football.bi_match_team_stats")
    require(schema == after_schema and team_schema == after_team_schema, "Source schema changed during series validation.")
    equal_projection(race, after_race, SHOT_KEY, types)
    equal_projection(teams, after_teams, (*MATCH_KEY, "team_id"), dict(team_schema))
    return result
