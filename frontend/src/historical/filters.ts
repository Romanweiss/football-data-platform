import type { HistoricalContext, HistoricalQuery } from './types';
import { historicalId } from './source';

export type HistoricalView = 'fixtures' | 'participants' | 'quality' | 'capabilities';
export interface HistoricalSelection extends HistoricalQuery { view: HistoricalView }
export function readHistoricalSelection(search: string, context?: HistoricalContext): HistoricalSelection | null {
  const params = new URLSearchParams(search);
  const allowed = ['view', 'team_id', 'stage_id', 'round_id', 'limit', 'offset'];
  for (const k of params.keys()) if (!allowed.includes(k) || params.getAll(k).length !== 1) return null;
  const requestedView = params.get('view') ?? 'fixtures';
  const view = requestedView === 'standings' ? 'capabilities' : requestedView;
  if (!['fixtures', 'participants', 'quality', 'capabilities'].includes(view)) return null;
  const limit = params.get('limit') ?? '50', offset = params.get('offset') ?? '0';
  if (!['25', '50', '100'].includes(limit) || !/^(0|[1-9][0-9]{0,4})$/.test(offset) || Number(offset) > 10000) return null;
  const selection: HistoricalSelection = { view: view as HistoricalView, limit: Number(limit), offset: Number(offset) };
  for (const key of ['team_id', 'stage_id', 'round_id'] as const) if (params.has(key)) {
    const value = params.get(key);
    if (!historicalId(value, key === 'team_id' ? 'participant' : key.slice(0, -3))) return null;
    selection[key] = value;
  }
  if (context && ((selection.team_id && !context.participants.some(t => t.id === selection.team_id))
    || (selection.stage_id && !context.coverage.some(r => r.stage_id === selection.stage_id))
    || (selection.round_id && !context.coverage.some(r => r.round_id === selection.round_id && (!selection.stage_id || r.stage_id === selection.stage_id))))) return null;
  return selection;
}
export function historicalSearch(s: HistoricalSelection): string {
  const p = new URLSearchParams();
  if (s.view !== 'fixtures') p.set('view', s.view);
  for (const k of ['team_id', 'stage_id', 'round_id'] as const) if (s[k]) p.set(k, s[k]!);
  if (s.limit !== 50) p.set('limit', String(s.limit));
  if (s.offset) p.set('offset', String(s.offset));
  return p.size ? '?' + p.toString() : '';
}
