"""No HTTP: six fabricated responses test the weaker, explicit consistency model."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch

from football_data_fakes import NOW, encode, make_payloads, observations
from provider_collection_fakes import make_scenario
from src.providers.collection import CollectionPlan
from src.providers.football_data import MappingError
from src.providers.models import ContractError
from src.providers.observed_window import Observation, response_fingerprint, verify_observed_window


class ObservedWindowTests(unittest.TestCase):
    def setUp(self):
        self.context, self.metadata, self.fixtures, self.standings = make_payloads()
        self.records = observations(self.metadata, self.fixtures, self.standings)

    def verified(self, **kwargs):
        return verify_observed_window(self.records, context=self.context, **kwargs)

    def invalid(self, code):
        with self.assertRaises(MappingError) as caught:
            self.verified()
        self.assertEqual(caught.exception.code, code)

    def change(self, index, document):
        values = list(self.records)
        values[index] = replace(values[index], payload=encode(document))
        self.records = tuple(values)

    def test_stable_window_has_bounded_provenance_and_no_server_revision_or_publication(self):
        result = self.verified()
        self.assertEqual(result.started_at, NOW)
        self.assertEqual(result.ended_at, NOW + timedelta(seconds=11))
        self.assertEqual(result.consistency, "OBSERVED_WINDOW_STABLE_NOT_ATOMIC")
        self.assertIsNone(result.source_revision)
        self.assertFalse(result.publish_authorized)
        self.assertEqual(len(result.receipts), 6)
        for i, receipt in enumerate(result.receipts):
            self.assertEqual(receipt.sequence, i + 1)
            self.assertLessEqual(receipt.received_bytes, 1024 * 1024)
            self.assertEqual(len(receipt.raw_sha256), 64)
            self.assertEqual(len(receipt.content_fingerprint), 64)
            self.assertFalse(hasattr(receipt, "payload"))
        self.assertTrue(result.mapping.ready_for_offline_use)

    def test_changed_metadata_fixture_or_table_fence_stops(self):
        for resource, index in (("metadata", 5), ("fixtures", 3), ("standings", 4)):
            with self.subTest(resource=resource):
                self.setUp()
                doc = deepcopy({"metadata": self.metadata, "fixtures": self.fixtures, "standings": self.standings}[resource])
                if resource == "metadata":
                    doc["currentSeason"]["currentMatchday"] += 1
                elif resource == "fixtures":
                    doc["matches"][0]["score"]["fullTime"]["home"] += 1
                else:
                    doc["standings"][0]["table"][0]["position"] = 36
                self.change(index, doc)
                self.invalid("SOURCE_CHANGED")

    def test_updated_timestamp_drift_is_not_treated_as_stable_revision(self):
        doc = deepcopy(self.fixtures)
        doc["matches"][0]["lastUpdated"] = (NOW - timedelta(minutes=1)).isoformat()
        self.change(3, doc)
        self.invalid("SOURCE_CHANGED")

    def test_identical_reads_with_cross_resource_table_drift_still_fail(self):
        doc = deepcopy(self.standings)
        doc["standings"][0]["table"][0]["goalsFor"] += 1
        doc["standings"][0]["table"][0]["goalDifference"] += 1
        for index in (2, 4):
            self.change(index, doc)
        self.invalid("DQ")

    def test_equal_fingerprints_do_not_make_wrong_season_valid(self):
        self.fixtures["matches"][0]["season"]["id"] = 999
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("SCOPE")

    def test_missing_or_extra_response_and_wrong_resource_order_fail(self):
        original = self.records
        for records in (original[:-1], (*original, original[-1]), (original[1], original[0], *original[2:])):
            with self.subTest(length=len(records)):
                self.records = records
                self.invalid("WINDOW")

    def test_backward_overlapping_or_naive_time_is_rejected(self):
        original = self.records
        for changed, code in (
            (replace(original[1], started_at=NOW - timedelta(seconds=1)), "WINDOW"),
            (replace(original[1], ended_at=NOW), "WINDOW"),
            (replace(original[1], started_at=NOW.replace(tzinfo=None)), "UTC"),
        ):
            with self.subTest(code=code):
                self.records = (original[0], changed, *original[2:])
                self.invalid(code)

    def test_window_duration_is_bounded_and_not_a_client_revision(self):
        self.records = (*self.records[:-1], replace(self.records[-1], ended_at=NOW + timedelta(seconds=121)))
        self.invalid("WINDOW")
        self.records = observations(self.metadata, self.fixtures, self.standings)
        for invalid in (True, 0, 301):
            with self.assertRaises(MappingError):
                self.verified(max_window_seconds=invalid)

    def test_reordered_records_and_json_keys_keep_fence_and_semantic_digest(self):
        original = self.verified()
        fixtures, standings = deepcopy(self.fixtures), deepcopy(self.standings)
        fixtures["matches"].reverse()
        standings["standings"].reverse()
        for table in standings["standings"]:
            table["table"].reverse()
        self.change(3, fixtures)
        self.change(4, standings)
        second = self.verified()
        self.assertEqual(original.semantic_digest, second.semantic_digest)
        self.assertNotEqual(second.receipts[1].raw_sha256, second.receipts[3].raw_sha256)
        self.assertEqual(second.receipts[1].content_fingerprint, second.receipts[3].content_fingerprint)
        self.assertEqual(response_fingerprint(b'{"b":2,"a":1}'), response_fingerprint(b'{"a":1,"b":2}'))

    def test_replay_at_another_collection_time_has_same_semantic_digest(self):
        first = self.verified()
        self.records = observations(self.metadata, self.fixtures, self.standings, offset=timedelta(hours=1))
        second = self.verified()
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertNotEqual(first.started_at, second.started_at)
        self.assertNotEqual(first.mapping.snapshot.freshness, second.mapping.snapshot.freshness)

    def test_unverified_status_is_not_promoted_to_real_source_acceptance(self):
        row = next(row for row in self.fixtures["matches"] if row["status"] == "TIMED")
        row["status"] = "SCHEDULED"
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("UNSUPPORTED")

    def test_retained_suspended_score_closes_window_gate(self):
        row = next(row for row in self.fixtures["matches"] if row["status"] == "TIMED")
        row["status"] = "SUSPENDED"
        row["score"]["fullTime"] = {"home": 1, "away": 1}
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("UNSUPPORTED")

    def test_window_gate_requires_home_and_away_evidence(self):
        self.standings["standings"] = [table for table in self.standings["standings"] if table["type"] == "TOTAL"]
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("DQ")

    def test_payload_limit_and_malformed_json_apply_before_candidate_creation(self):
        for raw, code in ((b'{}' * (1024 * 1024), "LIMIT"), (b'{broken', "MALFORMED")):
            self.records = (Observation("metadata", NOW, NOW + timedelta(seconds=1), raw), *self.records[1:])
            self.invalid(code)

    def test_duplicate_fixtures_are_not_deduplicated_by_fingerprinting(self):
        self.fixtures["matches"][-1] = deepcopy(self.fixtures["matches"][0])
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("DUPLICATE")

    def test_window_does_not_fetch_or_persist_or_weaken_original_collector(self):
        with patch("socket.create_connection", side_effect=AssertionError("offline only")), \
                patch("pathlib.Path.open", side_effect=AssertionError("no persistence")), \
                patch("subprocess.run", side_effect=AssertionError("no processes")):
            self.assertTrue(self.verified().mapping.ready_for_offline_use)
        original, rules = make_scenario()
        # The existing B collector still insists on a genuine non-null revision.
        with self.assertRaises(ContractError):
            CollectionPlan(replace(original, fixtures=(), standings=()), None, 144, 36, rules)

    def test_same_bad_table_arithmetic_is_not_fixed_to_match_fixtures(self):
        for table in self.standings["standings"]:
            for row in table["table"]:
                row["points"] += 1
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("DQ")

    def test_counter_evidence_is_not_uefa_rank_validation(self):
        result = self.verified()
        skipped = {check.rule_id for check in result.mapping.checks if check.status == "SKIP"}
        self.assertIn("provider.standings.tie_breakers", skipped)
        self.assertIn("football_data.points_adjustment_authority", skipped)

    def test_future_source_update_cannot_hide_behind_later_resource_read(self):
        # F0 ends at t=3, S0 at t=5: t=4 is invalid even though collection is later.
        self.fixtures["matches"][0]["lastUpdated"] = (NOW + timedelta(seconds=4)).isoformat()
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("UTC")
        self.setUp()
        # M0 ends at t=1: the subsequent fixture/table timestamps are irrelevant.
        self.metadata["lastUpdated"] = (NOW + timedelta(seconds=2)).isoformat()
        self.records = observations(self.metadata, self.fixtures, self.standings)
        self.invalid("UTC")

    def test_deeply_nested_unexpected_json_has_a_safe_error_code(self):
        raw = b'{"extra":' + b'[' * 80 + b'0' + b']' * 80 + b'}'
        with self.assertRaises(MappingError) as caught:
            response_fingerprint(raw)
        self.assertEqual(caught.exception.code, "LIMIT")
