"""Offline football-data.org mapping. No transport, storage or implicit identity allocation.

Only a configured 36-team/eight-round league phase is supported. Neutral fixture
revisions MUST be supplied by the caller: they are not vendor revisions. Unsupported
status/score combinations remain explicit records and prevent a candidate Snapshot.
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math

from src.providers.models import (
    Availability, Capability, ContractError, DataFreshness, EntityKind, Fixture, FixtureStatus,
    ProviderIdentity, Score, Snapshot, SourceCapability, StageType, StandingsEntry, TeamType, identifier,
)
from src.providers.reconciliation import Check, PhaseRules, check, reconcile
from src.providers.validation import (
    MAX_RESPONSE_BYTES, _decode, _json, _object, content_digest,
    primitive, validate_snapshot, validate_update,
)


class MappingError(ValueError):
    """Fixed codes only: no source values or original exception messages."""
    CODES = frozenset(("MALFORMED", "SCHEMA", "LIMIT", "IDENTITY", "SCOPE",
                       "DUPLICATE", "UTC", "CONTRACT", "DQ", "REVISION",
                       "SOURCE_CHANGED", "WINDOW", "UNSUPPORTED"))

    def __init__(self, code):
        self.code = code if type(code) is str and code in self.CODES else "SCHEMA"
        super().__init__("football_data_mapping:" + self.code)


def ensure(condition, code="SCHEMA"):
    if not condition:
        raise MappingError(code)


def decode_document(payload):
    ensure(type(payload) is bytes and 0 < len(payload) <= MAX_RESPONSE_BYTES, "LIMIT")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_object, parse_float=_finite_float,
                              parse_constant=lambda _: (_ for _ in ()).throw(MappingError("SCHEMA")))
        ensure(type(document) is dict)
        pending = [(document, 0)]
        while pending:
            value, depth = pending.pop()
            ensure(depth <= 32, "LIMIT")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return document
    except MappingError:
        raise
    except ContractError:
        raise MappingError("DUPLICATE") from None
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise MappingError("MALFORMED") from None


def _finite_float(value):
    parsed = float(value)
    ensure(math.isfinite(parsed))
    return parsed


def external_id(value):
    ensure(type(value) is int and 0 < value <= 2**63 - 1, "IDENTITY")
    return str(value)


def integer(value, minimum=0, maximum=10000):
    ensure(type(value) is int and minimum <= value <= maximum)
    return value


def text(value):
    ensure(type(value) is str and 0 < len(value) <= 240 and value.strip() and
           not any(ord(char) < 32 for char in value))
    return value


def utc(value):
    try:
        return _decode(datetime, value)
    except (ContractError, ValueError, TypeError, OverflowError):
        raise MappingError("UTC") from None


def utc_time(value):
    ensure(type(value) is datetime and value.tzinfo is not None and
           value.utcoffset() == timezone.utc.utcoffset(value), "UTC")
    return value


def obj(value):
    ensure(type(value) is dict)
    return value


def rows(value, maximum):
    ensure(type(value) is list and len(value) <= maximum, "LIMIT")
    ensure(all(type(item) is dict for item in value))
    return value


@dataclass(frozen=True)
class FixtureBinding:
    external_id: str
    canonical_id: str
    neutral_revision: int  # Explicit caller-owned version, NEVER source_revision.


@dataclass(frozen=True)
class MappingContext:
    empty_snapshot: Snapshot
    fixture_bindings: tuple[FixtureBinding, ...]

    def validate(self):
        snapshot = self.empty_snapshot
        validate_snapshot(snapshot)
        ensure(snapshot.provider == "football-data-org" and snapshot.partial and
               snapshot.competition.team_type is TeamType.CLUB and
               not snapshot.fixtures and not snapshot.standings and not snapshot.ties, "SCOPE")
        ensure(len(snapshot.stages) == 1 and snapshot.stages[0].kind is StageType.LEAGUE_PHASE and
               not snapshot.stages[0].division and not snapshot.stages[0].group, "SCOPE")
        ensure(len(snapshot.participants) == 36 and len(snapshot.rounds) == 8 and
               {item.order for item in snapshot.rounds} == set(range(1, 9)), "SCOPE")
        ensure(type(self.fixture_bindings) is tuple and len(self.fixture_bindings) == 144, "SCOPE")
        for binding in self.fixture_bindings:
            ensure(type(binding) is FixtureBinding)
            identifier(binding.canonical_id)
            ensure(type(binding.external_id) is str and 1 <= len(binding.external_id) <= 19 and binding.external_id.isascii() and
                   binding.external_id.isdigit() and 0 < int(binding.external_id) <= 2**63 - 1 and
                   str(int(binding.external_id)) == binding.external_id, "IDENTITY")
            integer(binding.neutral_revision, 1, 2**31 - 1)
        ensure(len({b.external_id for b in self.fixture_bindings}) == 144 and
               len({b.canonical_id for b in self.fixture_bindings}) == 144, "DUPLICATE")


@dataclass(frozen=True)
class UnsupportedFixture:
    external_id: str
    provider_status: str
    reason: str
    duration: str | None
    full_time: tuple[int | None, int | None] = field(repr=False)
    regular_time: tuple[int | None, int | None] | None = field(repr=False)
    extra_time: tuple[int | None, int | None] | None = field(repr=False)
    penalties: tuple[int | None, int | None] | None = field(repr=False)


@dataclass(frozen=True)
class TableView:
    kind: str
    entries: tuple[StandingsEntry, ...]


@dataclass(frozen=True)
class MappingResult:
    snapshot: Snapshot | None
    unsupported: tuple[UnsupportedFixture, ...]
    tables: tuple[TableView, ...]
    checks: tuple[Check, ...]
    semantic_digest: str | None
    synthetic_only_statuses: tuple[str, ...]
    revision_origin: str = "CALLER_SUPPLIED_NEUTRAL_VERSION_NOT_PROVIDER_REVISION"

    @property
    def ready_for_offline_use(self):
        return self.snapshot is not None and self.semantic_digest is not None and not any(
            item.status == "FAIL" for item in self.checks)


STATUS_MAP = {
    "TIMED": FixtureStatus.SCHEDULED, "FINISHED": FixtureStatus.FINISHED,
    # Conventional mappings exercised ONLY with synthetic data in this stage.
    "SCHEDULED": FixtureStatus.SCHEDULED, "IN_PLAY": FixtureStatus.LIVE,
    "POSTPONED": FixtureStatus.POSTPONED, "CANCELLED": FixtureStatus.CANCELLED,
}
LIVE_VERIFIED_STATUSES = frozenset(("TIMED", "FINISHED"))
TABLE_KINDS = frozenset(("TOTAL", "HOME", "AWAY"))


def _pair(score, key, required=False):
    if key not in score or score[key] is None:
        ensure(not required)
        return None
    value = obj(score[key])
    ensure("home" in value and "away" in value)
    home, away = value["home"], value["away"]
    ensure((home is None) == (away is None))
    if home is not None:
        integer(home, 0, 100)
        integer(away, 0, 100)
    return home, away


def _fixture_score(row):
    score = obj(row.get("score"))
    full = _pair(score, "fullTime", required=True)
    pairs = tuple(_pair(score, key) for key in ("regularTime", "extraTime", "penalties"))
    duration = score.get("duration")
    if duration is not None:
        text(duration)
    status = text(row.get("status"))
    reason = None
    if status not in STATUS_MAP:
        reason = "UNSUPPORTED_STATUS"
    elif duration != "REGULAR" or any(pair is not None and pair != (None, None) for pair in pairs):
        reason = "UNVERIFIED_SCORE_SEMANTICS"
    elif STATUS_MAP[status] not in (FixtureStatus.LIVE, FixtureStatus.FINISHED) and full != (None, None):
        reason = "RETAINED_SCORE_REQUIRES_STATUS_EXTENSION"
    elif status == "FINISHED" and full == (None, None):
        reason = "MISSING_FINISHED_SCORE"
    if reason:
        return UnsupportedFixture(external_id(row.get("id")), status, reason, duration, full, *pairs)
    return Score(*full)


def _scope(document, context):
    competition = obj(document.get("competition"))
    ensure(external_id(competition.get("id")) == context.competition.identity.external_id, "SCOPE")


def _team(value, participants, names):
    team = obj(value)
    key = external_id(team.get("id"))
    ensure(key in participants, "SCOPE")
    name = text(team.get("name"))
    ensure(key not in names or names[key] == name, "IDENTITY")
    names[key] = name
    return participants[key]


def _tables(document, base, participants, names):
    _scope(document, base)
    ensure(external_id(obj(document.get("season")).get("id")) == base.season.identity.external_id, "SCOPE")
    views = {}
    for table in rows(document.get("standings"), 3):
        kind = table.get("type")
        ensure(type(kind) is str and kind in TABLE_KINDS, "UNSUPPORTED")
        ensure(kind not in views, "DUPLICATE")
        ensure(table.get("stage") == "LEAGUE_STAGE" and table.get("group") is None, "SCOPE")
        entries = []
        seen = set()
        for row in rows(table.get("table"), 36):
            team = _team(row.get("team"), participants, names)
            ensure(team.id not in seen, "DUPLICATE")
            seen.add(team.id)
            gf, ga = integer(row.get("goalsFor")), integer(row.get("goalsAgainst"))
            ensure(integer(row.get("goalDifference"), -10000) == gf - ga, "DQ")
            try:
                entries.append(StandingsEntry(base.stages[0].id, team.id,
                    integer(row.get("position"), 1, 36), integer(row.get("playedGames"), 0, 8),
                    integer(row.get("won"), 0, 8), integer(row.get("draw"), 0, 8),
                    integer(row.get("lost"), 0, 8), gf, ga, integer(row.get("points"))))
            except ContractError:
                # No inferred deduction/adjustment to force provider points to fit.
                raise MappingError("DQ") from None
        ensure(seen == {item.id for item in participants.values()}, "DQ")
        views[kind] = TableView(kind, tuple(sorted(entries, key=lambda item: item.participant_id)))
    ensure("TOTAL" in views, "DQ")
    return tuple(views[key] for key in sorted(views))


def _view_checks(snapshot, tables):
    checks = []
    for kind in ("HOME", "AWAY"):
        view = next((item for item in tables if item.kind == kind), None)
        if view is None:
            checks.append(Check("football_data.standings." + kind.lower(), "reconciliation", "SKIP", None, None))
            continue
        totals = {team.id: [0] * 7 for team in snapshot.participants}
        for fixture in snapshot.fixtures:
            if fixture.status is not FixtureStatus.FINISHED:
                continue
            home, away = fixture.score.regulation_home, fixture.score.regulation_away
            team, gf, ga = (fixture.home_id, home, away) if kind == "HOME" else (fixture.away_id, away, home)
            values = totals[team]
            values[0] += 1
            values[1] += int(gf > ga)
            values[2] += int(gf == ga)
            values[3] += int(gf < ga)
            values[4] += gf
            values[5] += ga
            values[6] += 3 if gf > ga else int(gf == ga)
        mismatches = sum([getattr(entry, field) for field in
            ("played", "won", "drawn", "lost", "goals_for", "goals_against", "points")] != totals[entry.participant_id]
            for entry in view.entries)
        checks.append(check("football_data.standings." + kind.lower(), mismatches == 0, observed=mismatches, expected=0))
    return tuple(checks)


def _map(metadata, fixtures, standings, context, fetched_at, previous):
    context.validate()
    utc_time(fetched_at)
    base = context.empty_snapshot
    ensure(external_id(metadata.get("id")) == base.competition.identity.external_id, "SCOPE")
    ensure(metadata.get("type") == "CUP", "UNSUPPORTED")
    season = obj(metadata.get("currentSeason"))
    ensure(external_id(season.get("id")) == base.season.identity.external_id, "SCOPE")
    ensure(date.fromisoformat(season["startDate"]) <= date.fromisoformat(season["endDate"]), "SCHEMA")
    if metadata.get("lastUpdated") is not None:
        ensure(utc(metadata["lastUpdated"]) <= fetched_at, "UTC")
    for document in (metadata, fixtures, standings):
        ensure(not any(key in document for key in ("pagination", "next", "nextCursor", "total")), "UNSUPPORTED")
    _scope(fixtures, base)
    participants = {item.identity.external_id: item for item in base.participants}
    ensure(len(participants) == 36, "IDENTITY")
    bindings = {binding.external_id: binding for binding in context.fixture_bindings}
    rounds = {item.order: item for item in base.rounds}
    names, mapped, unsupported, seen, synthetic_statuses = {}, [], [], set(), set()
    source = rows(fixtures.get("matches"), 144)
    ensure(len(source) == 144 and type(obj(fixtures.get("resultSet")).get("count")) is int and
           fixtures["resultSet"]["count"] == len(source), "DQ")
    for row in source:
        key = external_id(row.get("id"))
        ensure(key not in seen, "DUPLICATE")
        seen.add(key)
        ensure(key in bindings, "IDENTITY")
        _scope(row, base)
        ensure(external_id(obj(row.get("season")).get("id")) == base.season.identity.external_id, "SCOPE")
        ensure(row.get("stage") == "LEAGUE_STAGE" and row.get("group") is None, "UNSUPPORTED")
        round_item = rounds[integer(row.get("matchday"), 1, 8)]
        home, away = (_team(row.get(key), participants, names) for key in ("homeTeam", "awayTeam"))
        ensure(home.id != away.id, "IDENTITY")
        status = text(row.get("status"))
        if status not in LIVE_VERIFIED_STATUSES:
            synthetic_statuses.add(status)
        kickoff = utc(row["utcDate"]) if row.get("utcDate") is not None else None
        updated = utc(row.get("lastUpdated"))
        ensure(updated <= fetched_at and (status not in ("FINISHED", "IN_PLAY") or
               kickoff is None or kickoff <= fetched_at), "UTC")
        score = _fixture_score(row)
        if isinstance(score, UnsupportedFixture):
            unsupported.append(score)
            continue
        binding = bindings[key]
        mapped.append(Fixture(binding.canonical_id, ProviderIdentity(base.provider, EntityKind.FIXTURE, key),
            base.season.id, base.stages[0].id, round_item.id, home.id, away.id, kickoff,
            STATUS_MAP[status], score, binding.neutral_revision, updated))
    ensure(seen == set(bindings), "IDENTITY")
    played = fixtures["resultSet"].get("played")
    if played is not None:
        ensure(type(played) is int and played == sum(row.get("status") == "FINISHED" for row in source), "DQ")
    tables = _tables(standings, base, participants, names)
    checks = (check("football_data.mapping.supported", not unsupported,
                    category="semantic", observed=len(unsupported), expected=0),)
    if unsupported:
        return MappingResult(None, tuple(sorted(unsupported, key=lambda item: item.external_id)),
                             tables, checks, None, tuple(sorted(synthetic_statuses)))
    snapshot = replace(base, competition=replace(base.competition, name=text(metadata.get("name"))),
        participants=tuple(sorted((replace(item, name=names[key]) for key, item in participants.items()), key=lambda item: item.id)),
        fixtures=tuple(sorted(mapped, key=lambda item: item.id)),
        standings=next(table.entries for table in tables if table.kind == "TOTAL"),
        capabilities=tuple(SourceCapability(cap, Availability.UNKNOWN if cap is Capability.RESULTS and
                           not any(f.status is FixtureStatus.FINISHED for f in mapped) else Availability.VERIFIED)
                           for cap in (Capability.FIXTURES, Capability.RESULTS, Capability.STANDINGS)),
        freshness=DataFreshness(fetched_at, fetched_at))
    validate_snapshot(snapshot)
    rules = (PhaseRules(base.stages[0].id, tuple(sorted(team.id for team in participants.values())), 8, 4),)
    checks += reconcile(snapshot, rules) + _view_checks(snapshot, tables)
    checks += (Check("football_data.points_adjustment_authority", "semantic", "SKIP", None, None),)
    if previous is not None:
        try:
            validate_update(previous, snapshot)
        except ContractError:
            raise MappingError("REVISION") from None
    valid = not any(item.status == "FAIL" for item in checks)
    digest = sha256(_json({"snapshot": content_digest(snapshot),
                           "tables": primitive(tables)}).encode("utf-8")).hexdigest() if valid else None
    return MappingResult(snapshot if valid else None, (), tables, checks, digest, tuple(sorted(synthetic_statuses)))


def map_responses(metadata: bytes, fixtures: bytes, standings: bytes, *, context: MappingContext,
                  fetched_at: datetime, previous: Snapshot | None = None) -> MappingResult:
    """Pure bounded mapping. Caller supplies canonical IDs and neutral versions.

    No automatic revision allocation, provider registration, persistence or HTTP.
    Unsupported records and failed DQ never yield a candidate Snapshot/digest.
    """
    try:
        ensure(type(context) is MappingContext)
        return _map(decode_document(metadata), decode_document(fixtures), decode_document(standings),
                    context, fetched_at, previous)
    except MappingError:
        raise
    except ContractError:
        raise MappingError("CONTRACT") from None
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError):
        raise MappingError("SCHEMA") from None
