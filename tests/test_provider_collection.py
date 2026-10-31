"""Offline pagination/reconciliation/failure injection; never real provider data."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import io
import json
import unittest
from unittest.mock import patch

from provider_collection_fakes import (
    FakeAdapter, NOW, SCENARIOS, VirtualClock, corrected, make_scenario, table_from_fixtures,
)
from src.providers.adapter import RequestPolicy
from src.providers.collection import (
    BoundedCollector, CollectionFailure, CollectionLimits, CollectionState, Completeness,
    FailureCode, FreshnessState, Page, Resource, decode_page, encode_page,
)
from src.providers.models import ContractError, FixtureStatus, Score
from src.providers.reconciliation import reconcile
from src.providers.validation import canonical_bytes, content_digest


def mutate(payload, function):
    document = json.loads(payload)
    function(document)
    return json.dumps(document).encode()


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.rules = make_scenario()
        self.clock = VirtualClock()

    def collect(self, *, source=None, snapshot=None, rules=None, policy=None, limits=None, previous=None, **kwargs):
        adapter = source or FakeAdapter(snapshot or self.snapshot, rules=self.rules if rules is None else rules, **kwargs)
        self.adapter = adapter
        return BoundedCollector(clock=self.clock, policy=policy or RequestPolicy(),
                                limits=limits or CollectionLimits()).collect(adapter, previous=previous)

    def assert_failure(self, result, code):
        self.assertEqual(result.state, CollectionState.FAILED)
        self.assertEqual(result.error, code)
        self.assertFalse(result.eligible_for_full_snapshot)
        self.assertIsNone(result.data)
        self.assertIsNone(result.semantic_digest)
        with self.assertRaisesRegex(CollectionFailure, "NOT_COMPLETE"):
            result.require_complete()

    def test_ucl_complete_counts_and_provenance(self):
        result = self.collect()
        self.assertTrue(result.eligible_for_full_snapshot)
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(result.completeness, Completeness.COMPLETE)
        self.assertEqual(result.freshness, FreshnessState.FRESH)
        self.assertEqual(result.entity_count, 180)
        self.assertEqual(result.page_count, 10)
        self.assertEqual(result.request_count, 12)
        self.assertEqual(len(result.require_complete().participants), 36)
        self.assertEqual(len(result.data.fixtures), 144)
        self.assertEqual(len(result.data.rounds), 8)
        self.assertEqual(sum(item.payload_bytes for item in result.provenance), result.bytes_received)
        self.assertTrue(all(len(item.payload_sha256) == len(item.cursor_sha256) == 64 for item in result.provenance))
        self.assertEqual(len(result.source_fence_sha256), 64)

    def test_each_uefa_synthetic_scenario(self):
        for name in ("ucl", "uel", "conference", "nations"):
            snapshot, rules = make_scenario(name)
            result = self.collect(snapshot=snapshot, rules=rules)
            with self.subTest(name=name):
                self.assertEqual(result.state, CollectionState.SUCCEEDED)
                self.assertEqual(len(result.data.fixtures), SCENARIOS[name]["expected_fixtures"])
                counter = next(c for c in result.checks if c.rule_id == "provider.standings.counters")
                self.assertEqual((counter.status, counter.observed), ("PASS", 0))
                self.assertEqual(result.eligible_for_full_snapshot, name != "nations")
                if name == "nations":
                    self.assertEqual({stage.division for stage in result.data.stages}, {"A", "B"})
                    self.assertTrue(all(stage.group == "1" for stage in result.data.stages))
                    self.assertEqual(result.completeness, Completeness.PARTIAL)

    def test_same_collection_replay_is_deterministic(self):
        first = self.collect()
        self.clock = VirtualClock(NOW + timedelta(minutes=10))
        second = self.collect(previous=first.data)
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(first.data, second.data)
        self.assertNotEqual(first.collected_at, second.collected_at)

    def test_page_size_and_input_order_do_not_change_semantics(self):
        first = self.collect(page_size=20)
        reversed_snapshot = replace(self.snapshot, fixtures=tuple(reversed(self.snapshot.fixtures)),
                                    standings=tuple(reversed(self.snapshot.standings)))
        second = self.collect(snapshot=reversed_snapshot, page_size=100)
        self.assertTrue(second.eligible_for_full_snapshot)
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertNotEqual(first.page_count, second.page_count)

    def test_result_and_nested_snapshot_are_immutable(self):
        result = self.collect()
        with self.assertRaises(FrozenInstanceError):
            result.page_count = 0
        with self.assertRaises(FrozenInstanceError):
            result.data.partial = True
        with self.assertRaises(ContractError):
            replace(result, error=FailureCode.DQ)

    def test_stale_is_separate_from_complete_collection(self):
        self.clock = VirtualClock(NOW + timedelta(hours=2))
        result = self.collect()
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(result.completeness, Completeness.COMPLETE)
        self.assertEqual(result.freshness, FreshnessState.STALE)
        self.assertFalse(result.eligible_for_full_snapshot)

    def test_source_partial_flag_cannot_be_published_as_full(self):
        result = self.collect(snapshot=replace(self.snapshot, partial=True))
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(result.completeness, Completeness.PARTIAL)
        self.assertFalse(result.eligible_for_full_snapshot)

    def test_page_partial_flag_cannot_be_published_as_full(self):
        result = self.collect(transform=lambda _a, _r, _c, payload: mutate(payload, lambda d: d.update(complete=False)))
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(result.completeness, Completeness.PARTIAL)
        self.assertTrue(result.data.partial)
        self.assertFalse(result.eligible_for_full_snapshot)

    def test_page_limit_stops_instead_of_truncating(self):
        result = self.collect(page_size=10)
        self.assert_failure(result, FailureCode.LIMIT)
        self.assertEqual(result.page_count, 10)

    def test_record_limit(self):
        result = self.collect(limits=replace(CollectionLimits(), max_entities=30))
        self.assert_failure(result, FailureCode.LIMIT)

    def test_byte_limit(self):
        result = self.collect(limits=replace(CollectionLimits(), max_bytes=100))
        self.assert_failure(result, FailureCode.LIMIT)

    def test_response_size_limit(self):
        result = self.collect(policy=replace(RequestPolicy(), max_response_bytes=100))
        self.assert_failure(result, FailureCode.LIMIT)

    def test_request_limit(self):
        result = self.collect(limits=replace(CollectionLimits(), max_requests=2))
        self.assert_failure(result, FailureCode.LIMIT)
        self.assertEqual(result.request_count, 2)

    def test_collection_time_limit(self):
        result = self.collect(limits=replace(CollectionLimits(), max_elapsed_seconds=3))
        self.assert_failure(result, FailureCode.LIMIT)
        self.assertLessEqual(self.clock.seconds, 3)

    def test_fractional_request_spacing_is_not_a_false_limit(self):
        result = self.collect(policy=replace(RequestPolicy(), requests_per_minute=29))
        self.assertTrue(result.eligible_for_full_snapshot)
        self.assertAlmostEqual(self.clock.seconds, 11 * 60 / 29)

    def test_request_spacing_covers_metadata_pages_and_retries(self):
        times = []
        failed = False
        def describe(_a, plan):
            times.append(self.clock.seconds)
            return plan
        def transform(_a, _r, _c, payload):
            nonlocal failed
            times.append(self.clock.seconds)
            if not failed:
                failed = True
                raise CollectionFailure(FailureCode.HTTP_503)
            return payload
        result = self.collect(transform=transform, describe_transform=describe)
        self.assertTrue(result.eligible_for_full_snapshot)
        self.assertTrue(all(later - earlier >= 2 for earlier, later in zip(times, times[1:])))

    def test_clock_wait_must_actually_advance(self):
        self.clock.wait = lambda _: None
        self.assert_failure(self.collect(), FailureCode.LIMIT)

    def test_limits_are_strict(self):
        for change in ({"max_entities": 3001}, {"max_bytes": 0}, {"max_requests": True},
                       {"max_wait_seconds": 61}, {"max_age_seconds": 0}):
            with self.assertRaises(ContractError):
                replace(CollectionLimits(), **change)

    def test_empty_continuing_page_is_incomplete(self):
        def transform(_a, resource, cursor, payload):
            return mutate(payload, lambda d: d.update(fixtures=[])) if resource is Resource.FIXTURES and cursor is None else payload
        self.assert_failure(self.collect(transform=transform), FailureCode.INCOMPLETE)

    def test_empty_terminal_nonzero_total_is_incomplete(self):
        self.assert_failure(self.collect(transform=lambda _a, _r, _c, body: mutate(
            body, lambda d: d.update(fixtures=[], next_cursor=None))), FailureCode.INCOMPLETE)

    def test_empty_zero_total_is_explicitly_supported(self):
        # Empty declared knockout scope, not an assertion that a UCL season has 0 fixtures.
        from src.providers.models import StageType
        context = replace(self.snapshot, stages=(replace(self.snapshot.stages[0], kind=StageType.KNOCKOUT),),
                          participants=(), fixtures=(), standings=(), partial=True)
        result = self.collect(snapshot=context, rules=())
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.entity_count, 0)
        self.assertFalse(result.eligible_for_full_snapshot)

    def test_missing_tail_page_fails_counts(self):
        self.assert_failure(self.collect(transform=lambda _a, _r, _c, body: mutate(
            body, lambda d: d.update(next_cursor=None))), FailureCode.INCOMPLETE)

    def test_missing_middle_page_or_wrong_echo_is_rejected(self):
        for changes in ({"sequence": 3}, {"request_cursor": "wrong"}, {"resource": "standings"}):
            def transform(_a, resource, cursor, body):
                return mutate(body, lambda d: d.update(changes)) if resource is Resource.FIXTURES and cursor == "page-2" else body
            with self.subTest(changes=changes):
                result = self.collect(transform=transform)
                self.assertEqual(result.state, CollectionState.FAILED)
                self.assertFalse(result.eligible_for_full_snapshot)

    def test_repeated_cursor_loop_is_bounded(self):
        def transform(_a, resource, cursor, body):
            return mutate(body, lambda d: d.update(next_cursor="page-2")) if cursor == "page-2" else body
        result = self.collect(transform=transform)
        self.assert_failure(result, FailureCode.CURSOR)
        self.assertLessEqual(result.request_count, 3)

    def test_invalid_cursor_grammar_is_rejected(self):
        for value in ("https://secret@host/", "../private", "", 123):
            with self.subTest(value=value):
                result = self.collect(transform=lambda _a, _r, _c, body: mutate(body, lambda d: d.update(next_cursor=value)))
                self.assert_failure(result, FailureCode.MALFORMED)

    def test_duplicate_page_with_different_cursor_is_rejected(self):
        first = None
        def transform(_a, resource, cursor, body):
            nonlocal first
            if resource is Resource.FIXTURES and cursor is None:
                first = json.loads(body)["fixtures"]
            if resource is Resource.FIXTURES and cursor == "page-2":
                return mutate(body, lambda d: d.update(fixtures=first))
            return body
        self.assert_failure(self.collect(transform=transform), FailureCode.DUPLICATE_PAGE)

    def test_duplicate_fixture_within_page_is_not_counted_twice(self):
        def transform(_a, _r, _c, body):
            def change(d):
                d["fixtures"][1] = d["fixtures"][0]
            return mutate(body, change)
        self.assert_failure(self.collect(transform=transform), FailureCode.DUPLICATE_ENTITY)

    def test_duplicate_provider_external_id_with_new_canonical_id(self):
        def transform(_a, _r, _c, body):
            def change(d):
                d["fixtures"][1]["identity"] = d["fixtures"][0]["identity"]
            return mutate(body, change)
        self.assert_failure(self.collect(transform=transform), FailureCode.DUPLICATE_ENTITY)

    def test_conflicting_revisions_across_pages_are_not_last_wins(self):
        first = None
        def transform(_a, resource, cursor, body):
            nonlocal first
            if resource is Resource.FIXTURES and cursor is None:
                first = json.loads(body)["fixtures"][0]
            if resource is Resource.FIXTURES and cursor == "page-2":
                def change(d):
                    revised = dict(first)
                    revised["revision"] = 2
                    d["fixtures"][0] = revised
                return mutate(body, change)
            return body
        self.assert_failure(self.collect(transform=transform), FailureCode.REVISION_CONFLICT)

    def test_total_count_changes_between_pages(self):
        self.assert_failure(self.collect(transform=lambda _a, _r, _c, body: mutate(
            body, lambda d: d.update(total=d["total"] + 1))), FailureCode.INCOMPLETE)

    def test_source_revision_change_between_pages(self):
        def transform(_a, resource, cursor, body):
            return mutate(body, lambda d: d.update(source_revision="synthetic-new")) if cursor == "page-2" else body
        self.assert_failure(self.collect(transform=transform), FailureCode.SOURCE_CHANGED)

    def test_final_source_fence_change(self):
        def description(adapter, plan):
            return replace(plan, source_revision="synthetic-new") if adapter.description_count == 2 else plan
        self.assert_failure(self.collect(describe_transform=description), FailureCode.SOURCE_CHANGED)

    def test_final_count_change_without_revision_change(self):
        def description(adapter, plan):
            return replace(plan, fixture_count=plan.fixture_count + 1) if adapter.description_count == 2 else plan
        self.assert_failure(self.collect(describe_transform=description), FailureCode.SOURCE_CHANGED)

    def test_corrections_between_successful_collections(self):
        first = self.collect()
        after = self.collect(snapshot=corrected(self.snapshot, self.rules), previous=first.data)
        self.assertTrue(after.eligible_for_full_snapshot)
        self.assertNotEqual(first.semantic_digest, after.semantic_digest)
        self.assertEqual({f.id for f in first.data.fixtures}, {f.id for f in after.data.fixtures})
        self.assertEqual(len(first.data.fixtures), len(after.data.fixtures))

    def test_same_revision_changed_result_fails(self):
        changed = corrected(self.snapshot, self.rules)
        changed = replace(changed, fixtures=tuple(replace(f, revision=1) for f in changed.fixtures))
        self.assert_failure(self.collect(snapshot=changed, previous=self.snapshot), FailureCode.CONTRACT)

    def test_rescheduling_preserves_fixture_identity(self):
        first = next(f for f in self.snapshot.fixtures if f.status is FixtureStatus.SCHEDULED)
        changed = replace(first, kickoff=first.kickoff + timedelta(days=1), revision=2)
        snapshot = replace(self.snapshot, fixtures=tuple(changed if f.id == first.id else f for f in self.snapshot.fixtures))
        result = self.collect(snapshot=snapshot, previous=self.snapshot)
        self.assertTrue(result.eligible_for_full_snapshot)
        self.assertEqual(len(result.data.fixtures), 144)

    def test_incorrect_standings_never_silently_recomputed(self):
        entry = self.snapshot.standings[0]
        invalid = replace(entry, goals_for=entry.goals_for + 1)
        snapshot = replace(self.snapshot, standings=(invalid, *self.snapshot.standings[1:]))
        result = self.collect(snapshot=snapshot)
        self.assert_failure(result, FailureCode.DQ)
        self.assertEqual(result.completeness, Completeness.COMPLETE)  # All pages arrived, but quality failed.
        self.assertEqual(next(c for c in result.checks if c.rule_id == "provider.standings.counters").status, "FAIL")

    def test_correction_without_standings_correction_is_dq_failure(self):
        changed = replace(corrected(self.snapshot, self.rules), standings=self.snapshot.standings)
        self.assert_failure(self.collect(snapshot=changed), FailureCode.DQ)

    def test_no_fake_uefa_tie_breaker_validation(self):
        shuffled_ranks = replace(self.snapshot, standings=tuple(replace(e, rank=1) for e in self.snapshot.standings))
        result = self.collect(snapshot=shuffled_ranks)
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(next(c for c in result.checks if c.rule_id == "provider.standings.tie_breakers").status, "SKIP")

    def test_point_adjustments_are_explicit_unverified_evidence(self):
        entry = self.snapshot.standings[0]
        snapshot = replace(self.snapshot, standings=(replace(entry, points=entry.points - 1, adjustment=-1), *self.snapshot.standings[1:]))
        result = self.collect(snapshot=snapshot)
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertEqual(next(c for c in result.checks if c.rule_id == "provider.standings.adjustments").status, "WARN")

    def test_schedule_constraints_not_only_fixture_total(self):
        first, second = self.snapshot.fixtures[:2]
        bad = replace(second, home_id=first.home_id, away_id=first.away_id, round_id=first.round_id)
        fixtures = (first, bad, *self.snapshot.fixtures[2:])
        snapshot = replace(self.snapshot, fixtures=fixtures, standings=table_from_fixtures(fixtures, self.rules))
        result = self.collect(snapshot=snapshot)
        self.assert_failure(result, FailureCode.DQ)
        self.assertEqual(next(c for c in result.checks if c.rule_id == "provider.schedule.structure").status, "FAIL")

    def test_group_membership_and_division_are_validated(self):
        snapshot, rules = make_scenario("nations")
        snapshot = replace(snapshot, stages=(replace(snapshot.stages[0], division=None), *snapshot.stages[1:]))
        self.assert_failure(self.collect(snapshot=snapshot, rules=rules), FailureCode.DQ)

    def test_missing_rules_fail_closed(self):
        self.assert_failure(self.collect(rules=()), FailureCode.DQ)

    def test_partial_schedule_does_not_verify_all_table_counters(self):
        rules = (replace(self.rules[0], schedule_complete=False),)
        result = self.collect(rules=rules)
        self.assertEqual(result.state, CollectionState.SUCCEEDED)
        self.assertFalse(result.eligible_for_full_snapshot)
        self.assertEqual(next(c for c in result.checks if c.rule_id == "provider.standings.counters").status, "SKIP")

    def test_malformed_json_or_schema_not_retried(self):
        for body in (b'null', b'{}', b'\xff', b'{', b'{"x":NaN}', b'{"x":1,"x":2}',
                     b'[' * 2000 + b']' * 2000):
            with self.subTest(body=body[:20]):
                result = self.collect(transform=lambda *_: body)
                self.assert_failure(result, FailureCode.MALFORMED)
                self.assertEqual(result.request_count, 2)

    def test_unexpected_response_structure_fields_or_types(self):
        for changes in ({"schema_version": 2}, {"schema_version": True}, {"total": "144"},
                        {"complete": "true"}, {"unrecognized": "synthetic-secret-sentinel"}):
            result = self.collect(transform=lambda _a, _r, _c, body: mutate(body, lambda d: d.update(changes)))
            self.assert_failure(result, FailureCode.MALFORMED)

    def test_nullable_score_status_and_references_still_enforced(self):
        for change in ({"away_id": "team:absent"}, {"round_id": "round:absent"},
                       {"status": "scheduled", "score": {"regulation_home": 1, "regulation_away": 0}}):
            result = self.collect(transform=lambda _a, _r, _c, body: mutate(body, lambda d: d["fixtures"][0].update(change)))
            self.assertEqual(result.state, CollectionState.FAILED)
            self.assertFalse(result.eligible_for_full_snapshot)

    def test_timeout_is_forwarded_and_cooperatively_checked(self):
        calls = 0
        def transform(_a, _r, _c, body):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.clock.seconds += 11
            return body
        result = self.collect(transform=transform)
        self.assertTrue(result.eligible_for_full_snapshot)
        self.assertTrue(all(call[2] == 10 for call in self.adapter.calls))
        self.assertEqual(result.request_count, 13)

    def test_transient_status_and_timeout_retry(self):
        for code in (FailureCode.HTTP_429, FailureCode.HTTP_500, FailureCode.HTTP_502,
                     FailureCode.HTTP_503, FailureCode.TIMEOUT):
            failures = 0
            def transform(_a, _r, _c, body):
                nonlocal failures
                if failures < 2:
                    failures += 1
                    raise CollectionFailure(code)
                return body
            self.clock = VirtualClock()
            result = self.collect(transform=transform, policy=replace(RequestPolicy(), requests_per_minute=60))
            with self.subTest(code=code):
                self.assertTrue(result.eligible_for_full_snapshot)
                self.assertEqual(result.request_count, 14)
                self.assertIn(2, self.clock.waits)

    def test_retry_exhaustion_is_failure(self):
        def transform(*_):
            raise CollectionFailure(FailureCode.TIMEOUT)
        result = self.collect(transform=transform)
        self.assert_failure(result, FailureCode.TIMEOUT)
        self.assertEqual(result.request_count, 4)  # metadata + three page attempts

    def test_retry_after_is_honored_without_real_sleep(self):
        failed = False
        def transform(_a, _r, _c, body):
            nonlocal failed
            if not failed:
                failed = True
                raise CollectionFailure(FailureCode.HTTP_429, retry_after=7)
            return body
        result = self.collect(transform=transform)
        self.assertTrue(result.eligible_for_full_snapshot)
        self.assertIn(7, self.clock.waits)

    def test_quota_exhaustion_and_auth_tls_do_not_retry(self):
        for code in (FailureCode.QUOTA_EXHAUSTED, FailureCode.TLS, FailureCode.AUTHENTICATION, FailureCode.ACCESS_DENIED):
            def transform(*_):
                raise CollectionFailure(code)
            result = self.collect(transform=transform)
            with self.subTest(code=code):
                self.assert_failure(result, code)
                self.assertEqual(result.request_count, 2)

    def test_unreasonable_retry_after_stops_at_budget(self):
        def transform(*_):
            raise CollectionFailure(FailureCode.HTTP_429, retry_after=3600)
        result = self.collect(transform=transform)
        self.assert_failure(result, FailureCode.LIMIT)
        self.assertLess(self.clock.seconds, 30)

    def test_unsupported_is_distinct(self):
        def describe(*_):
            raise CollectionFailure(FailureCode.UNSUPPORTED)
        result = self.collect(describe_transform=describe)
        self.assertEqual(result.state, CollectionState.UNSUPPORTED)
        self.assertEqual(result.completeness, Completeness.UNKNOWN)
        self.assertEqual(result.freshness, FreshnessState.UNKNOWN)
        self.assertFalse(result.eligible_for_full_snapshot)

    def test_unknown_exception_and_payload_are_not_diagnostics(self):
        secret = "synthetic-secret-sentinel"
        def transform(*_):
            raise RuntimeError("https://user:" + secret + "@host/")
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = self.collect(transform=transform)
        self.assert_failure(result, FailureCode.MALFORMED)
        self.assertNotIn(secret, repr(result))
        self.assertEqual(output.getvalue(), "")

    def test_offline_no_credentials_sleep_or_persistence(self):
        adapter = FakeAdapter(self.snapshot, rules=self.rules)
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("time.sleep", side_effect=AssertionError("real sleep forbidden")), \
             patch("builtins.open", side_effect=AssertionError("file access forbidden")), \
             patch("os.getenv", side_effect=AssertionError("credentials forbidden")):
            result = self.collect(source=adapter)
            self.assertTrue(result.eligible_for_full_snapshot)

    def test_failed_refresh_does_not_mutate_previous_snapshot(self):
        before = canonical_bytes(self.snapshot)
        result = self.collect(previous=self.snapshot, transform=lambda *_: b'bad')
        self.assert_failure(result, FailureCode.MALFORMED)
        self.assertEqual(before, canonical_bytes(self.snapshot))

    def test_cursor_and_raw_payload_not_exposed_in_receipts(self):
        result = self.collect()
        self.assertNotIn("page-2", repr(result.provenance))
        self.assertFalse(any(hasattr(receipt, "payload") for receipt in result.provenance))


if __name__ == "__main__":
    unittest.main()
