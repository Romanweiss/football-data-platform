"""Bounded, offline OpenFootball results proposal; never downloads or persists.

Not a ProviderAdapter/Snapshot: source ft is NOT proven regulation score and a
date/local time is NOT a UTC kickoff. Keep these semantics in a small boundary
DTO instead of weakening the existing strict UEFA models.
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from hashlib import sha256
import json
import re

from src.providers.identity_registry import (
    IdentityEvidence, IdentityKind, IdentityRegistry, RegistryError, checked_id, digest,
)
from src.providers.models import (
    Competition, EntityKind, FixtureStatus, Participant, ProviderIdentity, Round, Season, SourceCapability, Stage, StageType, TeamType,
)
from src.providers.observed_versions import StreamKind, StreamRef, VersionLedger, VersionReceipt, utc_observation
from src.providers.openfootball_manifest import OpenFootballManifest, UCL_2024_25
from src.providers.validation import primitive

PROVIDER = "openfootball"
MAX_BYTES = 1024 * 1024
MAX_MATCHES = 512


@dataclass(frozen=True)
class Diagnostic:
    code: str
    row: int | None = None  # Zero-based input row, never a team name or payload.
    severity: str = "FATAL"


@dataclass(frozen=True)
class DQLimitation:
    code: str
    fixture_id: str
    severity: str = "NON_FATAL"


@dataclass(frozen=True)
class DQReport:
    limitations: tuple[DQLimitation, ...]
    fatal_count: int = 0  # Fatal failures raise; they never return accepted data.

    @property
    def counts(self):
        result = {}
        for item in self.limitations:
            result[item.code] = result.get(item.code, 0) + 1
        return dict(sorted(result.items()))


class OpenFootballError(ValueError):
    CODES = frozenset(("SCHEMA", "UNKNOWN_FIELD", "REQUIRED", "NULL", "LIMIT", "DATE", "TIME", "SCORE",
        "DUPLICATE", "SELF_MATCH", "UNKNOWN_TEAM", "ROUND", "SCOPE", "COVERAGE", "SCORE_STATUS",
        "IDENTITY_REVIEW_REQUIRED", "CONTENT_MISMATCH", "REVIEW_REQUIRED", "UTC", "OUT_OF_ORDER",
        "VERSION_CONFLICT", "REVERSION_REQUIRES_REVIEW", "MANIFEST"))

    def __init__(self, code, row=None):
        code = code if type(code) is str and code in self.CODES else "SCHEMA"
        self.diagnostic = Diagnostic(code, row)
        super().__init__("openfootball:" + code)


def _check(condition, code, row=None):
    if not condition:
        raise OpenFootballError(code, row)


def _text(value, code="SCHEMA", row=None):
    _check(type(value) is str and 0 < len(value) <= 160 and value == value.strip() and
           not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value), code, row)
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result, "DUPLICATE")
        result[key] = value
    return result


def _shape(value, required, optional=(), row=None):
    _check(type(value) is dict, "SCHEMA", row)
    _check(set(value) <= set(required) | set(optional), "UNKNOWN_FIELD", row)
    _check(set(required) <= set(value), "REQUIRED", row)
    _check(all(v is not None for v in value.values()), "NULL", row)


@dataclass(frozen=True)
class TeamBinding:
    source_name: str
    external_id: str  # Reviewed project key; NOT claimed to be an upstream ID.
    display_name: str


@dataclass(frozen=True)
class RoundBinding:
    source_round: str
    stage_key: str
    stage_name: str
    kind: StageType
    round_key: str
    order: int


@dataclass(frozen=True)
class StatusReview:
    fixture_key: str
    status: FixtureStatus
    evidence: IdentityEvidence


@dataclass(frozen=True)
class OpenFootballMapping:
    source_name: str  # Exact document name, approved after actual PET-2 inspection.
    teams: tuple[TeamBinding, ...]
    rounds: tuple[RoundBinding, ...]
    date_start: date
    date_end: date
    evidence: IdentityEvidence
    expected_rows: int | None = None  # Verified file count, NOT guessed tournament size.
    status_reviews: tuple[StatusReview, ...] = ()


@dataclass(frozen=True)
class OpenFootballFixture:
    id: str
    identity: ProviderIdentity
    season_id: str
    stage_id: str
    round_id: str
    home_id: str
    away_id: str
    match_date: str
    source_time: str | None
    source_round: str
    source_ft: tuple[int, int] | None
    source_ht: tuple[int, int] | None
    status: FixtureStatus
    status_origin: str
    status_review_reference: str | None
    local_revision: int = 1
    # Deliberately absent evidence, not a fabricated midnight/time zone/score split.
    kickoff_utc: None = None
    regulation_score: None = None
    source_revision: None = None
    source_et: tuple[int, int] | None = None
    source_p: tuple[int, int] | None = None
    source_score_state: str = "ABSENT"  # ABSENT / EMPTY / COMPONENTS, not silently collapsed.
    result_availability: str = "MISSING"  # REPORTED requires an actual source ft pair.
    score_quality: str = "MISSING_RESULT"
    after_extra_time_score: None = None  # Not the unverified source_et pair.
    penalty_shootout_score: None = None  # Not the unverified source_p pair, even if unequal.
    winner_id: None = None
    standings_eligible: bool = False
    points_home: None = None
    points_away: None = None


def fixture_fingerprint(fixture):
    content = primitive(fixture)
    del content["local_revision"], content["status_review_reference"]
    return digest({"domain": "openfootball-results-semantic-v2", "content": content})


@dataclass(frozen=True)
class OpenFootballProposal:
    manifest: OpenFootballManifest
    competition: Competition
    season: Season
    participants: tuple[Participant, ...]
    stages: tuple[Stage, ...]
    rounds: tuple[Round, ...]
    fixtures: tuple[OpenFootballFixture, ...]
    observed_at: datetime
    input_sha256: str | None  # Bytes supplied by caller, not proof of upstream acquisition.
    semantic_digest: str
    versions: tuple[VersionReceipt, ...]
    registry_after_state: bytes = field(repr=False)
    ledger_after_state: bytes = field(repr=False)
    dq: DQReport
    capabilities: tuple[SourceCapability, ...]
    schema_version: int = 2  # Normalized results contract, not upstream JSON schema.
    batch_status: str = "ACCEPTED_WITH_LIMITATIONS"
    result_coverage: str = "INCOMPLETE"
    coverage: str = "UNKNOWN"
    source_revision: None = None
    publish_authorized: bool = False


def _mapping(mapping):
    _check(type(mapping) is OpenFootballMapping, "SCHEMA")
    _text(mapping.source_name)
    IdentityRegistry._evidence(mapping.evidence)
    _check(type(mapping.date_start) is date and type(mapping.date_end) is date and
           date(2024, 1, 1) <= mapping.date_start <= mapping.date_end <= date(2025, 12, 31), "DATE")
    _check(type(mapping.teams) is tuple and 0 < len(mapping.teams) <= 128 and
           type(mapping.rounds) is tuple and 0 < len(mapping.rounds) <= 128, "LIMIT")
    _check(mapping.expected_rows is None or type(mapping.expected_rows) is int and
           0 < mapping.expected_rows <= MAX_MATCHES, "COVERAGE")
    teams, displays, rounds, stage_keys, round_keys = {}, {}, {}, {}, {}
    for item in mapping.teams:
        _check(type(item) is TeamBinding, "SCHEMA")
        _text(item.source_name)
        _text(item.display_name)
        checked_id(item.external_id)
        _check(item.source_name not in teams, "DUPLICATE")
        _check(item.external_id not in displays or displays[item.external_id] == item.display_name,
               "IDENTITY_REVIEW_REQUIRED")
        teams[item.source_name] = item
        displays[item.external_id] = item.display_name
    for item in mapping.rounds:
        _check(type(item) is RoundBinding, "SCHEMA")
        _text(item.source_round)
        _text(item.stage_name)
        checked_id(item.stage_key)
        checked_id(item.round_key)
        _check(type(item.kind) is StageType and type(item.order) is int and 1 <= item.order <= 1000, "ROUND")
        _check(item.source_round not in rounds, "DUPLICATE")
        stage = item.stage_name, item.kind
        key = item.stage_key, item.round_key
        _check(item.stage_key not in stage_keys or stage_keys[item.stage_key] == stage, "ROUND")
        _check(key not in round_keys or round_keys[key] == item.order, "ROUND")
        stage_keys[item.stage_key] = stage
        round_keys[key] = item.order
        rounds[item.source_round] = item
    _check(type(mapping.status_reviews) is tuple and len(mapping.status_reviews) <= MAX_MATCHES, "LIMIT")
    reviews = {}
    for review in mapping.status_reviews:
        _check(type(review) is StatusReview, "SCHEMA")
        checked_id(review.fixture_key)
        IdentityRegistry._evidence(review.evidence)
        _check(type(review.status) is FixtureStatus and review.status in (FixtureStatus.UNKNOWN,
            FixtureStatus.SCHEDULED, FixtureStatus.POSTPONED, FixtureStatus.CANCELLED), "SCORE_STATUS")
        _check(review.fixture_key not in reviews, "DUPLICATE")
        reviews[review.fixture_key] = review
    return teams, rounds, reviews


def _score(raw, row):
    _check(type(raw) is list and len(raw) == 2 and
           all(type(value) is int and 0 <= value <= 100 for value in raw), "SCORE", row)
    return tuple(raw)


def _rows(document, mapping, manifest, teams, rounds, reviews):
    _shape(document, ("name", "matches"))
    _text(document["name"])
    _check(document["name"] == mapping.source_name, "SCOPE")
    raw = document["matches"]
    _check(type(raw) is list, "SCHEMA")
    _check(0 < len(raw) <= MAX_MATCHES, "COVERAGE")
    _check(mapping.expected_rows is None or len(raw) == mapping.expected_rows, "COVERAGE")
    result, seen, used_reviews = [], set(), set()
    for index, row in enumerate(raw):
        _shape(row, ("round", "date", "team1", "team2"), ("time", "score"), index)
        for key in ("round", "date", "team1", "team2"):
            _text(row[key], row=index)
        _check(row["round"] in rounds, "ROUND", index)
        _check(row["team1"] in teams and row["team2"] in teams, "UNKNOWN_TEAM", index)
        home, away = teams[row["team1"]].external_id, teams[row["team2"]].external_id
        _check(home != away, "SELF_MATCH", index)
        _check(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["date"]), "DATE", index)
        try:
            when = date.fromisoformat(row["date"])
        except ValueError:
            raise OpenFootballError("DATE", index) from None
        _check(mapping.date_start <= when <= mapping.date_end, "SCOPE", index)
        source_time = row.get("time")
        if source_time is not None:
            _check(type(source_time) is str and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",
                                                         source_time), "TIME", index)
        ft, ht, et, penalties = None, None, None, None
        score_state = "ABSENT"
        if "score" in row:
            _shape(row["score"], (), ("ft", "ht", "et", "p"), index)
            score_state = "COMPONENTS" if row["score"] else "EMPTY"
            ft = _score(row["score"]["ft"], index) if "ft" in row["score"] else None
            ht = _score(row["score"]["ht"], index) if "ht" in row["score"] else None
            et = _score(row["score"]["et"], index) if "et" in row["score"] else None
            penalties = _score(row["score"]["p"], index) if "p" in row["score"] else None
            _check(ht is None or ft is None or all(f >= h for f, h in zip(ft, ht)), "SCORE", index)
        round_binding = rounds[row["round"]]
        external_id = "composite:" + digest({"domain": "openfootball-composite-fixture-v1",
            "dataset": manifest.dataset_id, "stage": round_binding.stage_key,
            "round": round_binding.round_key, "date": row["date"], "home": home, "away": away})
        _check(external_id not in seen, "DUPLICATE", index)
        seen.add(external_id)
        status = FixtureStatus.FINISHED if ft is not None else FixtureStatus.UNKNOWN
        origin = "source_ft_present" if ft is not None else "unscored_unknown"
        review_reference = None
        if external_id in reviews:
            _check(ft is None, "SCORE_STATUS", index)
            status, origin = reviews[external_id].status, "explicit_operator_review"
            review_reference = reviews[external_id].evidence.reference
            used_reviews.add(external_id)
        result.append((external_id, row["date"], source_time, row["round"], home, away, ft, ht, status, origin,
                       review_reference, et, penalties, score_state))
    _check(used_reviews == set(reviews), "COVERAGE")
    return sorted(result)


def _prepare(document, *, manifest, mapping, observed_at, registry, versions, previous, input_sha256):
    _check(type(manifest) is OpenFootballManifest, "MANIFEST")
    manifest.validate()
    utc_observation(observed_at)
    if manifest.acquired_at is not None:
        _check(manifest.acquired_at <= observed_at, "UTC")
        _check(input_sha256 is not None and input_sha256 == manifest.content_sha256, "CONTENT_MISMATCH")
    teams, rounds, reviews = _mapping(mapping)
    rows = _rows(document, mapping, manifest, teams, rounds, reviews)
    _check(all(row[6] is None or date.fromisoformat(row[1]) <= observed_at.date() for row in rows), "SCORE_STATUS")
    _check(type(registry) is IdentityRegistry and type(versions) is VersionLedger, "SCHEMA")
    before_registry, before_ledger = registry.to_bytes(), versions.to_bytes()
    # Transactional proposal: even late ledger/DQ errors cannot mutate caller state.
    working = IdentityRegistry.from_bytes(before_registry)
    ledger = VersionLedger.from_bytes(before_ledger)

    def register(kind, key, **kwargs):
        return working.register(PROVIDER, kind, key, evidence=mapping.evidence, **kwargs)

    def identity(kind, external_id):
        return ProviderIdentity(PROVIDER, EntityKind(kind.value), external_id)

    root = register(IdentityKind.PROVIDER, PROVIDER)
    comp = register(IdentityKind.COMPETITION, manifest.competition_key, parent_id=root.id, team_type=TeamType.CLUB)
    season = register(IdentityKind.SEASON, manifest.season_key, parent_id=comp.id)
    competition_model = Competition(comp.id, identity(comp.kind, comp.external_id), manifest.competition_name, TeamType.CLUB)
    season_model = Season(season.id, identity(season.kind, season.external_id), comp.id, manifest.season_label, "openfootball-results-v2")
    participants, stages, round_models = {}, {}, {}
    for binding in sorted(teams.values(), key=lambda b: b.source_name):
        record = register(IdentityKind.PARTICIPANT, binding.external_id, parent_id=root.id, team_type=TeamType.CLUB)
        working.confirm_participation(season.id, record.id, evidence=mapping.evidence)
        participants[binding.external_id] = Participant(record.id, identity(record.kind, record.external_id),
                                                       binding.display_name, TeamType.CLUB)
    for binding in sorted(rounds.values(), key=lambda b: b.source_round):
        stage = register(IdentityKind.STAGE, binding.stage_key, parent_id=season.id, stage_kind=binding.kind)
        record = register(IdentityKind.ROUND, binding.round_key, parent_id=stage.id, order=binding.order)
        stages[binding.stage_key] = Stage(stage.id, identity(stage.kind, stage.external_id), season.id,
                                          binding.stage_name, binding.kind)
        round_models[binding.stage_key, binding.round_key] = Round(record.id, identity(record.kind, record.external_id),
                                                                  stage.id, binding.source_round, binding.order)
    old_keys = {r.external_id for r in registry.records if r.kind is IdentityKind.FIXTURE and r.parent_id == season.id}
    _check(not old_keys or old_keys == {row[0] for row in rows}, "IDENTITY_REVIEW_REQUIRED")
    metadata_ref = StreamRef(season.id, StreamKind.METADATA)
    if ledger.current(metadata_ref) is not None:
        _check(type(previous) is OpenFootballProposal and previous.registry_after_state == before_registry and
               previous.schema_version == 2 and previous.ledger_after_state == before_ledger and
               previous.manifest.dataset_id == manifest.dataset_id,
               "REVIEW_REQUIRED")
    else:
        _check(previous is None, "REVIEW_REQUIRED")
    prior = {f.id: f for f in previous.fixtures} if previous is not None else {}
    if previous is not None:
        old_ids = {r.id for r in registry.records if r.kind is IdentityKind.FIXTURE and r.parent_id == season.id}
        _check(type(previous.fixtures) is tuple and len(prior) == len(previous.fixtures) and
               set(prior) == old_ids, "REVIEW_REQUIRED")
        for old in prior.values():
            _check(type(old) is OpenFootballFixture, "REVIEW_REQUIRED")
            state = ledger.current(StreamRef(old.id, StreamKind.FIXTURE))
            _check(state is not None and state.versions[-1].number == old.local_revision and
                   state.versions[-1].semantic_digest == fixture_fingerprint(old), "REVIEW_REQUIRED")
    fixtures, receipts = [], []
    for key, when, local_time, source_round, home, away, ft, ht, status, origin, review_reference, et, penalties, score_state in rows:
        binding = rounds[source_round]
        record = register(IdentityKind.FIXTURE, key, parent_id=season.id,
                          participants=(participants[home].id, participants[away].id))
        item = OpenFootballFixture(record.id, identity(record.kind, key), season.id, stages[binding.stage_key].id,
            round_models[binding.stage_key, binding.round_key].id, participants[home].id, participants[away].id,
            when, local_time, source_round, ft, ht, status, origin, review_reference,
            source_et=et, source_p=penalties, source_score_state=score_state,
            result_availability="REPORTED" if ft is not None else "MISSING",
            score_quality="AMBIGUOUS_SOURCE_COMPONENTS" if et is not None or penalties is not None else
                          "REPORTED_FULL_TIME_UNKNOWN_PERIOD" if ft is not None else "MISSING_RESULT")
        old = prior.get(item.id)
        _check(old is None or old.status is not FixtureStatus.FINISHED or status is FixtureStatus.FINISHED,
               "SCORE_STATUS")
        ref = StreamRef(item.id, StreamKind.FIXTURE)
        _check(ledger.current(ref) is None or previous is not None, "REVIEW_REQUIRED")
        # No Git commit is passed as a global provider revision/sequence.
        receipt = ledger.observe(ref, fixture_fingerprint(item), observed_at=observed_at,
                                 expected_version=ledger.version(ref))
        fixtures.append(replace(item, local_revision=receipt.local_content_version))
        receipts.append(receipt)
    fixture_tuple = tuple(sorted(fixtures, key=lambda f: f.id))
    participant_tuple = tuple(sorted(participants.values(), key=lambda p: p.id))
    stage_tuple = tuple(sorted(stages.values(), key=lambda s: s.id))
    round_tuple = tuple(sorted(round_models.values(), key=lambda r: r.id))
    metadata = {"competition": primitive(competition_model), "season": primitive(season_model),
        "participants": primitive(participant_tuple), "stages": primitive(stage_tuple), "rounds": primitive(round_tuple)}
    metadata_digest = digest({"domain": "openfootball-metadata-v2", "content": metadata})
    receipts.append(ledger.observe(metadata_ref, metadata_digest, observed_at=observed_at,
                                    expected_version=ledger.version(metadata_ref)))
    semantic = digest({"domain": "openfootball-dataset-semantic-v2", "metadata": metadata_digest,
                       "fixtures": [fixture_fingerprint(f) for f in fixture_tuple]})
    limitations = []
    for fixture in fixture_tuple:
        codes = ["KICKOFF_UTC_UNKNOWN"]
        codes.append("REGULATION_SCORE_UNKNOWN" if fixture.source_ft is not None else "RESULT_MISSING")
        if fixture.source_ht is None:
            codes.append("HALF_TIME_SCORE_MISSING")
        if fixture.source_ft is None and any(component is not None for component in
                                             (fixture.source_ht, fixture.source_et, fixture.source_p)):
            codes.append("SCORE_COMPONENTS_WITHOUT_FT")
        if fixture.source_et is not None:
            codes.append("EXTRA_TIME_SEMANTICS_UNKNOWN")
        if fixture.source_p is not None:
            codes.append("PENALTY_SEMANTICS_UNKNOWN")
            if fixture.source_p[0] == fixture.source_p[1]:
                codes.append("TIED_PENALTY_PAIR")
        for code in sorted(codes):
            limitations.append(DQLimitation(code, fixture.id))
    return OpenFootballProposal(manifest, competition_model, season_model, participant_tuple, stage_tuple, round_tuple,
        fixture_tuple, observed_at, input_sha256, semantic, tuple(receipts), working.to_bytes(), ledger.to_bytes(),
        DQReport(tuple(limitations)), manifest.capabilities,
        result_coverage="INCOMPLETE" if any(f.result_availability == "MISSING" for f in fixture_tuple) else
                        "REPORTED_NOT_FULLY_VERIFIED")


def prepare_openfootball(source, *, mapping, observed_at, manifest=UCL_2024_25,
                         registry=None, versions=None, previous=None):
    """Accept bytes or an exact {name, matches} dict of parsed records. No I/O.

    Result states are inert proposals, not applied updates. A caller continues a
    SERIAL replay with registry/ledger reconstructed from the last result and
    passes that result as previous. Untrusted state needs a trusted fingerprint.
    """
    try:
        input_sha256 = None
        if type(source) is bytes:
            _check(0 < len(source) <= MAX_BYTES, "LIMIT")
            input_sha256 = sha256(source).hexdigest()
            source = json.loads(source.decode("utf-8"), object_pairs_hook=_object,
                                parse_constant=lambda _: (_ for _ in ()).throw(OpenFootballError("SCHEMA")))
        return _prepare(source, manifest=manifest, mapping=mapping, observed_at=observed_at,
            registry=registry if registry is not None else IdentityRegistry(),
            versions=versions if versions is not None else VersionLedger(), previous=previous, input_sha256=input_sha256)
    except OpenFootballError:
        raise
    except RegistryError as error:
        code = error.code if error.code in OpenFootballError.CODES else "IDENTITY_REVIEW_REQUIRED"
        raise OpenFootballError(code) from None
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise OpenFootballError("SCHEMA") from None
