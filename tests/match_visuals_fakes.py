"""Offline visual fixture: tied clocks, interleaved teams, extra time and misses."""
from collections import defaultdict
from copy import deepcopy

from match_analysis_fakes import fixture as analysis_fixture
from src.analytics.match_visuals import BASE_FIELDS, COORDINATES, TEAM_CONTEXT, key_of


def fixture():
    views, _, _ = analysis_fixture()
    overview = views["overview"]
    shots = views["shots"][:4]
    for index, shot in enumerate(shots):
        shot["event_index"] = (20, 10, 30, 40)[index]
        shot["period"] = (1, 1, 3, 4)[index]
        shot["minute"], shot["second"] = (12, 30) if index < 2 else (90, 0) if index == 2 else (105, 0)
        shot["team_id"] = 10 if index % 2 == 0 else 20
        shot["team_name"] = "Home" if shot["team_id"] == 10 else "Away"
    for index, (team, outcome) in enumerate(((20, 97), (10, 97), (20, 100), (10, 97)), 1):
        shot = deepcopy(views["shots"][-1])
        shot.update(event_id=f"penalty-{index}", event_index=100 + index, team_id=team,
                    team_name="Home" if team == 10 else "Away", outcome_id=outcome, outcome_name="not a goal classifier")
        shots.append(shot)
    overview[-1].update(home_shootout_attempts=2, away_shootout_attempts=2, home_shootout_goals=2, away_shootout_goals=1)
    teams = deepcopy(views["team_stats"])
    for team in teams:
        team["shot_xg"] = sum(s["statsbomb_xg"] for s in shots if not s["is_shootout"] and key_of(s) == key_of(team) and s["team_id"] == team["team_id"])
    actual = {"xg_race": [], "shot_map": [], "shootout": []}
    for parent in overview:
        match_shots = [s for s in shots if key_of(s) == key_of(parent)]
        normal = sorted((s for s in match_shots if not s["is_shootout"]), key=lambda s: (s["period"], s["minute"], s["second"], s["event_index"]))
        sums = defaultdict(float)
        context = {f: parent[f] for f in TEAM_CONTEXT}
        for order, shot in enumerate(normal, 1):
            base = {f: shot[f] for f in BASE_FIELDS}
            sums[shot["team_id"]] += shot["statsbomb_xg"]
            actual["xg_race"].append({**base, **context, "event_order": order,
                "event_time_seconds": shot["minute"] * 60 + shot["second"], "team_cumulative_xg": sums[shot["team_id"]],
                "home_cumulative_xg": sums[10], "away_cumulative_xg": sums[20]})
            actual["shot_map"].append({**base, **{f: shot[f] for f in COORDINATES}, "is_goal": shot["outcome_id"] == 97})
        attempts, goals = defaultdict(int), defaultdict(int)
        for order, shot in enumerate(sorted((s for s in match_shots if s["is_shootout"]), key=lambda s: s["event_index"]), 1):
            team = shot["team_id"]
            attempts[team] += 1
            goals[team] += int(shot["outcome_id"] == 97)
            actual["shootout"].append({**{f: shot[f] for f in BASE_FIELDS}, **context,
                "shootout_order": order, "team_attempt_number": attempts[team], "is_goal": shot["outcome_id"] == 97,
                "home_shootout_goals_after": goals[10], "away_shootout_goals_after": goals[20]})
    expected = dict(normal=4, shootout=4, shootout_matches=1, extra_time=2, normal_xg=0.4)
    return actual, shots, overview, teams, expected
