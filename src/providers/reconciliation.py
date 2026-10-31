"""Pure fixture/table reconciliation using existing DQ rule/scalar contracts."""
from collections import Counter
from dataclasses import dataclass

from src.dq.model import Rule, scalar
from src.providers.models import FixtureStatus, Model, Snapshot, StageType, TeamType, identifier, require


@dataclass(frozen=True)
class PhaseRules(Model):
    stage_id: str
    participant_ids: tuple[str, ...]
    matches_per_team: int
    home_games: int
    meetings_per_opponent: int = 1
    schedule_complete: bool = True

    def __post_init__(self):
        super().__post_init__()
        require(2 <= len(self.participant_ids) <= 100 and len(set(self.participant_ids)) == len(self.participant_ids), "REFERENCE")
        for item in self.participant_ids:
            identifier(item)
        require(1 <= self.matches_per_team <= 50 and 0 <= self.home_games <= self.matches_per_team and
                self.meetings_per_opponent in (1, 2), "TYPE")
        require(len(self.participant_ids) * self.matches_per_team % 2 == 0, "TYPE")


@dataclass(frozen=True)
class Check(Model):
    rule_id: str
    category: str
    status: str
    observed: int | None
    expected: int | None

    def __post_init__(self):
        super().__post_init__()
        # Reuse the established DQ vocabulary without fabricating numeric
        # StatsBomb context IDs or invoking its database/history writers.
        Rule(self.rule_id, self.category, "operational", "current_collection", "Synthetic provider collection check")
        require(self.status in ("PASS", "FAIL", "WARN", "SKIP"), "TYPE")
        scalar(self.observed)
        scalar(self.expected)


def check(rule_id, passed, *, category="reconciliation", observed=None, expected=None):
    return Check(rule_id, category, "PASS" if passed else "FAIL", observed, expected)


def reconcile(snapshot: Snapshot, rules: tuple[PhaseRules, ...]) -> tuple[Check, ...]:
    """Compare counters, never claim independent verification of UEFA tie-breaks."""
    stages = {stage.id: stage for stage in snapshot.stages}
    participants = {item.id for item in snapshot.participants}
    rule_stages = [rule.stage_id for rule in rules]
    require(len(rule_stages) == len(set(rule_stages)), "DUPLICATE")
    results = []
    covered = {stage.id for stage in snapshot.stages if stage.kind in (StageType.LEAGUE_PHASE, StageType.GROUP)}
    results.append(check("provider.rules.coverage", set(rule_stages) == covered, category="structural"))
    structural_errors = 0
    counter_errors = 0
    adjustments = 0
    for rule in rules:
        require(rule.stage_id in stages and set(rule.participant_ids) <= participants, "REFERENCE")
        stage = stages[rule.stage_id]
        require(stage.kind in (StageType.LEAGUE_PHASE, StageType.GROUP), "STAGE_ROUND")
        if snapshot.competition.team_type is TeamType.NATIONAL:
            structural_errors += int(stage.kind is not StageType.GROUP or not stage.division or not stage.group)
        members = set(rule.participant_ids)
        fixtures = [item for item in snapshot.fixtures if item.stage_id == stage.id]
        rounds = {item.id for item in snapshot.rounds if item.stage_id == stage.id}
        structural_errors += int(len(rounds) != rule.matches_per_team)
        games, homes, pairs, directions, round_teams = Counter(), Counter(), Counter(), Counter(), Counter()
        totals = {team: [0] * 7 for team in members}  # P,W,D,L,GF,GA,points
        for fixture in fixtures:
            if fixture.home_id not in members or fixture.away_id not in members:
                structural_errors += 1
                continue
            games.update((fixture.home_id, fixture.away_id))
            homes[fixture.home_id] += 1
            pairs[tuple(sorted((fixture.home_id, fixture.away_id)))] += 1
            directions[(fixture.home_id, fixture.away_id)] += 1
            round_teams.update(((fixture.round_id, fixture.home_id), (fixture.round_id, fixture.away_id)))
            if fixture.status is not FixtureStatus.FINISHED:
                continue
            home, away = fixture.score.regulation_home, fixture.score.regulation_away
            for team, scored, conceded in ((fixture.home_id, home, away), (fixture.away_id, away, home)):
                row = totals[team]
                row[0] += 1
                row[1] += int(scored > conceded)
                row[2] += int(scored == conceded)
                row[3] += int(scored < conceded)
                row[4] += scored
                row[5] += conceded
                row[6] += 3 if scored > conceded else int(scored == conceded)
        structural_errors += sum(value > rule.meetings_per_opponent for value in pairs.values())
        if rule.meetings_per_opponent == 2:
            structural_errors += sum(value > 1 for value in directions.values())
        structural_errors += sum(value > 1 for value in round_teams.values())
        for team in members:
            if rule.schedule_complete:
                structural_errors += int(games[team] != rule.matches_per_team or homes[team] != rule.home_games)
            else:
                structural_errors += int(games[team] > rule.matches_per_team or homes[team] > rule.home_games)
        entries = {item.participant_id: item for item in snapshot.standings if item.stage_id == stage.id}
        structural_errors += int(set(entries) != members)
        for team, entry in entries.items():
            if team not in totals:
                continue
            expected = totals[team][:]
            expected[6] += entry.adjustment
            actual = [getattr(entry, name) for name in ("played", "won", "drawn", "lost", "goals_for", "goals_against", "points")]
            counter_errors += int(actual != expected)
            structural_errors += int(entry.rank > len(members))
            adjustments += int(entry.adjustment != 0)
    results.append(check("provider.schedule.structure", structural_errors == 0, category="structural", observed=structural_errors, expected=0))
    # Incomplete schedules cannot independently prove that ALL results underlying
    # a provider's table were included, even if a few counters happen to match.
    if any(not rule.schedule_complete for rule in rules):
        results.append(Check("provider.standings.counters", "reconciliation", "SKIP", None, None))
    else:
        results.append(check("provider.standings.counters", counter_errors == 0, observed=counter_errors, expected=0))
    results.append(Check("provider.standings.adjustments", "semantic", "WARN" if adjustments else "PASS", adjustments, 0))
    results.append(Check("provider.standings.tie_breakers", "semantic", "SKIP", None, None))
    return tuple(results)
