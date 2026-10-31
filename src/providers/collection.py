"""Bounded synthetic collection only. No network, real clock, sleep or storage."""
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Protocol

from src.providers.adapter import RequestPolicy
from src.providers.models import ContractError, DataFreshness, Fixture, Model, Snapshot, StandingsEntry, require
from src.providers.reconciliation import Check, PhaseRules, check, reconcile
from src.providers.validation import (
    MAX_ROWS, _decode, _json, _object, canonical_bytes, content_digest, primitive,
    validate_snapshot, validate_update,
)


class Resource(str, Enum):
    FIXTURES = "fixtures"
    STANDINGS = "standings"


class CollectionState(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class FailureCode(str, Enum):
    HTTP_429 = "HTTP_429"
    HTTP_500 = "HTTP_500"
    HTTP_502 = "HTTP_502"
    HTTP_503 = "HTTP_503"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TIMEOUT = "TIMEOUT"
    TLS = "TLS"
    AUTHENTICATION = "AUTHENTICATION"
    ACCESS_DENIED = "ACCESS_DENIED"
    UNSUPPORTED = "UNSUPPORTED"
    MALFORMED = "MALFORMED"
    LIMIT = "LIMIT"
    INCOMPLETE = "INCOMPLETE"
    CURSOR = "CURSOR"
    DUPLICATE_PAGE = "DUPLICATE_PAGE"
    DUPLICATE_ENTITY = "DUPLICATE_ENTITY"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    CONTRACT = "CONTRACT"
    DQ = "DQ"
    NOT_COMPLETE = "NOT_COMPLETE"


RETRYABLE = frozenset((FailureCode.HTTP_429, FailureCode.HTTP_500, FailureCode.HTTP_502,
                       FailureCode.HTTP_503, FailureCode.TIMEOUT))


class CollectionFailure(RuntimeError):
    def __init__(self, code: FailureCode, *, retry_after: int = 0):
        self.code = code if isinstance(code, FailureCode) else FailureCode.MALFORMED
        self.retry_after = retry_after if type(retry_after) is int and 0 <= retry_after <= 3600 else 3600
        super().__init__("provider_collection:" + self.code.value)


@dataclass(frozen=True)
class CollectionLimits(Model):
    max_entities: int = 3000
    max_bytes: int = 4 * 1024 * 1024
    max_requests: int = 64
    max_elapsed_seconds: int = 120
    max_wait_seconds: int = 30
    max_age_seconds: int = 3600

    def __post_init__(self):
        super().__post_init__()
        require(1 <= self.max_entities <= 3000 and 1 <= self.max_bytes <= 4 * 1024 * 1024 and
                1 <= self.max_requests <= 64 and 1 <= self.max_elapsed_seconds <= 300 and
                0 <= self.max_wait_seconds <= 60 and 1 <= self.max_age_seconds <= 86400, "LIMIT")


@dataclass(frozen=True)
class CollectionPlan(Model):
    context: Snapshot
    source_revision: str
    fixture_count: int
    standings_count: int
    rules: tuple[PhaseRules, ...]
    schema_version: int = 1

    def __post_init__(self):
        super().__post_init__()
        validate_snapshot(self.context)
        require(self.context.provider == "synthetic" and not self.context.fixtures and not self.context.standings, "SCOPE")
        require(self.schema_version == 1 and 0 <= self.fixture_count <= MAX_ROWS and
                0 <= self.standings_count <= MAX_ROWS and len(self.rules) <= 100, "LIMIT")
        from src.providers.models import identifier
        identifier(self.source_revision)


@dataclass(frozen=True)
class Page(Model):
    resource: Resource
    sequence: int
    request_cursor: str | None
    next_cursor: str | None
    source_revision: str
    total: int
    complete: bool
    fixtures: tuple[Fixture, ...] = ()
    standings: tuple[StandingsEntry, ...] = ()
    schema_version: int = 1

    def __post_init__(self):
        super().__post_init__()
        from src.providers.models import identifier
        for token in (self.request_cursor, self.next_cursor, self.source_revision):
            if token is not None:
                identifier(token)
        require(self.schema_version == 1 and 1 <= self.sequence <= 10 and 0 <= self.total <= MAX_ROWS, "LIMIT")
        require(len(self.fixtures) <= MAX_ROWS and len(self.standings) <= MAX_ROWS, "LIMIT")
        require(not (self.standings if self.resource is Resource.FIXTURES else self.fixtures), "TYPE")

    @property
    def items(self):
        return self.fixtures if self.resource is Resource.FIXTURES else self.standings


@dataclass(frozen=True)
class PageReceipt(Model):
    resource: Resource
    sequence: int
    item_count: int
    payload_bytes: int
    payload_sha256: str
    cursor_sha256: str

    def __post_init__(self):
        super().__post_init__()
        require(1 <= self.sequence <= 10 and 0 <= self.item_count <= MAX_ROWS and
                0 < self.payload_bytes <= 1024 * 1024, "LIMIT")
        for digest in (self.payload_sha256, self.cursor_sha256):
            require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "TYPE")


@dataclass(frozen=True)
class CollectionSnapshot(Model):
    provider: str
    competition_id: str | None
    season_id: str | None
    collected_at: datetime
    state: CollectionState
    completeness: Completeness
    freshness: FreshnessState
    page_count: int
    entity_count: int
    request_count: int
    bytes_received: int
    semantic_digest: str | None
    source_freshness: DataFreshness | None
    source_fence_sha256: str | None
    provenance: tuple[PageReceipt, ...]
    checks: tuple[Check, ...]
    error: FailureCode | None
    data: Snapshot | None = field(repr=False)
    schema_version: int = 1

    def __post_init__(self):
        super().__post_init__()
        require(self.provider == "synthetic" and self.schema_version == 1 and self.page_count == len(self.provenance), "TYPE")
        require(0 <= self.entity_count <= 3000 and 0 <= self.request_count <= 64 and self.bytes_received >= 0, "LIMIT")
        require(sum(item.item_count for item in self.provenance) <= self.entity_count, "TYPE")
        if self.state is CollectionState.SUCCEEDED:
            require(self.data is not None and self.error is None and not any(c.status == "FAIL" for c in self.checks), "TYPE")
            require(self.semantic_digest == content_digest(self.data), "CONFLICT")
            require(self.competition_id == self.data.competition.id and self.season_id == self.data.season.id, "SCOPE")
            require((self.completeness is Completeness.COMPLETE) == (not self.data.partial), "TYPE")
        else:
            require(self.data is None and self.semantic_digest is None and self.error is not None, "TYPE")

    @property
    def eligible_for_full_snapshot(self):
        # Synthetic eligibility, NOT authorization to publish or write Bronze.
        return (self.state is CollectionState.SUCCEEDED and self.completeness is Completeness.COMPLETE
                and self.freshness is FreshnessState.FRESH and self.data is not None and not self.data.partial
                and self.error is None
                and not any(item.status == "FAIL" for item in self.checks)
                and any(item.rule_id == "provider.standings.counters" and item.status == "PASS" for item in self.checks))

    def require_complete(self):
        if not self.eligible_for_full_snapshot:
            raise CollectionFailure(FailureCode.NOT_COMPLETE)
        return self.data


class CollectionClock(Protocol):
    def monotonic(self) -> float: ...
    def now(self) -> datetime: ...
    def wait(self, seconds: float) -> None: ...


class PagedProviderAdapter(Protocol):
    def describe(self, *, timeout_seconds: int) -> CollectionPlan: ...
    def fetch_page(self, resource: Resource, cursor: str | None, *, timeout_seconds: int) -> bytes: ...


def encode_page(page: Page) -> bytes:
    return _json(primitive(page)).encode("utf-8")


def decode_page(payload: bytes, limit: int) -> Page:
    if type(payload) is not bytes or len(payload) > limit:
        raise CollectionFailure(FailureCode.LIMIT)
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ContractError("TYPE")))
        return _decode(Page, document)
    except (ContractError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise CollectionFailure(FailureCode.MALFORMED) from None


def _fence(plan):
    return sha256(_json(primitive(plan)).encode("utf-8")).hexdigest()


class BoundedCollector:
    """Per-call bounded state; failed/partial results never become full snapshots.

    The clock and offline adapter are explicit dependencies. A timeout is passed
    to the adapter and checked on return; this is not a preemptive HTTP timeout.
    """
    def __init__(self, *, clock: CollectionClock, policy: RequestPolicy = RequestPolicy(),
                 limits: CollectionLimits = CollectionLimits()):
        self.clock, self.policy, self.limits = clock, policy, limits

    def collect(self, adapter: PagedProviderAdapter, *, previous: Snapshot | None = None) -> CollectionSnapshot:
        # State belongs to this invocation, so replay never reuses a cursor/cache.
        return _Collection(self, adapter).run(previous)


class _Collection:
    def __init__(self, owner, adapter):
        self.clock, self.policy, self.limits = owner.clock, owner.policy, owner.limits
        self.adapter = adapter
        self.started = self.clock.monotonic()
        self.last_request = None
        self.requests = 0
        self.receipts = []
        self.bytes_received = 0
        self.entity_count = 0

    def _wait(self, seconds):
        if not math.isfinite(seconds) or seconds < 0 or seconds > self.limits.max_wait_seconds:
            raise CollectionFailure(FailureCode.LIMIT)
        before = self.clock.monotonic()
        if before - self.started + seconds > self.limits.max_elapsed_seconds:
            raise CollectionFailure(FailureCode.LIMIT)
        if seconds > 0:
            self.clock.wait(seconds)
            if self.clock.monotonic() - before + 1e-9 < seconds:
                raise CollectionFailure(FailureCode.LIMIT)

    def _request(self, operation):
        for attempt in range(1, self.policy.max_attempts + 1):
            if self.last_request is not None:
                self._wait(max(0, 60 / self.policy.requests_per_minute - (self.clock.monotonic() - self.last_request)))
            if self.requests >= self.limits.max_requests or self.clock.monotonic() - self.started >= self.limits.max_elapsed_seconds:
                raise CollectionFailure(FailureCode.LIMIT)
            self.requests += 1
            self.last_request = self.clock.monotonic()
            failure = None
            try:
                value = operation(timeout_seconds=self.policy.timeout_seconds)
                if self.clock.monotonic() - self.last_request > self.policy.timeout_seconds:
                    raise CollectionFailure(FailureCode.TIMEOUT)
                if self.clock.monotonic() - self.started > self.limits.max_elapsed_seconds:
                    raise CollectionFailure(FailureCode.LIMIT)
                return value
            except CollectionFailure as error:
                failure = error
            except Exception:
                raise CollectionFailure(FailureCode.MALFORMED) from None
            if failure.code not in RETRYABLE or attempt == self.policy.max_attempts:
                raise failure from None
            self._wait(max(self.policy.retry_delay(attempt), failure.retry_after))

    def _pages(self, resource, plan):
        cursor, seen_cursors, seen_pages, records, identities = None, set(), set(), {}, {}
        expected = plan.fixture_count if resource is Resource.FIXTURES else plan.standings_count
        complete = True
        for sequence in range(1, self.policy.max_pages + 1):
            payload = self._request(lambda **kw: self.adapter.fetch_page(resource, cursor, **kw))
            if type(payload) is not bytes:
                raise CollectionFailure(FailureCode.MALFORMED)
            self.bytes_received += len(payload)
            if self.bytes_received > self.limits.max_bytes:
                raise CollectionFailure(FailureCode.LIMIT)
            page = decode_page(payload, self.policy.max_response_bytes)
            if page.resource is not resource or page.request_cursor != cursor or page.sequence != sequence:
                raise CollectionFailure(FailureCode.CURSOR)
            if page.source_revision != plan.source_revision:
                raise CollectionFailure(FailureCode.SOURCE_CHANGED)
            if page.total != expected:
                raise CollectionFailure(FailureCode.INCOMPLETE)
            rows_digest = sha256(_json(primitive(page.items)).encode("utf-8")).hexdigest()
            if rows_digest in seen_pages:
                raise CollectionFailure(FailureCode.DUPLICATE_PAGE)
            seen_pages.add(rows_digest)
            if not page.items and (page.next_cursor is not None or expected != 0):
                raise CollectionFailure(FailureCode.INCOMPLETE)
            complete = complete and page.complete
            for item in page.items:
                key = item.id if resource is Resource.FIXTURES else (item.stage_id, item.participant_id)
                if key in records:
                    raise CollectionFailure(FailureCode.DUPLICATE_ENTITY if records[key] == item else FailureCode.REVISION_CONFLICT)
                if resource is Resource.FIXTURES:
                    external = (item.identity.provider, item.identity.entity_kind, item.identity.external_id)
                    if external in identities:
                        raise CollectionFailure(FailureCode.DUPLICATE_ENTITY)
                    identities[external] = key
                if self.entity_count >= self.limits.max_entities or len(records) >= MAX_ROWS:
                    raise CollectionFailure(FailureCode.LIMIT)
                records[key] = item
                self.entity_count += 1
            self.receipts.append(PageReceipt(resource, sequence, len(page.items), len(payload), sha256(payload).hexdigest(),
                                             sha256((cursor or "").encode()).hexdigest()))
            if len(records) > expected:
                raise CollectionFailure(FailureCode.INCOMPLETE)
            if page.next_cursor is None:
                if len(records) != expected:
                    raise CollectionFailure(FailureCode.INCOMPLETE)
                return tuple(records.values()), complete
            if page.next_cursor in seen_cursors or page.next_cursor == cursor:
                raise CollectionFailure(FailureCode.CURSOR)
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise CollectionFailure(FailureCode.LIMIT)

    def run(self, previous):
        plan, candidate, checks, error = None, None, (), None
        state, completeness, freshness = CollectionState.FAILED, Completeness.UNKNOWN, FreshnessState.UNKNOWN
        try:
            plan = self._request(self.adapter.describe)
            if type(plan) is not CollectionPlan:
                raise CollectionFailure(FailureCode.MALFORMED)
            if plan.fixture_count + plan.standings_count > self.limits.max_entities:
                raise CollectionFailure(FailureCode.LIMIT)
            fixtures, fixtures_complete = self._pages(Resource.FIXTURES, plan)
            standings, standings_complete = self._pages(Resource.STANDINGS, plan)
            final = self._request(self.adapter.describe)
            if type(final) is not CollectionPlan or _fence(plan) != _fence(final):
                raise CollectionFailure(FailureCode.SOURCE_CHANGED)
            complete = fixtures_complete and standings_complete and not plan.context.partial
            completeness = Completeness.COMPLETE if complete else Completeness.PARTIAL
            candidate = replace(plan.context, fixtures=fixtures, standings=standings, partial=not complete)
            # Normalize before handing any successful immutable object to callers.
            from src.providers.validation import parse_snapshot
            candidate = parse_snapshot(canonical_bytes(candidate))
            if previous is not None:
                validate_update(previous, candidate)
            checks = (check("provider.collection.complete", complete, category="source_integrity"),
                      check("provider.contracts.valid", True, category="referential"), *reconcile(candidate, plan.rules))
            checks = (*checks, check("provider.source.fence", True, category="source_integrity"))
            if not complete:
                checks = (Check("provider.collection.complete", "source_integrity", "WARN", 0, 1), *checks[1:])
            if any(item.status == "FAIL" for item in checks):
                raise CollectionFailure(FailureCode.DQ)
            state = CollectionState.SUCCEEDED
        except CollectionFailure as failure:
            error = failure.code
            state = CollectionState.UNSUPPORTED if error is FailureCode.UNSUPPORTED else CollectionState.FAILED
        except ContractError:
            error = FailureCode.CONTRACT
        except Exception:
            error = FailureCode.MALFORMED
        if plan is not None and type(plan) is CollectionPlan:
            try:
                freshness = FreshnessState.STALE if plan.context.freshness.is_stale(
                    now=self.clock.now(), max_age_seconds=self.limits.max_age_seconds) else FreshnessState.FRESH
            except ContractError:
                error, state = FailureCode.CONTRACT, CollectionState.FAILED
        if state is not CollectionState.SUCCEEDED:
            candidate = None
            if completeness is Completeness.UNKNOWN:
                completeness = Completeness.PARTIAL if self.receipts else Completeness.UNKNOWN
            checks = (*checks, check("provider.collection.failed", False, category="operational"))
        return CollectionSnapshot(
            "synthetic", plan.context.competition.id if type(plan) is CollectionPlan else None,
            plan.context.season.id if type(plan) is CollectionPlan else None, self.clock.now(), state,
            completeness, freshness, len(self.receipts), self.entity_count, self.requests, self.bytes_received,
            content_digest(candidate) if candidate is not None else None,
            plan.context.freshness if type(plan) is CollectionPlan else None,
            _fence(plan) if type(plan) is CollectionPlan else None, tuple(self.receipts), checks, error, candidate,
        )


class SyntheticPagedAdapter:
    """Small offline source implementation over A's typed Snapshot, not an API."""
    def __init__(self, snapshot: Snapshot, *, rules: tuple[PhaseRules, ...], page_size: int = 20,
                 source_revision: str = "synthetic-revision-1"):
        validate_snapshot(snapshot)
        require(snapshot.provider == "synthetic" and type(page_size) is int and 1 <= page_size <= 100, "SCOPE")
        self.snapshot = snapshot
        self.page_size = page_size
        self.plan = CollectionPlan(replace(snapshot, fixtures=(), standings=()), source_revision,
                                   len(snapshot.fixtures), len(snapshot.standings), rules)

    def describe(self, *, timeout_seconds: int) -> CollectionPlan:
        return self.plan

    def fetch_page(self, resource: Resource, cursor: str | None, *, timeout_seconds: int) -> bytes:
        if cursor is None:
            sequence = 1
        elif cursor.startswith("page-") and cursor[5:].isdigit():
            sequence = int(cursor[5:])
        else:
            raise CollectionFailure(FailureCode.CURSOR)
        items = sorted(getattr(self.snapshot, resource.value), key=lambda item: _json(primitive(item)))
        offset = (sequence - 1) * self.page_size
        selected = tuple(items[offset:offset + self.page_size])
        next_cursor = f"page-{sequence + 1}" if offset + self.page_size < len(items) else None
        return encode_page(Page(resource, sequence, cursor, next_cursor, self.plan.source_revision,
                                len(items), True, **{resource.value: selected}))
