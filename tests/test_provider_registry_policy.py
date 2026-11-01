"""Artificial six-response windows exercise the complete offline proposal boundary."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import io
import unittest
from unittest.mock import patch

from football_data_fakes import NOW, encode, observations
from provider_identity_fakes import identity_setup, rebuild_tables
from src.providers.football_data import MappingError
from src.providers.identity_registry import IdentityKind, IdentityRegistry, RegistryError
from src.providers.models import ContractError
from src.providers.observed_versions import StreamKind, StreamRef, VersionLedger
from src.providers.registry_policy import bind_mapping_context, prepare_registered_window
from src.providers.validation import canonical_bytes, validate_update


class RegistryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.ledger, self.context, self.metadata, self.fixtures, self.standings = identity_setup()

    def bound_context(self):
        return bind_mapping_context(self.registry, self.context.empty_snapshot,
            tuple(binding.external_id for binding in self.context.fixture_bindings), self.ledger)

    def propose(self, previous=None, seconds=0):
        return prepare_registered_window(observations(self.metadata, self.fixtures, self.standings,
            offset=timedelta(seconds=seconds)), registry=self.registry, versions=self.ledger,
            context=self.bound_context(), previous=previous)

    def accept_first_locally(self):
        proposal = self.propose()
        self.ledger = VersionLedger.from_bytes(proposal.ledger_after_state)
        return proposal

    def source_fixture(self, status='TIMED'):
        return next(f for f in self.fixtures['matches'] if f['status'] == status)

    def neutral_fixture(self, snapshot, source):
        return next(f for f in snapshot.fixtures if f.identity.external_id == str(source['id']))

    def assert_input_unchanged_on_failure(self, previous, error):
        before = self.registry.to_bytes(), self.ledger.to_bytes()
        with self.assertRaises(error):
            self.propose(previous, seconds=3600)
        self.assertEqual(before, (self.registry.to_bytes(), self.ledger.to_bytes()))

    def test_initial_proposal_is_fully_bound_dq_checked_and_not_publication(self):
        registry_before, ledger_before = self.registry.to_bytes(), self.ledger.to_bytes()
        proposal = self.propose()
        self.assertEqual(len(proposal.snapshot.fixtures), 144)
        self.assertEqual(len(proposal.snapshot.participants), 36)
        self.assertEqual(len(proposal.versions), 148)
        self.assertTrue(all(v.local_content_version == 1 and v.changed for v in proposal.versions))
        self.assertTrue(all(v.provider_revision is None for v in proposal.versions))
        self.assertEqual(proposal.consistency, 'OBSERVED_WINDOW_STABLE_NOT_ATOMIC')
        self.assertIsNone(proposal.source_revision)
        self.assertFalse(proposal.publish_authorized)
        self.assertEqual(len(proposal.window.receipts), 6)
        self.assertFalse(any(c.status == 'FAIL' for c in proposal.window.mapping.checks))
        self.assertEqual((registry_before, ledger_before), (self.registry.to_bytes(), self.ledger.to_bytes()))

    def test_identical_load_and_reordered_input_do_not_create_revisions(self):
        first = self.accept_first_locally()
        self.fixtures['matches'].reverse()
        self.standings['standings'].reverse()
        for table in self.standings['standings']:
            table['table'].reverse()
        second = self.propose(first.snapshot, 3600)
        self.assertFalse(any(v.changed for v in second.versions))
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual({f.id: f.revision for f in first.snapshot.fixtures},
                         {f.id: f.revision for f in second.snapshot.fixtures})

    def test_rescheduling_changes_content_version_not_fixture_id(self):
        first = self.accept_first_locally()
        row = self.source_fixture()
        row['utcDate'] = (NOW + timedelta(days=40)).isoformat()
        row['lastUpdated'] = (NOW + timedelta(minutes=30)).isoformat()
        second = self.propose(first.snapshot, 3600)
        before, after = self.neutral_fixture(first.snapshot, row), self.neutral_fixture(second.snapshot, row)
        self.assertEqual(before.id, after.id)
        self.assertEqual(after.revision, before.revision + 1)
        self.assertEqual(sum(v.changed for v in second.versions), 1)

    def test_score_correction_versions_fixture_and_each_affected_table(self):
        first = self.accept_first_locally()
        row = self.source_fixture('FINISHED')
        row['score']['fullTime']['home'] += 1
        row['lastUpdated'] = (NOW + timedelta(minutes=30)).isoformat()
        rebuild_tables(self.fixtures, self.standings)
        second = self.propose(first.snapshot, 3600)
        before, after = self.neutral_fixture(first.snapshot, row), self.neutral_fixture(second.snapshot, row)
        self.assertEqual(before.id, after.id)
        self.assertEqual(after.revision, 2)
        self.assertEqual({v.ref.kind for v in second.versions if v.changed},
                         {StreamKind.FIXTURE, StreamKind.TOTAL, StreamKind.HOME, StreamKind.AWAY})
        self.assertEqual(sum(v.changed for v in second.versions), 4)

    def test_timed_to_finished_status_change_and_counter_reconciliation(self):
        first = self.accept_first_locally()
        row = self.source_fixture()
        row.update(status='FINISHED', utcDate=(NOW - timedelta(days=1)).isoformat(),
                   lastUpdated=(NOW + timedelta(minutes=30)).isoformat())
        row['score']['fullTime'] = {'home': 2, 'away': 1}
        rebuild_tables(self.fixtures, self.standings)
        second = self.propose(first.snapshot, 3600)
        self.assertEqual(self.neutral_fixture(second.snapshot, row).revision, 2)
        self.assertEqual(sum(f.status.value == 'finished' for f in second.snapshot.fixtures), 37)
        self.assertEqual(sum(entry.played for entry in second.snapshot.standings), 74)

    def test_standings_order_correction_has_its_own_version_not_fixture_changes(self):
        first = self.accept_first_locally()
        table = next(t for t in self.standings['standings'] if t['type'] == 'TOTAL')['table']
        table[0]['position'], table[1]['position'] = table[1]['position'], table[0]['position']
        second = self.propose(first.snapshot, 3600)
        self.assertEqual([v.ref.kind for v in second.versions if v.changed], [StreamKind.TOTAL])
        self.assertEqual({f.id: f.revision for f in first.snapshot.fixtures},
                         {f.id: f.revision for f in second.snapshot.fixtures})
        self.assertIn('provider.standings.tie_breakers',
                      {c.rule_id for c in second.window.mapping.checks if c.status == 'SKIP'})

    def test_source_poll_timestamp_alone_does_not_fabricate_local_revision(self):
        first = self.accept_first_locally()
        row = self.source_fixture()
        row['lastUpdated'] = (NOW + timedelta(minutes=30)).isoformat()
        second = self.propose(first.snapshot, 3600)
        self.assertFalse(any(v.changed for v in second.versions))
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(self.neutral_fixture(second.snapshot, row).updated_at,
                         NOW + timedelta(minutes=30))
        # Old A/B policy is deliberately NOT weakened by the new local policy.
        with self.assertRaises(ContractError):
            validate_update(first.snapshot, second.snapshot)

    def test_display_name_correction_keeps_identity_and_versions_metadata_only(self):
        first = self.accept_first_locally()
        self.metadata['name'] = 'An updated invented competition label'
        second = self.propose(first.snapshot, 3600)
        self.assertEqual(first.snapshot.competition.id, second.snapshot.competition.id)
        self.assertEqual([v.ref.kind for v in second.versions if v.changed], [StreamKind.METADATA])

    def test_failed_table_reconciliation_never_changes_registry_or_versions(self):
        first = self.accept_first_locally()
        self.source_fixture('FINISHED')['score']['fullTime']['home'] += 1
        self.assert_input_unchanged_on_failure(first.snapshot, MappingError)

    def test_unknown_team_or_changed_season_never_allocate_silent_identities(self):
        first = self.accept_first_locally()
        for change in ('team', 'season'):
            saved = deepcopy(self.fixtures)
            if change == 'team':
                self.source_fixture()['homeTeam']['id'] = 999999999
            else:
                self.source_fixture()['season']['id'] = 999999999
            with self.subTest(change=change):
                self.assert_input_unchanged_on_failure(first.snapshot, MappingError)
            self.fixtures = saved

    def test_context_cannot_reassign_fixture_id_or_invent_version(self):
        first = self.context.fixture_bindings[0]
        for replacement in (replace(first, neutral_revision=99),
                            replace(first, canonical_id=self.context.fixture_bindings[1].canonical_id)):
            altered = replace(self.context, fixture_bindings=(replacement, *self.context.fixture_bindings[1:]))
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RegistryError, 'VERSION_CONFLICT'):
                prepare_registered_window(observations(self.metadata, self.fixtures, self.standings),
                    registry=self.registry, versions=self.ledger, context=altered)
        self.assertFalse(self.ledger.streams)

    def test_out_of_order_collection_and_regressing_source_time_fail(self):
        first = self.accept_first_locally()
        with self.assertRaisesRegex(RegistryError, 'OUT_OF_ORDER'):
            self.propose(first.snapshot, -1)
        self.source_fixture()['lastUpdated'] = (NOW - timedelta(days=10)).isoformat()
        self.assert_input_unchanged_on_failure(first.snapshot, RegistryError)

    def test_refresh_requires_previous_snapshot_paired_with_ledger(self):
        first = self.accept_first_locally()
        with self.assertRaisesRegex(RegistryError, 'UNCONFIRMED'):
            self.propose(seconds=3600)
        altered = replace(first.snapshot, standings=tuple(
            replace(entry, rank=1) for entry in first.snapshot.standings))
        with self.assertRaisesRegex(RegistryError, 'VERSION_CONFLICT'):
            self.propose(altered, 3600)
        altered_time = replace(first.snapshot, fixtures=tuple(
            replace(f, updated_at=f.updated_at - timedelta(days=1)) for f in first.snapshot.fixtures))
        with self.assertRaisesRegex(RegistryError, 'VERSION_CONFLICT'):
            self.propose(altered_time, 3600)

    def test_registry_and_ledger_recovery_reproduce_identical_proposal(self):
        first = self.accept_first_locally()
        before = self.propose(first.snapshot, 3600)
        self.registry = IdentityRegistry.from_bytes(self.registry.to_bytes())
        self.ledger = VersionLedger.from_bytes(self.ledger.to_bytes())
        after = self.propose(first.snapshot, 3600)
        self.assertEqual(before, after)
        self.assertEqual(canonical_bytes(before.snapshot), canonical_bytes(after.snapshot))

    def test_source_change_during_window_blocks_all_local_state_changes(self):
        raw = list(observations(self.metadata, self.fixtures, self.standings))
        changed = deepcopy(self.fixtures)
        changed['matches'][0]['score']['fullTime']['home'] += 1
        raw[3] = replace(raw[3], payload=encode(changed))
        old = self.registry.to_bytes(), self.ledger.to_bytes()
        with self.assertRaisesRegex(MappingError, 'SOURCE_CHANGED'):
            prepare_registered_window(tuple(raw), registry=self.registry, versions=self.ledger, context=self.context)
        self.assertEqual(old, (self.registry.to_bytes(), self.ledger.to_bytes()))

    def test_mathematically_consistent_fixture_id_reassignment_is_still_conflict(self):
        a, b = self.fixtures['matches'][:2]
        a['id'], b['id'] = b['id'], a['id']
        old = self.registry.to_bytes(), self.ledger.to_bytes()
        with self.assertRaisesRegex(RegistryError, 'CONFLICT'):
            self.propose()
        self.assertEqual(old, (self.registry.to_bytes(), self.ledger.to_bytes()))

    def test_score_reversion_requires_review_even_with_newer_source_clock(self):
        first = self.accept_first_locally()
        row = self.source_fixture('FINISHED')
        row['score']['fullTime']['home'] += 1
        row['lastUpdated'] = (NOW + timedelta(minutes=30)).isoformat()
        rebuild_tables(self.fixtures, self.standings)
        second = self.propose(first.snapshot, 3600)
        self.ledger = VersionLedger.from_bytes(second.ledger_after_state)
        row['score']['fullTime']['home'] -= 1
        row['lastUpdated'] = (NOW + timedelta(minutes=90)).isoformat()
        rebuild_tables(self.fixtures, self.standings)
        saved = self.ledger.to_bytes()
        with self.assertRaisesRegex(RegistryError, 'REVERSION_REQUIRES_REVIEW'):
            self.propose(second.snapshot, 7200)
        self.assertEqual(saved, self.ledger.to_bytes())

    def test_existing_revision_fenced_collector_and_live_allowlist_remain_strict(self):
        from provider_collection_fakes import make_scenario
        from src.providers.adapter import AdapterFailure, require_live_provider
        from src.providers.collection import CollectionPlan
        snap, rules = make_scenario()
        with self.assertRaises(ContractError):
            CollectionPlan(replace(snap, fixtures=(), standings=()), None, 144, 36, rules)
        with self.assertRaises(AdapterFailure):
            require_live_provider('football-data-org')

    def test_unseen_provider_status_and_retained_score_cannot_bypass_window_gate(self):
        first = self.accept_first_locally()
        row = self.source_fixture()
        row['status'] = 'SUSPENDED'
        row['score']['fullTime'] = {'home': 3, 'away': 1}
        self.assert_input_unchanged_on_failure(first.snapshot, MappingError)

    def test_no_network_storage_environment_or_logging_in_proposal(self):
        raw = observations(self.metadata, self.fixtures, self.standings)
        output = io.StringIO()
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
                patch('pathlib.Path.open', side_effect=AssertionError('storage forbidden')), \
                patch('subprocess.run', side_effect=AssertionError('process forbidden')), \
                redirect_stdout(output), redirect_stderr(output):
            proposal = prepare_registered_window(raw, registry=self.registry, versions=self.ledger, context=self.context)
        self.assertFalse(proposal.publish_authorized)
        self.assertEqual(output.getvalue(), '')
