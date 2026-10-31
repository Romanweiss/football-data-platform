"""Pure parsing, context/revision DQ and deterministic normalization. No I/O."""
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from src.providers.models import (
    Availability, Capability, ContractError, FixtureStatus, Snapshot, StageType, require,
)

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ROWS = 2000


def _decode(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return None
        return _decode(next(arg for arg in args if arg is not type(None)), value)
    if origin is tuple:
        require(type(value) is list and len(value) <= MAX_ROWS, "LIMIT")
        return tuple(sorted((_decode(args[0], item) for item in value), key=lambda item: _json(primitive(item))))
    if annotation is datetime:
        require(type(value) is str and len(value) <= 40 and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value), "UTC")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if is_dataclass(annotation):
        require(type(value) is dict, "TYPE")
        declared = {field.name for field in fields(annotation)}
        require(not set(value) - declared, "TYPE")
        hints = get_type_hints(annotation)
        return annotation(**{key: _decode(hints[key], item) for key, item in value.items()})
    return value  # Model constructors enforce exact primitive types (no coercion).


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE")
        result[key] = value
    return result


def parse_snapshot(payload: bytes) -> Snapshot:
    require(type(payload) is bytes and len(payload) <= MAX_RESPONSE_BYTES, "LIMIT")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ContractError("TYPE")))
        snapshot = _decode(Snapshot, document)
        validate_snapshot(snapshot)
        return snapshot
    except ContractError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ContractError("MALFORMED") from None


def _unique(items, key):
    values = [key(item) for item in items]
    require(len(values) == len(set(values)), "DUPLICATE")


def validate_snapshot(snapshot: Snapshot) -> None:
    require(isinstance(snapshot, Snapshot), "TYPE")
    entities = (snapshot.competition, snapshot.season, *snapshot.stages, *snapshot.rounds,
                *snapshot.participants, *snapshot.ties, *snapshot.fixtures)
    require(all(len(getattr(snapshot, name)) <= MAX_ROWS for name in
                ("stages", "rounds", "participants", "ties", "fixtures", "standings", "capabilities")), "LIMIT")
    _unique(entities, lambda item: item.id)
    _unique(entities, lambda item: (item.identity.provider, item.identity.entity_kind, item.identity.external_id))
    require(all(item.identity.provider == snapshot.provider for item in entities), "SCOPE")
    require(snapshot.season.competition_id == snapshot.competition.id, "REFERENCE")
    require(bool(snapshot.stages), "REFERENCE")
    stages = {item.id: item for item in snapshot.stages}
    rounds = {item.id: item for item in snapshot.rounds}
    participants = {item.id: item for item in snapshot.participants}
    ties = {item.id: item for item in snapshot.ties}
    _unique(snapshot.rounds, lambda item: (item.stage_id, item.order))
    require(all(item.season_id == snapshot.season.id for item in snapshot.stages), "REFERENCE")
    require(all(item.stage_id in stages for item in snapshot.rounds), "REFERENCE")
    require(all(item.team_type == snapshot.competition.team_type for item in snapshot.participants), "REFERENCE")
    for tie in snapshot.ties:
        require(tie.stage_id in stages and stages[tie.stage_id].kind in (StageType.KNOCKOUT, StageType.QUALIFYING), "STAGE_ROUND")
        require(tie.participant_a_id in participants and tie.participant_b_id in participants, "REFERENCE")
    for fixture in snapshot.fixtures:
        require(fixture.season_id == snapshot.season.id and fixture.stage_id in stages, "SCOPE")
        require(fixture.round_id in rounds and rounds[fixture.round_id].stage_id == fixture.stage_id, "STAGE_ROUND")
        require(fixture.home_id in participants and fixture.away_id in participants, "REFERENCE")
        if fixture.kickoff is not None and fixture.status in (FixtureStatus.LIVE, FixtureStatus.FINISHED):
            require(fixture.kickoff <= snapshot.freshness.fetched_at, "FRESHNESS")
        knockout = stages[fixture.stage_id].kind in (StageType.KNOCKOUT, StageType.QUALIFYING)
        require(knockout or fixture.score.extra_home is None and fixture.score.penalties_home is None, "SCORE_STATUS")
        if fixture.tie_id is not None:
            require(fixture.tie_id in ties, "REFERENCE")
            tie = ties[fixture.tie_id]
            require(tie.stage_id == fixture.stage_id and fixture.leg <= tie.legs, "STAGE_ROUND")
            require({fixture.home_id, fixture.away_id} == {tie.participant_a_id, tie.participant_b_id}, "REFERENCE")
            # A shootout decides the tie on the last leg, not the first leg.
            require(fixture.score.penalties_home is None or fixture.leg == tie.legs, "SCORE_STATUS")
    _unique((item for item in snapshot.fixtures if item.tie_id is not None), lambda item: (item.tie_id, item.leg))
    for tie in snapshot.ties:
        legs = [item for item in snapshot.fixtures if item.tie_id == tie.id]
        if len(legs) == 2:
            require(legs[0].home_id == legs[1].away_id and legs[0].away_id == legs[1].home_id, "STAGE_ROUND")
        for leg in legs:
            require(leg.score.extra_home is None or leg.leg == tie.legs, "SCORE_STATUS")
            if leg.score.penalties_home is not None:
                require(len(legs) == tie.legs and all(f.status == FixtureStatus.FINISHED for f in legs), "SCORE_STATUS")
                totals = {tie.participant_a_id: 0, tie.participant_b_id: 0}
                for item in legs:
                    totals[item.home_id] += item.score.regulation_home + (item.score.extra_home or 0)
                    totals[item.away_id] += item.score.regulation_away + (item.score.extra_away or 0)
                require(len(set(totals.values())) == 1, "SCORE_STATUS")
    for fixture in snapshot.fixtures:
        if (stages[fixture.stage_id].kind in (StageType.KNOCKOUT, StageType.QUALIFYING)
                and fixture.tie_id is None and fixture.status == FixtureStatus.FINISHED):
            score = fixture.score
            tied = score.regulation_home + (score.extra_home or 0) == score.regulation_away + (score.extra_away or 0)
            require(tied == (score.penalties_home is not None), "SCORE_STATUS")
    _unique(snapshot.standings, lambda item: (item.stage_id, item.participant_id))
    for entry in snapshot.standings:
        require(entry.stage_id in stages and entry.participant_id in participants, "REFERENCE")
        require(stages[entry.stage_id].kind in (StageType.LEAGUE_PHASE, StageType.GROUP), "STAGE_ROUND")
    # Equal provisional ranks are valid; no points/GD re-sorting here.
    _unique(snapshot.capabilities, lambda item: item.name)
    capabilities = {item.name: item.availability for item in snapshot.capabilities}
    for name, present in ((Capability.FIXTURES, bool(snapshot.fixtures)),
                          (Capability.RESULTS, any(f.status == FixtureStatus.FINISHED for f in snapshot.fixtures)),
                          (Capability.STANDINGS, bool(snapshot.standings))):
        require(not present or capabilities.get(name) == Availability.VERIFIED, "CAPABILITY")
    require(all(item.updated_at <= snapshot.freshness.fetched_at for item in snapshot.fixtures), "FRESHNESS")


def primitive(value):
    if is_dataclass(value):
        return {field.name: primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        # All collections in this contract are sets of records, not positional
        # tuples. Reordering a provider response must not change content identity.
        return sorted((primitive(item) for item in value), key=_json)
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_bytes(snapshot: Snapshot) -> bytes:
    validate_snapshot(snapshot)
    return _json(primitive(snapshot)).encode("utf-8")


def content_digest(snapshot: Snapshot) -> str:
    """Semantic contract fingerprint, NOT an existing Silver/Gold build ID."""
    validate_snapshot(snapshot)
    document = primitive(snapshot)
    del document["freshness"]
    return sha256(_json(document).encode("utf-8")).hexdigest()


TRANSITIONS = {
    FixtureStatus.SCHEDULED: frozenset(("scheduled", "live", "finished", "postponed", "cancelled")),
    FixtureStatus.LIVE: frozenset(("live", "finished", "postponed", "cancelled")),
    FixtureStatus.FINISHED: frozenset(("finished",)),
    FixtureStatus.POSTPONED: frozenset(("postponed", "scheduled", "live", "finished", "cancelled")),
    FixtureStatus.CANCELLED: frozenset(("cancelled", "scheduled", "postponed")),
    FixtureStatus.UNKNOWN: frozenset(status.value for status in FixtureStatus),
}


def validate_update(previous: Snapshot, current: Snapshot) -> None:
    """Pure replay/correction gate; writes no state and publishes nothing."""
    validate_snapshot(previous)
    validate_snapshot(current)
    require((previous.provider, previous.competition, previous.season) ==
            (current.provider, current.competition, current.season), "SCOPE")
    require(current.freshness.fetched_at >= previous.freshness.fetched_at, "FRESHNESS")
    for collection in ("stages", "rounds", "participants", "ties"):
        before_entities = {item.id: item.identity for item in getattr(previous, collection)}
        after_entities = {item.id: item.identity for item in getattr(current, collection)}
        require(before_entities.keys() <= after_entities.keys(), "CONFLICT")
        require(all(after_entities[key] == identity for key, identity in before_entities.items()), "IDENTITY")
    old = {item.id: item for item in previous.fixtures}
    new = {item.id: item for item in current.fixtures}
    # A reduced/partial response is not a deletion instruction.
    require(old.keys() <= new.keys(), "CONFLICT")
    for fixture_id, before in old.items():
        after = new[fixture_id]
        require(before.identity == after.identity and before.home_id == after.home_id and
                before.away_id == after.away_id, "IDENTITY")
        require(after.status.value in TRANSITIONS[before.status], "TRANSITION")
        if after != before:
            require(after.revision > before.revision and after.updated_at >= before.updated_at, "REVISION")
