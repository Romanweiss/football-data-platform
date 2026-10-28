"""Bounded StatsBomb pass-map projection; no writes or changes to Gold metrics.

StatsBomb Open Data Events v4: successful passes omit pass.outcome. Only an
absent ID AND absent name represent that default. 77/Unknown, unfamiliar IDs
and malformed name-only outcomes are never promoted to successful passes.
"""
import json

from application.errors import ApiError, ServingIntegrityError

MAX_PASSES = 5000
MAX_PASS_RESPONSE_BYTES = 4 * 1024 * 1024
PASS_FIELDS = tuple("event_id event_index team_id team_name player_id player_name recipient_id recipient_name period minute second start_x start_y end_x end_y outcome_id outcome_name".split())
COMPLETION_SQL = """multiIf(
    isNull(outcome_id) AND isNull(outcome_name), 'completed',
    outcome_id IN (9, 74, 75, 76), 'failed', 'unknown')"""
EXCLUSION_SQL = """multiIf(
    isNull(start_x) OR isNull(start_y) OR isNull(end_x) OR isNull(end_y), 'missing_coordinates',
    NOT isFinite(start_x) OR NOT isFinite(start_y) OR NOT isFinite(end_x) OR NOT isFinite(end_y), 'non_finite_coordinates',
    start_x < 0 OR start_x > 120 OR end_x < 0 OR end_x > 120 OR
    start_y < 0 OR start_y > 80 OR end_y < 0 OR end_y > 80, 'out_of_bounds_coordinates', '')"""
REASONS = ('missing_coordinates', 'non_finite_coordinates', 'out_of_bounds_coordinates')
STATUSES = ('completed', 'failed', 'unknown')
COORDINATE_SYSTEM = {
    'name': 'StatsBomb', 'length': 120, 'width': 80, 'origin': 'top-left',
    'x_direction': 'right', 'y_direction': 'down', 'orientation': 'source_preserved',
    'units': 'statsbomb', 'tracking': False,
}


def read_passes(repository, *, context, match_id, filters):
    """Two bounded SELECTs over an immutable match; fail closed if counts drift.

    total_count/outcome_counts cover ALL matching source rows; excluded reasons
    are mutually exclusive. passes contains only drawable rows. Never paginate
    or sample silently; the response bound fails explicitly before the row read.
    """
    predicate = ("competition_id = {competition_id:UInt32} AND season_id = {season_id:UInt32} "
                 "AND match_id = {match_id:UInt64}")
    parameters = {**context, 'match_id': match_id}
    for name, sql_type in (('team_id', 'UInt32'), ('player_id', 'UInt32'), ('period', 'UInt8')):
        if name in filters:
            predicate += f" AND {name} = {{{name}:{sql_type}}}"
            parameters[name] = filters[name]
    columns = ["count() AS total_count"]
    columns += [f"countIf(completion_status = '{value}') AS {value}" for value in STATUSES]
    columns += [f"countIf(exclusion_reason = '{value}') AS {value}" for value in REASONS]
    with_sql = f"WITH {COMPLETION_SQL} AS completion_status, {EXCLUSION_SQL} AS exclusion_reason "
    summary = repository._query(with_sql + 'SELECT ' + ', '.join(columns)
                                + ' FROM football.pass_events WHERE ' + predicate, parameters)
    if len(summary) != 1 or set(summary[0]) != {'total_count', *STATUSES, *REASONS}:
        raise ServingIntegrityError('Invalid pass summary')
    counts = summary[0]
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ServingIntegrityError('Invalid pass summary counts')
    total = counts['total_count']
    excluded = sum(counts[name] for name in REASONS)
    if sum(counts[name] for name in STATUSES) != total or excluded > total:
        raise ServingIntegrityError('Pass summary does not reconcile')
    expected = total - excluded
    if expected > MAX_PASSES:
        raise ApiError('pass_result_too_large', 'Too many passes; select a team, player or period', 422)
    rows = repository._query(
        with_sql + 'SELECT ' + ', '.join(PASS_FIELDS) + ', completion_status'
        + ' FROM football.pass_events WHERE ' + predicate + " AND exclusion_reason = ''"
        + f' ORDER BY event_index, event_id LIMIT {MAX_PASSES + 1}', parameters)
    if (len(rows) != expected or len({row['event_id'] for row in rows}) != len(rows)
            or any(row['completion_status'] not in STATUSES for row in rows)):
        raise ServingIntegrityError('Pass rows differ from summary or identity contract')
    result = {
        **context, 'match_id': match_id, 'filters': {name: filters.get(name) for name in ('team_id', 'player_id', 'period')},
        'coordinate_system': dict(COORDINATE_SYSTEM), 'response_limit': MAX_PASSES,
        'total_count': total, 'returned_count': len(rows),
        'outcome_counts': {name: counts[name] for name in STATUSES},
        'excluded': {'count': excluded, 'reasons': {name: counts[name] for name in REASONS}},
        'passes': rows,
    }
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_PASS_RESPONSE_BYTES:
        raise ApiError('pass_result_too_large', 'Pass response exceeds size bound; narrow the filters', 422)
    return result
