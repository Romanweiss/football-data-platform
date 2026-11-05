"""PET-1 artificial records only. No real clubs/results, dataset, files or HTTP."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.providers.identity_registry import IdentityEvidence, IdentityKind, IdentityRegistry
from src.providers.models import Availability, Capability, FixtureStatus, StageType, TeamType
from src.providers.observed_versions import VersionLedger
from src.providers.openfootball import (
    MAX_BYTES, MAX_MATCHES, OpenFootballError, OpenFootballMapping, RoundBinding, StatusReview, TeamBinding,
    fixture_fingerprint, prepare_openfootball,
)
from src.providers.openfootball_manifest import UCL_2024_25

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
EVIDENCE = IdentityEvidence(True, "pet1-synthetic-mapping-v1")


def mapping():
    return OpenFootballMapping("Artificial cup 2024/25", (
        TeamBinding("Amber FC", "amber", "Amber FC"), TeamBinding("Blue FC", "blue", "Blue FC"),
        TeamBinding("Cyan FC", "cyan", "Cyan FC"), TeamBinding("Dune FC", "dune", "Dune FC"),
    ), (
        RoundBinding("League, Matchday 1", "league", "League phase", StageType.LEAGUE_PHASE, "md1", 1),
        RoundBinding("Group A, Matchday 1", "group-a", "Group A", StageType.GROUP, "md1", 1),
        RoundBinding("Synthetic quarter-finals", "knockout", "Knockout", StageType.KNOCKOUT, "qf", 1),
    ), date(2024, 7, 1), date(2025, 6, 30), EVIDENCE)


def payload():
    return {"name": "Artificial cup 2024/25", "matches": [
        {"round": "League, Matchday 1", "date": "2024-09-18", "team1": "Amber FC", "team2": "Blue FC",
         "score": {"ft": [2, 2], "ht": [1, 1]}},
        {"round": "Group A, Matchday 1", "date": "2024-09-19", "time": "20:45",
         "team1": "Cyan FC", "team2": "Dune FC", "score": {"ft": [1, 0]}},
        {"round": "Synthetic quarter-finals", "date": "2025-04-01", "team1": "Amber FC", "team2": "Cyan FC"},
    ]}


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class OpenFootballTests(unittest.TestCase):
    def prepare(self, source=None, **kwargs):
        return prepare_openfootball(payload() if source is None else source, mapping=kwargs.pop("mapping", mapping()),
                                    observed_at=kwargs.pop("observed_at", NOW), **kwargs)

    def continued(self, first, source=None, **kwargs):
        return self.prepare(source, registry=IdentityRegistry.from_bytes(first.registry_after_state),
            versions=VersionLedger.from_bytes(first.ledger_after_state), previous=first,
            observed_at=kwargs.pop("observed_at", NOW + timedelta(seconds=1)), **kwargs)

    def assert_code(self, code, source=None, **kwargs):
        with self.assertRaises(OpenFootballError) as raised:
            self.prepare(source, **kwargs)
        self.assertEqual(code, raised.exception.diagnostic.code)
        self.assertEqual("openfootball:" + code, str(raised.exception))
        return raised.exception.diagnostic

    def test_declarative_manifest_unacquired_and_capabilities_not_verified(self):
        UCL_2024_25.validate()
        self.assertEqual(UCL_2024_25.commit, "e6744429ee395bc86f247348c6184bb08d4eb361")
        self.assertEqual(UCL_2024_25.path, "2024-25/uefa.cl.json")
        self.assertIsNone(UCL_2024_25.content_sha256)
        self.assertIsNone(UCL_2024_25.acquired_at)
        self.assertEqual("UNKNOWN", UCL_2024_25.coverage)
        capabilities = {c.name: c.availability for c in UCL_2024_25.capabilities}
        self.assertEqual(Availability.DECLARED, capabilities[Capability.RESULTS])
        for cap in (Capability.STANDINGS, Capability.EVENT_COORDINATES, Capability.XG):
            self.assertEqual(Availability.UNAVAILABLE, capabilities[cap])

    def test_fields_group_league_knockout_draw_and_missing_time(self):
        result = self.prepare()
        self.assertEqual(3, len(result.fixtures))
        self.assertEqual(4, len(result.participants))
        self.assertEqual({StageType.GROUP, StageType.LEAGUE_PHASE, StageType.KNOCKOUT}, {s.kind for s in result.stages})
        scored = next(f for f in result.fixtures if f.source_ft == (2, 2))
        self.assertEqual(FixtureStatus.FINISHED, scored.status)
        self.assertEqual((1, 1), scored.source_ht)
        self.assertIsNone(scored.source_time)
        self.assertIsNone(scored.kickoff_utc)
        self.assertIsNone(scored.regulation_score)
        self.assertEqual("2024-09-18", scored.match_date)
        unscored = next(f for f in result.fixtures if f.source_ft is None)
        self.assertEqual(FixtureStatus.UNKNOWN, unscored.status)  # NOT inferred postponed/scheduled.
        self.assertEqual("20:45", next(f for f in result.fixtures if f.source_time).source_time)
        self.assertIsNone(result.source_revision)
        self.assertFalse(result.publish_authorized)

    def test_bytes_parsed_equivalence_and_provenance_distinction(self):
        raw = encode(payload())
        a, b = self.prepare(raw), self.prepare()
        self.assertEqual(a.fixtures, b.fixtures)
        self.assertEqual(a.semantic_digest, b.semantic_digest)
        self.assertIsNone(b.input_sha256)
        self.assertEqual(sha256(raw).hexdigest(), a.input_sha256)
        self.assertIsNone(a.manifest.content_sha256)  # No false acquisition claim.

    def test_deterministic_ordering_fields_mappings_and_records(self):
        first = self.prepare()
        source = payload()
        source["matches"].reverse()
        source = {k: source[k] for k in reversed(source)}
        context = mapping()
        context = replace(context, teams=tuple(reversed(context.teams)), rounds=tuple(reversed(context.rounds)))
        second = self.prepare(source, mapping=context)
        self.assertEqual(first, second)

    def test_input_and_proposal_immutable(self):
        raw, context = payload(), mapping()
        copy = deepcopy(raw)
        result = self.prepare(raw, mapping=context)
        self.assertEqual(copy, raw)
        with self.assertRaises(FrozenInstanceError):
            result.coverage = "COMPLETE"
        raw["matches"][0]["score"]["ft"][0] = 99
        self.assertNotIn((99, 2), [f.source_ft for f in result.fixtures])

    def test_postponement_requires_explicit_review_not_invention(self):
        first = self.prepare()
        target = next(f for f in first.fixtures if f.source_ft is None)
        context = replace(mapping(), status_reviews=(StatusReview(target.identity.external_id,
            FixtureStatus.POSTPONED, EVIDENCE),))
        result = self.prepare(mapping=context)
        item = next(f for f in result.fixtures if f.id == target.id)
        self.assertEqual(FixtureStatus.POSTPONED, item.status)
        self.assertEqual("explicit_operator_review", item.status_origin)
        self.assertEqual(EVIDENCE.reference, item.status_review_reference)
        raw = payload()
        raw["matches"][2]["status"] = "POSTPONED"
        self.assert_code("UNKNOWN_FIELD", raw)  # Not in verified source shape.

    def test_score_review_conflict_and_unmatched_reviews(self):
        result = self.prepare()
        target = next(f for f in result.fixtures if f.source_ft is not None)
        context = replace(mapping(), status_reviews=(StatusReview(target.identity.external_id,
            FixtureStatus.POSTPONED, EVIDENCE),))
        self.assert_code("SCORE_STATUS", mapping=context)
        context = replace(mapping(), status_reviews=(StatusReview("unknown-fixture", FixtureStatus.UNKNOWN, EVIDENCE),))
        self.assert_code("COVERAGE", mapping=context)

    def test_replay_is_idempotent_semantic_versions_not_observation_time(self):
        first = self.prepare()
        second = self.continued(first)
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(first.fixtures, second.fixtures)
        self.assertEqual(first.registry_after_state, second.registry_after_state)
        self.assertTrue(all(not r.changed and r.local_content_version == 1 for r in second.versions))
        self.assertNotEqual(first.observed_at, second.observed_at)
        self.assertNotEqual(first.ledger_after_state, second.ledger_after_state)  # Last-seen only.
        same_instant = self.continued(first, observed_at=NOW)
        self.assertEqual(first.ledger_after_state, same_instant.ledger_after_state)

    def test_score_correction_keeps_id_and_allocates_one_local_version(self):
        first = self.prepare()
        source = payload()
        source["matches"][0]["score"]["ft"] = [3, 2]
        result = self.continued(first, source)
        corrected = next(f for f in result.fixtures if f.source_ft == (3, 2))
        self.assertEqual(2, corrected.local_revision)
        self.assertIn(corrected.id, {f.id for f in first.fixtures})
        self.assertEqual(1, sum(r.changed for r in result.versions))
        self.assertTrue(all(r.provider_revision is None for r in result.versions))

    def test_local_time_correction_is_not_date_identity_change(self):
        first = self.prepare()
        source = payload()
        source["matches"][1]["time"] = "21:00"
        result = self.continued(first, source)
        self.assertEqual({f.id for f in first.fixtures}, {f.id for f in result.fixtures})
        self.assertEqual(2, next(f for f in result.fixtures if f.source_time).local_revision)

    def test_status_correction_unknown_to_finished(self):
        first = self.prepare()
        raw = payload()
        raw["matches"][2]["score"] = {"ft": [0, 0]}
        second = self.continued(first, raw)
        self.assertTrue(all(f.status is FixtureStatus.FINISHED for f in second.fixtures))
        with self.assertRaisesRegex(OpenFootballError, "SCORE_STATUS"):
            self.continued(second, observed_at=NOW + timedelta(seconds=2))

    def test_changed_date_or_participants_requires_review_even_without_previous(self):
        first = self.prepare()
        for field, value in (("date", "2024-09-20"), ("team2", "Dune FC"), ("round", "Group A, Matchday 1")):
            raw = payload()
            raw["matches"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(OpenFootballError, "IDENTITY_REVIEW_REQUIRED"):
                self.prepare(raw, registry=IdentityRegistry.from_bytes(first.registry_after_state))

    def test_missing_previous_or_stale_ledger_requires_review(self):
        first = self.prepare()
        self.assert_code("REVIEW_REQUIRED", registry=IdentityRegistry.from_bytes(first.registry_after_state),
            versions=VersionLedger.from_bytes(first.ledger_after_state))
        newer = self.continued(first)
        self.assert_code("REVIEW_REQUIRED", registry=IdentityRegistry.from_bytes(newer.registry_after_state),
            versions=VersionLedger.from_bytes(newer.ledger_after_state), previous=first)

    def test_tampered_previous_cannot_bypass_finished_score_guard(self):
        first = self.prepare()
        for altered in (replace(first, fixtures=first.fixtures[:-1]), replace(first,
                fixtures=tuple(replace(f, status=FixtureStatus.UNKNOWN, source_ft=None, source_ht=None)
                               for f in first.fixtures))):
            with self.subTest(count=len(altered.fixtures)):
                self.assert_code("REVIEW_REQUIRED", previous=altered,
                    registry=IdentityRegistry.from_bytes(first.registry_after_state),
                    versions=VersionLedger.from_bytes(first.ledger_after_state))

    def test_missing_or_extra_fixture_in_replay_requires_review(self):
        first = self.prepare()
        for addition in (False, True):
            raw = payload()
            if addition:
                raw["matches"].append(dict(raw["matches"][2], date="2025-04-02"))
            else:
                raw["matches"].pop()
            with self.subTest(addition=addition), self.assertRaisesRegex(OpenFootballError, "IDENTITY_REVIEW_REQUIRED"):
                self.continued(first, raw)

    def test_different_round_keys_with_same_stage_order_fail_closed(self):
        context = mapping()
        conflicting = replace(context.rounds[0], source_round="Another round", round_key="collision")
        self.assert_code("IDENTITY_REVIEW_REQUIRED", mapping=replace(context, rounds=(*context.rounds, conflicting)))

    def test_source_alias_rebinding_to_another_team_fails(self):
        first = self.prepare()
        context = mapping()
        changed = tuple(replace(t, external_id="dune", display_name="Dune FC") if t.external_id == "amber" else t
                        for t in context.teams)
        with self.assertRaisesRegex(OpenFootballError, "IDENTITY_REVIEW_REQUIRED"):
            self.continued(first, mapping=replace(context, teams=changed))

    def test_reversion_out_of_order_and_simultaneous_conflict(self):
        first = self.prepare()
        changed = payload()
        changed["matches"][0]["score"]["ft"] = [3, 2]
        second = self.continued(first, changed)
        for source, previous, when, code in ((payload(), second, NOW + timedelta(seconds=2), "REVERSION_REQUIRES_REVIEW"),
                (payload(), first, NOW - timedelta(seconds=1), "OUT_OF_ORDER"),
                (changed, first, NOW, "VERSION_CONFLICT")):
            with self.subTest(code=code), self.assertRaisesRegex(OpenFootballError, code):
                self.continued(previous, source, observed_at=when)

    def test_failure_does_not_partially_apply_registry_or_ledger(self):
        first = self.prepare()
        registry = IdentityRegistry.from_bytes(first.registry_after_state)
        versions = VersionLedger.from_bytes(first.ledger_after_state)
        before = registry.to_bytes(), versions.to_bytes()
        source = payload()
        source["matches"][0]["score"]["ft"] = [3, 2]
        # Force a late error after one fixture has already been observed in the clone.
        original = VersionLedger.observe
        calls = []

        def failing(instance, *args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                raise OpenFootballError("VERSION_CONFLICT")
            return original(instance, *args, **kwargs)

        with patch.object(VersionLedger, "observe", failing):
            self.assert_code("VERSION_CONFLICT", source, registry=registry, versions=versions, previous=first,
                             observed_at=NOW + timedelta(seconds=1))
        self.assertEqual(before, (registry.to_bytes(), versions.to_bytes()))

    def test_duplicate_rows_not_discarded_and_row_diagnostic(self):
        source = payload()
        source["matches"].append(deepcopy(source["matches"][0]))
        diagnostic = self.assert_code("DUPLICATE", source)
        self.assertEqual(3, diagnostic.row)

    def test_unknown_teams_exact_names_only_and_self_match(self):
        for name, code in (("Amber fc", "UNKNOWN_TEAM"), (" Amber FC", "SCHEMA"), ("Amber FC", "SELF_MATCH")):
            source = payload()
            source["matches"][0]["team2"] = name
            self.assert_code(code, source)

    def test_explicit_alias_preserves_ids_not_automatic_fuzzy_matching(self):
        first = self.prepare()
        source = payload()
        source["matches"][0]["team1"] = "Reviewed Amber Alias"
        context = replace(mapping(), teams=(*mapping().teams, TeamBinding("Reviewed Amber Alias", "amber", "Amber FC")))
        second = self.continued(first, source, mapping=context)
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(first.fixtures, second.fixtures)

    def test_namespaces_do_not_collide_with_other_sources(self):
        registry = IdentityRegistry()
        for provider in ("statsbomb", "football_data"):
            root = registry.register(provider, IdentityKind.PROVIDER, provider, evidence=EVIDENCE)
            registry.register(provider, IdentityKind.PARTICIPANT, "amber", parent_id=root.id,
                              team_type=TeamType.CLUB, evidence=EVIDENCE)
        result = self.prepare(registry=registry)
        state = IdentityRegistry.from_bytes(result.registry_after_state)
        ids = {r.id for r in state.records if r.kind is IdentityKind.PARTICIPANT and r.external_id == "amber"}
        self.assertEqual(3, len(ids))
        self.assertTrue(all(f.identity.provider == "openfootball" for f in result.fixtures))

    def test_registry_preexisting_fixture_participant_conflict_rejected(self):
        first = self.prepare()
        registry = IdentityRegistry.from_bytes(first.registry_after_state)
        record = next(r for r in registry.records if r.kind is IdentityKind.FIXTURE)
        # Construct a separately confirmed conflicting registry, not edit a serialized snapshot.
        registry = IdentityRegistry()
        original = IdentityRegistry.from_bytes(first.registry_after_state)
        for kind in IdentityKind:
            if kind is IdentityKind.FIXTURE:
                for member in original.participations:
                    registry.confirm_participation(member.season_id, member.participant_id, evidence=EVIDENCE)
            for old in original.records:
                if old.kind is kind:
                    registry.register(old.provider, kind, old.external_id, evidence=EVIDENCE,
                        parent_id=old.parent_id, team_type=old.team_type, stage_kind=old.stage_kind,
                        participants=tuple(reversed(old.participants)) if old.id == record.id else old.participants,
                        order=old.order, legs=old.legs)
        before = registry.to_bytes()
        self.assert_code("IDENTITY_REVIEW_REQUIRED", registry=registry)
        self.assertEqual(before, registry.to_bytes())

    def test_invalid_dates_times_and_season_bounds(self):
        for value in ("2024-02-30", "20240918", "2024-9-18", "2024-09-18T00:00:00Z"):
            source = payload()
            source["matches"][0]["date"] = value
            self.assert_code("DATE", source)
        source = payload()
        source["matches"][0]["date"] = "2026-09-18"
        self.assert_code("SCOPE", source)
        for value in ("24:00", "20:61", "20:45Z", 2045):
            source = payload()
            source["matches"][1]["time"] = value
            self.assert_code("TIME", source)

    def test_invalid_scores_and_unsupported_semantics(self):
        for score, code in (({"ft": [-1, 0]}, "SCORE"), ({"ft": [True, 0]}, "SCORE"),
                ({"ft": [1.0, 0]}, "SCORE"), ({"ft": [101, 0]}, "SCORE"), ({"ft": [1]}, "SCORE"),
                ({"ft": "1-0"}, "SCORE"), ({"ft": [0, 0], "ht": [1, 0]}, "SCORE"),
                ({"ft": [1, 0], "unreviewed": [1, 0]}, "UNKNOWN_FIELD")):
            source = payload()
            source["matches"][0]["score"] = score
            self.assert_code(code, source)

    def test_unknown_fields_nulls_and_required_fields(self):
        for scope in ("root", "row", "score"):
            source = payload()
            obj = source if scope == "root" else source["matches"][0] if scope == "row" else source["matches"][0]["score"]
            obj["unexpected"] = "private-sentinel-never-in-errors"
            diagnostic = self.assert_code("UNKNOWN_FIELD", source)
            self.assertNotIn("private-sentinel", str(diagnostic))
        for key in ("date", "team1", "team2", "round", "time", "score"):
            source = payload()
            source["matches"][0][key] = None
            self.assert_code("NULL", source)
        for key in ("date", "team1", "team2", "round"):
            source = payload()
            del source["matches"][0][key]
            self.assert_code("REQUIRED", source)

    def test_schema_encoding_duplicate_keys_constants_and_size(self):
        for raw, code in ((b"{bad", "SCHEMA"), (b"\xff", "SCHEMA"), (b"[]", "SCHEMA"),
                (b'{"name":"a","name":"b"}', "DUPLICATE"),
                (b'{"name":NaN}', "SCHEMA"), (b" " * (MAX_BYTES + 1), "LIMIT"), (b"", "LIMIT")):
            self.assert_code(code, raw)
        self.assert_code("SCHEMA", {"name": "Artificial cup 2024/25", "matches": {}})
        self.assert_code("COVERAGE", {"name": "Artificial cup 2024/25", "matches": []})
        self.assert_code("COVERAGE", {"name": "Artificial cup 2024/25", "matches": [{}] * (MAX_MATCHES + 1)})

    def test_scope_coverage_round_and_mapping_validation(self):
        source = payload()
        source["name"] = "Unreviewed season"
        self.assert_code("SCOPE", source)
        source = payload()
        source["matches"][0]["round"] = "Mystery final"
        self.assert_code("ROUND", source)
        self.assert_code("COVERAGE", mapping=replace(mapping(), expected_rows=4))
        self.assert_code("COVERAGE", mapping=replace(mapping(), expected_rows=True))
        self.assert_code("IDENTITY_REVIEW_REQUIRED", mapping=replace(mapping(), evidence=IdentityEvidence(False, "unreviewed")))
        self.assert_code("DUPLICATE", mapping=replace(mapping(), teams=(*mapping().teams, mapping().teams[0])))

    def test_future_finished_and_observation_not_utc(self):
        self.assert_code("SCORE_STATUS", observed_at=datetime(2024, 9, 1, tzinfo=timezone.utc))
        self.assert_code("UTC", observed_at=NOW.replace(tzinfo=None))

    def test_verified_content_digest_requires_original_bytes_and_bounded_acquisition_time(self):
        raw = encode(payload())
        manifest = replace(UCL_2024_25, content_sha256=sha256(raw).hexdigest(), acquired_at=NOW)
        self.prepare(raw, manifest=manifest)
        self.assert_code("CONTENT_MISMATCH", manifest=manifest)
        self.assert_code("CONTENT_MISMATCH", raw + b" ", manifest=manifest)
        self.assert_code("UTC", raw, manifest=replace(manifest, acquired_at=NOW + timedelta(seconds=1)))
        self.assert_code("SCOPE", manifest=replace(UCL_2024_25, path="../escape.json"))

    def test_manifest_commit_is_provenance_not_semantic_revision(self):
        first = self.prepare()
        manifest = replace(UCL_2024_25, commit="a" * 40, license_reference=
            "https://github.com/openfootball/football.json/blob/" + "a" * 40 + "/LICENSE.md")
        result = self.continued(first, manifest=manifest)
        self.assertEqual(first.semantic_digest, result.semantic_digest)
        self.assertTrue(all(not v.changed and v.provider_revision is None for v in result.versions))

    def test_offline_no_network_files_or_clock_reads(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
                patch("builtins.open", side_effect=AssertionError("files forbidden")), \
                patch.object(Path, "open", side_effect=AssertionError("files forbidden")):
            self.prepare(encode(payload()))

    def test_fixture_digest_excludes_revision_and_review_reference_not_football_content(self):
        fixture = self.prepare().fixtures[0]
        self.assertEqual(fixture_fingerprint(fixture), fixture_fingerprint(replace(fixture, local_revision=9)))
        self.assertEqual(fixture_fingerprint(fixture), fixture_fingerprint(replace(fixture,
            status_review_reference="another-reviewed-reference")))
        self.assertNotEqual(fixture_fingerprint(fixture), fixture_fingerprint(replace(fixture, source_time="12:00")))


if __name__ == "__main__":
    unittest.main()
