"""Identity and local version rules, entirely artificial and offline."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from hashlib import sha256
import json
import unittest

from football_data_fakes import NOW, encode
from provider_identity_fakes import EVIDENCE, identity_setup
from src.providers.identity_registry import IdentityEvidence, IdentityKind, IdentityRegistry, RegistryError
from src.providers.models import StageType, TeamType
from src.providers.observed_versions import (
    ProviderRevisionEvidence, StreamKind, StreamRef, VersionLedger, fixture_fingerprint,
)


class IdentityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.versions, self.context, *_ = identity_setup()
        self.empty = self.context.empty_snapshot
        self.provider = self.empty.provider

    def record(self, kind):
        return next(r for r in self.registry.records if r.kind is kind)

    def register_again(self, record, **changes):
        values = dict(parent_id=record.parent_id, team_type=record.team_type,
                      stage_kind=record.stage_kind, participants=record.participants,
                      order=record.order, legs=record.legs)
        values.update(changes)
        return self.registry.register(record.provider, record.kind, record.external_id, evidence=EVIDENCE, **values)

    def test_names_dates_and_insertion_order_are_not_identity_keys(self):
        first = IdentityRegistry()
        second = IdentityRegistry()
        for target, order in ((first, ("100", "200")), (second, ("200", "100"))):
            root = target.register("synthetic", IdentityKind.PROVIDER, "synthetic", evidence=EVIDENCE)
            for key in order:
                target.register("synthetic", IdentityKind.PARTICIPANT, key, parent_id=root.id,
                                team_type=TeamType.CLUB, evidence=EVIDENCE)
        self.assertEqual(first.to_bytes(), second.to_bytes())
        self.assertTrue(all(r.id.startswith('uefa:') for r in self.registry.records))
        self.assertNotEqual(self.empty.competition.id, '2001')

    def test_identical_binding_is_idempotent_and_retains_canonical_identity(self):
        before = self.registry.to_bytes()
        for record in self.registry.records:
            self.assertEqual(self.register_again(record), record)
        self.assertEqual(before, self.registry.to_bytes())

    def test_new_evidence_does_not_reassign_existing_identity(self):
        record = self.record(IdentityKind.PARTICIPANT)
        before = self.registry.to_bytes()
        same = self.registry.register(record.provider, record.kind, record.external_id,
            parent_id=record.parent_id, team_type=record.team_type,
            evidence=IdentityEvidence(True, 'synthetic-second-review'))
        self.assertEqual(record, same)
        self.assertEqual(before, self.registry.to_bytes())

    def test_unconfirmed_or_missing_evidence_cannot_allocate_identity(self):
        for evidence in (None, IdentityEvidence(False, 'unreviewed'), IdentityEvidence(1, 'not-a-bool')):
            before = self.registry.to_bytes()
            with self.assertRaisesRegex(RegistryError, 'UNCONFIRMED'):
                self.registry.register('another', IdentityKind.PROVIDER, 'another', evidence=evidence)
            self.assertEqual(before, self.registry.to_bytes())

    def test_club_national_collision_fails_without_mutation(self):
        record = self.record(IdentityKind.PARTICIPANT)
        before = self.registry.to_bytes()
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            self.register_again(record, team_type=TeamType.NATIONAL)
        self.assertEqual(before, self.registry.to_bytes())

    def test_provider_namespaces_keep_same_external_ids_separate(self):
        other = self.registry.register('another', IdentityKind.PROVIDER, 'another', evidence=EVIDENCE)
        record = self.record(IdentityKind.PARTICIPANT)
        second = self.registry.register('another', record.kind, record.external_id, parent_id=other.id,
                                        team_type=TeamType.CLUB, evidence=EVIDENCE)
        self.assertNotEqual(record.id, second.id)

    def test_season_specific_participation_preserves_team_identity(self):
        team, season = self.record(IdentityKind.PARTICIPANT), self.record(IdentityKind.SEASON)
        later = self.registry.register(self.provider, IdentityKind.SEASON, 'later-season',
                                       parent_id=season.parent_id, evidence=EVIDENCE)
        self.assertFalse(self.registry.has_participation(later.id, team.id))
        self.registry.confirm_participation(later.id, team.id, evidence=EVIDENCE)
        self.assertTrue(self.registry.has_participation(later.id, team.id))
        self.assertEqual(team, self.registry.get(team.id))
        self.assertTrue(self.registry.has_participation(season.id, team.id))

    def test_unconfirmed_team_membership_stops_fixture_registration(self):
        season = self.record(IdentityKind.SEASON)
        later = self.registry.register(self.provider, IdentityKind.SEASON, 'later', parent_id=season.parent_id, evidence=EVIDENCE)
        teams = tuple(r.id for r in self.registry.records if r.kind is IdentityKind.PARTICIPANT)[:2]
        with self.assertRaisesRegex(RegistryError, 'UNCONFIRMED'):
            self.registry.register(self.provider, IdentityKind.FIXTURE, 'new-fixture',
                                   parent_id=later.id, participants=teams, evidence=EVIDENCE)

    def test_fixture_cannot_silently_change_teams_or_home_away(self):
        fixture = self.record(IdentityKind.FIXTURE)
        before = self.registry.to_bytes()
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            self.register_again(fixture, participants=tuple(reversed(fixture.participants)))
        self.assertEqual(before, self.registry.to_bytes())

    def test_fixture_external_id_reuse_in_new_season_is_conflict(self):
        fixture = self.record(IdentityKind.FIXTURE)
        season = self.registry.get(fixture.parent_id)
        later = self.registry.register(self.provider, IdentityKind.SEASON, 'later', parent_id=season.parent_id, evidence=EVIDENCE)
        for team in fixture.participants:
            self.registry.confirm_participation(later.id, team, evidence=EVIDENCE)
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            self.register_again(fixture, parent_id=later.id)

    def test_missing_team_and_cross_provider_references_fail_closed(self):
        fixture = self.record(IdentityKind.FIXTURE)
        with self.assertRaisesRegex(RegistryError, 'REFERENCE'):
            self.registry.register(self.provider, IdentityKind.FIXTURE, 'missing-team-fixture',
                parent_id=fixture.parent_id, participants=('missing-team', fixture.participants[1]), evidence=EVIDENCE)
        foreign = self.registry.register('foreign', IdentityKind.PROVIDER, 'foreign', evidence=EVIDENCE)
        with self.assertRaisesRegex(RegistryError, 'SCOPE'):
            self.registry.register(self.provider, IdentityKind.PARTICIPANT, 'foreign-team',
                                    parent_id=foreign.id, team_type=TeamType.CLUB, evidence=EVIDENCE)

    def test_national_participant_cannot_join_club_competition(self):
        root = self.record(IdentityKind.PROVIDER)
        national = self.registry.register(self.provider, IdentityKind.PARTICIPANT, 'national-team',
            parent_id=root.id, team_type=TeamType.NATIONAL, evidence=EVIDENCE)
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            self.registry.confirm_participation(self.empty.season.id, national.id, evidence=EVIDENCE)

    def test_stages_and_ties_are_scoped_and_tie_pair_has_no_home_direction(self):
        season = self.record(IdentityKind.SEASON)
        stage = self.registry.register(self.provider, IdentityKind.STAGE, 'knockout', parent_id=season.id,
                                       stage_kind=StageType.KNOCKOUT, evidence=EVIDENCE)
        teams = self.record(IdentityKind.FIXTURE).participants
        tie = self.registry.register(self.provider, IdentityKind.TIE, 'synthetic-tie', parent_id=stage.id,
                                     participants=teams, legs=2, evidence=EVIDENCE)
        self.assertEqual(tie, self.register_again(tie, participants=tuple(reversed(teams))))
        with self.assertRaisesRegex(RegistryError, 'SCOPE'):
            self.registry.register(self.provider, IdentityKind.TIE, 'invalid-league-tie',
                parent_id=self.empty.stages[0].id, participants=teams, legs=2, evidence=EVIDENCE)
        self.assertEqual(self.registry.to_bytes(), IdentityRegistry.from_bytes(self.registry.to_bytes()).to_bytes())

    def test_same_round_order_cannot_have_two_identity_bindings(self):
        item = self.record(IdentityKind.ROUND)
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            self.registry.register(self.provider, item.kind, 'different-external-round',
                                   parent_id=item.parent_id, order=item.order, evidence=EVIDENCE)

    def test_registry_snapshot_is_deterministic_and_fixture_direction_preserved(self):
        payload = self.registry.to_bytes()
        raw = json.loads(payload)
        raw['records'].reverse()
        raw['participations'].reverse()
        restored = IdentityRegistry.from_bytes(encode(raw))
        self.assertEqual(restored.to_bytes(), payload)
        for record in self.registry.records:
            self.assertEqual(record, restored.get(record.id))
        with self.assertRaises(FrozenInstanceError):
            restored.records[0].id = 'another-id'

    def test_tampered_canonical_id_duplicate_record_or_unknown_field_is_rejected(self):
        for change in ('id', 'duplicate', 'unknown'):
            document = json.loads(self.registry.to_bytes())
            if change == 'id':
                document['records'][0]['id'] = 'forged-canonical-id'
            elif change == 'duplicate':
                document['records'].append(deepcopy(document['records'][0]))
            else:
                document['unexpected'] = True
            with self.subTest(change=change), self.assertRaises(RegistryError):
                IdentityRegistry.from_bytes(encode(document))

    def test_schema_limits_and_safe_errors(self):
        for raw in (b'{broken', b'{"domain":1,"domain":2}', b'[]', b'x' * (1024 * 1024 + 1)):
            with self.assertRaises(RegistryError):
                IdentityRegistry.from_bytes(raw)
        with self.assertRaises(RegistryError) as caught:
            self.registry.register('do not echo sensitive marker', IdentityKind.PROVIDER,
                                   'bad', evidence=EVIDENCE)
        self.assertEqual(str(caught.exception), 'provider_registry:IDENTITY')

    def test_pinned_snapshot_detects_changed_binding_attributes(self):
        original = self.registry.to_bytes()
        fingerprint = sha256(original).hexdigest()
        self.assertEqual(IdentityRegistry.from_bytes(original, expected_fingerprint=fingerprint).to_bytes(), original)
        modified = json.loads(original)
        fixture = next(r for r in modified['records'] if r['kind'] == 'fixture')
        fixture['participants'].reverse()
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            IdentityRegistry.from_bytes(encode(modified), expected_fingerprint=fingerprint)

    def test_lookup_bad_scope_has_safe_error(self):
        with self.assertRaises(RegistryError):
            self.registry.lookup(self.provider, IdentityKind.SEASON, '2557', parent_id={})

    def test_restore_cannot_drop_participation_needed_by_fixtures(self):
        raw = json.loads(self.registry.to_bytes())
        raw['participations'].pop()
        with self.assertRaisesRegex(RegistryError, 'UNCONFIRMED'):
            IdentityRegistry.from_bytes(encode(raw))

    def test_registry_record_limit_does_not_insert_partial_identity(self):
        from unittest.mock import patch
        before = self.registry.to_bytes()
        with patch('src.providers.identity_registry.MAX_RECORDS', len(self.registry.records)):
            with self.assertRaisesRegex(RegistryError, 'LIMIT'):
                self.registry.register('new-provider', IdentityKind.PROVIDER, 'new-provider', evidence=EVIDENCE)
        self.assertEqual(before, self.registry.to_bytes())


class ObservedVersionsTests(unittest.TestCase):
    def setUp(self):
        self.ledger = VersionLedger()
        self.ref = StreamRef('uefa:fixture:synthetic-one', StreamKind.FIXTURE)
        self.a, self.b = 'a' * 64, 'b' * 64

    def observe(self, value, seconds=0, expected=None, **kwargs):
        return self.ledger.observe(self.ref, value, observed_at=NOW + timedelta(seconds=seconds),
                                   expected_version=self.ledger.version(self.ref) if expected is None else expected, **kwargs)

    def test_identical_replays_and_newer_observation_do_not_make_versions(self):
        first = self.observe(self.a)
        self.assertEqual((first.local_content_version, first.changed, first.provider_revision), (1, True, None))
        snapshot = self.ledger.to_bytes()
        self.assertFalse(self.observe(self.a).changed)
        self.assertEqual(snapshot, self.ledger.to_bytes())
        latest = self.observe(self.a, seconds=1)
        self.assertEqual(latest.local_content_version, 1)
        self.assertEqual(len(self.ledger.current(self.ref).versions), 1)

    def test_content_changes_increment_local_sequence_not_provider_revision(self):
        self.observe(self.a)
        second = self.observe(self.b, seconds=1)
        self.assertEqual(second.local_content_version, 2)
        self.assertIsNone(second.provider_revision)

    def test_out_of_order_equal_time_conflict_and_stale_expected_version(self):
        self.observe(self.a, seconds=5)
        for value, seconds, expected, code in ((self.a, 4, 1, 'OUT_OF_ORDER'),
            (self.b, 5, 1, 'VERSION_CONFLICT'), (self.a, 6, 0, 'VERSION_CONFLICT')):
            before = self.ledger.to_bytes()
            with self.subTest(code=code), self.assertRaisesRegex(RegistryError, code):
                self.observe(value, seconds, expected=expected)
            self.assertEqual(before, self.ledger.to_bytes())

    def test_reversion_is_explicit_review_not_newer_clock_wins(self):
        self.observe(self.a)
        self.observe(self.b, 1)
        with self.assertRaisesRegex(RegistryError, 'REVERSION_REQUIRES_REVIEW'):
            self.observe(self.a, 2)

    def test_provider_evidence_required_and_same_token_cannot_change_content(self):
        with self.assertRaisesRegex(RegistryError, 'UNCONFIRMED'):
            self.observe(self.a, provider_revision=ProviderRevisionEvidence('p1', False))
        self.observe(self.a, provider_revision=ProviderRevisionEvidence('p1', True))
        with self.assertRaisesRegex(RegistryError, 'VERSION_CONFLICT'):
            self.observe(self.b, 1, provider_revision=ProviderRevisionEvidence('p1', True))

    def test_new_provider_token_same_content_does_not_increment_local_version(self):
        self.observe(self.a, provider_revision=ProviderRevisionEvidence('p1', True, 1))
        second = self.observe(self.a, 1, provider_revision=ProviderRevisionEvidence('p2', True, 2))
        self.assertEqual(second.local_content_version, 1)
        self.assertEqual(len(self.ledger.current(self.ref).provider_bindings), 2)
        with self.assertRaisesRegex(RegistryError, 'OUT_OF_ORDER'):
            self.observe(self.a, 2, provider_revision=ProviderRevisionEvidence('p1', True, 1))
        with self.assertRaisesRegex(RegistryError, 'UNCONFIRMED'):
            self.observe(self.a, 2)

    def test_provider_tokens_are_scoped_per_stream_not_global_snapshot(self):
        self.observe(self.a, provider_revision=ProviderRevisionEvidence('token', True))
        other = StreamRef('uefa:stage:synthetic-one', StreamKind.TOTAL)
        self.ledger.observe(other, self.b, observed_at=NOW, expected_version=0,
                            provider_revision=ProviderRevisionEvidence('token', True))
        self.assertEqual(len(self.ledger.streams), 2)

    def test_roundtrip_and_stream_insertion_order_are_deterministic(self):
        self.observe(self.a)
        self.observe(self.b, 1)
        payload = self.ledger.to_bytes()
        self.assertEqual(VersionLedger.from_bytes(payload).to_bytes(), payload)
        fingerprint = sha256(payload).hexdigest()
        self.assertEqual(VersionLedger.from_bytes(payload, expected_fingerprint=fingerprint).to_bytes(), payload)
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            VersionLedger.from_bytes(payload + b' ', expected_fingerprint=fingerprint)

    def test_corrupt_history_duplicate_stream_and_revision_gap_are_rejected(self):
        self.observe(self.a)
        self.observe(self.b, 1)
        for failure in ('duplicate', 'gap', 'clock', 'digest'):
            doc = json.loads(self.ledger.to_bytes())
            if failure == 'duplicate':
                doc['streams'].append(deepcopy(doc['streams'][0]))
            elif failure == 'gap':
                doc['streams'][0]['versions'][1]['number'] = 5
            elif failure == 'clock':
                doc['streams'][0]['last_observed_at'] = (NOW - timedelta(days=1)).isoformat()
            else:
                doc['streams'][0]['versions'][0]['semantic_digest'] = 'not-a-digest'
            with self.subTest(failure=failure), self.assertRaises(RegistryError):
                VersionLedger.from_bytes(encode(doc))

    def test_fixture_fingerprint_excludes_versions_and_source_poll_time_not_kickoff(self):
        from football_data_fakes import make_payloads
        from src.providers.football_data import map_responses
        context, m, f, s = make_payloads()
        snapshot = map_responses(encode(m), encode(f), encode(s), context=context, fetched_at=NOW).snapshot
        fixture = snapshot.fixtures[0]
        self.assertEqual(fixture_fingerprint(fixture), fixture_fingerprint(replace(
            fixture, revision=10, updated_at=fixture.updated_at + timedelta(seconds=1))))
        self.assertNotEqual(fixture_fingerprint(fixture), fixture_fingerprint(replace(
            fixture, kickoff=fixture.kickoff + timedelta(hours=1))))

    def test_bad_clock_bool_expected_and_invalid_digest_do_not_mutate(self):
        with self.assertRaisesRegex(RegistryError, 'VERSION_CONFLICT'):
            self.observe(self.a, expected=False)
        with self.assertRaisesRegex(RegistryError, 'UTC'):
            self.ledger.observe(self.ref, self.a, observed_at=NOW.replace(tzinfo=None), expected_version=0)
        with self.assertRaises(RegistryError):
            self.observe('not-a-digest')
        self.assertFalse(self.ledger.streams)

    def test_source_update_time_is_separate_and_cannot_regress_or_disappear(self):
        first = self.observe(self.a, source_updated_at=NOW - timedelta(hours=1))
        latest = self.observe(self.a, 1, source_updated_at=NOW)
        self.assertEqual((first.local_content_version, latest.local_content_version), (1, 1))
        for value, code in ((NOW - timedelta(hours=2), 'OUT_OF_ORDER'), (None, 'UNCONFIRMED')):
            with self.assertRaisesRegex(RegistryError, code):
                self.observe(self.a, 2, source_updated_at=value)
        self.assertEqual(VersionLedger.from_bytes(self.ledger.to_bytes()).to_bytes(), self.ledger.to_bytes())

    def test_provider_counter_history_roundtrip_and_conflicting_restore(self):
        self.observe(self.a, provider_revision=ProviderRevisionEvidence('p1', True, 1))
        self.observe(self.b, 1, provider_revision=ProviderRevisionEvidence('p2', True, 2))
        saved = self.ledger.to_bytes()
        self.assertEqual(VersionLedger.from_bytes(saved).to_bytes(), saved)
        for mutation in ('counter', 'content'):
            raw = json.loads(saved)
            binding = raw['streams'][0]['provider_bindings'][-1]
            if mutation == 'counter':
                binding['sequence'] = 1
            else:
                binding['semantic_digest'] = self.a
            with self.subTest(mutation=mutation), self.assertRaisesRegex(RegistryError, 'VERSION_CONFLICT'):
                VersionLedger.from_bytes(encode(raw))

    def test_history_cap_refuses_new_version_without_trimming_old_ones(self):
        for i in range(32):
            self.observe(format(i, '064x'), i)
        saved = self.ledger.to_bytes()
        with self.assertRaisesRegex(RegistryError, 'LIMIT'):
            self.observe(format(32, '064x'), 32)
        self.assertEqual(saved, self.ledger.to_bytes())
