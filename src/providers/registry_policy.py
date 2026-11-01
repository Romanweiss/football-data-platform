"""Offline transactional handoff: registry-bound window -> immutable proposal.

No registry/ledger input is mutated; no publication or persistence is authorized.
The existing B collector and its strict source revision fences remain unchanged.
"""
from dataclasses import dataclass, field, replace
from hashlib import sha256

from src.providers.football_data import FixtureBinding, MappingContext
from src.providers.identity_registry import IdentityKind, IdentityRegistry, RegistryError, checked_id, digest, guard
from src.providers.models import ContractError, Snapshot
from src.providers.observed_versions import (
    StreamKind, StreamRef, VersionLedger, VersionReceipt, fixture_fingerprint, standings_fingerprint,
)
from src.providers.observed_window import WindowEvidence, verify_observed_window
from src.providers.validation import primitive, validate_snapshot, validate_update


def _bound(registry, entity, kind, parent_id=None):
    record = registry.get(entity.id)
    guard(record.kind is kind and record.provider == entity.identity.provider and
          record.external_id == entity.identity.external_id and
          kind.value == entity.identity.entity_kind.value, "IDENTITY")
    if parent_id is not None:
        guard(record.parent_id == parent_id, "CONFLICT")
    if hasattr(entity, "team_type"):
        guard(record.team_type is entity.team_type, "CONFLICT")
    return record


def validate_bound_snapshot(registry, snapshot):
    guard(type(registry) is IdentityRegistry and type(snapshot) is Snapshot)
    try:
        validate_snapshot(snapshot)
        _bound(registry, snapshot.competition, IdentityKind.COMPETITION)
        _bound(registry, snapshot.season, IdentityKind.SEASON, snapshot.competition.id)
        for stage in snapshot.stages:
            record = _bound(registry, stage, IdentityKind.STAGE, snapshot.season.id)
            guard(record.stage_kind is stage.kind, "CONFLICT")
        for item in snapshot.rounds:
            record = _bound(registry, item, IdentityKind.ROUND, item.stage_id)
            guard(record.order == item.order, "CONFLICT")
        for team in snapshot.participants:
            _bound(registry, team, IdentityKind.PARTICIPANT)
            guard(registry.has_participation(snapshot.season.id, team.id), "UNCONFIRMED")
        for fixture in snapshot.fixtures:
            record = _bound(registry, fixture, IdentityKind.FIXTURE, snapshot.season.id)
            guard(record.participants == (fixture.home_id, fixture.away_id), "CONFLICT")
        for tie in snapshot.ties:
            record = _bound(registry, tie, IdentityKind.TIE, tie.stage_id)
            guard(record.participants == tuple(sorted((tie.participant_a_id, tie.participant_b_id))) and
                  record.legs == tie.legs, "CONFLICT")
    except ContractError:
        raise RegistryError("IDENTITY") from None


def bind_mapping_context(registry, empty_snapshot, external_fixture_ids, versions):
    """Parse-only binding versions; prospective local 1 is explicit, not vendor data.

    No versions are recorded until complete observed-window validation succeeds.
    """
    guard(type(versions) is VersionLedger)
    validate_bound_snapshot(registry, empty_snapshot)
    guard(type(external_fixture_ids) is tuple and len(external_fixture_ids) == 144, "SCOPE")
    for external_id in external_fixture_ids:
        checked_id(external_id)
    guard(len(set(external_fixture_ids)) == len(external_fixture_ids), "DUPLICATE")
    bindings = []
    for external_id in external_fixture_ids:
        record = registry.lookup(empty_snapshot.provider, IdentityKind.FIXTURE, external_id,
                                 parent_id=empty_snapshot.season.id)
        local_version = versions.version(StreamRef(record.id, StreamKind.FIXTURE))
        bindings.append(FixtureBinding(external_id, record.id, local_version or 1))
    context = MappingContext(empty_snapshot, tuple(bindings))
    try:
        context.validate()
    except (ContractError, ValueError):
        raise RegistryError("SCOPE") from None
    return context


def validate_observed_update(previous, current):
    """Explicit LOCAL-content policy; does not alter A/B validate_update defaults.

    Provider updated_at must still not regress. A source timestamp-only refresh
    keeps its local revision; the original strict guard sees a comparison-only
    projection. Returned snapshots retain the actual latest source timestamp.
    Display names/season labels are metadata, never identity reassignment.
    """
    guard(type(previous) is Snapshot and type(current) is Snapshot)
    before = {fixture.id: fixture for fixture in previous.fixtures}
    projected = []
    for fixture in current.fixtures:
        old = before.get(fixture.id)
        if old is not None:
            guard(fixture.updated_at >= old.updated_at, "OUT_OF_ORDER")
            same = fixture_fingerprint(fixture) == fixture_fingerprint(old)
            guard(fixture.revision == old.revision + int(not same), "VERSION_CONFLICT")
            if same:
                fixture = replace(fixture, updated_at=old.updated_at)
        projected.append(fixture)
    try:
        validate_update(previous, replace(current, fixtures=tuple(projected),
            competition=replace(current.competition, name=previous.competition.name),
            season=replace(current.season, label=previous.season.label)))
    except ContractError:
        raise RegistryError("CONFLICT") from None


@dataclass(frozen=True)
class RegistryProposal:
    snapshot: Snapshot
    window: WindowEvidence
    versions: tuple[VersionReceipt, ...]
    registry_fingerprint: str
    ledger_before_fingerprint: str
    ledger_after_state: bytes = field(repr=False)
    semantic_digest: str
    consistency: str = "OBSERVED_WINDOW_STABLE_NOT_ATOMIC"
    source_revision: None = None
    publish_authorized: bool = False


def _metadata_fingerprint(snapshot):
    metadata = primitive(snapshot)
    for name in ("fixtures", "standings", "freshness"):
        del metadata[name]
    return digest({"domain": "metadata-semantic-v1", "content": metadata})


def prepare_registered_window(observations, *, registry, versions, context,
                              previous=None, max_window_seconds=120):
    """Pure proposal: failures leave input identities/versions and old data intact."""
    guard(type(registry) is IdentityRegistry and type(versions) is VersionLedger and type(context) is MappingContext)
    registry_before = registry.to_bytes()
    ledger_before = versions.to_bytes()
    expected_context = bind_mapping_context(registry, context.empty_snapshot,
        tuple(binding.external_id for binding in context.fixture_bindings), versions)
    guard(expected_context == context, "VERSION_CONFLICT")
    # Do not pass the old Snapshot to E's strict revision guard before assigning
    # prospective LOCAL versions. This new policy validates the final update below.
    window = verify_observed_window(observations, context=context, max_window_seconds=max_window_seconds)
    source = window.mapping.snapshot
    validate_bound_snapshot(registry, source)
    working = VersionLedger.from_bytes(ledger_before)
    refs = [StreamRef(f.id, StreamKind.FIXTURE) for f in source.fixtures]
    refs += [StreamRef(source.season.id, StreamKind.METADATA)]
    refs += [StreamRef(source.stages[0].id, StreamKind[kind]) for kind in ("TOTAL", "HOME", "AWAY")]
    guard(previous is not None or not any(working.current(ref) for ref in refs), "UNCONFIRMED")
    if previous is not None:
        validate_bound_snapshot(registry, previous)
        # Prove that the supplied old data actually belongs to this ledger.
        for fixture in previous.fixtures:
            ref = StreamRef(fixture.id, StreamKind.FIXTURE)
            state = working.current(ref)
            guard(state is not None and state.versions[-1].number == fixture.revision and
                  state.versions[-1].semantic_digest == fixture_fingerprint(fixture) and
                  state.source_updated_at == fixture.updated_at, "VERSION_CONFLICT")
        for ref, value in ((StreamRef(previous.season.id, StreamKind.METADATA), _metadata_fingerprint(previous)),
                           (StreamRef(previous.stages[0].id, StreamKind.TOTAL),
                            standings_fingerprint(StreamKind.TOTAL, previous.standings))):
            state = working.current(ref)
            guard(state is not None and state.versions[-1].semantic_digest == value, "VERSION_CONFLICT")
    receipts, fixtures = [], []
    for fixture in source.fixtures:
        ref = StreamRef(fixture.id, StreamKind.FIXTURE)
        receipt = working.observe(ref, fixture_fingerprint(fixture), observed_at=window.ended_at,
                                  expected_version=working.version(ref), source_updated_at=fixture.updated_at)
        receipts.append(receipt)
        fixtures.append(replace(fixture, revision=receipt.local_content_version))
    ref = StreamRef(source.season.id, StreamKind.METADATA)
    receipts.append(working.observe(ref, _metadata_fingerprint(source),
                                   observed_at=window.ended_at, expected_version=working.version(ref)))
    for table in window.mapping.tables:
        kind = StreamKind[table.kind]
        ref = StreamRef(source.stages[0].id, kind)
        receipts.append(working.observe(ref, standings_fingerprint(kind, table.entries),
            observed_at=window.ended_at, expected_version=working.version(ref)))
    candidate = replace(source, fixtures=tuple(fixtures))
    validate_snapshot(candidate)
    if previous is not None:
        validate_observed_update(previous, candidate)
    guard(registry.to_bytes() == registry_before and versions.to_bytes() == ledger_before, "CONFLICT")
    semantic = primitive(candidate)
    del semantic["freshness"]
    # Metadata-only source timestamp updates do not alter the semantic digest.
    for fixture in semantic["fixtures"]:
        del fixture["updated_at"]
    return RegistryProposal(candidate, window, tuple(receipts), sha256(registry_before).hexdigest(),
        sha256(ledger_before).hexdigest(), working.to_bytes(),
        digest({"domain": "registry-candidate-v1", "snapshot": semantic,
                "tables": primitive(window.mapping.tables)}))
