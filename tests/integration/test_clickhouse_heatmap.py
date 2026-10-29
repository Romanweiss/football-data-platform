"""SELECT-only SQL fixtures; no tables, real football payloads or cloud access."""
import math
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from application.heatmap import read_heatmap, read_pressure_coordinates
from application.serialization import serialize_row
from src.common.clickhouse import create_clickhouse_client


@unittest.skipUnless(os.environ.get('PLATFORM_CI_EPHEMERAL') == 'true'
                     or os.environ.get('HEATMAP_READONLY_SQL_TESTS') == 'true',
                     'Requires explicit SELECT-only ClickHouse test opt-in')
class HeatmapSqlTests(unittest.TestCase):
    def test_exact_sql_boundaries_exclusions_and_determinism(self):
        points = [(0, 0), (10, 10), (120, 80), (119.999999999, 79.999999999),
                  (9.999999999, 9.999999999), (60, 40), (None, 1), (1, None),
                  (float('nan'), 5), (5, float('inf')), (-0.1, 0), (120.1, 3),
                  (10, 80.1), (float('nan'), None), (float('inf'), -0.1)]
        def literal(value):
            if value is None:
                return 'CAST(NULL AS Nullable(Float64))'
            return "toNullable(toFloat64('" + str(value) + "'))"
        tuples = ','.join('tuple(' + literal(x) + ',' + literal(y) + ',' + str(i) + ')' for i, (x, y) in enumerate(points))
        source = ('(SELECT 9 AS competition_id,281 AS season_id,3895052 AS match_id,17 AS type_id,'
                  '1 AS period,tupleElement(point,3) AS event_index,toString(event_index) AS event_id,'
                  'tupleElement(point,1) AS location_x,tupleElement(point,2) AS location_y '
                  'FROM (SELECT arrayJoin([' + tuples + ']) AS point))')
        client = create_clickhouse_client()
        self.addCleanup(client.close)
        class LiteralRepository:
            def _query(self, sql, parameters):
                # Substitute only a fixed literal-only FROM source, preserving
                # the actual production bin/exclusion/aggregate expressions.
                sql = sql.replace('FROM football.event_core WHERE', 'FROM ' + source + ' WHERE')
                result = client.query(sql, parameters=parameters, settings={'readonly': 1})
                return [serialize_row(dict(zip(result.column_names, row, strict=True))) for row in result.result_rows]
        actual = read_heatmap(LiteralRepository(), context={'competition_id': 9, 'season_id': 281},
                              match_id=3895052, filters={})
        repeated = read_heatmap(LiteralRepository(), context={'competition_id': 9, 'season_id': 281},
                                match_id=3895052, filters={})
        self.assertEqual(actual, repeated)
        reference = [0] * 96
        reasons = dict.fromkeys(('missing_coordinates', 'non_finite_coordinates', 'out_of_bounds_coordinates'), 0)
        for x, y in points:
            if x is None or y is None:
                reasons['missing_coordinates'] += 1
            elif not math.isfinite(x) or not math.isfinite(y):
                reasons['non_finite_coordinates'] += 1
            elif not (0 <= x <= 120 and 0 <= y <= 80):
                reasons['out_of_bounds_coordinates'] += 1
            else:
                reference[min(int(y // 10), 7) * 12 + min(int(x // 10), 11)] += 1
        self.assertEqual([c['count'] for c in actual['cells']], reference)
        self.assertEqual(actual['excluded']['reasons'], reasons)
        self.assertEqual(actual['total_count'], 15)
        self.assertEqual(actual['eligible_event_total'], 6)
        self.assertEqual(actual['excluded']['count'], 9)
        coordinates = read_pressure_coordinates(LiteralRepository(), context={'competition_id': 9, 'season_id': 281},
                                                match_id=3895052, filters={})
        self.assertEqual({k: v for k, v in coordinates.items() if k not in ('points', 'response_limit')}, actual)
        self.assertEqual(len(coordinates['points']), 6)
        self.assertEqual(coordinates['points'][2], {'event_id': '2', 'x': 120.0, 'y': 80.0})


if __name__ == '__main__':
    unittest.main()
