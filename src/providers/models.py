"""Immutable, runtime-validated football contracts; Python 3.10+, stdlib only.

The repository does not use Pydantic. These contracts deliberately introduce no
new dependency. Parsing rejects coercions, unknown fields and non-finite values.
"""
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints


class ContractError(ValueError):
    """Only a fixed diagnostic code escapes, never external values/payloads."""
    CODES = frozenset(("TYPE", "IDENTITY", "UTC", "REFERENCE", "DUPLICATE", "SCOPE",
                       "SCORE_STATUS", "STAGE_ROUND", "TRANSITION", "REVISION", "LIMIT",
                       "MALFORMED", "CAPABILITY", "FRESHNESS", "CONFLICT"))

    def __init__(self, code):
        self.code = code if type(code) is str and code in self.CODES else "MALFORMED"
        super().__init__("provider_contract:" + self.code)


class EntityKind(str, Enum):
    COMPETITION = "competition"
    SEASON = "season"
    STAGE = "stage"
    ROUND = "round"
    PARTICIPANT = "participant"
    FIXTURE = "fixture"
    TIE = "tie"


class TeamType(str, Enum):
    CLUB = "club"
    NATIONAL = "national"


class StageType(str, Enum):
    QUALIFYING = "qualifying"
    LEAGUE_PHASE = "league_phase"
    KNOCKOUT = "knockout"
    GROUP = "group"


class FixtureStatus(str, Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class Capability(str, Enum):
    FIXTURES = "fixtures"
    RESULTS = "results"
    STANDINGS = "standings"
    INCIDENTS = "incidents"
    LINEUPS = "lineups"
    MATCH_STATISTICS = "match_statistics"
    PLAYER_STATISTICS = "player_statistics"
    EVENT_COORDINATES = "event_coordinates"
    XG = "xg"


class Availability(str, Enum):
    VERIFIED = "verified"
    DECLARED = "declared"
    UNAVAILABLE = "unavailable"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


def require(condition, code):
    if not condition:
        raise ContractError(code)


def _matches(value, annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return any(_matches(value, option) for option in args)
    if origin is tuple:
        return type(value) is tuple and all(_matches(item, args[0]) for item in value)
    if annotation in (str, int, bool, datetime, type(None)):
        return type(value) is annotation
    return isinstance(value, annotation)


def identifier(value):
    # Explicit v1 grammar, not URL/path acceptance. Provider IDs are never cast
    # to numeric canonical IDs or derived from kickoff/team display names.
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value), "IDENTITY")


def _utc(value):
    require(value.tzinfo is not None and value.utcoffset() == timedelta(0), "UTC")


@dataclass(frozen=True)
class Model:
    def __post_init__(self):
        hints = get_type_hints(type(self))
        for field in fields(self):
            value = getattr(self, field.name)
            require(_matches(value, hints[field.name]), "TYPE")
            if isinstance(value, datetime):
                _utc(value)
            if isinstance(value, str):
                require(len(value) <= 240 and not any(ord(c) < 32 for c in value), "TYPE")
            if field.name == "id" or field.name.endswith("_id"):
                if value is not None:
                    identifier(value)
        _validate_model(self)


@dataclass(frozen=True)
class ProviderIdentity(Model):
    provider: str
    entity_kind: EntityKind
    external_id: str


@dataclass(frozen=True)
class Competition(Model):
    id: str
    identity: ProviderIdentity
    name: str
    team_type: TeamType


@dataclass(frozen=True)
class Season(Model):
    id: str
    identity: ProviderIdentity
    competition_id: str
    label: str
    format_version: str


@dataclass(frozen=True)
class Stage(Model):
    id: str
    identity: ProviderIdentity
    season_id: str
    name: str
    kind: StageType
    division: str | None = None
    group: str | None = None


@dataclass(frozen=True)
class Round(Model):
    id: str
    identity: ProviderIdentity
    stage_id: str
    name: str
    order: int


@dataclass(frozen=True)
class Participant(Model):
    id: str
    identity: ProviderIdentity
    name: str
    team_type: TeamType


@dataclass(frozen=True)
class Tie(Model):
    id: str
    identity: ProviderIdentity
    stage_id: str
    participant_a_id: str
    participant_b_id: str
    legs: int


@dataclass(frozen=True)
class Score(Model):
    regulation_home: int | None = None
    regulation_away: int | None = None
    # ADDITIONAL goals during extra time, not an inclusive 120-minute score.
    extra_home: int | None = None
    extra_away: int | None = None
    penalties_home: int | None = None
    penalties_away: int | None = None


@dataclass(frozen=True)
class Fixture(Model):
    id: str
    identity: ProviderIdentity
    season_id: str
    stage_id: str
    round_id: str
    home_id: str
    away_id: str
    kickoff: datetime | None
    status: FixtureStatus
    score: Score
    revision: int
    updated_at: datetime
    tie_id: str | None = None
    leg: int | None = None


@dataclass(frozen=True)
class StandingsEntry(Model):
    stage_id: str
    participant_id: str
    rank: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int
    adjustment: int = 0


@dataclass(frozen=True)
class SourceCapability(Model):
    name: Capability
    availability: Availability


@dataclass(frozen=True)
class DataFreshness(Model):
    fetched_at: datetime
    checked_at: datetime
    provider_updated_at: datetime | None = None
    published_at: datetime | None = None

    def is_stale(self, *, now: datetime, max_age_seconds: int) -> bool:
        require(type(now) is datetime, "TYPE")
        _utc(now)
        require(type(max_age_seconds) is int and max_age_seconds > 0 and now >= self.checked_at, "FRESHNESS")
        return (now - self.checked_at).total_seconds() > max_age_seconds


@dataclass(frozen=True)
class Snapshot(Model):
    provider: str
    competition: Competition
    season: Season
    stages: tuple[Stage, ...]
    rounds: tuple[Round, ...]
    participants: tuple[Participant, ...]
    fixtures: tuple[Fixture, ...]
    standings: tuple[StandingsEntry, ...]
    ties: tuple[Tie, ...]
    capabilities: tuple[SourceCapability, ...]
    freshness: DataFreshness
    partial: bool
    coverage_note: str
    schema_version: int = 1


def _validate_model(model):
    if isinstance(model, ProviderIdentity):
        require(re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", model.provider), "IDENTITY")
    if hasattr(model, "identity"):
        expected = type(model).__name__.lower()
        require(model.identity.entity_kind.value == expected, "IDENTITY")
    for name in ("name", "label", "format_version", "coverage_note"):
        if hasattr(model, name):
            require(bool(getattr(model, name).strip()), "TYPE")
    if isinstance(model, Round):
        require(0 < model.order <= 1000, "STAGE_ROUND")
    if isinstance(model, Tie):
        require(model.legs in (1, 2) and model.participant_a_id != model.participant_b_id, "REFERENCE")
    if isinstance(model, Score):
        for home, away in ((model.regulation_home, model.regulation_away),
                           (model.extra_home, model.extra_away), (model.penalties_home, model.penalties_away)):
            require((home is None) == (away is None), "SCORE_STATUS")
            require(home is None or 0 <= home <= 100 and 0 <= away <= 100, "SCORE_STATUS")
        require(model.extra_home is None or model.regulation_home is not None, "SCORE_STATUS")
        require(model.penalties_home is None or model.regulation_home is not None, "SCORE_STATUS")
    if isinstance(model, Fixture):
        require(model.home_id != model.away_id, "REFERENCE")
        require(0 < model.revision <= 2**31 - 1, "REVISION")
        require((model.tie_id is None) == (model.leg is None), "STAGE_ROUND")
        require(model.leg is None or model.leg in (1, 2), "STAGE_ROUND")
        empty = model.score == Score()
        if model.status in (FixtureStatus.SCHEDULED, FixtureStatus.POSTPONED, FixtureStatus.CANCELLED, FixtureStatus.UNKNOWN):
            require(empty, "SCORE_STATUS")
        if model.status is FixtureStatus.FINISHED:
            require(model.score.regulation_home is not None, "SCORE_STATUS")
            if model.score.penalties_home is not None:
                score = model.score
                require(score.regulation_home + (score.extra_home or 0) ==
                        score.regulation_away + (score.extra_away or 0) or model.tie_id is not None, "SCORE_STATUS")
                require(score.penalties_home != score.penalties_away, "SCORE_STATUS")
    if isinstance(model, StandingsEntry):
        require(0 < model.rank <= 1000 and 0 <= model.played <= 1000, "TYPE")
        require(all(0 <= getattr(model, name) <= 10000 for name in ("won", "drawn", "lost", "goals_for", "goals_against")), "TYPE")
        require(model.played == model.won + model.drawn + model.lost, "SCORE_STATUS")
        require(abs(model.adjustment) <= 1000 and model.points == 3 * model.won + model.drawn + model.adjustment, "SCORE_STATUS")
    if isinstance(model, DataFreshness):
        require(model.checked_at >= model.fetched_at, "FRESHNESS")
        require(model.provider_updated_at is None or model.provider_updated_at <= model.fetched_at, "FRESHNESS")
        require(model.published_at is None or model.published_at >= model.fetched_at, "FRESHNESS")
    if isinstance(model, Snapshot):
        require(model.schema_version == 1, "TYPE")
        require(re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", model.provider), "IDENTITY")
