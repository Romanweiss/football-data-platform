"""Fixed Pressure-event counts over source coordinates; no tracking or smoothing."""
from collections import Counter

from application.errors import ApiError, ServingIntegrityError
from application.passes import COORDINATE_SYSTEM

GRID = {'columns': 12, 'rows': 8, 'cell_width': 10, 'cell_height': 10,
        'boundary_rule': 'left_closed_right_open_outer_inclusive'}
INTENSITY_SCALE = {'kind': 'fixed_absolute_count', 'lower_bounds': [0, 1, 2, 4, 8, 16], 'top_bin': '16+'}
METRIC = {'id': 'pressure_event_count', 'event_type': 'Pressure', 'type_id': 17,
          'definition': 'Count of registered Pressure events with valid coordinates per cell; not player movement or pressing effectiveness.',
          'normalization': 'none', 'smoothing': 'none'}
REASONS = ('missing_coordinates', 'non_finite_coordinates', 'out_of_bounds_coordinates')
EXCLUSION_SQL = """multiIf(
    isNull(location_x) OR isNull(location_y), 'missing_coordinates',
    NOT isFinite(location_x) OR NOT isFinite(location_y), 'non_finite_coordinates',
    location_x < 0 OR location_x > 120 OR location_y < 0 OR location_y > 80, 'out_of_bounds_coordinates', '')"""
# Sanitize excluded coordinates BEFORE casting, even if the engine eagerly
# evaluates an expression. Outer touchlines belong to the final cell, not a 13th/9th cell.
COLUMN_SQL = "least(toUInt8(floor(if(exclusion_reason = '', ifNull(location_x, 0), 0) / 10)), 11)"
ROW_SQL = "least(toUInt8(floor(if(exclusion_reason = '', ifNull(location_y, 0), 0) / 10)), 7)"
MAX_GROUPS = 99  # 96 spatial cells + three mutually exclusive exclusion buckets.
MAX_POINTS = 5000


def read_heatmap(repository, *, context, match_id, filters):
    predicate = ('competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32} '
                 'AND match_id = {match_id:UInt64} AND type_id = {type_id:UInt16}')
    parameters = {**context, 'match_id': match_id, 'type_id': 17}
    for name, sql_type in (('team_id', 'UInt32'), ('period', 'UInt8')):
        if name in filters:
            predicate += f' AND {name} = {{{name}:{sql_type}}}'
            parameters[name] = filters[name]
    # One aggregate statement: totals and cells use the same set of input rows.
    # No event payload collection, interpolation of user input or silent LIMIT truncation.
    sql = (f'WITH {EXCLUSION_SQL} AS exclusion_reason, {COLUMN_SQL} AS column_index, {ROW_SQL} AS row_index '
           'SELECT exclusion_reason, column_index, row_index, count() AS event_count '
           'FROM football.event_core WHERE ' + predicate
           + f' GROUP BY exclusion_reason, column_index, row_index ORDER BY exclusion_reason, row_index, column_index LIMIT {MAX_GROUPS + 1}')
    groups = repository._query(sql, parameters)
    return _format_groups(groups, context=context, match_id=match_id, filters=filters)


def _format_groups(groups, *, context, match_id, filters):
    if len(groups) > MAX_GROUPS:
        raise ServingIntegrityError('Heatmap aggregate exceeds fixed grid bound')
    cells = [{'column': column, 'row': row, 'count': 0} for row in range(8) for column in range(12)]
    reasons = dict.fromkeys(REASONS, 0)
    seen = set()
    for group in groups:
        if set(group) != {'exclusion_reason', 'column_index', 'row_index', 'event_count'}:
            raise ServingIntegrityError('Invalid heatmap aggregate schema')
        reason, column, row, count = (group[k] for k in ('exclusion_reason', 'column_index', 'row_index', 'event_count'))
        if (not isinstance(reason, str) or reason not in ('', *REASONS)
                or any(type(v) is not int for v in (column, row, count))
                or not (0 <= column < 12 and 0 <= row < 8 and 0 < count < 2**53)):
            raise ServingIntegrityError('Invalid heatmap aggregate values')
        key = (reason, column, row)
        if key in seen or (reason and (column != 0 or row != 0)):
            raise ServingIntegrityError('Duplicate or invalid heatmap bucket')
        seen.add(key)
        if reason:
            reasons[reason] += count
        else:
            cells[row * 12 + column]['count'] = count
    eligible = sum(cell['count'] for cell in cells)
    excluded = sum(reasons.values())
    if eligible + excluded >= 2**53:
        raise ServingIntegrityError('Heatmap count exceeds exact JSON integer range')
    return {**context, 'match_id': match_id,
            'filters': {'type': 'pressure', 'team_id': filters.get('team_id'), 'period': filters.get('period')},
            'coordinate_system': dict(COORDINATE_SYSTEM), 'grid': dict(GRID),
            'metric': dict(METRIC), 'intensity_scale': {**INTENSITY_SCALE, 'lower_bounds': list(INTENSITY_SCALE['lower_bounds'])},
            'total_count': eligible + excluded, 'eligible_event_total': eligible,
            'excluded': {'count': excluded, 'reasons': reasons}, 'cells': cells}


def read_pressure_coordinates(repository, *, context, match_id, filters):
    """One bounded SELECT; overflow fails explicitly rather than dropping events."""
    predicate = ('competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32} '
                 'AND match_id = {match_id:UInt64} AND type_id = {type_id:UInt16}')
    parameters = {**context, 'match_id': match_id, 'type_id': 17}
    for name, kind in (('team_id', 'UInt32'), ('period', 'UInt8')):
        if name in filters:
            predicate += f' AND {name} = {{{name}:{kind}}}'
            parameters[name] = filters[name]
    # Exclude before JSON serialization: NaN/Infinity must never enter a response.
    rows = repository._query(f'WITH {EXCLUSION_SQL} AS exclusion_reason SELECT event_id, exclusion_reason, '
                             "if(exclusion_reason = '', location_x, NULL) AS x, "
                             "if(exclusion_reason = '', location_y, NULL) AS y FROM football.event_core WHERE "
                             + predicate + f' ORDER BY period, event_index, event_id LIMIT {MAX_POINTS + 1}', parameters)
    if len(rows) > MAX_POINTS:
        raise ApiError('heatmap_response_too_large', 'Pressure selection exceeds 5000 events; narrow the filters', 422)
    seen, points, counts = set(), [], Counter()
    for row in rows:
        if set(row) != {'event_id', 'x', 'y', 'exclusion_reason'}:
            raise ServingIntegrityError('Invalid Pressure coordinate schema')
        identity, x, y = row['event_id'], row['x'], row['y']
        if not isinstance(identity, str) or not identity or len(identity) > 64 or identity in seen:
            raise ServingIntegrityError('Invalid or duplicate Pressure identity')
        seen.add(identity)
        if any(v is not None and type(v) not in (int, float) for v in (x, y)):
            raise ServingIntegrityError('Invalid Pressure coordinate value')
        reason = row['exclusion_reason']
        if (reason not in ('', *REASONS) or (reason and (x is not None or y is not None))
                or (not reason and (x is None or y is None or not (0 <= x <= 120 and 0 <= y <= 80)))):
            raise ServingIntegrityError('Invalid Pressure exclusion contract')
        column, grid_row = (0, 0) if reason else (min(int(x // 10), 11), min(int(y // 10), 7))
        counts[(reason, column, grid_row)] += 1
        if not reason:
            points.append({'event_id': identity, 'x': x, 'y': y})
    groups = [{'exclusion_reason': reason, 'column_index': column, 'row_index': row, 'event_count': count}
              for (reason, column, row), count in counts.items()]
    return {**_format_groups(groups, context=context, match_id=match_id, filters=filters),
            'response_limit': MAX_POINTS, 'points': points}
