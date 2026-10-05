"""Read-only before/after replay evidence: catalog, serving counts, full API hashes.

No S3/source requests. Output contains only public context/build IDs and aggregates.
Use the exact same command before and after a DAG run; compare JSON structurally.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_application_api import make_request
from scripts.inspect_context_catalog import inspect_catalog
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection
from src.orchestration.commands import SILVER, GOLD


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def capture():
    request = make_request("http://football-api:8000")
    result = {"contexts": {}}
    ch = create_clickhouse_client()
    try:
        with create_postgres_connection() as pg, pg.cursor() as cur:
            cur.execute("SELECT id, source, dataset, source_url, object_key, sha256, size_bytes "
                        "FROM metadata.ingestion_objects ORDER BY id")
            bronze = cur.fetchall()
            result["bronze_global"] = {"count": len(bronze), "sha256": checksum(bronze)}
            for competition_id, season_id in ((9, 281), (43, 106)):
                c = dict(competition_id=competition_id, season_id=season_id)
                item = inspect_catalog(pg, c)
                # Parent + child paths are context-scoped; shared competitions
                # catalog is intentionally covered by the global checksum above.
                prefix = f"competition_id={competition_id}/season_id={season_id}/"
                scoped = [r for r in bronze if prefix in r[4]]
                item["load_catalog"] = {}
                for table, field in (("clickhouse_loads", "silver_build_id"),
                                     ("clickhouse_gold_loads", "gold_build_id")):
                    cur.execute(f"SELECT dataset, {field}, clickhouse_table, row_count FROM metadata.{table} "
                                "WHERE competition_id=%s AND season_id=%s ORDER BY dataset, " + field,
                                (competition_id, season_id))
                    rows = cur.fetchall()
                    item["load_catalog"][table] = {"count": len(rows), "sha256": checksum(rows)}
                item["clickhouse"] = {}
                for table in (*SILVER, *GOLD):
                    actual_table = table + "_v2" if table in ("team_match_stats", "player_match_stats") else table
                    field = "silver_build_id" if table in SILVER else "gold_build_id"
                    rows = ch.query(f"SELECT toString({field}), count() FROM football.{actual_table} "
                                    "WHERE competition_id={competition:UInt32} AND season_id={season:UInt32} "
                                    f"GROUP BY {field} ORDER BY {field}",
                                    parameters={"competition": competition_id, "season": season_id}).result_rows
                    item["clickhouse"][actual_table] = rows
                base = f"/competitions/{competition_id}/seasons/{season_id}/matches"
                status, payload = request(base)
                if status != 200:
                    raise ValueError("API match listing failed")
                match_ids = {m["match_id"] for m in payload["matches"]}
                # WC's already-published legacy children have no context in
                # their key. Include them by the serving match membership.
                scoped_ids = {r[0] for r in scoped}
                for row in bronze:
                    child = re.search(r"/(events|lineups)/([0-9]+)\.json$", row[3])
                    if child and int(child[2]) in match_ids and row[0] not in scoped_ids:
                        scoped.append(row)
                scoped.sort(key=lambda r: r[0])
                item["bronze"] = {"count": len(scoped), "sha256": checksum(scoped)}
                analyses = []
                for match in sorted(payload["matches"], key=lambda r: r["match_id"]):
                    status, body = request(base + f"/{match['match_id']}/analysis")
                    if status != 200:
                        raise ValueError("API analysis failed")
                    analyses.append({"match_id": match["match_id"], "analysis": body})
                item["api"] = {"match_count": len(analyses), "all_analysis_sha256": checksum(analyses)}
                result["contexts"][f"{competition_id}/{season_id}"] = item
    finally:
        ch.close()
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(capture(), sort_keys=True, indent=2))
    except Exception as exc:
        print(f"Snapshot failed: exception={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
