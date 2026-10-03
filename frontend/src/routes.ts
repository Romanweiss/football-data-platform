import type { Context } from './types';
import { contextPath } from './api';

export type Route = { kind: 'root' } | { kind: 'legacy'; id: number } | { kind: 'missing' }
  | { kind: 'competition'; competitionId: number }
  | ({ kind: 'context' } & Context) | ({ kind: 'match'; id: number } & Context);
export function readRoute(path: string): Route {
  if (path === '/') return { kind: 'root' };
  const legacy = /^\/matches\/([1-9][0-9]*)\/?$/.exec(path);
  if (legacy) return Number.isSafeInteger(Number(legacy[1])) ? { kind: 'legacy', id: Number(legacy[1]) } : { kind: 'missing' };
  const parts = /^\/competitions\/([1-9][0-9]*)(?:\/seasons\/([1-9][0-9]*)(?:\/matches\/([1-9][0-9]*))?)?\/?$/.exec(path);
  if (!parts) return { kind: 'missing' };
  const competitionId = Number(parts[1]), seasonId = parts[2] ? Number(parts[2]) : undefined, id = parts[3] ? Number(parts[3]) : undefined;
  if (![competitionId, seasonId, id].every(value => value === undefined || Number.isSafeInteger(value))
      || competitionId >= 2 ** 32 || (seasonId !== undefined && seasonId >= 2 ** 32)) return { kind: 'missing' };
  if (seasonId === undefined) return { kind: 'competition', competitionId };
  return id === undefined ? { kind: 'context', competitionId, seasonId } : { kind: 'match', competitionId, seasonId, id };
}
export const matchPath = (context: Context, id: number) => `${contextPath(context)}/matches/${id}`;
