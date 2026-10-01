"""Read-only serving audit. Exact event-key joins; no S3 or catalog writes."""

import json
import math

TABLES = ("matches", "event_core", "pass_events", "shot_events", "team_match_stats", "player_match_stats")
EVENT_KEY = "competition_id, season_id, match_id, event_id"


def audit(client):
    parameters = {"competition_id": 43, "season_id": 106}
    identities = {}
    snapshots = {}
    for table in TABLES:
        column = "gold_build_id" if table.endswith("match_stats") else "silver_build_id"
        rows = client.query(f"SELECT count(), uniqExact({column}), min(toString({column})) "
            f"FROM football.{table} WHERE competition_id=43 AND season_id=106", settings={"readonly": 1}).result_rows
        count, distinct, build_id = rows[0]
        snapshots[table] = tuple(rows[0])
        if not count or distinct != 1:
            raise ValueError("Audit requires exactly one nonempty serving build per dataset")
        identities[table] = build_id
        parameters[table + "_build"] = build_id
    ctes = []
    for table in TABLES:
        column = "gold_build_id" if table.endswith("match_stats") else "silver_build_id"
        ctes.append(f"{table} AS (SELECT * FROM football.{table} WHERE competition_id=%(competition_id)s "
                    f"AND season_id=%(season_id)s AND {column}=%({table}_build)s)")
    ctes.append(f"shots AS (SELECT s.*, e.period AS core_period FROM shot_events s "
                f"INNER JOIN event_core e USING ({EVENT_KEY}))")
    prefix = "WITH " + ",\n".join(ctes) + "\n"

    def query(sql):
        result = client.query(prefix + sql, parameters=parameters, settings={"readonly": 1})
        return [dict(zip((name.split('.')[-1] for name in result.column_names), row)) for row in result.result_rows]

    for table in TABLES:
        keys = ("match_id, team_id, player_id" if table == "player_match_stats" else
                "match_id, team_id" if table == "team_match_stats" else
                "match_id" if table == "matches" else "match_id, event_id")
        if query(f"SELECT count()-uniqExact(tuple({keys})) AS duplicates FROM {table}")[0]["duplicates"]:
            raise ValueError("Duplicate serving grain prevents reliable audit")
    for domain in ("shot_events", "pass_events"):
        if query(f"SELECT count() AS missing FROM {domain} s LEFT ANTI JOIN event_core e USING ({EVENT_KEY})")[0]["missing"]:
            raise ValueError("Domain events missing from event_core")
        if query(f"SELECT countIf(s.period != e.period OR s.team_id != e.team_id "
                 f"OR ifNull(s.player_id,0)!=ifNull(e.player_id,0)) AS invalid "
                 f"FROM {domain} s INNER JOIN event_core e USING ({EVENT_KEY})")[0]["invalid"]:
            raise ValueError("Domain/core identity or period mismatch")
    report = {"context": {"competition_id": 43, "season_id": 106}, "builds": identities}
    report["shots_by_period"] = query("SELECT core_period AS period, count() AS attempts, "
        "countIf(outcome_id=97) AS goals, arraySum(arraySort(groupArray(statsbomb_xg))) AS xg "
        "FROM shots GROUP BY core_period ORDER BY core_period")
    report["shootout_teams"] = query("SELECT match_id, team_id, any(team_name) AS team_name, count() AS attempts, "
        "countIf(outcome_id=97) AS goals, arraySum(arraySort(groupArray(statsbomb_xg))) AS xg "
        "FROM shots WHERE core_period=5 GROUP BY match_id, team_id ORDER BY match_id, team_id")
    report["shootout_matches"] = query("SELECT m.match_id, m.home_team_name, m.away_team_name, m.home_score, m.away_score, "
        "countIf(e.period IN (3,4)) > 0 AS has_extra_time FROM matches m INNER JOIN event_core e "
        "USING (competition_id,season_id,match_id) GROUP BY m.match_id,m.home_team_name,m.away_team_name,m.home_score,m.away_score "
        "HAVING countIf(e.period=5)>0 ORDER BY m.match_id")
    report["period5_events"] = query("SELECT type_id, type_name, count() AS events, "
        "countIf(under_pressure) AS under_pressure, countIf(counterpress) AS counterpress "
        "FROM event_core WHERE period=5 GROUP BY type_id,type_name ORDER BY type_id")
    for dataset in ("team_match_stats", "player_match_stats"):
        player = dataset.startswith("player")
        keys = "match_id, team_id" + (", player_id" if player else "")
        condition = " WHERE player_id IS NOT NULL" if player else ""
        # Reconstruct both v1 (all periods) and the proposed v2 at the original grain.
        sql = f"""SELECT g.*, a.all_shots, a.all_xg, a.all_goals,
            a.normal_shots, a.normal_xg, a.normal_goals,
            toInt64(g.shot_count)-toInt64(a.normal_shots) AS delta_shots,
            g.shot_xg-a.normal_xg AS delta_xg,
            toInt64(g.shot_goals)-toInt64(a.normal_goals) AS delta_goals,
            toInt64(g.event_count)-toInt64(e.normal_events) AS delta_events,
            toInt64(g.under_pressure_events)-toInt64(e.normal_pressure) AS delta_pressure,
            toInt64(g.counterpress_events)-toInt64(e.normal_counterpress) AS delta_counterpress,
            toInt64(g.pass_attempts)-toInt64(p.normal_passes) AS delta_passes
            {'' if player else ', toInt64(g.players_with_events)-toInt64(e.normal_players) AS delta_players_with_events'}
            FROM {dataset} g LEFT JOIN (
              SELECT {keys}, count() AS all_shots, countIf(outcome_id=97) AS all_goals,
              arraySum(arraySort(groupArray(statsbomb_xg))) AS all_xg,
              countIf(core_period!=5) AS normal_shots, countIf(core_period!=5 AND outcome_id=97) AS normal_goals,
              arraySum(arraySort(groupArrayIf(statsbomb_xg,core_period!=5))) AS normal_xg
              FROM shots {condition} GROUP BY {keys}
            ) a USING ({keys}) LEFT JOIN (
              SELECT {keys}, countIf(period!=5) AS normal_events,
              countIf(period!=5 AND under_pressure) AS normal_pressure,
              countIf(period!=5 AND counterpress) AS normal_counterpress,
              uniqExactIf(player_id,period!=5) AS normal_players
              FROM event_core {condition} GROUP BY {keys}
            ) e USING ({keys}) LEFT JOIN (
              SELECT {keys}, countIf(period!=5) AS normal_passes
              FROM pass_events {condition} GROUP BY {keys}
            ) p USING ({keys}) ORDER BY {keys}"""
        rows = query(sql)
        for row in rows:
            if (row["shot_count"] != row["all_shots"] or row["shot_goals"] != row["all_goals"]
                    or not math.isclose(row["shot_xg"], row["all_xg"], rel_tol=1e-9, abs_tol=1e-9)):
                raise ValueError("Serving Gold does not match reconstructed v1; investigate lineage before cutover")
        deltas = ("delta_shots", "delta_xg", "delta_goals", "delta_events", "delta_pressure", "delta_counterpress", "delta_passes")
        if not player:
            deltas += ("delta_players_with_events",)
        affected = [row for row in rows if any(abs(row[key]) > 1e-9 for key in deltas)]
        # Omit runtime timestamps; preserve every affected grain and exact Float64 differences.
        fields = keys.split(", ") + ["team_name"] + (["player_name"] if player else [])
        fields += ["shot_count", "shot_xg", "shot_goals", "normal_shots", "normal_xg", "normal_goals", *deltas]
        report[dataset] = {"rows": len(rows), "affected_rows": len(affected),
            "shot_affected_rows": sum(row["delta_shots"] != 0 for row in rows),
            "v1_matches_all_period_shots": True,
            "totals": {key: math.fsum(row[key] for row in rows) if key == "delta_xg" else sum(row[key] for row in rows) for key in deltas},
            "differences": [{key: row[key] for key in fields} for row in affected]}
    for table in TABLES:
        column = "gold_build_id" if table.endswith("match_stats") else "silver_build_id"
        current = client.query(f"SELECT count(), uniqExact({column}), min(toString({column})) "
            f"FROM football.{table} WHERE competition_id=43 AND season_id=106", settings={"readonly": 1}).result_rows[0]
        if tuple(current) != snapshots[table]:
            raise ValueError("Serving snapshot changed during audit; repeat after writers finish")
    return report


def main():
    from src.common.clickhouse import create_clickhouse_client
    try:
        with create_clickhouse_client() as client:
            print(json.dumps(audit(client), ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as error:
        print(f"Shot semantics audit failed: operation=read_only_audit exception={type(error).__name__}")
        return 1
