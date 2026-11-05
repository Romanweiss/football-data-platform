"""PET-2R source-score semantics and DQ. Artificial records, no files/network."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import unittest
from unittest.mock import patch

from src.providers.identity_registry import IdentityRegistry
from src.providers.models import Availability, Capability, ContractError, FixtureStatus
from src.providers.observed_versions import VersionLedger
from src.providers.openfootball import OpenFootballError, fixture_fingerprint, prepare_openfootball
from src.providers.validation import validate_snapshot
from test_openfootball import NOW, encode, mapping, payload


class OpenFootballRemediationTests(unittest.TestCase):
    def prepare(self, source=None, **kwargs):
        return prepare_openfootball(source if source is not None else payload(), mapping=mapping(),
            observed_at=kwargs.pop("observed_at", NOW), **kwargs)

    def with_score(self, score):
        source = payload()
        source["matches"][2]["score"] = score
        return source

    def target(self, proposal):
        return next(f for f in proposal.fixtures if f.match_date == "2025-04-01")

    def continued(self, previous, source=None, **kwargs):
        return self.prepare(source, registry=IdentityRegistry.from_bytes(previous.registry_after_state),
            versions=VersionLedger.from_bytes(previous.ledger_after_state), previous=previous,
            observed_at=kwargs.pop("observed_at", NOW + timedelta(seconds=1)), **kwargs)

    def test_empty_absent_and_partial_scores_preserve_fixture_and_unknown_result(self):
        for score, state in ((None, "ABSENT"), ({}, "EMPTY"), ({"ht": [1, 0]}, "COMPONENTS"),
                             ({"et": [1, 0], "p": [4, 4]}, "COMPONENTS")):
            source = payload() if score is None else self.with_score(score)
            with self.subTest(state=state, score=score):
                result = self.prepare(source)
                item = self.target(result)
                self.assertEqual(3, len(result.fixtures))
                self.assertEqual("MISSING", item.result_availability)
                self.assertEqual(state, item.source_score_state)
                self.assertIsNone(item.source_ft)
                self.assertEqual(FixtureStatus.UNKNOWN, item.status)
                self.assertEqual(1, result.dq.counts["RESULT_MISSING"])
                self.assertEqual("INCOMPLETE", result.result_coverage)
                if state == "COMPONENTS":
                    self.assertEqual(1, result.dq.counts["SCORE_COMPONENTS_WITHOUT_FT"])

    def test_unknown_results_cannot_enter_standings_or_receive_points(self):
        result = self.prepare(self.with_score({}))
        self.assertEqual(Availability.UNAVAILABLE, next(c.availability for c in result.capabilities
                         if c.name is Capability.STANDINGS))
        for item in result.fixtures:
            self.assertFalse(item.standings_eligible)
            self.assertIsNone(item.points_home)
            self.assertIsNone(item.points_away)
        # The published canonical Snapshot/standings boundary is not weakened.
        with self.assertRaises(ContractError):
            validate_snapshot(result)

    def test_raw_extra_time_is_not_added_or_mapped_to_ninety_minutes(self):
        for et in ([0, 1], [3, 2]):  # Neither incremental nor inclusive semantics assumed.
            result = self.prepare(self.with_score({"ht": [0, 0], "ft": [1, 1], "et": et}))
            item = self.target(result)
            self.assertEqual((1, 1), item.source_ft)
            self.assertEqual(tuple(et), item.source_et)
            self.assertIsNone(item.regulation_score)
            self.assertIsNone(item.after_extra_time_score)
            self.assertEqual("REPORTED", item.result_availability)
            self.assertEqual(1, result.dq.counts["EXTRA_TIME_SEMANTICS_UNKNOWN"])

    def test_tied_and_unequal_raw_penalties_never_infer_winner(self):
        for penalties in ([4, 4], [1, 4], [0, 0]):
            with self.subTest(p=penalties):
                result = self.prepare(self.with_score({"ft": [1, 0], "et": [1, 0], "p": penalties}))
                item = self.target(result)
                self.assertEqual(tuple(penalties), item.source_p)
                self.assertIsNone(item.penalty_shootout_score)
                self.assertIsNone(item.winner_id)
                self.assertEqual("AMBIGUOUS_SOURCE_COMPONENTS", item.score_quality)
                self.assertEqual(1, result.dq.counts["PENALTY_SEMANTICS_UNKNOWN"])
                self.assertEqual(int(penalties[0] == penalties[1]), result.dq.counts.get("TIED_PENALTY_PAIR", 0))

    def test_zero_zero_is_only_reported_when_actually_present(self):
        item = self.target(self.prepare(self.with_score({"ft": [0, 0]})))
        self.assertEqual((0, 0), item.source_ft)
        self.assertEqual("REPORTED", item.result_availability)
        self.assertEqual(FixtureStatus.FINISHED, item.status)
        self.assertIsNone(item.winner_id)

    def test_all_limitations_are_structured_immutable_and_order_invariant(self):
        source = self.with_score({"ft": [0, 1], "et": [0, 1], "p": [4, 4]})
        result = self.prepare(source)
        source["matches"].reverse()
        reordered = self.prepare(source)
        self.assertEqual(result, reordered)
        self.assertEqual(0, result.dq.fatal_count)
        self.assertEqual(2, result.schema_version)
        self.assertTrue(all(d.severity == "NON_FATAL" and d.fixture_id in {f.id for f in result.fixtures}
                            for d in result.dq.limitations))
        with self.assertRaises(FrozenInstanceError):
            result.dq.fatal_count = 1
        counts = result.dq.counts
        counts.clear()
        self.assertTrue(result.dq.counts)  # Counts are a copy, not mutable shared state.

    def test_et_p_and_missing_score_corrections_keep_identity_and_change_semantics(self):
        initial = self.prepare(self.with_score({}))
        scored = self.continued(initial, self.with_score({"ft": [1, 0], "et": [1, 0], "p": [4, 4]}))
        corrected = self.continued(scored, self.with_score({"ft": [1, 0], "et": [2, 0], "p": [1, 4]}),
                                   observed_at=NOW + timedelta(seconds=2))
        items = [self.target(p) for p in (initial, scored, corrected)]
        self.assertEqual(1, len({i.id for i in items}))
        self.assertEqual([1, 2, 3], [i.local_revision for i in items])
        self.assertEqual(3, len({fixture_fingerprint(i) for i in items}))
        self.assertEqual(1, sum(r.changed for r in corrected.versions))
        self.assertNotIn("TIED_PENALTY_PAIR", corrected.dq.counts)

    def test_missing_to_empty_changes_source_state_not_identity(self):
        before = self.prepare()
        after = self.continued(before, self.with_score({}))
        self.assertEqual(self.target(before).id, self.target(after).id)
        self.assertEqual(2, self.target(after).local_revision)
        self.assertEqual("MISSING", self.target(after).result_availability)

    def test_replay_is_idempotent_and_source_commit_not_version_counter(self):
        source = self.with_score({"ft": [1, 0], "p": [4, 4]})
        initial = self.prepare(encode(source))
        replay = self.continued(initial, source)
        self.assertEqual(initial.semantic_digest, replay.semantic_digest)
        self.assertEqual(initial.dq, replay.dq)
        self.assertEqual(initial.fixtures, replay.fixtures)
        self.assertTrue(all(not v.changed and v.provider_revision is None for v in replay.versions))

    def test_input_is_not_modified_even_for_ambiguous_components(self):
        source = self.with_score({"ft": [1, 0], "et": [1, 0], "p": [4, 4]})
        original = deepcopy(source)
        result = self.prepare(source)
        source["matches"][2]["score"]["p"][0] = 99
        self.assertEqual([4, 4], original["matches"][2]["score"]["p"])
        self.assertEqual((4, 4), self.target(result).source_p)

    def test_invalid_components_and_unreviewed_fields_remain_fatal(self):
        for component in ("ht", "ft", "et", "p"):
            for invalid in ([-1, 0], [1, 101], [True, 0], [1.0, 0], [1], "1-0", None):
                with self.subTest(component=component, invalid=invalid), self.assertRaises(OpenFootballError) as raised:
                    self.prepare(self.with_score({component: invalid}))
                self.assertIn(raised.exception.diagnostic.code, ("SCORE", "NULL"))
                self.assertEqual("FATAL", raised.exception.diagnostic.severity)
        with self.assertRaisesRegex(OpenFootballError, "UNKNOWN_FIELD"):
            self.prepare(self.with_score({"arbitrary_optional_detail": [1, 0]}))
        with self.assertRaisesRegex(OpenFootballError, "SCORE"):
            self.prepare(self.with_score({"ht": [2, 0], "ft": [1, 0]}))

    def test_late_fatal_failure_does_not_apply_earlier_valid_observations(self):
        initial = self.prepare(self.with_score({"ft": [1, 0], "p": [4, 4]}))
        registry = IdentityRegistry.from_bytes(initial.registry_after_state)
        ledger = VersionLedger.from_bytes(initial.ledger_after_state)
        before = registry.to_bytes(), ledger.to_bytes()
        original_observe = VersionLedger.observe
        calls = []

        def fail_late(instance, *args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                raise OpenFootballError("VERSION_CONFLICT")
            return original_observe(instance, *args, **kwargs)

        with patch.object(VersionLedger, "observe", fail_late), self.assertRaisesRegex(OpenFootballError, "VERSION_CONFLICT"):
            self.prepare(self.with_score({"ft": [2, 0], "p": [1, 4]}), registry=registry, versions=ledger,
                         previous=initial, observed_at=NOW + timedelta(seconds=1))
        self.assertEqual(before, (registry.to_bytes(), ledger.to_bytes()))

    def test_legacy_normalized_contract_is_not_silently_reinterpreted(self):
        initial = self.prepare()
        legacy = replace(initial, schema_version=1)
        with self.assertRaisesRegex(OpenFootballError, "REVIEW_REQUIRED"):
            self.continued(legacy)


if __name__ == "__main__":
    unittest.main()
