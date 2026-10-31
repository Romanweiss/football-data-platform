"""Bounded generated schedules, virtual clock and fake byte-page transport."""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.providers.collection import SyntheticPagedAdapter
from src.providers.models import (
    Availability, Capability, Competition, DataFreshness, EntityKind, Fixture, FixtureStatus,
    Participant, ProviderIdentity, Round, Score, Season, Snapshot, SourceCapability,
    Stage, StageType, StandingsEntry, TeamType,
)
from src.providers.reconciliation import PhaseRules

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
SCENARIOS = json.loads((Path(__file__).parent / "fixtures/provider_collection_scenarios.json").read_text(encoding="utf-8"))


class VirtualClock:
    def __init__(self, base=NOW):
        self.base, self.seconds, self.waits = base, 0.0, []

    def monotonic(self):
        return self.seconds

    def now(self):
        return self.base + timedelta(seconds=self.seconds)

    def wait(self, seconds):
        self.waits.append(seconds)
        self.seconds += seconds


def identity(kind, value):
    return ProviderIdentity("synthetic", EntityKind(kind), value)


def _schedule(count, games, national):
    """Circle-method rounds; Euler orientation balances club home/away counts."""
    rotation, edges = list(range(count)), []
    first_half = []
    for number in range(games):
        if national and number >= count - 1:
            pairs = [(away, home) for home, away in first_half[number - count + 1]]
        else:
            pairs = [(rotation[i], rotation[-1 - i]) for i in range(count // 2)]
            first_half.append(pairs)
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
        edges.extend((home, away, number) for home, away in pairs)
    if national:
        return edges
    adjacency = defaultdict(list)
    for index, (home, away, _) in enumerate(edges):
        adjacency[home].append((away, index))
        adjacency[away].append((home, index))
    visited, orientation = set(), {}
    for start in range(count):
        stack = [start]
        while stack:
            home = stack[-1]
            if not adjacency[home]:
                stack.pop()
                continue
            away, edge = adjacency[home].pop()
            if edge not in visited:
                visited.add(edge)
                orientation[edge] = (home, away)
                stack.append(away)
    return [(*orientation[index], edge[2]) for index, edge in enumerate(edges)]


def make_scenario(name="ucl"):
    spec = SCENARIOS[name]
    competition_id, season_id = "competition:test-" + name, "season:test-" + name
    team_type = TeamType.NATIONAL if spec["national"] else TeamType.CLUB
    competition = Competition(competition_id, identity("competition", name), "Synthetic " + name, team_type)
    season = Season(season_id, identity("season", "2026-" + name), competition_id, "2026/27", "synthetic-" + name + "-v1")
    stages, rounds, participants, fixtures, rules = [], [], [], [], []
    for group in range(spec["groups"]):
        tag = f"{name}-{group}"
        stage_id = "stage:" + tag
        stage = Stage(stage_id, identity("stage", tag), season_id, "Synthetic phase " + tag,
                      StageType.GROUP if spec["national"] else StageType.LEAGUE_PHASE,
                      chr(65 + group) if spec["national"] else None, "1" if spec["national"] else None)
        stages.append(stage)
        teams = [f"team:{tag}-{i}" for i in range(spec["teams_per_stage"])]
        participants.extend(Participant(team, identity("participant", team[5:]), "Invented club/team " + team, team_type) for team in teams)
        round_ids = [f"round:{tag}-{i}" for i in range(spec["matches_per_team"])]
        rounds.extend(Round(rid, identity("round", rid[6:]), stage_id, f"Synthetic round {i + 1}", i + 1)
                      for i, rid in enumerate(round_ids))
        for index, (home, away, number) in enumerate(_schedule(len(teams), spec["matches_per_team"], spec["national"])):
            finished = number < 2
            kickoff = NOW - timedelta(days=5 - number) if finished else NOW + timedelta(days=number + 1)
            score = Score((home + number) % 3, (away + number) % 2) if finished else Score()
            fid = f"fixture:{tag}-{index}"
            fixtures.append(Fixture(fid, identity("fixture", fid[8:]), season_id, stage_id, round_ids[number],
                                    teams[home], teams[away], kickoff, FixtureStatus.FINISHED if finished else FixtureStatus.SCHEDULED,
                                    score, 1, NOW - timedelta(hours=1)))
        rules.append(PhaseRules(stage_id, tuple(teams), spec["matches_per_team"], spec["home_games"], 2 if spec["national"] else 1))
    standings = table_from_fixtures(tuple(fixtures), tuple(rules))
    snapshot = Snapshot("synthetic", competition, season, tuple(stages), tuple(rounds), tuple(participants),
                        tuple(fixtures), standings, (),
                        tuple(SourceCapability(cap, Availability.VERIFIED) for cap in
                              (Capability.FIXTURES, Capability.RESULTS, Capability.STANDINGS)),
                        DataFreshness(NOW, NOW, NOW - timedelta(hours=1)), spec["partial"],
                        "Synthetic declared phase/group scope only; not actual UEFA data or a full competition season")
    return snapshot, tuple(rules)


def table_from_fixtures(fixtures, rules):
    """Independent fixture builder oracle; not the production reconciler."""
    entries = []
    for rule in rules:
        for index, team in enumerate(rule.participant_ids):
            games = [fixture for fixture in fixtures if fixture.stage_id == rule.stage_id and
                     fixture.status is FixtureStatus.FINISHED and team in (fixture.home_id, fixture.away_id)]
            scores = [(fixture.score.regulation_home, fixture.score.regulation_away) if fixture.home_id == team
                      else (fixture.score.regulation_away, fixture.score.regulation_home) for fixture in games]
            won = sum(home > away for home, away in scores)
            drawn = sum(home == away for home, away in scores)
            entries.append(StandingsEntry(rule.stage_id, team, index + 1, len(games), won, drawn,
                                          len(games) - won - drawn, sum(home for home, _ in scores),
                                          sum(away for _, away in scores), 3 * won + drawn))
    return tuple(entries)


class FakeAdapter(SyntheticPagedAdapter):
    def __init__(self, snapshot, *, rules, page_size=20, transform=None, describe_transform=None):
        super().__init__(snapshot, rules=rules, page_size=page_size)
        self.calls, self.description_count = [], 0
        self.transform, self.describe_transform = transform, describe_transform

    def describe(self, *, timeout_seconds):
        self.description_count += 1
        self.calls.append(("describe", None, timeout_seconds))
        return self.describe_transform(self, self.plan) if self.describe_transform else self.plan

    def fetch_page(self, resource, cursor, *, timeout_seconds):
        self.calls.append((resource.value, cursor, timeout_seconds))
        payload = super().fetch_page(resource, cursor, timeout_seconds=timeout_seconds)
        return self.transform(self, resource, cursor, payload) if self.transform else payload


def corrected(snapshot, rules):
    first = next(item for item in snapshot.fixtures if item.status is FixtureStatus.FINISHED)
    changed = replace(first, score=replace(first.score, regulation_home=first.score.regulation_home + 1),
                      revision=2, updated_at=NOW - timedelta(minutes=30))
    fixtures = tuple(changed if item.id == first.id else item for item in snapshot.fixtures)
    return replace(snapshot, fixtures=fixtures, standings=table_from_fixtures(fixtures, rules))
