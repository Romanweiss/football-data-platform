"""Local content history, NOT an authoritative provider revision or clock token."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import re

from src.providers.identity_registry import RegistryError, checked_id, decode_state, digest, guard
from src.providers.models import Fixture, StandingsEntry
from src.providers.validation import _decode, _json, primitive


class StreamKind(str, Enum):
    FIXTURE = "fixture"
    METADATA = "metadata"
    TOTAL = "standings_total"
    HOME = "standings_home"
    AWAY = "standings_away"


@dataclass(frozen=True)
class StreamRef:
    entity_id: str
    kind: StreamKind


@dataclass(frozen=True)
class ProviderRevisionEvidence:
    token: str
    confirmed: bool
    sequence: int | None = None  # Only a confirmed monotonic PROVIDER counter.


@dataclass(frozen=True)
class ContentVersion:
    number: int
    semantic_digest: str
    first_seen_at: datetime


@dataclass(frozen=True)
class ProviderBinding:
    token: str
    sequence: int | None
    semantic_digest: str


@dataclass(frozen=True)
class StreamState:
    ref: StreamRef
    versions: tuple[ContentVersion, ...]
    last_observed_at: datetime
    provider_bindings: tuple[ProviderBinding, ...]
    source_updated_at: datetime | None


@dataclass(frozen=True)
class VersionReceipt:
    ref: StreamRef
    local_content_version: int
    semantic_digest: str
    observed_at: datetime
    changed: bool
    provider_revision: str | None
    source_updated_at: datetime | None


def utc_observation(value):
    guard(type(value) is datetime and value.tzinfo is not None and value.utcoffset() == timedelta(0), "UTC")
    return value


def checked_digest(value):
    guard(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "MALFORMED")
    return value


def fixture_fingerprint(fixture):
    guard(type(fixture) is Fixture)
    data = primitive(fixture)
    # A refreshed source timestamp alone is not a new football content version.
    del data["revision"], data["updated_at"]
    return digest({"domain": "fixture-semantic-v1", "content": data})


def standings_fingerprint(kind, entries):
    guard(type(kind) is StreamKind and kind in (StreamKind.TOTAL, StreamKind.HOME, StreamKind.AWAY))
    guard(type(entries) is tuple and len(entries) <= 2000 and all(type(e) is StandingsEntry for e in entries))
    return digest({"domain": "standings-semantic-v1", "kind": kind.value, "entries": primitive(entries)})


class VersionLedger:
    """Serial in-memory history with optimistic version checks and bounded size.

    No wall clock, provider IO, auto-publication or persistent version allocation.
    Reverts to earlier content require review rather than trusting a newer clock.
    """
    def __init__(self):
        self._streams = {}

    @property
    def streams(self):
        return tuple(sorted(self._streams.values(), key=lambda s: (s.ref.entity_id, s.ref.kind.value)))

    def current(self, ref):
        guard(type(ref) is StreamRef and type(ref.kind) is StreamKind)
        checked_id(ref.entity_id)
        return self._streams.get(ref)

    def version(self, ref):
        current = self.current(ref)
        return current.versions[-1].number if current is not None else 0

    def observe(self, ref, semantic_digest, *, observed_at, expected_version, provider_revision=None,
                source_updated_at=None):
        current = self.current(ref)
        checked_digest(semantic_digest)
        utc_observation(observed_at)
        number = current.versions[-1].number if current is not None else 0
        guard(type(expected_version) is int and expected_version == number, "VERSION_CONFLICT")
        versions = list(current.versions) if current else []
        bindings = list(current.provider_bindings) if current else []
        if current:
            guard(observed_at >= current.last_observed_at, "OUT_OF_ORDER")
        if source_updated_at is not None:
            utc_observation(source_updated_at)
            guard(source_updated_at <= observed_at, "UTC")
        if current and current.source_updated_at is not None:
            guard(source_updated_at is not None, "UNCONFIRMED")
            guard(source_updated_at >= current.source_updated_at, "OUT_OF_ORDER")
        changed = not current or versions[-1].semantic_digest != semantic_digest
        if changed and current:
            guard(observed_at > current.last_observed_at, "VERSION_CONFLICT")
            guard(semantic_digest not in {v.semantic_digest for v in versions}, "REVERSION_REQUIRES_REVIEW")
        if provider_revision is not None:
            guard(type(provider_revision) is ProviderRevisionEvidence and
                  type(provider_revision.confirmed) is bool and provider_revision.confirmed, "UNCONFIRMED")
            checked_id(provider_revision.token)
            sequence = provider_revision.sequence
            guard(sequence is None or type(sequence) is int and 0 < sequence <= 2**63 - 1, "VERSION_CONFLICT")
            existing = next((b for b in bindings if b.token == provider_revision.token), None)
            if existing:
                guard(existing.semantic_digest == semantic_digest and existing.sequence == sequence, "VERSION_CONFLICT")
            counters = [b.sequence for b in bindings if b.sequence is not None]
            if counters:
                guard(sequence is not None, "UNCONFIRMED")
                guard(sequence >= max(counters), "OUT_OF_ORDER")
                guard(existing is not None or sequence > max(counters), "VERSION_CONFLICT")
            if not existing:
                guard(len(bindings) < 128, "LIMIT")
                bindings.append(ProviderBinding(provider_revision.token, sequence, semantic_digest))
        else:
            guard(not bindings, "UNCONFIRMED")  # Never silently drop a known provider fence.
        if changed:
            guard(len(versions) < 32, "LIMIT")
            versions.append(ContentVersion(number + 1, semantic_digest, observed_at))
        guard(current is not None or len(self._streams) < 2000, "LIMIT")
        self._streams[ref] = StreamState(ref, tuple(versions), observed_at, tuple(bindings), source_updated_at)
        return VersionReceipt(ref, versions[-1].number, semantic_digest, observed_at, changed,
                              provider_revision.token if provider_revision else None, source_updated_at)

    def to_bytes(self):
        states = []
        for state in self.streams:
            states.append({"ref": {"entity_id": state.ref.entity_id, "kind": state.ref.kind.value},
                "versions": [{"number": v.number, "semantic_digest": v.semantic_digest,
                              "first_seen_at": v.first_seen_at.isoformat()} for v in state.versions],
                "last_observed_at": state.last_observed_at.isoformat(),
                "source_updated_at": state.source_updated_at.isoformat() if state.source_updated_at is not None else None,
                "provider_bindings": [vars(binding) for binding in state.provider_bindings]})
        payload = _json({"domain": "offline-content-versions", "schema_version": 1, "streams": states}).encode("utf-8")
        guard(len(payload) <= 1024 * 1024, "LIMIT")
        return payload

    @classmethod
    def from_bytes(cls, payload, *, expected_fingerprint=None):
        guard(type(payload) is bytes and 0 < len(payload) <= 1024 * 1024, "LIMIT")
        if expected_fingerprint is not None:
            checked_digest(expected_fingerprint)
            guard(type(payload) is bytes and sha256(payload).hexdigest() == expected_fingerprint, "CONFLICT")
        document = decode_state(payload, "offline-content-versions")
        try:
            guard(set(document) == {"domain", "schema_version", "streams"})
            guard(type(document["streams"]) is list and len(document["streams"]) <= 2000, "LIMIT")
            ledger = cls()
            for raw in document["streams"]:
                guard(type(raw) is dict and set(raw) == {"ref", "versions", "last_observed_at", "provider_bindings", "source_updated_at"})
                reference = raw["ref"]
                guard(type(reference) is dict and set(reference) == {"entity_id", "kind"})
                ref = StreamRef(reference["entity_id"], StreamKind(reference["kind"]))
                guard(ledger.current(ref) is None, "DUPLICATE")
                versions = raw["versions"]
                guard(type(versions) is list and 0 < len(versions) <= 32, "LIMIT")
                previous_time, seen_digests, parsed_versions = None, set(), []
                for index, version in enumerate(versions, 1):
                    guard(type(version) is dict and set(version) == {"number", "semantic_digest", "first_seen_at"})
                    guard(type(version["number"]) is int and version["number"] == index, "VERSION_CONFLICT")
                    value = checked_digest(version["semantic_digest"])
                    when = _decode(datetime, version["first_seen_at"])
                    guard(previous_time is None or when > previous_time, "OUT_OF_ORDER")
                    guard(value not in seen_digests, "REVERSION_REQUIRES_REVIEW")
                    seen_digests.add(value)
                    parsed_versions.append(ContentVersion(index, value, when))
                    previous_time = when
                last_seen = _decode(datetime, raw["last_observed_at"])
                guard(last_seen >= previous_time, "OUT_OF_ORDER")
                source_time = _decode(datetime, raw["source_updated_at"]) if raw["source_updated_at"] is not None else None
                guard(source_time is None or source_time <= last_seen, "UTC")
                raw_bindings = raw["provider_bindings"]
                guard(type(raw_bindings) is list and len(raw_bindings) <= 128, "LIMIT")
                bindings, tokens, counter = [], set(), None
                for item in raw_bindings:
                    guard(type(item) is dict and set(item) == {"token", "sequence", "semantic_digest"})
                    token = checked_id(item["token"])
                    guard(token not in tokens, "DUPLICATE")
                    guard(checked_digest(item["semantic_digest"]) in seen_digests, "VERSION_CONFLICT")
                    sequence = item["sequence"]
                    guard(sequence is None or type(sequence) is int and 0 < sequence <= 2**63 - 1, "VERSION_CONFLICT")
                    if counter is not None:
                        guard(sequence is not None and sequence > counter, "VERSION_CONFLICT")
                    if sequence is not None:
                        counter = sequence
                    bindings.append(ProviderBinding(token, sequence, item["semantic_digest"]))
                    tokens.add(token)
                guard(not bindings or bindings[-1].semantic_digest == parsed_versions[-1].semantic_digest, "VERSION_CONFLICT")
                ledger._streams[ref] = StreamState(ref, tuple(parsed_versions), last_seen, tuple(bindings), source_time)
            return ledger
        except RegistryError:
            raise
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            raise RegistryError("MALFORMED") from None
