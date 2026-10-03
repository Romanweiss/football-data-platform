import type { ApiError, MatchAnalysisResponse, MatchOverview, Metrics, PlayerMatchStats, Shot, Shootout, ShootoutAttempt, TeamMatchStats, XgRacePoint } from './types';
import type { Competition, Season, Context } from './types';

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
