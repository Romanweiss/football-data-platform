"""Offline mapping, unsupported semantics and all-view arithmetic on invented JSON."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import io
import unittest
from unittest.mock import patch

from football_data_fakes import NOW, encode, make_payloads
from src.providers.adapter import LIVE_PROVIDER_ALLOWLIST
from src.providers.football_data import (
    FixtureBinding, MappingError, map_responses,
)
from src.providers.models import FixtureStatus, Score
from src.providers.validation import canonical_bytes, validate_snapshot


class FootballDataMappingTests(unittest.TestCase):
    def setUp(self):
        self.context, self.metadata, self.fixtures, self.standings = make_payloads()

    def mapped(self, **options):
        return map_responses(encode(self.metadata), encode(self.fixtures), encode(self.standings),
                             context=self.context, fetched_at=NOW, **options)

    def invalid(self, code=None):
        with self.assertRaises(MappingError) as caught:
            self.mapped()
        if code:
            self.assertEqual(caught.exception.code, code)
        return caught.exception

    def fixture(self, status="TIMED"):
        return next(row for row in self.fixtures["matches"] if row["status"] == status)

    def change_status(self, row, status):
        row["status"] = status
        self.fixtures["resultSet"]["played"] = sum(r["status"] == "FINISHED" for r in self.fixtures["matches"])

    def test_36_teams_144_fixtures_three_views_and_all_dq(self):
        result = self.mapped()
        self.assertTrue(result.ready_for_offline_use)
        snapshot = result.snapshot
        validate_snapshot(snapshot)
        self.assertEqual((len(snapshot.participants), len(snapshot.fixtures), len(snapshot.standings)), (36, 144, 36))
        self.assertEqual({view.kind: len(view.entries) for view in result.tables}, {"TOTAL": 36, "HOME": 36, "AWAY": 36})
        self.assertFalse(any(check.status == "FAIL" for check in result.checks))
        self.assertEqual({check.rule_id for check in result.checks if check.status == "SKIP"},
                         {"provider.standings.tie_breakers", "football_data.points_adjustment_authority"})
        self.assertEqual(len(snapshot.rounds), 8)
        self.assertTrue(snapshot.partial)
        self.assertEqual(sum(f.status is FixtureStatus.FINISHED for f in snapshot.fixtures), 36)
        self.assertEqual(sum(entry.played for entry in snapshot.standings), 72)

    def test_ids_are_explicit_registry_values_not_provider_ids_or_names(self):
        snapshot = self.mapped().snapshot
        self.assertEqual(snapshot.competition.identity.external_id, "2001")
        self.assertEqual(snapshot.season.identity.external_id, "2557")
        self.assertNotEqual(snapshot.competition.id, "2001")
        for source, binding in zip(self.fixtures["matches"], self.context.fixture_bindings):
            mapped = next(f for f in snapshot.fixtures if f.identity.external_id == str(source["id"]))
            self.assertEqual(mapped.id, binding.canonical_id)
            self.assertEqual(mapped.revision, binding.neutral_revision)
        self.assertIn("NOT_PROVIDER_REVISION", self.mapped().revision_origin)
        self.assertNotIn("football-data-org", LIVE_PROVIDER_ALLOWLIST)

    def test_no_provider_revision_or_unobserved_analytics_fabricated(self):
        result = self.mapped()
        self.assertFalse(hasattr(result, "source_revision"))
        for fixture in result.snapshot.fixtures:
            self.assertIsNone(fixture.score.extra_home)
            self.assertIsNone(fixture.score.penalties_home)
            self.assertFalse(hasattr(fixture, "xg"))
            self.assertFalse(hasattr(fixture, "location_x"))
        self.assertEqual({cap.name.value for cap in result.snapshot.capabilities}, {"fixtures", "results", "standings"})

    def test_scheduled_null_scores_not_zero(self):
        snapshot = self.mapped().snapshot
        self.assertTrue(all(f.score == Score() for f in snapshot.fixtures if f.status is FixtureStatus.SCHEDULED))

    def test_finished_regular_full_time_is_not_extra_time(self):
        source = self.fixture("FINISHED")
        mapped = next(f for f in self.mapped().snapshot.fixtures if f.identity.external_id == str(source["id"]))
        self.assertEqual((mapped.score.regulation_home, mapped.score.regulation_away),
                         (source["score"]["fullTime"]["home"], source["score"]["fullTime"]["away"]))

    def test_documented_unseen_statuses_are_synthetic_only(self):
        for status, expected in (("SCHEDULED", FixtureStatus.SCHEDULED), ("IN_PLAY", FixtureStatus.LIVE),
                                 ("POSTPONED", FixtureStatus.POSTPONED), ("CANCELLED", FixtureStatus.CANCELLED)):
            with self.subTest(status=status):
                self.setUp()
                row = self.fixture()
                self.change_status(row, status)
                if status == "IN_PLAY":
                    row["utcDate"] = (NOW - timedelta(hours=2)).isoformat()
                    row["score"]["fullTime"] = {"home": 7, "away": 3}
                result = self.mapped()
                self.assertTrue(result.ready_for_offline_use)
                self.assertEqual(result.synthetic_only_statuses, (status,))
                fixture = next(f for f in result.snapshot.fixtures if f.identity.external_id == str(row["id"]))
                self.assertIs(fixture.status, expected)
                # A live 7-3 score does not affect the standings.
                self.assertEqual(sum(entry.played for entry in result.snapshot.standings), 72)

    def test_suspended_abandoned_live_alias_and_unknown_preserve_score(self):
        for status in ("SUSPENDED", "ABANDONED", "LIVE", "SOMETHING_NEW"):
            with self.subTest(status=status):
                self.setUp()
                row = self.fixture("FINISHED")
                self.change_status(row, status)
                row["score"]["fullTime"] = {"home": 2, "away": 1}
                result = self.mapped()
                self.assertFalse(result.ready_for_offline_use)
                self.assertIsNone(result.snapshot)
                self.assertIsNone(result.semantic_digest)
                self.assertEqual(len(result.unsupported), 1)
                record = result.unsupported[0]
                self.assertEqual((record.provider_status, record.full_time, record.reason),
                                 (status, (2, 1), "UNSUPPORTED_STATUS"))

    def test_postponed_cancelled_retained_score_is_not_discarded(self):
        for status in ("POSTPONED", "CANCELLED"):
            with self.subTest(status=status):
                self.setUp()
                row = self.fixture()
                self.change_status(row, status)
                row["score"]["fullTime"] = {"home": 3, "away": 2}
                result = self.mapped()
                self.assertEqual(result.unsupported[0].full_time, (3, 2))
                self.assertEqual(result.unsupported[0].reason, "RETAINED_SCORE_REQUIRES_STATUS_EXTENSION")
                self.assertIsNone(result.snapshot)

    def test_extra_time_penalties_and_inclusive_score_are_not_guessed(self):
        for key in ("extraTime", "penalties", "regularTime"):
            with self.subTest(key=key):
                self.setUp()
                row = self.fixture("FINISHED")
                row["score"][key] = {"home": 1, "away": 0}
                row["score"]["duration"] = "EXTRA_TIME"
                result = self.mapped()
                self.assertIsNone(result.snapshot)
                self.assertEqual(result.unsupported[0].reason, "UNVERIFIED_SCORE_SEMANTICS")
                attr = {"extraTime": "extra_time", "regularTime": "regular_time", "penalties": "penalties"}[key]
                self.assertEqual(getattr(result.unsupported[0], attr), (1, 0))

    def test_missing_duration_is_unsupported_not_assumed_regular(self):
        del self.fixture()["score"]["duration"]
        self.assertEqual(self.mapped().unsupported[0].reason, "UNVERIFIED_SCORE_SEMANTICS")

    def test_finished_null_score_is_not_silently_created(self):
        self.fixture("FINISHED")["score"]["fullTime"] = {"home": None, "away": None}
        result = self.mapped()
        self.assertIsNone(result.snapshot)
        self.assertEqual(result.unsupported[0].reason, "MISSING_FINISHED_SCORE")

    def test_null_optional_extra_fields_do_not_create_goals(self):
        self.fixture()["score"].update(extraTime=None, penalties={"home": None, "away": None})
        self.assertTrue(self.mapped().ready_for_offline_use)

    def test_missing_unmapped_optional_fields_and_nullable_kickoff(self):
        del self.metadata["lastUpdated"]
        self.fixture()["utcDate"] = None
        self.assertTrue(self.mapped().ready_for_offline_use)

    def test_total_is_required_home_away_remain_distinct_optional_views(self):
        self.standings["standings"] = [view for view in self.standings["standings"] if view["type"] == "TOTAL"]
        result = self.mapped()
        self.assertTrue(result.ready_for_offline_use)
        self.assertEqual(len(result.snapshot.standings), 36)
        self.assertEqual(sum(c.status == "SKIP" for c in result.checks), 4)
        self.standings["standings"] = []
        self.invalid("DQ")

    def test_provider_rank_is_not_recomputed_by_points_or_goal_difference(self):
        for view in self.standings["standings"]:
            for row in view["table"]:
                row["position"] = 1  # Equal provisional ranks are explicitly allowed by A.
        result = self.mapped()
        self.assertTrue(result.ready_for_offline_use)
        self.assertEqual({row.rank for row in result.snapshot.standings}, {1})

    def test_point_adjustments_are_not_inferred(self):
        self.standings["standings"][0]["table"][0]["points"] += 1
        self.invalid("DQ")

    def test_cross_resource_arithmetic_drift_in_each_view_blocks_candidate(self):
        for kind in ("TOTAL", "HOME", "AWAY"):
            with self.subTest(kind=kind):
                self.setUp()
                row = next(view for view in self.standings["standings"] if view["type"] == kind)["table"][0]
                row["goalsFor"] += 1
                row["goalDifference"] += 1
                result = self.mapped()
                self.assertFalse(result.ready_for_offline_use)
                self.assertIsNone(result.snapshot)
                self.assertTrue(any(check.status == "FAIL" for check in result.checks))

    def test_wdl_points_and_played_drift_are_rejected(self):
        for key in ("playedGames", "won", "draw", "lost", "points", "goalDifference"):
            with self.subTest(key=key):
                self.setUp()
                self.standings["standings"][0]["table"][0][key] += 1
                self.invalid("DQ")

    def test_duplicate_fixture_and_missing_registry_binding(self):
        self.fixtures["matches"][-1] = deepcopy(self.fixtures["matches"][0])
        self.invalid("DUPLICATE")
        self.setUp()
        self.context = replace(self.context, fixture_bindings=self.context.fixture_bindings[:-1])
        self.invalid("SCOPE")

    def test_missing_fixture_not_treated_as_deletion_or_truncated_success(self):
        self.fixtures["matches"].pop()
        self.fixtures["resultSet"]["count"] = 143
        self.invalid("DQ")

    def test_count_and_played_metadata_mismatch(self):
        for key in ("count", "played"):
            with self.subTest(key=key):
                self.setUp()
                self.fixtures["resultSet"][key] += 1
                self.invalid("DQ")

    def test_duplicate_table_and_duplicate_member(self):
        self.standings["standings"][1] = deepcopy(self.standings["standings"][0])
        self.invalid("DUPLICATE")
        self.setUp()
        table = self.standings["standings"][0]["table"]
        table[-1] = deepcopy(table[0])
        self.invalid("DUPLICATE")

    def test_scope_is_checked_in_all_resources_and_each_fixture(self):
        for mutate in (
            lambda: self.metadata.update(id=100),
            lambda: self.metadata["currentSeason"].update(id=100),
            lambda: self.fixtures["competition"].update(id=100),
            lambda: self.fixture()["season"].update(id=100),
            lambda: self.fixture()["competition"].update(id=100),
            lambda: self.standings["season"].update(id=100),
            lambda: self.standings["competition"].update(id=100),
        ):
            with self.subTest(mutate=mutate):
                self.setUp()
                mutate()
                self.invalid("SCOPE")

    def test_strict_identifier_types_and_required_ids(self):
        for bad in (None, True, "2001", -1, 0, 2**64):
            with self.subTest(bad=bad):
                self.metadata["id"] = bad
                self.invalid("IDENTITY")
        self.setUp()
        del self.fixture()["id"]
        self.invalid("IDENTITY")

    def test_name_conflict_is_not_identity_merge(self):
        self.standings["standings"][0]["table"][0]["team"]["name"] = "A different invented club"
        self.invalid("IDENTITY")

    def test_unknown_table_stage_and_pagination_fail_closed(self):
        self.standings["standings"][0]["type"] = "NEW_VIEW"
        self.invalid("UNSUPPORTED")
        self.setUp()
        self.fixture()["stage"] = "LAST_16"
        self.invalid("UNSUPPORTED")
        self.setUp()
        self.fixtures["nextCursor"] = "another-page"
        self.invalid("UNSUPPORTED")

    def test_invalid_and_nonfinite_scores_and_bool_counters(self):
        for bad in (True, -1, 101, 0.5, "1"):
            with self.subTest(bad=bad):
                self.setUp()
                self.fixture("FINISHED")["score"]["fullTime"]["home"] = bad
                self.invalid("SCHEMA")
        self.setUp()
        self.standings["standings"][0]["table"][0]["playedGames"] = True
        self.invalid("SCHEMA")

    def test_mixed_null_score_and_unexpected_schema(self):
        self.fixture()["score"]["fullTime"] = {"home": None, "away": 1}
        self.invalid("SCHEMA")
        self.setUp()
        self.fixtures["matches"] = {"unexpected": "schema"}
        self.invalid("LIMIT")

    def test_malformed_duplicate_key_and_oversized_json(self):
        for raw, code in ((b'{broken', "MALFORMED"), (b'{"id":1,"id":2}', "DUPLICATE"),
                          (b'{"id":NaN}', "SCHEMA"), (b'{"unused":1e999}', "SCHEMA"), (b'[]', "SCHEMA"),
                          (b'x' * (1024 * 1024 + 1), "LIMIT")):
            with self.subTest(code=code):
                with self.assertRaises(MappingError) as caught:
                    map_responses(raw, encode(self.fixtures), encode(self.standings), context=self.context, fetched_at=NOW)
                self.assertEqual(caught.exception.code, code)

    def test_temporal_inconsistency_and_bad_timestamp(self):
        for target, key, bad in ((self.metadata, "lastUpdated", "2099-01-01T00:00:00Z"),
                                 (self.fixture(), "lastUpdated", "2099-01-01T00:00:00Z"),
                                 (self.fixture("FINISHED"), "utcDate", "2099-01-01T00:00:00Z"),
                                 (self.fixture(), "lastUpdated", "2026-10-29T10:00:00")):
            with self.subTest(key=key, bad=bad):
                original = target[key]
                target[key] = bad
                self.invalid("UTC")
                target[key] = original

    def test_input_reordering_does_not_change_semantics_or_canonical_snapshot(self):
        first = self.mapped()
        self.fixtures["matches"].reverse()
        self.standings["standings"].reverse()
        for table in self.standings["standings"]:
            table["table"].reverse()
        second = self.mapped()
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(canonical_bytes(first.snapshot), canonical_bytes(second.snapshot))

    def test_caller_revision_is_required_and_no_silent_revision_one(self):
        first = self.context.fixture_bindings[0]
        self.context = replace(self.context, fixture_bindings=(FixtureBinding(first.external_id, first.canonical_id, None),
                                                             *self.context.fixture_bindings[1:]))
        self.invalid("SCHEMA")

    def test_previous_snapshot_correction_needs_explicit_higher_neutral_version(self):
        previous = self.mapped().snapshot
        row = self.fixture()
        row["utcDate"] = (NOW + timedelta(days=2)).isoformat()
        row["lastUpdated"] = (NOW - timedelta(minutes=30)).isoformat()
        self.invalid_previous(previous)
        self.context = replace(self.context, fixture_bindings=tuple(
            replace(binding, neutral_revision=2) if binding.external_id == str(row["id"]) else binding
            for binding in self.context.fixture_bindings))
        self.assertTrue(self.mapped(previous=previous).ready_for_offline_use)

    def invalid_previous(self, previous):
        with self.assertRaises(MappingError) as caught:
            self.mapped(previous=previous)
        self.assertEqual(caught.exception.code, "REVISION")

    def test_safe_diagnostics_and_no_runtime_io(self):
        payloads = tuple(map(encode, (self.metadata, self.fixtures, self.standings)))
        output = io.StringIO()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
                patch("pathlib.Path.open", side_effect=AssertionError("files forbidden")), \
                patch("subprocess.run", side_effect=AssertionError("processes forbidden")), \
                redirect_stdout(output), redirect_stderr(output):
            result = map_responses(*payloads, context=self.context, fetched_at=NOW)
        self.assertTrue(result.ready_for_offline_use)
        self.assertEqual(output.getvalue(), "")
        self.metadata["id"] = "synthetic-sensitive-marker"
        error = self.invalid("IDENTITY")
        self.assertEqual(str(error), "football_data_mapping:IDENTITY")
        self.assertNotIn("sensitive", str(error))
        self.assertIsNone(error.__cause__)

    def test_no_double_count_or_schedule_holes_hidden_by_same_total(self):
        first, last = self.fixtures["matches"][0], self.fixtures["matches"][-1]
        last["homeTeam"], last["awayTeam"] = deepcopy(first["homeTeam"]), deepcopy(first["awayTeam"])
        result = self.mapped()
        self.assertIsNone(result.snapshot)
        self.assertEqual(next(c.status for c in result.checks if c.rule_id == "provider.schedule.structure"), "FAIL")

    def test_home_away_balance_checked_for_full_declared_schedule(self):
        row = self.fixture()
        row["homeTeam"], row["awayTeam"] = row["awayTeam"], row["homeTeam"]
        result = self.mapped()
        self.assertFalse(result.ready_for_offline_use)
        self.assertEqual(next(c.status for c in result.checks if c.rule_id == "provider.schedule.structure"), "FAIL")

    def test_duplicate_team_in_round_checked(self):
        self.fixture()["matchday"] = 1
        result = self.mapped()
        self.assertFalse(result.ready_for_offline_use)

    def test_absent_member_or_out_of_scope_team_is_rejected(self):
        self.context = replace(self.context, empty_snapshot=replace(
            self.context.empty_snapshot, participants=self.context.empty_snapshot.participants[:-1]))
        self.invalid("SCOPE")
        self.setUp()
        self.fixture()["homeTeam"]["id"] = 1
        self.invalid("SCOPE")

    def test_utc_z_and_explicit_zero_offset_have_same_semantics(self):
        first = self.mapped()
        row = self.fixture("FINISHED")
        row["utcDate"] = row["utcDate"].replace("Z", "+00:00")
        self.assertEqual(first.semantic_digest, self.mapped().semantic_digest)

    def test_no_finished_fixtures_does_not_invent_results_capability(self):
        for row in self.fixtures["matches"]:
            row["status"] = "TIMED"
            row["score"]["fullTime"] = {"home": None, "away": None}
            row["utcDate"] = (NOW + timedelta(days=1)).isoformat()
        self.fixtures["resultSet"]["played"] = 0
        for view in self.standings["standings"]:
            for row in view["table"]:
                for key in ("playedGames", "won", "draw", "lost", "goalsFor", "goalsAgainst", "goalDifference", "points"):
                    row[key] = 0
        result = self.mapped()
        self.assertTrue(result.ready_for_offline_use)
        self.assertEqual(next(cap.availability.value for cap in result.snapshot.capabilities
                              if cap.name.value == "results"), "unknown")
        self.assertEqual(sum(entry.played for entry in result.snapshot.standings), 0)

    def test_missing_fixture_binding_does_not_allocate_new_identity(self):
        self.fixture()["id"] = 999999999
        self.invalid("IDENTITY")

    def test_context_and_payloads_are_not_mutated(self):
        before = (encode(self.metadata), encode(self.fixtures), encode(self.standings))
        original = self.context
        self.assertTrue(self.mapped().ready_for_offline_use)
        self.assertEqual(before, (encode(self.metadata), encode(self.fixtures), encode(self.standings)))
        self.assertEqual(original, self.context)
