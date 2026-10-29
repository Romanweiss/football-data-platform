"""Offline Pressure heatmap contract/security tests; no network or credentials."""
import os
import unittest
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock, patch
from clickhouse_connect.driver.exceptions import Error as ClickHouseError

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'application.settings')
import django
django.setup()
from django.test import Client

from application.errors import ApiError, ServingIntegrityError
from application.heatmap import COLUMN_SQL, EXCLUSION_SQL, GRID, INTENSITY_SCALE, MAX_GROUPS, ROW_SQL, read_heatmap, read_pressure_coordinates
from application.services import FootballService
from application.repository import FootballRepository

CONTEXT = {'competition_id': 9, 'season_id': 281}
PREFIX = '/api/v1/competitions/9/seasons/281/matches/3895052/event-heatmap'


def bucket(column=0, row=0, count=1, reason=''):
    return {'exclusion_reason': reason, 'column_index': column, 'row_index': row, 'event_count': count}


class HeatmapProjectionTests(unittest.TestCase):
    def read(self, groups, filters=None):
        repo = Mock()
        repo._query.return_value = groups
        return read_heatmap(repo, context=CONTEXT, match_id=3895052, filters=filters or {}), repo

    def test_scoped_typed_single_query_is_bounded(self):
        data, repo = self.read([bucket()], {'team_id': 904, 'period': 1})
        self.assertEqual(repo._query.call_count, 1)
        sql, params = repo._query.call_args.args
        self.assertEqual(params, {**CONTEXT, 'match_id': 3895052, 'type_id': 17, 'team_id': 904, 'period': 1})
        for name, kind in (('competition_id', 'UInt32'), ('season_id', 'UInt32'), ('match_id', 'UInt64'),
                           ('type_id', 'UInt16'), ('team_id', 'UInt32'), ('period', 'UInt8')):
            self.assertIn(name + ' = {' + name + ':' + kind + '}', sql)
        self.assertIn('FROM football.event_core WHERE', sql)
        self.assertIn('count() AS event_count', sql)
        self.assertTrue(sql.endswith(f'LIMIT {MAX_GROUPS + 1}'))
        self.assertNotIn('3895052', sql)
        self.assertNotIn('904', sql)
        self.assertEqual(data['filters'], {'type': 'pressure', 'team_id': 904, 'period': 1})

    def test_all_cells_counts_exclusions_and_zero_result(self):
        groups = [bucket(0, 0, 2), bucket(11, 7, 3), *[bucket(count=i+1, reason=r) for i, r in enumerate(
            ('missing_coordinates', 'non_finite_coordinates', 'out_of_bounds_coordinates'))]]
        data, _ = self.read(groups)
        self.assertEqual((data['total_count'], data['eligible_event_total'], data['excluded']['count']), (11, 5, 6))
        self.assertEqual(len(data['cells']), 96)
        self.assertEqual(sum(c['count'] for c in data['cells']), 5)
        self.assertEqual(data['cells'][0], {'column': 0, 'row': 0, 'count': 2})
        self.assertEqual(data['cells'][-1], {'column': 11, 'row': 7, 'count': 3})
        empty, _ = self.read([])
        self.assertEqual(sum(c['count'] for c in empty['cells']), 0)
        self.assertEqual(empty['total_count'], 0)

    def test_grid_boundaries_exclusions_and_scale_are_explicit_and_stable(self):
        for token in ('isNull(location_x) OR isNull(location_y)', 'NOT isFinite(location_x)',
                      'location_x < 0', 'location_x > 120', 'location_y < 0', 'location_y > 80'):
            self.assertIn(token, EXCLUSION_SQL)
        self.assertIn("if(exclusion_reason = '', ifNull(location_x, 0), 0)", COLUMN_SQL)
        self.assertIn('/ 10)), 11)', COLUMN_SQL)
        self.assertIn('/ 10)), 7)', ROW_SQL)
        first, _ = self.read([bucket(count=1)])
        second, _ = self.read([bucket(count=300)])
        self.assertEqual(first['grid'], GRID)
        self.assertEqual(first['intensity_scale'], second['intensity_scale'])
        self.assertEqual(first['intensity_scale'], INTENSITY_SCALE)
        self.assertEqual(first['metric']['smoothing'], 'none')
        self.assertFalse(first['coordinate_system']['tracking'])

    def test_no_duplicates_unknown_buckets_invalid_values_or_truncation(self):
        bad = [[bucket(), bucket()], [bucket(column=12)], [bucket(row=8)], [bucket(count=0)],
               [bucket(count=-1)], [bucket(count=True)], [bucket(count=2**53)],
               [bucket(reason='unknown')], [bucket(column=1, reason='missing_coordinates')],
               [{'event_count': 1}], [bucket()] * 100]
        for groups in bad:
            with self.subTest(groups=groups[:2]), self.assertRaises(ServingIntegrityError):
                self.read(groups)

    def test_parameters_never_interpolate_and_results_do_not_mutate_constants(self):
        injection = "904 OR 1=1 --"
        data, repo = self.read([bucket()], {'team_id': injection})
        self.assertNotIn(injection, repo._query.call_args.args[0])
        self.assertEqual(repo._query.call_args.args[1]['team_id'], injection)
        original = deepcopy(INTENSITY_SCALE)
        data['intensity_scale']['lower_bounds'].append(999)
        self.assertEqual(INTENSITY_SCALE, original)


class HeatmapHttpTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.repo.match.return_value = {**CONTEXT, 'match_id': 3895052}
        self.repo._query.return_value = [bucket()]
        @contextmanager
        def opened(): yield self.repo
        self.opened = patch('application.views.open_repository', side_effect=opened).start()
        self.addCleanup(patch.stopall)
        self.http = Client(HTTP_HOST='localhost', raise_request_exception=False)

    def test_canonical_filters_and_unchanged_scope(self):
        response = self.http.get(PREFIX + '?type=pressure&team_id=904&period=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['eligible_event_total'], 1)
        self.repo.match.assert_called_once_with(3895052, CONTEXT)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_invalid_type_injection_unknown_or_repeated_parameters_no_connection(self):
        for query in ('', 'type=pass', 'type=Pressure', 'type=pressure&type=pressure', 'type=pressure&player_id=1',
                      'type=pressure&period=0', 'type=pressure&period=6', 'type=pressure&period=1.0',
                      'type=pressure&team_id=1%20OR%201=1', 'type=pressure&team_id=',
                      'type=pressure&team_id=4294967296', 'type=pressure&team_id=1&team_id=2',
                      'type=pressure&period=1&period=2',
                      'type=pressure&grid=10000', 'type=pressure&limit=1'):
            with self.subTest(query=query):
                self.assertEqual(self.http.get(PREFIX + '?' + query).status_code, 400)
        self.assertEqual(self.http.get(PREFIX.replace('/3895052/', '/bad/') + '?type=pressure').status_code, 400)
        self.opened.assert_not_called()

    def test_missing_match_and_wrong_context_do_not_read_events(self):
        self.repo.match.return_value = None
        self.assertEqual(self.http.get(PREFIX + '?type=pressure').status_code, 404)
        self.repo._query.assert_not_called()
        with self.assertRaises(ApiError):
            FootballService(self.repo).event_heatmap(3895052, CONTEXT, {})
        self.repo._query.assert_not_called()

    def test_post_rejected_and_errors_are_safe(self):
        self.assertEqual(self.http.post(PREFIX + '?type=pressure').status_code, 405)
        self.opened.assert_not_called()
        self.repo._query.side_effect = RuntimeError('password=SECRET SELECT internal')
        with self.assertLogs('football_api', level='ERROR') as logs:
            response = self.http.get(PREFIX + '?type=pressure')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('SECRET', str(logs.output) + response.content.decode())

    def test_response_bound_and_last_cell(self):
        self.repo._query.return_value = [bucket(column=11, row=7, count=2**53 - 1)]
        result = self.http.get(PREFIX + '?type=pressure')
        self.assertEqual(result.status_code, 200)
        self.assertLess(len(result.content), 16 * 1024)
        self.assertEqual(result.json()['cells'][-1]['count'], 2**53 - 1)

    def test_sdk_source_errors_use_readonly_and_return_safe_503(self):
        for error in (ClickHouseError, OSError, TimeoutError):
            with self.subTest(error=error.__name__):
                client = Mock()
                client.query.side_effect = error('password=SECRET SELECT internal')
                self.repo._query.side_effect = FootballRepository(client)._query
                with self.assertLogs('football_api', level='WARNING') as logs:
                    result = self.http.get(PREFIX + '?type=pressure')
                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.json()['error']['code'], 'clickhouse_unavailable')
                self.assertEqual(client.query.call_args.kwargs['settings'], {'readonly': 1})
                self.assertNotIn('SECRET', str(logs.output) + result.content.decode())
                self.assertNotIn('SELECT', str(logs.output) + result.content.decode())


class PressureCoordinatesTests(unittest.TestCase):
    def read(self, rows):
        repo = Mock()
        repo._query.return_value = rows
        return read_pressure_coordinates(repo, context=CONTEXT, match_id=3895052,
                                         filters={'team_id': 904, 'period': 1}), repo

    def test_original_coordinates_exact_grid_and_exclusion_reconciliation(self):
        rows = [{'event_id': str(i), 'x': x, 'y': y, 'exclusion_reason': ''}
                for i, (x, y) in enumerate(((0, 0), (120, 80), (9.99, 10.01), (10, 10)))]
        rows += [{'event_id': reason, 'x': None, 'y': None, 'exclusion_reason': reason}
                 for reason in ('missing_coordinates', 'non_finite_coordinates', 'out_of_bounds_coordinates')]
        data, repo = self.read(rows)
        self.assertEqual((data['total_count'], data['eligible_event_total'], data['excluded']['count']), (7, 4, 3))
        self.assertEqual(data['points'][2], {'event_id': '2', 'x': 9.99, 'y': 10.01})
        expected, _ = HeatmapProjectionTests().read([bucket(0, 0), bucket(11, 7), bucket(0, 1), bucket(1, 1),
            *[bucket(reason=r) for r in data['excluded']['reasons']]], {'team_id': 904, 'period': 1})
        self.assertEqual({k: v for k, v in data.items() if k not in ('points', 'response_limit')}, expected)
        sql, params = repo._query.call_args.args
        self.assertIn('ORDER BY period, event_index, event_id LIMIT 5001', sql)
        self.assertIn("if(exclusion_reason = '', location_x, NULL)", sql)
        for name, kind in (('competition_id', 'UInt32'), ('season_id', 'UInt32'), ('match_id', 'UInt64'),
                           ('type_id', 'UInt16'), ('team_id', 'UInt32'), ('period', 'UInt8')):
            self.assertIn(name + ' = {' + name + ':' + kind + '}', sql)
        self.assertEqual(params, {**CONTEXT, 'match_id': 3895052, 'type_id': 17, 'team_id': 904, 'period': 1})
        self.assertEqual(repo._query.call_count, 1)

    def test_overflow_duplicates_malformed_and_empty(self):
        point = {'event_id': 'a', 'x': 1, 'y': 2, 'exclusion_reason': ''}
        with self.assertRaises(ApiError) as raised:
            self.read([point] * 5001)
        self.assertEqual(raised.exception.status, 422)
        for rows in ([point, point], [{**point, 'x': 121}], [{**point, 'x': float('nan')}],
                     [{**point, 'exclusion_reason': 'unknown'}], [{**point, 'event_id': 'x' * 65}],
                     [{**point, 'x': None}], [{**point, 'x': True}]):
            with self.subTest(rows=rows), self.assertRaises(ServingIntegrityError):
                self.read(rows)
        data, _ = self.read([])
        self.assertEqual(data['points'], [])
        self.assertEqual(data['total_count'], 0)

    def test_maximum_coordinate_response_is_bounded_without_truncation(self):
        import json
        rows = [{'event_id': str(i).zfill(64), 'x': 119.99999999999999, 'y': 79.99999999999999,
                 'exclusion_reason': ''} for i in range(5000)]
        data, _ = self.read(rows)
        self.assertEqual(len(data['points']), 5000)
        self.assertEqual(data['cells'][-1]['count'], 5000)
        self.assertLess(len(json.dumps(data).encode()), 1024 * 1024)

    def test_canonical_http_validation_scope_bound_and_safe_errors(self):
        http = Client(HTTP_HOST='localhost', raise_request_exception=False)
        repo = Mock()
        repo.match.return_value = CONTEXT
        repo._query.return_value = []
        @contextmanager
        def opened(): yield repo
        path = PREFIX + '/coordinates'
        with patch('application.views.open_repository', side_effect=opened) as connect:
            for query in ('', 'type=pass', 'type=pressure&period=0', 'type=pressure&team_id=1%20OR%201=1',
                          'type=pressure&type=pressure', 'type=pressure&limit=2'):
                self.assertEqual(http.get(path + '?' + query).status_code, 400)
            connect.assert_not_called()
            self.assertEqual(http.post(path + '?type=pressure').status_code, 405)
            result = http.get(path + '?type=pressure&team_id=904&period=1')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['points'], [])
            repo.match.assert_called_once_with(3895052, CONTEXT)
            repo.match.return_value = None
            repo._query.reset_mock()
            self.assertEqual(http.get(path + '?type=pressure').status_code, 404)
            repo._query.assert_not_called()
            repo.match.return_value = CONTEXT
            repo._query.side_effect = RuntimeError('SECRET raw SQL')
            with self.assertLogs('football_api', level='ERROR') as logs:
                result = http.get(path + '?type=pressure')
            self.assertEqual(result.status_code, 500)
            self.assertNotIn('SECRET', str(logs.output) + result.content.decode())
