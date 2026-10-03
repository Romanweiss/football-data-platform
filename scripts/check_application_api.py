"""Read-only API contract checks via Django in-process or a local HTTP server."""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def require(condition):
    if not condition:
        raise ValueError("Application API contract mismatch")


def make_request(base_url=None):
    if base_url:
        parsed = urlparse(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "football-api")
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Only a local HTTP API origin is supported")

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = build_opener(NoRedirect)

        def request(path):
            try:
                result = opener.open(base_url.rstrip("/") + "/api/v1" + path, timeout=30)
            except HTTPError as exc:
                result = exc
            with result:
                return result.status, json.load(result)
        return request

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
    import django
    django.setup()
    from django.test import Client
    client = Client(raise_request_exception=False, HTTP_HOST="localhost")

    def request(path):
        result = client.get("/api/v1" + path)
        return result.status_code, result.json()
    return request


def validate(request, *, competition_id, season_id, wc2022=False):
    timings = {}

    def get(path, status=200):
        start = time.perf_counter()
        actual_status, data = request(path)
        timings[path] = round((time.perf_counter() - start) * 1000, 2)
        require(actual_status == status)
        return data

    require(get("/health") == {"status": "ok"})
    require(get("/health/clickhouse") == {"status": "ok"})
    context = f"/competitions/{competition_id}/seasons/{season_id}"
    require({"competition_id": competition_id} in get("/competitions")["competitions"])
    require({"season_id": season_id} in get(f"/competitions/{competition_id}/seasons")["seasons"])
    matches = get(context + "/matches")["matches"]
    require(len(matches) == len({r["match_id"] for r in matches}) and bool(matches))
    if wc2022:
        require((competition_id, season_id) == (43, 106) and len(matches) == 64)
    require(matches == sorted(matches, key=lambda r: (r["match_date"], r["kick_off"], r["match_id"])))
    require(all(r["competition_id"] == competition_id and r["season_id"] == season_id for r in matches))
    missing = get(context + "/matches/18446744073709551615", 404)
    require(missing["error"]["code"] == "match_not_found")
    require(get(context + "/matches/not-an-id", 400)["error"]["code"] == "invalid_request")
    pairs = (("Argentina", "France"), ("Netherlands", "Argentina"), ("Mexico", "Poland"), ("Croatia", "Morocco"))
    selected = matches[:4]
    if wc2022:
        selected = []
        for home, away in pairs:
            candidates = [r for r in matches if (r["home_team_name"], r["away_team_name"]) == (home, away)]
            require(len(candidates) == 1)
            selected.append(candidates[0])
    checked = []
    for match in selected:
        home = match["home_team_name"]
        match_id = match["match_id"]
        prefix = context + f"/matches/{match_id}"
        require(get(prefix) == match)
        composite = get(prefix + "/analysis")
        require(set(composite) == {"match", "teams", "players", "shots", "xg_race", "shootout"})
        require(composite["match"] == match)
        for url, section in (("teams", "teams"), ("players", "players"), ("shots", "shots"), ("xg-race", "xg_race")):
            require(get(prefix + "/" + url)[section] == composite[section])
        require(get(prefix + "/shootout") == composite["shootout"])
        teams, players, shots, race = (composite[key] for key in ("teams", "players", "shots", "xg_race"))
        require(len(teams) == 2 and {r["team_id"] for r in teams} == {match["home_team_id"], match["away_team_id"]})
        require(players and len(players) == len({(r["team_id"], r["player_id"]) for r in players}))
        require(all(type(r["event_count"]) is int and type(r["shot_xg"]) is float and type(r["is_home"]) is bool for r in players))
        team_id = teams[0]["team_id"]
        require(get(prefix + f"/players?team_id={team_id}")["players"] == [r for r in players if r["team_id"] == team_id])
        require(get(prefix + "/players?team_id=oops", 400)["error"]["code"] == "invalid_request")
        require(shots == sorted(shots, key=lambda r: (r["period"], r["minute"], r["second"], r["event_index"])))
        require(all(r["period"] in (1, 2, 3, 4) and r["shot_label"] and type(r["is_goal"]) is bool for r in shots))
        require(len(shots) == len({r["event_id"] for r in shots}) == len({r["shot_label"] for r in shots}))
        require(race == sorted(race, key=lambda r: (r["event_order"], -int(r["is_home"]))))
        require(len(race) == 2 * len(shots))
        for team in teams:
            states = [r for r in race if r["team_id"] == team["team_id"]]
            require(math.isclose(states[-1]["cumulative_xg"] if states else 0, team["shot_xg"], rel_tol=1e-9, abs_tol=1e-9))
        shootout = composite["shootout"]
        require(shootout["went_to_penalties"] is match["went_to_penalties"])
        attempts = shootout["attempts"]
        require([r["shootout_order"] for r in attempts] == list(range(1, len(attempts) + 1)))
        if wc2022 and home == "Argentina":
            require(len(shots) == 30 and len(attempts) == 8)
            require(attempts[-1]["home_shootout_goals_after"] == 4 and attempts[-1]["away_shootout_goals_after"] == 2)
            for name, expected in (("Argentina", 2.758305926), ("France", 2.2726179490000002)):
                require(math.isclose(next(r["shot_xg"] for r in teams if r["team_name"] == name), expected, abs_tol=1e-9))
        if wc2022 and home == "Mexico":
            require(shootout == {"match_id": match_id, "went_to_penalties": False, "attempts": []})
        if wc2022:
            require(get(f"/matches/{match_id}/analysis") == composite)
        checked.append(match_id)
    return {"matches": len(matches), "checked_match_ids": checked, "latency_ms_single_request": timings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Optional local HTTP origin; default uses Django in-process, no server required")
    parser.add_argument("--competition-id", required=True, type=int)
    parser.add_argument("--season-id", required=True, type=int)
    parser.add_argument("--wc2022-regression", action="store_true", help="Explicit golden-fixture counts and four WC2022 matches")
    args = parser.parse_args(argv)
    if not all(0 < value < 2**32 for value in (args.competition_id, args.season_id)):
        parser.error("Context IDs must be positive UInt32")
    if args.wc2022_regression and (args.competition_id, args.season_id) != (43, 106):
        parser.error("WC2022 regression requires context 43/106")
    try:
        result = validate(make_request(args.base_url), competition_id=args.competition_id, season_id=args.season_id, wc2022=args.wc2022_regression)
        print("APPLICATION API CHECK PASSED: " + json.dumps(result))
        return 0
    except Exception as exc:
        print(f"Application API check failed: exception={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
