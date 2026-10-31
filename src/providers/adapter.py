"""Offline adapter boundary; deliberately NO HTTP implementation or credentials.

No provider passed the season/standings/licensing gate in 9C.1. A future live
adapter must implement the policy below using the existing source transport,
with a reviewed HTTPS endpoint allowlist, redirect and response-size guards.
"""
from dataclasses import dataclass
import ssl
from typing import Protocol
from urllib.error import HTTPError

from src.common.source_transport import transient_failure, transport_reason
from src.providers.models import Competition, ContractError, Fixture, FixtureStatus, Season, Snapshot, StandingsEntry, require
from src.providers.validation import canonical_bytes, content_digest, parse_snapshot, validate_snapshot

LIVE_PROVIDER_ALLOWLIST = frozenset()  # Deny all live providers, including arbitrary URLs.


@dataclass(frozen=True)
class RequestPolicy:
    timeout_seconds: int = 10
    max_attempts: int = 3
    backoff_seconds: int = 1
    requests_per_minute: int = 30
    max_pages: int = 10
    max_response_bytes: int = 1024 * 1024

    def __post_init__(self):
        require(all(type(value) is int for value in vars(self).values()), "TYPE")
        require(1 <= self.timeout_seconds <= 30 and 1 <= self.max_attempts <= 3 and
                1 <= self.backoff_seconds <= 5 and 1 <= self.requests_per_minute <= 60 and
                1 <= self.max_pages <= 10 and 1 <= self.max_response_bytes <= 1024 * 1024, "LIMIT")

    def retry_delay(self, attempt: int) -> int:
        require(type(attempt) is int and 1 <= attempt < self.max_attempts, "LIMIT")
        return self.backoff_seconds * 2 ** (attempt - 1)


class AdapterFailure(RuntimeError):
    CODES = frozenset(("INVALID_PAYLOAD", "TIMEOUT", "TLS", "AUTHENTICATION", "ACCESS_DENIED",
                       "RATE_LIMIT", "TRANSIENT", "LIVE_INTEGRATION_DISABLED"))

    def __init__(self, code):
        self.code = code if type(code) is str and code in self.CODES else "INVALID_PAYLOAD"
        super().__init__("provider_adapter:" + self.code)


def classify_failure(error: Exception) -> AdapterFailure:
    """Reuse transport classification, but retain neither original error nor URL."""
    reason = transport_reason(error)
    if isinstance(reason, ssl.SSLError):
        code = "TLS"
    elif isinstance(reason, TimeoutError):
        code = "TIMEOUT"
    elif isinstance(reason, HTTPError) and reason.code in (401, 403, 429):
        code = {401: "AUTHENTICATION", 403: "ACCESS_DENIED", 429: "RATE_LIMIT"}[reason.code]
    else:
        code = "TRANSIENT" if transient_failure(error) else "INVALID_PAYLOAD"
    return AdapterFailure(code)


def require_live_provider(provider: str) -> None:
    if provider not in LIVE_PROVIDER_ALLOWLIST:
        raise AdapterFailure("LIVE_INTEGRATION_DISABLED")


class ProviderAdapter(Protocol):
    """One explicit competition/season snapshot, not an arbitrary query engine."""
    def get_competition(self) -> Competition: ...
    def get_season(self) -> Season: ...
    def get_fixtures(self) -> tuple[Fixture, ...]: ...
    def get_results(self) -> tuple[Fixture, ...]: ...
    def get_standings(self) -> tuple[StandingsEntry, ...]: ...


class SyntheticAdapter:
    """Accepts only a complete in-memory synthetic contract, never a URL/file."""
    def __init__(self, snapshot: Snapshot):
        validate_snapshot(snapshot)
        require(snapshot.provider == "synthetic", "SCOPE")
        # Normalize once so all callers see stable resource order and UTC.
        self._snapshot = parse_snapshot(canonical_bytes(snapshot))

    @classmethod
    def from_bytes(cls, payload: bytes):
        try:
            return cls(parse_snapshot(payload))
        except ContractError:
            raise AdapterFailure("INVALID_PAYLOAD") from None

    @property
    def snapshot(self) -> Snapshot:
        return self._snapshot

    @property
    def digest(self) -> str:
        return content_digest(self._snapshot)

    def get_competition(self):
        return self._snapshot.competition

    def get_season(self):
        return self._snapshot.season

    def get_fixtures(self):
        return self._snapshot.fixtures

    def get_results(self):
        return tuple(item for item in self._snapshot.fixtures if item.status is FixtureStatus.FINISHED)

    def get_standings(self):
        return self._snapshot.standings
