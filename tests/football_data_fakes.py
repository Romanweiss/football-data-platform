"""Artificial vendor-shaped JSON in memory, no recorded/private API responses."""
from collections import Counter
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

from provider_collection_fakes import NOW, make_scenario
from src.providers.football_data import FixtureBinding, MappingContext
from src.providers.models import DataFreshness, FixtureStatus
from src.providers.observed_window import Observation, SEQUENCE
from src.providers.validation import _json

SPEC = json.loads((Path(__file__).parent / "fixtures/football_data_synthetic.json").read_text(encoding="utf-8"))


def encode(document):
    return _json(document).encode("utf-8")


def make_payloads():
    """Use B's invented balanced schedule, not any real competition results."""
    source, _ = make_scenario("ucl")
    provider = "football-data-org"

    def entity(item, external=None):
        identity = replace(item.identity, provider=provider,
                           external_id=external if external is not None else item.identity.external_id)
        return replace(item, identity=identity)

    competition = entity(source.competition, str(SPEC["metadata"]["id"]))
    season = entity(source.season, str(SPEC["metadata"]["currentSeason"]["id"]))
    participants = tuple(entity(team, str(SPEC["team_id_start"] + i)) for i, team in enumerate(source.participants))
    context_snapshot = replace(source, provider=provider, competition=competition, season=season,
        stages=tuple(entity(stage) for stage in source.stages), rounds=tuple(entity(r) for r in source.rounds),
        participants=participants, fixtures=(), standings=(), capabilities=(), partial=True,
        coverage_note="Invented league phase only; not the complete UCL season",
        freshness=DataFreshness(NOW, NOW))
    bindings = tuple(FixtureBinding(str(SPEC["fixture_id_start"] + i), fixture.id, fixture.revision)
                     for i, fixture in enumerate(source.fixtures))
    context = MappingContext(context_snapshot, bindings)
    teams = {item.id: {"id": int(item.identity.external_id), "name": item.name} for item in participants}
    matches = []
    for binding, fixture in zip(bindings, source.fixtures):
        matches.append({"id": int(binding.external_id), "competition": {"id": 2001}, "season": {"id": 2557},
            "utcDate": fixture.kickoff.isoformat().replace("+00:00", "Z"),
            "status": "FINISHED" if fixture.status is FixtureStatus.FINISHED else "TIMED",
            "lastUpdated": fixture.updated_at.isoformat().replace("+00:00", "Z"),
            "matchday": next(r.order for r in source.rounds if r.id == fixture.round_id),
            "stage": SPEC["stage"], "group": None,
            "homeTeam": teams[fixture.home_id], "awayTeam": teams[fixture.away_id],
            "score": {"duration": SPEC["duration"], "fullTime": {
                "home": fixture.score.regulation_home, "away": fixture.score.regulation_away}}})
    fixtures = {"competition": {"id": 2001}, "resultSet": {"count": len(matches),
        "played": sum(row["status"] == "FINISHED" for row in matches)}, "matches": matches}
    standings = {"competition": {"id": 2001}, "season": {"id": 2557}, "standings": []}
    # Independent test oracle, with home/away split. Production mapper never repairs tables.
    for kind in ("TOTAL", "HOME", "AWAY"):
        table = []
        for position, (canonical, team) in enumerate(teams.items(), 1):
            counts = Counter()
            for row in matches:
                if row["status"] != "FINISHED":
                    continue
                home, away = row["homeTeam"]["id"], row["awayTeam"]["id"]
                if team["id"] not in (home, away) or kind == "HOME" and team["id"] != home or kind == "AWAY" and team["id"] != away:
                    continue
                a, b = row["score"]["fullTime"]["home"], row["score"]["fullTime"]["away"]
                gf, ga = (a, b) if team["id"] == home else (b, a)
                counts.update({"playedGames": 1, "won": int(gf > ga), "draw": int(gf == ga),
                               "lost": int(gf < ga), "goalsFor": gf, "goalsAgainst": ga,
                               "points": 3 if gf > ga else int(gf == ga)})
            table.append({"team": team, "position": position, **{key: counts[key] for key in
                ("playedGames", "won", "draw", "lost", "goalsFor", "goalsAgainst", "points")},
                "goalDifference": counts["goalsFor"] - counts["goalsAgainst"]})
        standings["standings"].append({"stage": "LEAGUE_STAGE", "type": kind, "group": None, "table": table})
    return context, json.loads(encode(SPEC["metadata"])), json.loads(encode(fixtures)), json.loads(encode(standings))


def observations(metadata, fixtures, standings, *, offset=timedelta()):
    documents = {"metadata": metadata, "fixtures": fixtures, "standings": standings}
    return tuple(Observation(resource, NOW + offset + timedelta(seconds=i * 2),
                             NOW + offset + timedelta(seconds=i * 2 + 1), encode(documents[resource]))
                 for i, resource in enumerate(SEQUENCE))
