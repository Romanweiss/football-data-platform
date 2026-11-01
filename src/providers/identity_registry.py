"""Deterministic, confirmed identity bindings in memory only. No storage/transport.

IDs are provider-namespaced, never StatsBomb IDs or fuzzy name/date matches.
Fixture external IDs are provider-global: a different season/team pairing is a
conflict, not reassignment. Season/stage/round/tie keys have explicit parent scope.
"""
from dataclasses import dataclass, fields
from enum import Enum
from hashlib import sha256
import json
import re

from src.providers.models import ContractError, StageType, TeamType, identifier
from src.providers.validation import _json, _object

MAX_STATE_BYTES = 1024 * 1024
MAX_RECORDS = 2000


class RegistryError(ValueError):
    CODES = frozenset(("UNCONFIRMED", "IDENTITY", "CONFLICT", "REFERENCE", "SCOPE",
        "DUPLICATE", "MALFORMED", "LIMIT", "VERSION_CONFLICT", "OUT_OF_ORDER",
        "REVERSION_REQUIRES_REVIEW", "UNSUPPORTED", "DQ", "UTC"))

    def __init__(self, code):
        self.code = code if type(code) is str and code in self.CODES else "MALFORMED"
        super().__init__("provider_registry:" + self.code)


def guard(condition, code="MALFORMED"):
    if not condition:
        raise RegistryError(code)


def checked_id(value):
    try:
        identifier(value)
    except ContractError:
        raise RegistryError("IDENTITY") from None
    return value


def digest(document):
    return sha256(_json(document).encode("utf-8")).hexdigest()


def decode_state(payload, domain):
    guard(type(payload) is bytes and 0 < len(payload) <= MAX_STATE_BYTES, "LIMIT")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(RegistryError("MALFORMED")))
        guard(type(document) is dict and document.get("domain") == domain and
              type(document.get("schema_version")) is int and document["schema_version"] == 1)
        return document
    except RegistryError:
        raise
    except (ContractError, ValueError, TypeError, RecursionError, OverflowError):
        raise RegistryError("MALFORMED") from None


class IdentityKind(str, Enum):
    PROVIDER = "provider"
    COMPETITION = "competition"
    SEASON = "season"
    PARTICIPANT = "participant"
    STAGE = "stage"
    ROUND = "round"
    FIXTURE = "fixture"
    TIE = "tie"


@dataclass(frozen=True)
class IdentityEvidence:
    confirmed: bool
    reference: str  # Bounded reviewed evidence label, not a URL/token/raw payload.


@dataclass(frozen=True)
class IdentityRecord:
    id: str
    provider: str
    kind: IdentityKind
    external_id: str
    parent_id: str | None
    team_type: TeamType | None
    stage_kind: StageType | None
    participants: tuple[str, ...]
    order: int | None
    legs: int | None
    evidence_reference: str


@dataclass(frozen=True)
class Participation:
    season_id: str
    participant_id: str
    evidence_reference: str


SCOPED = frozenset((IdentityKind.SEASON, IdentityKind.STAGE, IdentityKind.ROUND, IdentityKind.TIE))
PARENT_KIND = {
    IdentityKind.COMPETITION: IdentityKind.PROVIDER, IdentityKind.PARTICIPANT: IdentityKind.PROVIDER,
    IdentityKind.SEASON: IdentityKind.COMPETITION, IdentityKind.STAGE: IdentityKind.SEASON,
    IdentityKind.ROUND: IdentityKind.STAGE, IdentityKind.FIXTURE: IdentityKind.SEASON,
    IdentityKind.TIE: IdentityKind.STAGE,
}


def identity_key(provider, kind, external_id, parent_id):
    return provider, kind.value, external_id, parent_id if kind in SCOPED else None


def record_document(record):
    # participants is positional for fixtures (home, away), NOT a generic set.
    return {"id": record.id, "provider": record.provider, "kind": record.kind.value,
        "external_id": record.external_id, "parent_id": record.parent_id,
        "team_type": record.team_type.value if record.team_type is not None else None,
        "stage_kind": record.stage_kind.value if record.stage_kind is not None else None,
        "participants": list(record.participants), "order": record.order, "legs": record.legs,
        "evidence_reference": record.evidence_reference}


class IdentityRegistry:
    """Serial, in-memory owner. Successful inserts only; no name-based matching."""
    def __init__(self):
        self._records = {}
        self._keys = {}
        self._participations = {}

    @property
    def records(self):
        return tuple(sorted(self._records.values(), key=lambda item: item.id))

    @property
    def participations(self):
        return tuple(self._participations[key] for key in sorted(self._participations))

    def get(self, canonical_id):
        checked_id(canonical_id)
        guard(canonical_id in self._records, "REFERENCE")
        return self._records[canonical_id]

    def lookup(self, provider, kind, external_id, *, parent_id=None):
        self._validate_key(provider, kind, external_id)
        if kind in SCOPED:
            guard(parent_id is not None, "SCOPE")
        if parent_id is not None:
            checked_id(parent_id)
        key = identity_key(provider, kind, external_id, parent_id)
        guard(key in self._keys, "REFERENCE")
        record = self.get(self._keys[key])
        if parent_id is not None:
            guard(record.parent_id == parent_id, "CONFLICT")
        return record

    @staticmethod
    def _validate_key(provider, kind, external_id):
        guard(type(provider) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", provider), "IDENTITY")
        guard(type(kind) is IdentityKind, "IDENTITY")
        checked_id(external_id)

    @staticmethod
    def _evidence(evidence):
        guard(type(evidence) is IdentityEvidence and type(evidence.confirmed) is bool and evidence.confirmed, "UNCONFIRMED")
        checked_id(evidence.reference)

    def register(self, provider, kind, external_id, *, evidence, parent_id=None,
                 team_type=None, stage_kind=None, participants=(), order=None, legs=None):
        self._validate_key(provider, kind, external_id)
        self._evidence(evidence)
        guard(type(participants) is tuple and len(participants) <= 2, "IDENTITY")
        guard(team_type is None or type(team_type) is TeamType, "IDENTITY")
        guard(stage_kind is None or type(stage_kind) is StageType, "IDENTITY")
        if kind is IdentityKind.PROVIDER:
            guard(parent_id is None and external_id == provider, "SCOPE")
        else:
            parent = self.get(parent_id)
            guard(parent.kind is PARENT_KIND[kind] and parent.provider == provider, "SCOPE")
        guard((team_type is not None) == (kind in (IdentityKind.COMPETITION, IdentityKind.PARTICIPANT)), "IDENTITY")
        guard((stage_kind is not None) == (kind is IdentityKind.STAGE), "IDENTITY")
        guard((type(order) is int and 1 <= order <= 1000) if kind is IdentityKind.ROUND else order is None, "IDENTITY")
        guard((type(legs) is int and legs in (1, 2)) if kind is IdentityKind.TIE else legs is None, "IDENTITY")
        if kind in (IdentityKind.FIXTURE, IdentityKind.TIE):
            guard(len(participants) == 2 and participants[0] != participants[1], "IDENTITY")
            for participant in participants:
                checked_id(participant)
            season = parent if kind is IdentityKind.FIXTURE else self.get(parent.parent_id)
            if kind is IdentityKind.TIE:
                guard(parent.stage_kind in (StageType.KNOCKOUT, StageType.QUALIFYING), "SCOPE")
                participants = tuple(sorted(participants))
            for participant in participants:
                record = self.get(participant)
                guard(record.kind is IdentityKind.PARTICIPANT and record.provider == provider, "SCOPE")
                guard((season.id, participant) in self._participations, "UNCONFIRMED")
        else:
            guard(not participants, "IDENTITY")
        key = identity_key(provider, kind, external_id, parent_id)
        canonical_id = "uefa:" + kind.value + ":" + digest({"domain": "football-platform-identity-v1", "key": key})
        record = IdentityRecord(canonical_id, provider, kind, external_id, parent_id, team_type,
                                stage_kind, participants, order, legs, evidence.reference)
        if key in self._keys:
            old = self.get(self._keys[key])
            # A repeated reviewed binding may cite new evidence; retain the first
            # reference without changing identity or duplicating the record.
            guard(record_document(old) == record_document(IdentityRecord(
                canonical_id, provider, kind, external_id, parent_id, team_type, stage_kind,
                participants, order, legs, old.evidence_reference)), "CONFLICT")
            return old
        guard(len(self._records) < MAX_RECORDS, "LIMIT")
        guard(canonical_id not in self._records, "CONFLICT")
        if kind is IdentityKind.ROUND:
            guard(not any(r.kind is IdentityKind.ROUND and r.parent_id == parent_id and r.order == order
                          for r in self._records.values()), "CONFLICT")
        self._records[canonical_id] = record
        self._keys[key] = canonical_id
        return record

    def confirm_participation(self, season_id, participant_id, *, evidence):
        self._evidence(evidence)
        season, participant = self.get(season_id), self.get(participant_id)
        guard(season.kind is IdentityKind.SEASON and participant.kind is IdentityKind.PARTICIPANT and
              season.provider == participant.provider, "SCOPE")
        competition = self.get(season.parent_id)
        guard(competition.team_type is participant.team_type, "CONFLICT")
        key = season_id, participant_id
        if key not in self._participations:
            guard(len(self._participations) < 3000, "LIMIT")
            self._participations[key] = Participation(*key, evidence.reference)
        return self._participations[key]

    def has_participation(self, season_id, participant_id):
        return (season_id, participant_id) in self._participations

    def to_bytes(self):
        document = {"domain": "offline-identity-registry", "schema_version": 1,
            "records": [record_document(record) for record in self.records],
            "participations": [vars(item) for item in self.participations]}
        payload = _json(document).encode("utf-8")
        guard(len(payload) <= MAX_STATE_BYTES, "LIMIT")
        return payload

    @classmethod
    def from_bytes(cls, payload, *, expected_fingerprint=None):
        guard(type(payload) is bytes and 0 < len(payload) <= MAX_STATE_BYTES, "LIMIT")
        if expected_fingerprint is not None:
            guard(type(expected_fingerprint) is str and re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint), "MALFORMED")
            guard(type(payload) is bytes and sha256(payload).hexdigest() == expected_fingerprint, "CONFLICT")
        document = decode_state(payload, "offline-identity-registry")
        try:
            guard(set(document) == {"domain", "schema_version", "records", "participations"})
            raw, memberships = document["records"], document["participations"]
            guard(type(raw) is list and len(raw) <= MAX_RECORDS and
                  type(memberships) is list and len(memberships) <= 3000, "LIMIT")
            result = cls()
            seen = set()
            # Explicit topological order; serialized record order is immaterial.
            for kind in IdentityKind:
                if kind is IdentityKind.FIXTURE:
                    for item in memberships:
                        guard(type(item) is dict and set(item) == {"season_id", "participant_id", "evidence_reference"})
                        pair = item["season_id"], item["participant_id"]
                        guard(pair not in seen, "DUPLICATE")
                        seen.add(pair)
                        result.confirm_participation(*pair, evidence=IdentityEvidence(True, item["evidence_reference"]))
                for item in raw:
                    guard(type(item) is dict and set(item) == {f.name for f in fields(IdentityRecord)})
                    guard(item["kind"] in {k.value for k in IdentityKind})
                    if item["kind"] != kind.value:
                        continue
                    guard(type(item["participants"]) is list)
                    record = result.register(item["provider"], kind, item["external_id"],
                        evidence=IdentityEvidence(True, item["evidence_reference"]), parent_id=item["parent_id"],
                        team_type=TeamType(item["team_type"]) if item["team_type"] is not None else None,
                        stage_kind=StageType(item["stage_kind"]) if item["stage_kind"] is not None else None,
                        participants=tuple(item["participants"]), order=item["order"], legs=item["legs"])
                    guard(record.id == item["id"], "CONFLICT")
            guard(len(result.records) == len(raw), "DUPLICATE")
            return result
        except RegistryError:
            raise
        except (ContractError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
            raise RegistryError("MALFORMED") from None
