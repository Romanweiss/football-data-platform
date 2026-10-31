"""Invented football only: no API keys, sockets, persistence or service access."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import ssl
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from src.providers import PROVIDER_STATUS
from src.providers.adapter import (
    AdapterFailure, LIVE_PROVIDER_ALLOWLIST, RequestPolicy, SyntheticAdapter,
    classify_failure, require_live_provider,
)
from src.providers.models import (
    ContractError, FixtureStatus, ProviderIdentity, EntityKind, Score, TeamType,
)
from src.providers.validation import (
    MAX_RESPONSE_BYTES, canonical_bytes, content_digest, parse_snapshot, validate_snapshot, validate_update,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = json.loads((FIXTURES / "provider_neutral_ucl.json").read_text(encoding="utf-8"))
UPDATES = json.loads((FIXTURES / "provider_neutral_updates.json").read_text(encoding="utf-8"))


def parse(document):
    return parse_snapshot(json.dumps(document, ensure_ascii=False).encode("utf-8"))


def changed_fixture(document, fixture_id, changes):
    document = deepcopy(document)
    next(item for item in document["fixtures"] if item["id"] == fixture_id).update(changes)
    return document


class ProviderContractsTests(unittest.TestCase):
    def setUp(self):
        self.document = deepcopy(BASE)
        self.snapshot = parse(self.document)

    def assert_invalid(self, document, code=None):
        with self.assertRaises(ContractError) as caught:
            parse(document)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertTrue(str(caught.exception).startswith("provider_contract:"))

    def test_all_required_status_scenarios(self):
        self.assertEqual({fixture.status for fixture in self.snapshot.fixtures}, {
            FixtureStatus.SCHEDULED, FixtureStatus.LIVE, FixtureStatus.FINISHED,
            FixtureStatus.POSTPONED, FixtureStatus.CANCELLED,
        })

    def test_optional_fields_missing_are_not_fabricated(self):
        self.assertIsNone(self.snapshot.stages[0].group)
        self.assertIsNone(self.snapshot.freshness.published_at)
        self.assertFalse(hasattr(self.snapshot.fixtures[0], "xg"))
        self.assertTrue(self.snapshot.partial)

    def test_future_scores_remain_null_not_zero(self):
        future = next(f for f in self.snapshot.fixtures if f.id == "fixture:scheduled")
        self.assertEqual(future.score, Score())
        self.assertIsNone(future.score.regulation_home)

    def test_extra_time_is_additional_and_penalties_separate(self):
        fixtures = {item.id: item for item in self.snapshot.fixtures}
        score = fixtures["fixture:extra"].score
        self.assertEqual(score.regulation_home + score.extra_home, 3)
        self.assertEqual(fixtures["fixture:penalties"].score.penalties_home, 4)

    def test_two_leg_tie_preserves_orientation_and_identity(self):
        legs = sorted((f for f in self.snapshot.fixtures if f.tie_id), key=lambda f: f.leg)
        self.assertEqual([f.leg for f in legs], [1, 2])
        self.assertEqual(legs[0].home_id, legs[1].away_id)

    def test_internal_and_external_ids_are_not_interchangeable(self):
        self.assertNotEqual(self.snapshot.competition.id, self.snapshot.competition.identity.external_id)
        self.assertEqual(self.snapshot.season.label, "2026/27")
        self.assertEqual(self.snapshot.season.identity.external_id, "2026")

    def test_normalization_roundtrip_is_idempotent(self):
        payload = canonical_bytes(self.snapshot)
        self.assertEqual(payload, canonical_bytes(parse_snapshot(payload)))
        self.assertEqual(self.snapshot, parse_snapshot(payload))

    def test_response_order_does_not_change_digest(self):
        for name in ("stages", "rounds", "participants", "fixtures", "standings", "ties", "capabilities"):
            self.document[name].reverse()
        self.assertEqual(content_digest(self.snapshot), content_digest(parse(self.document)))

    def test_freshness_not_part_of_semantic_identity(self):
        self.document["freshness"]["checked_at"] = "2026-10-30T12:00:00Z"
        self.assertEqual(content_digest(self.snapshot), content_digest(parse(self.document)))
        self.assertNotEqual(canonical_bytes(self.snapshot), canonical_bytes(parse(self.document)))

    def test_utc_normalization_and_equivalence(self):
        self.document["fixtures"][0]["kickoff"] = "2026-11-10T21:00:00+03:00"
        self.assertEqual(parse(self.document), self.snapshot)

    def test_invalid_timestamps_are_rejected(self):
        for timestamp in ("2026-01-01", "2026-11-10T18:00:00", "2026-13-10T18:00:00Z",
                          "2026-11-10 18:00:00Z", "2026-11-10T18:00:00+25:00",
                          "2026-11-10T18:00:00+00:99", 123, True):
            with self.subTest(timestamp=timestamp):
                self.assert_invalid(changed_fixture(self.document, "fixture:scheduled", {"kickoff": timestamp}))

    def test_typed_models_are_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.snapshot.provider = "other"

    def test_direct_model_construction_does_not_coerce(self):
        for value in (True, "1", -1, 101, 1.5):
            with self.subTest(value=value), self.assertRaises(ContractError):
                Score(regulation_home=value, regulation_away=0)
        with self.assertRaises(ContractError):
            ProviderIdentity("synthetic", "fixture", "7")
        with self.assertRaises(ContractError):
            replace(self.snapshot.fixtures[0], updated_at=datetime(2026, 1, 1))

    def test_provider_id_validation(self):
        for value in ("", "https://user:password@host/", "../escape", "id\nsecret", "a" * 161, 12):
            with self.subTest(value=value), self.assertRaises(ContractError):
                ProviderIdentity("synthetic", EntityKind.FIXTURE, value)

    def test_named_malformed_synthetic_scenarios(self):
        for name in ("duplicate_external_id", "malformed_timestamp", "invalid_participants",
                     "missing_reference", "wrong_round_stage"):
            scenario = UPDATES[name]
            with self.subTest(name=name):
                self.assert_invalid(changed_fixture(self.document, scenario["fixture_id"], scenario["changes"]))

    def test_duplicate_canonical_ids_are_rejected_not_dropped(self):
        self.document["fixtures"].append(deepcopy(self.document["fixtures"][0]))
        self.assert_invalid(self.document, "DUPLICATE")

    def test_duplicate_ids_in_every_entity_collection(self):
        for name in ("stages", "rounds", "participants", "ties"):
            document = deepcopy(self.document)
            document[name].append(deepcopy(document[name][0]))
            with self.subTest(name=name):
                self.assert_invalid(document, "DUPLICATE")

    def test_provider_and_entity_kind_scope(self):
        for changes in ({"provider": "other"}, {"entity_kind": "participant"}):
            document = deepcopy(self.document)
            document["fixtures"][0]["identity"].update(changes)
            self.assert_invalid(document)

    def test_foreign_competition_season_stage_round_references(self):
        for field in ("season_id", "stage_id", "round_id", "home_id", "away_id", "tie_id"):
            with self.subTest(field=field):
                self.assert_invalid(changed_fixture(self.document, "fixture:scheduled", {field: "absent"}))
        self.document["season"]["competition_id"] = "absent"
        self.assert_invalid(self.document, "REFERENCE")

    def test_club_and_national_team_mixing_is_rejected(self):
        self.document["participants"][0]["team_type"] = "national"
        self.assert_invalid(self.document, "REFERENCE")

    def test_national_teams_and_groups_can_use_same_contract(self):
        self.document["competition"]["team_type"] = "national"
        for participant in self.document["participants"]:
            participant["team_type"] = "national"
        self.document["stages"][0].update(kind="group", division="A", group="1")
        self.assertEqual(parse(self.document).competition.team_type, TeamType.NATIONAL)

    def test_round_order_is_unique_within_stage_not_globally(self):
        self.assertEqual([r.order for r in self.snapshot.rounds], [1, 1])
        duplicate = deepcopy(self.document["rounds"][0])
        duplicate.update(id="round:duplicate", identity={"provider": "synthetic", "entity_kind": "round", "external_id": "duplicate"})
        self.document["rounds"].append(duplicate)
        self.assert_invalid(self.document, "DUPLICATE")

    def test_scores_require_pairs_and_status_consistency(self):
        for score in ({"regulation_home": 1}, {"extra_home": 0, "extra_away": 0},
                      {"regulation_home": -1, "regulation_away": 0},
                      {"regulation_home": True, "regulation_away": 0}):
            self.assert_invalid(changed_fixture(self.document, "fixture:scheduled", {"score": score}))
        self.assert_invalid(changed_fixture(self.document, "fixture:finished", {"score": {}}), "SCORE_STATUS")
        for status in ("scheduled", "postponed", "cancelled", "unknown"):
            self.assert_invalid(changed_fixture(self.document, "fixture:finished", {"status": status}), "SCORE_STATUS")

    def test_live_may_have_unknown_score(self):
        document = changed_fixture(self.document, "fixture:live", {"score": {}})
        self.assertIsNone(next(f for f in parse(document).fixtures if f.status == FixtureStatus.LIVE).score.regulation_home)

    def test_extra_time_cannot_appear_in_league_phase(self):
        self.assert_invalid(changed_fixture(self.document, "fixture:finished", {"score": {
            "regulation_home": 1, "regulation_away": 1, "extra_home": 1, "extra_away": 0}}), "SCORE_STATUS")

    def test_penalty_shootout_requires_tied_single_match_and_winner(self):
        for score in ({"regulation_home": 2, "regulation_away": 1, "penalties_home": 4, "penalties_away": 3},
                      {"regulation_home": 1, "regulation_away": 1, "penalties_home": 4, "penalties_away": 4},
                      {"regulation_home": 1, "regulation_away": 1}):
            self.assert_invalid(changed_fixture(self.document, "fixture:penalties", {"score": score}), "SCORE_STATUS")

    def test_two_leg_penalties_require_tied_aggregate(self):
        self.assert_invalid(changed_fixture(self.document, "fixture:leg-1", {"score": {
            "regulation_home": 2, "regulation_away": 0}}), "SCORE_STATUS")

    def test_penalties_and_extra_time_cannot_be_on_first_leg(self):
        for score in ({"regulation_home": 1, "regulation_away": 1, "penalties_home": 4, "penalties_away": 3},
                      {"regulation_home": 1, "regulation_away": 1, "extra_home": 1, "extra_away": 0}):
            self.assert_invalid(changed_fixture(self.document, "fixture:leg-1", {"score": score}), "SCORE_STATUS")

    def test_tie_leg_and_participant_integrity(self):
        for change in ({"leg": 1}, {"leg": 3}, {"leg": None}, {"away_id": "team:gold"},
                       {"home_id": "team:red", "away_id": "team:blue"}):
            with self.subTest(change=change):
                self.assert_invalid(changed_fixture(self.document, "fixture:leg-2", change))

    def test_duplicate_standings_entries_not_shared_rank(self):
        self.assertEqual(sum(row.rank == 2 for row in self.snapshot.standings), 2)
        self.document["standings"].append(deepcopy(self.document["standings"][0]))
        self.assert_invalid(self.document, "DUPLICATE")

    def test_standings_arithmetic_and_deductions(self):
        self.document["standings"][0].update(adjustment=-1, points=2)
        parse(self.document)
        self.document["standings"][0]["played"] = 2
        self.assert_invalid(self.document, "SCORE_STATUS")

    def test_standings_references_and_stage_kind(self):
        for changes in ({"participant_id": "absent"}, {"stage_id": "stage:knockout"}):
            document = deepcopy(self.document)
            document["standings"][0].update(changes)
            self.assert_invalid(document)

    def test_synthetic_36_participant_table(self):
        for number in range(4, 36):
            participant = deepcopy(self.document["participants"][0])
            participant.update(id=f"team:test-{number}", name=f"Test club {number}")
            participant["identity"]["external_id"] = f"test-{number}"
            self.document["participants"].append(participant)
            entry = deepcopy(self.document["standings"][2])
            entry.update(participant_id=participant["id"], rank=number + 1)
            self.document["standings"].append(entry)
        self.assertEqual(len(parse(self.document).standings), 36)

    def test_capabilities_never_imply_missing_metrics(self):
        self.document["capabilities"][2]["availability"] = "declared"
        self.assert_invalid(self.document, "CAPABILITY")
        self.document["standings"] = []
        parse(self.document)

    def test_duplicate_capabilities_rejected(self):
        self.document["capabilities"].append(deepcopy(self.document["capabilities"][0]))
        self.assert_invalid(self.document, "DUPLICATE")

    def test_freshness_order_and_explicit_stale_clock(self):
        freshness = self.snapshot.freshness
        self.assertFalse(freshness.is_stale(now=freshness.checked_at, max_age_seconds=60))
        self.assertTrue(freshness.is_stale(now=freshness.checked_at + timedelta(seconds=61), max_age_seconds=60))
        self.document["freshness"]["checked_at"] = "2026-10-28T12:00:00Z"
        self.assert_invalid(self.document, "FRESHNESS")

    def test_provider_updated_at_cannot_be_after_collection(self):
        self.document["freshness"]["provider_updated_at"] = "2026-10-30T12:00:00Z"
        self.assert_invalid(self.document, "FRESHNESS")

    def test_future_fixture_revision_timestamp_rejected(self):
        self.assert_invalid(changed_fixture(self.document, "fixture:scheduled", {
            "updated_at": "2026-10-30T12:00:00Z"}), "FRESHNESS")

    def test_finished_and_live_cannot_have_future_kickoff(self):
        for fixture_id in ("fixture:finished", "fixture:live"):
            self.assert_invalid(changed_fixture(self.document, fixture_id, {
                "kickoff": "2026-11-10T18:00:00Z"}), "FRESHNESS")

    def test_stale_clock_type_and_timezone_are_strict(self):
        for now in ("2026-10-29", datetime(2026, 10, 29)):
            with self.assertRaises(ContractError):
                self.snapshot.freshness.is_stale(now=now, max_age_seconds=60)

    def test_no_unknown_fields_or_silent_type_coercion(self):
        for change in ({"status": "new_vendor_state"}, {"revision": True}, {"revision": "1"},
                       {"provider_secret": "synthetic-secret-sentinel"}):
            self.assert_invalid(changed_fixture(self.document, "fixture:scheduled", change))
        self.document["partial"] = "false"
        self.assert_invalid(self.document, "TYPE")

    def test_duplicate_json_keys_nonfinite_and_malformed_json(self):
        for payload in (b'{"provider":"synthetic","provider":"other"}', b'{"x":NaN}',
                        b'{"x":Infinity}', b'{', b'\xff', b'[]', b'null', b'"url"'):
            with self.subTest(payload=payload), self.assertRaises(ContractError):
                parse_snapshot(payload)

    def test_depth_and_payload_bounds(self):
        for payload in (b' ' * (MAX_RESPONSE_BYTES + 1), b'[' * 2000 + b']' * 2000):
            with self.assertRaises(ContractError):
                parse_snapshot(payload)
        self.document["fixtures"] *= 223  # 2007 records, below the byte budget.
        self.assert_invalid(self.document, "LIMIT")

    def test_parse_errors_do_not_echo_payload(self):
        secret = "synthetic-secret-sentinel"
        for value in ({"password": secret}, {"provider": secret}):
            with self.assertRaises(ContractError) as caught:
                parse(value)
            self.assertNotIn(secret, str(caught.exception))

    def test_same_snapshot_replay_and_correction_digests(self):
        validate_update(self.snapshot, self.snapshot)
        for name in ("rescheduled", "result_correction"):
            scenario = UPDATES[name]
            after = parse(changed_fixture(self.document, scenario["fixture_id"], scenario["changes"]))
            validate_update(self.snapshot, after)
            validate_update(after, after)
            self.assertNotEqual(content_digest(self.snapshot), content_digest(after))
            self.assertEqual({f.id for f in self.snapshot.fixtures}, {f.id for f in after.fixtures})

    def test_changed_payload_requires_monotonic_revision(self):
        for revision in (1,):
            after = parse(changed_fixture(self.document, "fixture:finished", {"score": {
                "regulation_home": 3, "regulation_away": 1}, "revision": revision}))
            with self.assertRaisesRegex(ContractError, "REVISION"):
                validate_update(self.snapshot, after)

    def test_finished_cannot_silently_return_to_scheduled(self):
        after = parse(changed_fixture(self.document, "fixture:finished", {
            "status": "scheduled", "score": {}, "revision": 2}))
        with self.assertRaisesRegex(ContractError, "TRANSITION"):
            validate_update(self.snapshot, after)

    def test_postponed_can_resume_and_cancelled_can_be_corrected(self):
        for fixture_id in ("fixture:postponed", "fixture:cancelled"):
            after = parse(changed_fixture(self.document, fixture_id, {"status": "scheduled", "revision": 2}))
            validate_update(self.snapshot, after)

    def test_missing_rows_do_not_mean_delete(self):
        self.document["fixtures"].pop(0)
        after = parse(self.document)
        with self.assertRaisesRegex(ContractError, "CONFLICT"):
            validate_update(self.snapshot, after)

    def test_revisions_cannot_reassign_provider_or_teams(self):
        after = parse(changed_fixture(self.document, "fixture:scheduled", {"away_id": "team:gold", "revision": 2}))
        with self.assertRaisesRegex(ContractError, "IDENTITY"):
            validate_update(self.snapshot, after)

    def test_updates_cannot_reassign_other_canonical_entity_ids(self):
        for collection in ("stages", "rounds", "participants", "ties"):
            document = deepcopy(self.document)
            document[collection][0]["identity"]["external_id"] = "reassigned"
            after = parse(document)
            with self.subTest(collection=collection), self.assertRaisesRegex(ContractError, "IDENTITY"):
                validate_update(self.snapshot, after)

    def test_update_cannot_cross_context(self):
        after = replace(self.snapshot, season=replace(self.snapshot.season, label="2027/28"))
        with self.assertRaisesRegex(ContractError, "SCOPE"):
            validate_update(self.snapshot, after)


class SyntheticAdapterTests(unittest.TestCase):
    def test_adapter_surface_and_counts(self):
        adapter = SyntheticAdapter.from_bytes(json.dumps(BASE).encode())
        self.assertEqual(adapter.get_competition().id, BASE["competition"]["id"])
        self.assertEqual(adapter.get_season().label, "2026/27")
        self.assertEqual(len(adapter.get_fixtures()), 9)
        self.assertEqual(len(adapter.get_results()), 5)
        self.assertEqual(len(adapter.get_standings()), 4)
        self.assertEqual(adapter.digest, content_digest(adapter.snapshot))

    def test_adapter_replay_is_stable(self):
        first = SyntheticAdapter.from_bytes(json.dumps(BASE).encode())
        second = SyntheticAdapter.from_bytes(canonical_bytes(first.snapshot))
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.get_fixtures(), second.get_fixtures())

    def test_empty_results_are_explicit_not_fabricated(self):
        document = deepcopy(BASE)
        document.update(fixtures=[], standings=[], ties=[])
        adapter = SyntheticAdapter.from_bytes(json.dumps(document).encode())
        self.assertEqual(adapter.get_fixtures(), ())
        self.assertEqual(adapter.get_results(), ())
        self.assertEqual(adapter.get_standings(), ())

    def test_synthetic_adapter_refuses_other_provider_payloads(self):
        document = deepcopy(BASE)
        document["provider"] = "other"
        for resource in ("competition", "season"):
            document[resource]["identity"]["provider"] = "other"
        for resource in ("stages", "rounds", "participants", "fixtures", "ties"):
            for record in document[resource]:
                record["identity"]["provider"] = "other"
        with self.assertRaisesRegex(AdapterFailure, "INVALID_PAYLOAD"):
            SyntheticAdapter.from_bytes(json.dumps(document).encode())

    def test_no_network_environment_or_persistence_access(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
             patch("builtins.open", side_effect=AssertionError("file access forbidden")), \
             patch("os.getenv", side_effect=AssertionError("credentials forbidden")):
            adapter = SyntheticAdapter.from_bytes(json.dumps(BASE).encode())
            validate_snapshot(adapter.snapshot)
            adapter.get_fixtures()

    def test_live_provider_and_arbitrary_urls_are_denied(self):
        self.assertEqual(PROVIDER_STATUS, "PROVIDER_UNDECIDED")
        self.assertFalse(LIVE_PROVIDER_ALLOWLIST)
        for provider in ("api-football", "football-data", "https://127.0.0.1/", "file:///secret", "synthetic"):
            with self.assertRaisesRegex(AdapterFailure, "LIVE_INTEGRATION_DISABLED"):
                require_live_provider(provider)
        with self.assertRaises(AdapterFailure):
            SyntheticAdapter.from_bytes(b'https://example.invalid')

    def test_error_codes_are_fixed_not_external_exception_text(self):
        secret = "synthetic-secret-sentinel"
        errors = [(TimeoutError(secret), "TIMEOUT"), (ssl.SSLCertVerificationError(secret), "TLS"),
                  (ValueError(secret), "INVALID_PAYLOAD")]
        for status, code in ((401, "AUTHENTICATION"), (403, "ACCESS_DENIED"),
                             (429, "RATE_LIMIT"), (503, "TRANSIENT")):
            errors.append((HTTPError("https://user:" + secret + "@host/", status, secret, {}, None), code))
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            for error, code in errors:
                failure = classify_failure(error)
                self.assertEqual(failure.code, code)
                self.assertNotIn(secret, repr(failure))
                self.assertFalse(hasattr(failure, "original_error"))
        self.assertEqual(output.getvalue(), "")

    def test_malformed_adapter_diagnostics_are_safe(self):
        with self.assertRaises(AdapterFailure) as caught:
            SyntheticAdapter.from_bytes(b'{"secret":"synthetic-secret-sentinel"}')
        self.assertEqual(str(caught.exception), "provider_adapter:INVALID_PAYLOAD")
        self.assertTrue(caught.exception.__suppress_context__)

    def test_live_policy_is_bounded_contract_not_executed_http(self):
        policy = RequestPolicy()
        self.assertEqual([policy.retry_delay(n) for n in (1, 2)], [1, 2])
        self.assertEqual(policy.max_attempts, 3)
        for change in ({"timeout_seconds": 0}, {"max_attempts": 4}, {"max_pages": 11},
                       {"requests_per_minute": 61}, {"max_response_bytes": MAX_RESPONSE_BYTES + 1},
                       {"timeout_seconds": True}):
            with self.assertRaises(ContractError):
                replace(policy, **change)
        with self.assertRaises(ContractError):
            policy.retry_delay(3)


if __name__ == "__main__":
    unittest.main()
