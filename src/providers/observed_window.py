"""Offline observed-window evidence, explicitly NOT an atomic source snapshot.

Six supplied byte responses: metadata, fixtures, standings, fixtures, standings,
metadata. No fetching, retries, clocks, credentials, publication or persistence.
Existing revision-fenced BoundedCollector is not changed or invoked.
"""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

from src.providers.football_data import (
    MappingContext, MappingError, MappingResult, decode_document, ensure, map_responses, rows, utc, utc_time,
)
from src.providers.models import Snapshot
from src.providers.validation import _json

SEQUENCE = ("metadata", "fixtures", "standings", "fixtures", "standings", "metadata")
UNORDERED_ARRAYS = frozenset(("matches", "standings", "table", "seasons"))


def _canonical(value, key=None):
    if isinstance(value, dict):
        return {name: _canonical(item, name) for name, item in value.items()}
    if isinstance(value, list):
        items = [_canonical(item) for item in value]
        return sorted(items, key=_json) if key in UNORDERED_ARRAYS else items
    return value


def response_fingerprint(payload: bytes) -> str:
    """Content fence; collection/list ordering is not a provider revision."""
    try:
        document = decode_document(payload)
        return sha256(_json(_canonical(document)).encode("utf-8")).hexdigest()
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        if isinstance(error, MappingError):
            raise
        raise MappingError("MALFORMED") from None


@dataclass(frozen=True)
class Observation:
    resource: str
    started_at: datetime
    ended_at: datetime
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class ResourceReceipt:
    resource: str
    sequence: int
    started_at: datetime
    ended_at: datetime
    received_bytes: int
    raw_sha256: str
    content_fingerprint: str


@dataclass(frozen=True)
class WindowEvidence:
    started_at: datetime
    ended_at: datetime
    receipts: tuple[ResourceReceipt, ...]
    mapping: MappingResult
    semantic_digest: str
    consistency: str = "OBSERVED_WINDOW_STABLE_NOT_ATOMIC"
    source_revision: None = None
    publish_authorized: bool = False


def verify_observed_window(observations: tuple[Observation, ...], *, context: MappingContext,
                           max_window_seconds: int = 120,
                           previous: Snapshot | None = None) -> WindowEvidence:
    """Re-read fences + all three table counter checks within a bounded window.

    At most six 1 MiB responses; no pagination/retry or implicit fallback to this
    contract. Window start/end are observations, not a server transaction token.
    A source can change and revert between reads; this cannot detect such ABA.
    """
    ensure(type(max_window_seconds) is int and 1 <= max_window_seconds <= 300, "LIMIT")
    ensure(type(observations) is tuple and len(observations) == 6 and
           all(type(item) is Observation for item in observations), "WINDOW")
    ensure(tuple(item.resource for item in observations) == SEQUENCE, "WINDOW")
    last = None
    receipts = []
    for number, item in enumerate(observations, 1):
        utc_time(item.started_at)
        utc_time(item.ended_at)
        ensure(item.started_at <= item.ended_at and (last is None or item.started_at >= last), "WINDOW")
        last = item.ended_at
        ensure((last - observations[0].started_at).total_seconds() <= max_window_seconds, "WINDOW")
        fingerprint = response_fingerprint(item.payload)
        # Validate source times against their OWN response, not a later table or
        # closing-metadata read that could conceal a future-dated update.
        document = decode_document(item.payload)
        if item.resource == "metadata" and document.get("lastUpdated") is not None:
            ensure(utc(document["lastUpdated"]) <= item.ended_at, "UTC")
        if item.resource == "fixtures":
            for row in rows(document.get("matches"), 144):
                ensure(utc(row.get("lastUpdated")) <= item.ended_at, "UTC")
                if row.get("status") in ("FINISHED", "IN_PLAY") and row.get("utcDate") is not None:
                    ensure(utc(row["utcDate"]) <= item.ended_at, "UTC")
        receipts.append(ResourceReceipt(item.resource, number, item.started_at, item.ended_at,
            len(item.payload), sha256(item.payload).hexdigest(), fingerprint))
    for before, after in ((0, 5), (1, 3), (2, 4)):
        ensure(receipts[before].content_fingerprint == receipts[after].content_fingerprint, "SOURCE_CHANGED")
    first = map_responses(observations[0].payload, observations[1].payload, observations[2].payload,
                          context=context, fetched_at=observations[2].ended_at, previous=previous)
    final = map_responses(observations[5].payload, observations[3].payload, observations[4].payload,
                          context=context, fetched_at=observations[5].ended_at, previous=previous)
    ensure(not first.unsupported and not final.unsupported and
           not first.synthetic_only_statuses and not final.synthetic_only_statuses, "UNSUPPORTED")
    ensure(first.ready_for_offline_use and final.ready_for_offline_use, "DQ")
    # TOTAL alone is mappable, but this stronger window gate requires all views.
    ensure({table.kind for table in first.tables} == {"TOTAL", "HOME", "AWAY"}, "DQ")
    ensure(first.semantic_digest == final.semantic_digest, "SOURCE_CHANGED")
    return WindowEvidence(observations[0].started_at, observations[-1].ended_at,
                          tuple(receipts), final, final.semantic_digest)
