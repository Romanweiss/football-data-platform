"""Reviewed-looking evidence labels and invented payloads ONLY; no real identity claims."""
from collections import Counter
from dataclasses import replace

from football_data_fakes import make_payloads
from src.providers.identity_registry import IdentityEvidence, IdentityKind, IdentityRegistry
from src.providers.models import EntityKind, ProviderIdentity
from src.providers.observed_versions import VersionLedger
from src.providers.registry_policy import bind_mapping_context

EVIDENCE = IdentityEvidence(True, "synthetic-reviewed-bindings-v1")


def identity_setup():
    context, metadata, fixtures, standings = make_payloads()
    original = context.empty_snapshot
    registry = IdentityRegistry()
    provider = original.provider
    root = registry.register(provider, IdentityKind.PROVIDER, provider, evidence=EVIDENCE)

    def register(kind, external, parent, **kwargs):
        return registry.register(provider, kind, external, parent_id=parent, evidence=EVIDENCE, **kwargs)

    comp = register(IdentityKind.COMPETITION, original.competition.identity.external_id, root.id,
                    team_type=original.competition.team_type)
    season = register(IdentityKind.SEASON, original.season.identity.external_id, comp.id)
    stage = register(IdentityKind.STAGE, original.stages[0].identity.external_id, season.id,
                     stage_kind=original.stages[0].kind)

    def bound(entity, record):
        return replace(entity, id=record.id, identity=ProviderIdentity(provider, EntityKind(record.kind.value), record.external_id))

    teams, ids = [], {}
    for team in original.participants:
        record = register(IdentityKind.PARTICIPANT, team.identity.external_id, root.id, team_type=team.team_type)
        registry.confirm_participation(season.id, record.id, evidence=EVIDENCE)
        teams.append(bound(team, record))
        ids[int(team.identity.external_id)] = record.id
    rounds = []
    for item in original.rounds:
        record = register(IdentityKind.ROUND, item.identity.external_id, stage.id, order=item.order)
        rounds.append(replace(bound(item, record), stage_id=stage.id))
    for row in fixtures["matches"]:
        register(IdentityKind.FIXTURE, str(row["id"]), season.id,
                 participants=(ids[row["homeTeam"]["id"]], ids[row["awayTeam"]["id"]]))
    empty = replace(original, competition=bound(original.competition, comp),
        season=replace(bound(original.season, season), competition_id=comp.id),
        stages=(replace(bound(original.stages[0], stage), season_id=season.id),),
        participants=tuple(teams), rounds=tuple(rounds))
    ledger = VersionLedger()
    context = bind_mapping_context(registry, empty, tuple(str(row["id"]) for row in fixtures["matches"]), ledger)
    return registry, ledger, context, metadata, fixtures, standings


def rebuild_tables(fixtures, standings):
    """Test oracle for result corrections, NEVER repair real provider input."""
    for view in standings["standings"]:
        for row in view["table"]:
            team = row["team"]["id"]
            totals = Counter()
            for fixture in fixtures["matches"]:
                home, away = fixture["homeTeam"]["id"], fixture["awayTeam"]["id"]
                if fixture["status"] != "FINISHED" or team not in (home, away):
                    continue
                if view["type"] == "HOME" and team != home or view["type"] == "AWAY" and team != away:
                    continue
                h, a = fixture["score"]["fullTime"]["home"], fixture["score"]["fullTime"]["away"]
                gf, ga = (h, a) if team == home else (a, h)
                totals.update({"playedGames": 1, "won": int(gf > ga), "draw": int(gf == ga),
                    "lost": int(gf < ga), "goalsFor": gf, "goalsAgainst": ga,
                    "points": 3 if gf > ga else int(gf == ga), "goalDifference": gf - ga})
            row.update({key: totals[key] for key in ("playedGames", "won", "draw", "lost",
                       "goalsFor", "goalsAgainst", "points", "goalDifference")})
    fixtures["resultSet"]["played"] = sum(row["status"] == "FINISHED" for row in fixtures["matches"])
