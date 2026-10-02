"""Small in-memory Stage 4D fixtures; no service or S3 dependencies."""

from copy import deepcopy
from datetime import date

from src.analytics.gold_specs import RESULTS
from src.analytics.specs import SHOTS
from src.analytics.match_analysis import METADATA_FIELDS, SHOT_CONTEXT, match_label


def fixture():
    results, matches, teams, players, shots = [], [], [], [], []
    for match_id in (1, 2):
        row = {name: 0 for name, _ in RESULTS.columns}
        row.update(competition_id=43, season_id=106, match_id=match_id, match_date=date(2022, 12, match_id),
                   kick_off="18:00:00", home_team_id=10, away_team_id=20, home_team_name="Home", away_team_name="Away",
                   winner_team_id=None, winner_team_name=None, display_score="0-0", result_method="DRAW",
                   went_to_extra_time=match_id == 2, went_to_penalties=match_id == 2,
                   home_shootout_attempts=int(match_id == 2), home_shootout_goals=int(match_id == 2))
        results.append(row)
        matches.append({**row, **{field: None for field in METADATA_FIELDS}})
        for team_id in (10, 20):
            # Include zero-activity player rows: presentation must never drop them.
            team = {k: row[k] for k in ("competition_id", "season_id", "match_id")}
            team.update(team_id=team_id, team_name=str(team_id), shot_count=0, shot_xg=0.0, event_count=0)
            teams.append(team)
            players.append({**team, "player_id": team_id + 100, "player_name": "Player"})
    for period in range(1, 6):
        shot = {name: None for name, _ in SHOTS.columns}
        shot.update(competition_id=43, season_id=106, match_id=1 if period < 3 else 2,
                    event_id=f"event-{period}", event_index=period, period=period, minute=period * 20, second=1,
                    timestamp="00:00:01", team_id=10, team_name="Home", player_id=None, player_name=None,
                    statsbomb_xg=0.1, outcome_id=97 if period == 5 else 98,
                    outcome_name="Deliberately not used for goal classification", start_x=100.0, start_y=30.0)
        shots.append(shot)
    sources = dict(results=results, matches=matches, team_stats=teams, player_stats=players, shots=shots)
    overview = [{**r, **{f: None for f in METADATA_FIELDS}, "match_label": match_label(r)} for r in results]
    views = {"overview": overview}
    for name in ("team_stats", "player_stats", "shots"):
        views[name] = []
        for row in sources[name]:
            parent = overview[row["match_id"] - 1]
            additions = {"match_label": parent["match_label"]}
            if name == "shots":
                additions.update({f: parent[f] for f in SHOT_CONTEXT})
                additions.update(is_shootout=int(row["period"] == 5), is_extra_time=int(row["period"] in (3, 4)))
            views[name].append({**row, **additions})
    expected = dict(overview=2, team_stats=4, player_stats=4, shots=5, normal_shots=4,
                    shootout_shots=1, extra_time_shots=2, normal_xg=0.4, shootout_xg=0.1,
                    raw_xg=0.5, shootout_matches={2})
    return deepcopy(views), deepcopy(sources), expected
