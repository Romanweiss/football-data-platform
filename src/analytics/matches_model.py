"""Stage 3E match references, built on the existing read-only model checks."""

from src.analytics.gold_model import current_gold_builds
from src.analytics.gold_specs import SPECS as GOLD_SPECS
from src.analytics.model import current_builds, validate_references
from src.analytics.specs import SPECS
from src.analytics.validation import ClickHouseIntegrityError


def match_queries(*, specs=SPECS, gold_specs=GOLD_SPECS):
    def relation(dataset):
        gold = dataset in gold_specs
        spec = (gold_specs if gold else specs)[dataset]
        column = "gold_build_id" if gold else "silver_build_id"
        return (f"{spec.target} WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s "
                f"AND {column} = %({dataset}_build_id)s")

    def anti(child, parent, keys):
        return (f"SELECT count() FROM ({child}) AS child LEFT ANTI JOIN ({parent}) AS parent ON "
                + " AND ".join(f"child.{key} = parent.{key}" for key in keys))

    queries = []
    for dataset in ("event_core", "pass_events", "shot_events", "match_squads", "team_match_stats", "player_match_stats"):
        queries.append((dataset + "_match_orphans", anti(f"SELECT DISTINCT match_id FROM {relation(dataset)}",
            f"SELECT match_id FROM {relation('matches')}", ("match_id",))))
    for side in ("home", "away"):
        queries.append(("matches_" + side + "_team_orphans", anti(
            f"SELECT DISTINCT {side}_team_id AS team_id FROM {relation('matches')}",
            f"SELECT team_id FROM {relation('teams')}", ("team_id",))))
    expected = (f"SELECT match_id, home_team_id AS team_id FROM {relation('matches')} UNION ALL "
                f"SELECT match_id, away_team_id AS team_id FROM {relation('matches')}")
    actual = f"SELECT match_id, team_id FROM {relation('team_match_stats')}"
    queries.extend((
        ("gold_team_not_home_or_away", anti(actual, expected, ("match_id", "team_id"))),
        ("missing_gold_home_or_away", anti(expected, actual, ("match_id", "team_id"))),
        ("gold_team_grain_invalid", f"SELECT count() FROM (SELECT match_id FROM {relation('team_match_stats')} "
         "GROUP BY match_id HAVING count() != 2 OR uniqExact(team_id) != 2)"),
    ))
    return queries


def validate_match_references(client, builds, *, competition_id, season_id, specs=SPECS, gold_specs=GOLD_SPECS):
    parameters = {"competition_id": competition_id, "season_id": season_id,
                  **{name + "_build_id": build_id for name, build_id in builds.items()}}
    counts = {}
    for name, sql in match_queries(specs=specs, gold_specs=gold_specs):
        counts[name] = client.query(sql, parameters=parameters).result_rows[0][0]
        print(f"HARD {name}: {counts[name]}")
    if any(counts.values()):
        raise ClickHouseIntegrityError("Match dimension cross-model references failed.")
    return counts


def check_model(client, connection, *, competition_id, season_id, specs=SPECS, gold_specs=GOLD_SPECS):
    context = {"competition_id": competition_id, "season_id": season_id}
    silver = current_builds(client, connection, specs=specs, **context)
    gold = current_gold_builds(client, connection, specs=gold_specs, **context)
    counts = validate_references(client, silver, specs=specs, **context)
    counts.update(validate_match_references(client, {**silver, **{name: row["build_id"] for name, row in gold.items()}},
        specs=specs, gold_specs=gold_specs, **context))
    if (silver != current_builds(client, connection, specs=specs, **context)
            or gold != current_gold_builds(client, connection, specs=gold_specs, **context)):
        raise ClickHouseIntegrityError("Model changed during validation; repeat after writers finish.")
    print("CLICKHOUSE MODEL CHECK PASSED")
    return counts
