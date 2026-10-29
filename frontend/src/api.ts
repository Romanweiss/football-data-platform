import type { ApiError, MatchAnalysisResponse, MatchOverview, Metrics, PlayerMatchStats, Shot, Shootout, ShootoutAttempt, TeamMatchStats, XgRacePoint } from './types';
import type { Competition, Season, Context } from './types';
import type { PassEvent, PassFilters, PassMapResponse, PassStatus } from './types';
import type { HeatmapFilters, PressureHeatmapResponse, PressureCoordinatesResponse } from './types';

type Guard<T> = (value: unknown) => value is T;
type Schema<T> = { [K in keyof T]: Guard<T[K]> };
const number: Guard<number> = (v): v is number => typeof v === 'number' && Number.isFinite(v);
const integer: Guard<number> = (v): v is number => number(v) && Number.isSafeInteger(v);
const string: Guard<string> = (v): v is string => typeof v === 'string';
const boolean: Guard<boolean> = (v): v is boolean => typeof v === 'boolean';
const nullable = <T,>(guard: Guard<T>): Guard<T | null> => (v): v is T | null => v === null || guard(v);
const array = <T,>(guard: Guard<T>): Guard<T[]> => (v): v is T[] => Array.isArray(v) && v.every(guard);
function shape<T>(schema: Schema<T>): Guard<T> {
  return (value): value is T => {
    if (value === null || typeof value !== 'object') return false;
    const record = value as Record<string, unknown>;
    return Object.entries(schema as Record<string, Guard<unknown>>).every(([key, guard]) => guard(record[key]));
  };
}
const metrics: Schema<Metrics> = { event_count: integer, pass_attempts: integer, shot_count: integer,
  shot_xg: number, shot_goals: integer, under_pressure_events: integer, counterpress_events: integer };
const team = { team_id: integer, team_name: string, is_home: boolean };
const player = { player_id: nullable(integer), player_name: nullable(string) };
const timing = { event_id: string, event_index: integer, period: integer, minute: integer, second: integer };
const outcome = { outcome_id: integer, outcome_name: nullable(string), is_goal: boolean };
const matchGuard = shape<MatchOverview>({
  competition_id: integer, season_id: integer, match_id: integer, match_label: string, match_date: string,
  kick_off: string, competition_stage_id: integer, competition_stage_name: string,
  home_team_id: integer, home_team_name: string, away_team_id: integer, away_team_name: string,
  home_score: integer, away_score: integer, display_score: string, result_method: string,
  went_to_extra_time: boolean, went_to_penalties: boolean, winner_team_id: nullable(integer), winner_team_name: nullable(string),
});
const teamGuard = shape<TeamMatchStats>({ ...team, ...metrics, opponent_team_id: integer,
  opponent_team_name: string, goals_for: integer, goals_against: integer, goal_difference: integer,
  match_result: string, players_with_events: integer });
const playerGuard = shape<PlayerMatchStats>({ ...team, ...metrics, player_id: integer, player_name: string });
const shotGuard = shape<Shot>({ ...timing, ...player, ...outcome, team_id: integer, team_name: string,
  shot_label: string, statsbomb_xg: number, is_extra_time: boolean,
  start_x: nullable(number), start_y: nullable(number), end_x: nullable(number), end_y: nullable(number), end_z: nullable(number) });
const raceGuard = shape<XgRacePoint>({ ...team, ...timing, event_order: integer, cumulative_xg: number });
const attemptGuard = shape<ShootoutAttempt>({ ...player, ...outcome, team_id: integer, team_name: string,
  shootout_order: integer, team_attempt_number: integer, home_shootout_goals_after: integer, away_shootout_goals_after: integer });
const shootoutGuard = shape<Shootout>({ match_id: integer, went_to_penalties: boolean, attempts: array(attemptGuard) });
const analysisGuard = shape<MatchAnalysisResponse>({ match: matchGuard, teams: array(teamGuard),
  players: array(playerGuard), shots: array(shotGuard), xg_race: array(raceGuard), shootout: shootoutGuard });
const apiErrorGuard = shape<ApiError>({ error: shape({ code: string, message: string }) });

export class ApiFailure extends Error {
  constructor(public readonly status: number, public readonly code = 'unexpected_error') {
    super('Unable to load football data');
  }
}
export function parseMatches(data: unknown): MatchOverview[] {
  if (!shape({ matches: array(matchGuard) })(data)) throw new ApiFailure(500, 'invalid_response');
  return data.matches;
}
export function parseAnalysis(data: unknown): MatchAnalysisResponse {
  if (!analysisGuard(data) || data.teams.length !== 2 || data.match.match_id !== data.shootout.match_id
      || data.shots.some(s => s.period < 1 || s.period > 4)
      || data.xg_race.some(p => p.period < 1 || p.period > 4)) throw new ApiFailure(500, 'invalid_response');
  return data;
}
async function get(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch('/api/v1' + path, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null);
    throw new ApiFailure(response.status, apiErrorGuard(error) ? error.error.code : 'unexpected_error');
  }
  return response.json();
}
const positive: Guard<number> = (v): v is number => integer(v) && v > 0;
const competitionGuard = shape<Competition>({ competition_id: positive });
const seasonGuard = shape<Season>({ season_id: positive });
export function contextPath(context: Context) {
  if (![context.competitionId, context.seasonId].every(v => Number.isSafeInteger(v) && v > 0 && v < 2 ** 32)) throw new ApiFailure(400, 'invalid_request');
  return `/competitions/${context.competitionId}/seasons/${context.seasonId}`;
}
export async function fetchCompetitions(signal: AbortSignal) {
  const data = await get('/competitions', signal);
  if (!shape({ competitions: array(competitionGuard) })(data)) throw new ApiFailure(500, 'invalid_response');
  return data.competitions;
}
export async function fetchSeasons(competitionId: number, signal: AbortSignal) {
  if (!Number.isSafeInteger(competitionId) || competitionId <= 0 || competitionId >= 2 ** 32) throw new ApiFailure(400, 'invalid_request');
  const data = await get(`/competitions/${competitionId}/seasons`, signal);
  if (!shape({ seasons: array(seasonGuard) })(data)) throw new ApiFailure(500, 'invalid_response');
  return data.seasons;
}
export async function fetchMatches(context: Context, signal: AbortSignal) {
  const rows = parseMatches(await get(contextPath(context) + '/matches', signal));
  if (rows.some(row => row.competition_id !== context.competitionId || row.season_id !== context.seasonId)) throw new ApiFailure(500, 'invalid_response');
  return rows;
}
export async function fetchLegacyMatch(matchId: number, signal: AbortSignal) {
  if (!Number.isSafeInteger(matchId) || matchId <= 0) throw new ApiFailure(404);
  const data = await get(`/matches/${matchId}`, signal);
  if (!matchGuard(data) || data.match_id !== matchId) throw new ApiFailure(500, 'invalid_response');
  return data;
}
export async function fetchAnalysis(context: Context, matchId: number, signal: AbortSignal) {
  if (!Number.isSafeInteger(matchId) || matchId <= 0) throw new ApiFailure(404);
  const data = parseAnalysis(await get(`${contextPath(context)}/matches/${matchId}/analysis`, signal));
  if (data.match.match_id !== matchId || data.match.competition_id !== context.competitionId || data.match.season_id !== context.seasonId) throw new ApiFailure(500, 'invalid_response');
  return data;
}

const passStatus: Guard<PassStatus> = (v): v is PassStatus => v === 'completed' || v === 'failed' || v === 'unknown';
const nonnegative: Guard<number> = (v): v is number => integer(v) && v >= 0;
const passGuard = shape<PassEvent>({ ...timing, ...player, team_id: integer, team_name: string,
  recipient_id: nullable(integer), recipient_name: nullable(string), start_x: number, start_y: number,
  end_x: number, end_y: number, outcome_id: nullable(integer), outcome_name: nullable(string), completion_status: passStatus });
const passMapGuard = shape<PassMapResponse>({ competition_id: integer, season_id: integer, match_id: integer,
  filters: shape({ team_id: nullable(integer), player_id: nullable(integer), period: nullable(integer) }),
  coordinate_system: shape({ name: string, length: number, width: number, origin: string, x_direction: string,
    y_direction: string, orientation: string, units: string, tracking: boolean }),
  response_limit: integer, total_count: nonnegative, returned_count: nonnegative,
  outcome_counts: shape({ completed: nonnegative, failed: nonnegative, unknown: nonnegative }),
  excluded: shape({ count: nonnegative, reasons: shape({ missing_coordinates: nonnegative,
    non_finite_coordinates: nonnegative, out_of_bounds_coordinates: nonnegative }) }), passes: array(passGuard) });
export function parsePasses(data: unknown): PassMapResponse {
  if (!passMapGuard(data)) throw new ApiFailure(500, 'invalid_response');
  const c = data.coordinate_system;
  if (c.name !== 'StatsBomb' || c.length !== 120 || c.width !== 80 || c.origin !== 'top-left'
      || c.x_direction !== 'right' || c.y_direction !== 'down' || c.orientation !== 'source_preserved'
      || c.units !== 'statsbomb' || c.tracking || data.response_limit !== 5000
      || data.returned_count !== data.passes.length || data.returned_count > data.response_limit
      || data.total_count !== data.returned_count + data.excluded.count
      || Object.values(data.outcome_counts).reduce((sum, n) => sum + n, 0) !== data.total_count
      || Object.values(data.excluded.reasons).reduce((sum, n) => sum + n, 0) !== data.excluded.count
      || new Set(data.passes.map(p => p.event_id)).size !== data.passes.length
      || data.passes.some(p => p.start_x < 0 || p.start_x > 120 || p.end_x < 0 || p.end_x > 120
        || p.start_y < 0 || p.start_y > 80 || p.end_y < 0 || p.end_y > 80 || p.period < 1 || p.period > 5))
    throw new ApiFailure(500, 'invalid_response');
  return data;
}
export async function fetchPasses(context: Context, matchId: number, filters: PassFilters, signal: AbortSignal) {
  if (!positive(matchId)) throw new ApiFailure(400, 'invalid_request');
  const query = new URLSearchParams();
  for (const key of ['team_id', 'player_id', 'period'] as const) {
    const value = filters[key];
    if (value !== undefined) {
      if (!positive(value) || value >= (key === 'period' ? 6 : 2 ** 32)) throw new ApiFailure(400, 'invalid_request');
      query.set(key, String(value));
    }
  }
  const data = parsePasses(await get(`${contextPath(context)}/matches/${matchId}/passes${query.size ? '?' + query : ''}`, signal));
  if (data.competition_id !== context.competitionId || data.season_id !== context.seasonId || data.match_id !== matchId
      || (['team_id', 'player_id', 'period'] as const).some(key => data.filters[key] !== (filters[key] ?? null))
      || data.passes.some(p => (filters.team_id !== undefined && p.team_id !== filters.team_id)
        || (filters.player_id !== undefined && p.player_id !== filters.player_id)
        || (filters.period !== undefined && p.period !== filters.period))) throw new ApiFailure(500, 'invalid_response');
  return data;
}

const heatmapGuard = shape<PressureHeatmapResponse>({
  competition_id: positive, season_id: positive, match_id: positive,
  filters: shape({ type: string, team_id: nullable(positive), period: nullable(positive) }),
  coordinate_system: shape({ name: string, length: number, width: number, origin: string, x_direction: string,
    y_direction: string, orientation: string, units: string, tracking: boolean }),
  grid: shape({ columns: integer, rows: integer, cell_width: number, cell_height: number, boundary_rule: string }),
  metric: shape({ id: string, event_type: string, type_id: integer, definition: string, normalization: string, smoothing: string }),
  intensity_scale: shape({ kind: string, lower_bounds: array(nonnegative), top_bin: string }),
  total_count: nonnegative, eligible_event_total: nonnegative,
  excluded: shape({ count: nonnegative, reasons: shape({ missing_coordinates: nonnegative,
    non_finite_coordinates: nonnegative, out_of_bounds_coordinates: nonnegative }) }),
  cells: array(shape({ column: nonnegative, row: nonnegative, count: nonnegative })),
});
export function parseHeatmap(data: unknown): PressureHeatmapResponse {
  if (!heatmapGuard(data)) throw new ApiFailure(500, 'invalid_response');
  const c = data.coordinate_system, g = data.grid, m = data.metric, scale = data.intensity_scale;
  if (c.name !== 'StatsBomb' || c.length !== 120 || c.width !== 80 || c.origin !== 'top-left'
      || c.x_direction !== 'right' || c.y_direction !== 'down' || c.orientation !== 'source_preserved'
      || c.units !== 'statsbomb' || c.tracking || data.filters.type !== 'pressure'
      || (data.filters.period !== null && data.filters.period > 5)
      || g.columns !== 12 || g.rows !== 8 || g.cell_width !== 10 || g.cell_height !== 10
      || g.boundary_rule !== 'left_closed_right_open_outer_inclusive'
      || m.id !== 'pressure_event_count' || m.event_type !== 'Pressure' || m.type_id !== 17
      || m.normalization !== 'none' || m.smoothing !== 'none'
      || scale.kind !== 'fixed_absolute_count' || scale.top_bin !== '16+'
      || JSON.stringify(scale.lower_bounds) !== '[0,1,2,4,8,16]'
      || data.cells.length !== 96 || data.cells.some((cell, i) => cell.column !== i % 12 || cell.row !== Math.floor(i / 12))
      || data.cells.reduce((sum, cell) => sum + cell.count, 0) !== data.eligible_event_total
      || data.total_count !== data.eligible_event_total + data.excluded.count
      || Object.values(data.excluded.reasons).reduce((sum, n) => sum + n, 0) !== data.excluded.count)
    throw new ApiFailure(500, 'invalid_response');
  return data;
}
export function parsePressureCoordinates(value: unknown): PressureCoordinatesResponse {
  const data = parseHeatmap(value) as PressureCoordinatesResponse;
  if (data.response_limit !== 5000 || !Array.isArray(data.points) || data.total_count > 5000
      || data.points.length !== data.eligible_event_total
      || !data.points.every(p => shape({ event_id: string, x: number, y: number })(p)
        && p.event_id.length > 0 && p.event_id.length <= 64 && p.x >= 0 && p.x <= 120 && p.y >= 0 && p.y <= 80)
      || new Set(data.points.map(p => p.event_id)).size !== data.points.length) throw new ApiFailure(500, 'invalid_response');
  const bins = Array<number>(96).fill(0);
  for (const p of data.points) bins[Math.min(Math.floor(p.y / 10), 7) * 12 + Math.min(Math.floor(p.x / 10), 11)]++;
  if (bins.some((n, i) => n !== data.cells[i].count)) throw new ApiFailure(500, 'invalid_response');
  return data;
}
export async function fetchPressureCoordinates(context: Context, matchId: number, filters: HeatmapFilters, signal: AbortSignal) {
  return await fetchHeatmap(context, matchId, filters, signal, true) as PressureCoordinatesResponse;
}
export async function fetchHeatmap(context: Context, matchId: number, filters: HeatmapFilters, signal: AbortSignal, coordinates = false) {
  if (!positive(matchId)) throw new ApiFailure(400, 'invalid_request');
  const query = new URLSearchParams({ type: 'pressure' });
  for (const key of ['team_id', 'period'] as const) {
    const value = filters[key];
    if (value !== undefined) {
      if (!positive(value) || value >= (key === 'period' ? 6 : 2 ** 32)) throw new ApiFailure(400, 'invalid_request');
      query.set(key, String(value));
    }
  }
  const data = (coordinates ? parsePressureCoordinates : parseHeatmap)(await get(`${contextPath(context)}/matches/${matchId}/event-heatmap${coordinates ? '/coordinates' : ''}?${query}`, signal));
  if (data.competition_id !== context.competitionId || data.season_id !== context.seasonId || data.match_id !== matchId
      || (['team_id', 'period'] as const).some(key => data.filters[key] !== (filters[key] ?? null)))
    throw new ApiFailure(500, 'invalid_response');
  return data;
}
