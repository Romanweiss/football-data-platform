"""Pass API contracts: offline/fake transport only; live SQL checked separately."""
import os
import unittest
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'application.settings')
import django
django.setup()
from django.test import Client

from application.errors import ApiError, ServingIntegrityError
from application.passes import COMPLETION_SQL, COORDINATE_SYSTEM, EXCLUSION_SQL, MAX_PASSES, MAX_PASS_RESPONSE_BYTES, read_passes
from application.repository import FootballRepository
from application.services import FootballService

CONTEXT = {'competition_id': 9, 'season_id': 281}
PREFIX = '/api/v1/competitions/9/seasons/281/matches/3895052/passes'
ROW = dict(event_id='00000000-0000-0000-0000-000000000001', event_index=8,
           team_id=904, team_name='Home', player_id=1, player_name='Player', recipient_id=2,
           recipient_name='Recipient', period=1, minute=0, second=12,
           start_x=0.123456789, start_y=80.0, end_x=120.0, end_y=0.0,
           outcome_id=None, outcome_name=None, completion_status='completed')


def summary(total=1, completed=1, failed=0, unknown=0, **reasons):
    return dict(total_count=total, completed=completed, failed=failed, unknown=unknown,
                **{name: reasons.get(name, 0) for name in
                   ('missing_coordinates', 'non_finite_coordinates', 'out_of_bounds_coordinates')})


class PassProjectionTests(unittest.TestCase):
    def repo(self, counts=None, rows=None):
        repo = Mock()
        repo._query.side_effect = [[counts or summary()], [deepcopy(ROW)] if rows is None else rows]
        return repo

    def test_sql_values_are_bound_with_full_context_and_stable_order(self):
        repo = self.repo()
        filters = {'team_id': 904, 'player_id': 1, 'period': 1}
        result = read_passes(repo, context=CONTEXT, match_id=3895052, filters=filters)
        for call in repo._query.call_args_list:
            sql = call.args[0]
            self.assertTrue(sql.startswith('WITH '))
            for name, value in {**CONTEXT, 'match_id': 3895052, **filters}.items():
                self.assertEqual(call.args[1][name], value)
                self.assertIn(name + ' = {' + name + ':', sql)
            self.assertNotIn('3895052', sql)
            self.assertNotIn('904', sql)
            for word in ('INSERT', 'ALTER', 'CREATE', 'DROP', 'DELETE'):
                self.assertNotIn(word, sql)
        self.assertIn(f'ORDER BY event_index, event_id LIMIT {MAX_PASSES + 1}', repo._query.call_args.args[0])
        self.assertEqual(result['passes'][0], ROW)
        self.assertEqual(result['filters'], filters)
        self.assertEqual(result['coordinate_system'], COORDINATE_SYSTEM)

    def test_no_filter_or_bucket_wildcard_and_readonly_sdk(self):
        client = Mock()
        client.query.side_effect = [
            SimpleNamespace(column_names=list(summary()), result_rows=[tuple(summary().values())]),
            SimpleNamespace(column_names=list(ROW), result_rows=[tuple(ROW.values())]),
        ]
        read_passes(FootballRepository(client), context=CONTEXT, match_id=3895052, filters={})
        for call in client.query.call_args_list:
            self.assertEqual(call.kwargs['settings'], {'readonly': 1})
            self.assertEqual(call.kwargs['parameters'], {**CONTEXT, 'match_id': 3895052})
            self.assertIn('FROM football.pass_events WHERE ', call.args[0])

    def test_outcome_sql_defaults_only_for_absent_pair_and_unknown_fails_closed(self):
        self.assertIn('isNull(outcome_id) AND isNull(outcome_name)', COMPLETION_SQL)
        self.assertIn("outcome_id IN (9, 74, 75, 76), 'failed', 'unknown'", COMPLETION_SQL)
        self.assertNotIn('77,', COMPLETION_SQL)
        self.assertIn('NOT isFinite', EXCLUSION_SQL)
        for boundary in ('start_x < 0', 'end_x > 120', 'start_y < 0', 'end_y > 80'):
            self.assertIn(boundary, EXCLUSION_SQL)

    def test_counts_include_excluded_and_never_drop_unknown_silently(self):
        repo = self.repo(summary(total=4, completed=2, failed=1, unknown=1,
                                 missing_coordinates=1, non_finite_coordinates=1, out_of_bounds_coordinates=1))
        result = read_passes(repo, context=CONTEXT, match_id=1, filters={})
        self.assertEqual((result['total_count'], result['returned_count'], result['excluded']['count']), (4, 1, 3))
        self.assertEqual(result['outcome_counts'], {'completed': 2, 'failed': 1, 'unknown': 1})
        self.assertEqual(sum(result['excluded']['reasons'].values()), 3)
        self.assertEqual(result['passes'][0]['start_x'], 0.123456789)

    def test_empty_match_filter_is_valid(self):
        repo = self.repo(summary(total=0, completed=0), [])
        result = read_passes(repo, context=CONTEXT, match_id=1, filters={'player_id': 999})
        self.assertEqual(result['total_count'], 0)
        self.assertEqual(result['passes'], [])

    def test_limit_is_explicit_error_without_partial_rows(self):
        repo = self.repo(summary(total=MAX_PASSES + 1, completed=MAX_PASSES + 1))
        with self.assertRaises(ApiError) as exc:
            read_passes(repo, context=CONTEXT, match_id=1, filters={})
        self.assertEqual((exc.exception.status, exc.exception.code), (422, 'pass_result_too_large'))
        self.assertEqual(repo._query.call_count, 1)

    def test_exact_row_limit_is_inclusive_without_sampling(self):
        rows = [{**ROW, 'event_id': f'00000000-0000-0000-0000-{index:012d}', 'event_index': index}
                for index in range(MAX_PASSES)]
        result = read_passes(self.repo(summary(total=MAX_PASSES, completed=MAX_PASSES), rows),
                             context=CONTEXT, match_id=1, filters={})
        self.assertEqual(result['total_count'], MAX_PASSES)
        self.assertEqual(result['returned_count'], MAX_PASSES)
        self.assertEqual(result['passes'], rows)

    def test_encoded_byte_bound_includes_variable_length_names(self):
        for name in ('x' * MAX_PASS_RESPONSE_BYTES, '\u0416' * (MAX_PASS_RESPONSE_BYTES // 2)):
            with self.subTest(multibyte=name[0] != 'x'):
                repo = self.repo(rows=[{**ROW, 'player_name': name}])
                with self.assertRaises(ApiError) as exc:
                    read_passes(repo, context=CONTEXT, match_id=1, filters={})
                self.assertEqual((exc.exception.status, exc.exception.code), (422, 'pass_result_too_large'))

    def test_drift_duplicates_or_unrecognized_status_fail_closed(self):
        cases = [(summary(), []), (summary(total=2, completed=2), [ROW, ROW]),
                 (summary(), [{**ROW, 'completion_status': 'new-status'}]),
                 (summary(total=2), [ROW]), (summary(missing_coordinates=2), [])]
        for counts, rows in cases:
            with self.subTest(counts=counts, rows=len(rows)), self.assertRaises(ServingIntegrityError):
                read_passes(self.repo(counts, rows), context=CONTEXT, match_id=1, filters={})

    def test_parameter_payload_never_becomes_sql(self):
        repo = self.repo()
        value = '904 OR 1=1 --'
        read_passes(repo, context=CONTEXT, match_id=1, filters={'team_id': value})
        for call in repo._query.call_args_list:
            self.assertNotIn(value, call.args[0])
            self.assertEqual(call.args[1]['team_id'], value)


class PassHttpTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.repo.match.return_value = {**CONTEXT, 'match_id': 3895052}
        self.repo._query.side_effect = [[summary()], [deepcopy(ROW)]]
        @contextmanager
        def opened(): yield self.repo
        self.opened = patch('application.views.open_repository', side_effect=opened).start()
        self.addCleanup(patch.stopall)
        self.http = Client(HTTP_HOST='localhost', raise_request_exception=False)

    def test_canonical_get_and_filters(self):
        response = self.http.get(PREFIX + '?team_id=904&player_id=1&period=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['passes'][0], ROW)
        self.repo.match.assert_called_once_with(3895052, CONTEXT)

    def test_invalid_queries_rejected_before_connection(self):
        for query in ('period=0', 'period=6', 'period=-1', 'period=1.0', 'player_id=',
                      'team_id=904%20OR%201=1', 'player_id=4294967296', 'team_id=1&team_id=2',
                      'period=1&period=2', 'unknown=1', 'limit=1', 'player_id=1;DROP'):
            with self.subTest(query=query):
                self.assertEqual(self.http.get(PREFIX + '?' + query).status_code, 400)
        for path in (PREFIX.replace('/9/', '/0/', 1), PREFIX.replace('/3895052/', '/bad/')):
            self.assertEqual(self.http.get(path).status_code, 400)
        self.opened.assert_not_called()

    def test_missing_or_wrong_context_match_does_not_read_passes(self):
        self.repo.match.return_value = None
        self.assertEqual(self.http.get(PREFIX).status_code, 404)
        self.repo._query.assert_not_called()
        self.repo.match.assert_called_with(3895052, CONTEXT)

    def test_post_does_not_open_connection(self):
        self.assertEqual(self.http.post(PREFIX).status_code, 405)
        self.opened.assert_not_called()

    def test_safe_exception_no_credential_or_sql_leakage(self):
        self.repo._query.side_effect = RuntimeError('password=SECRET SELECT internal')
        with self.assertLogs('football_api', level='ERROR') as logs:
            result = self.http.get(PREFIX)
        self.assertEqual(result.status_code, 500)
        self.assertNotIn('SECRET', str(logs.output) + result.content.decode())
        self.assertNotIn('SELECT', str(logs.output) + result.content.decode())

    def test_service_requires_match_before_projection(self):
        self.repo.match.return_value = None
        with self.assertRaises(ApiError):
            FootballService(self.repo).passes(1, CONTEXT, {})
        self.repo._query.assert_not_called()
