import type { CurrentFixture } from './types';

export interface CurrentFilters { view: 'fixtures' | 'standings'; round: string; team: string; from: string; to: string }
const validDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && Number.isFinite(Date.parse(`${s}T00:00:00Z`))
  && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;
export function readCurrentFilters(search: string, teamIds: readonly string[]): { filters: CurrentFilters; invalid: boolean } {
  const params = new URLSearchParams(search);
  const get = (key: string) => params.get(key) ?? '';
  const raw = { view: get('view'), round: get('round'), team: get('team'), from: get('from'), to: get('to') };
  const filters: CurrentFilters = { view: raw.view === 'standings' ? 'standings' : 'fixtures',
    round: /^[1-8]$/.test(raw.round) ? raw.round : '', team: teamIds.includes(raw.team) ? raw.team : '',
    from: validDate(raw.from) ? raw.from : '', to: validDate(raw.to) ? raw.to : '' };
  return { filters, invalid: (raw.view !== '' && raw.view !== filters.view)
    || (['round', 'team', 'from', 'to'] as const).some(key => raw[key] !== filters[key]) };
}
export function currentFilterSearch(filters: CurrentFilters): string {
  const params = new URLSearchParams();
  if (filters.view !== 'fixtures') params.set('view', filters.view);
  for (const key of ['round', 'team', 'from', 'to'] as const) if (filters[key]) params.set(key, filters[key]);
  return params.size ? `?${params}` : '';
}
export function filterCurrentFixtures(fixtures: readonly CurrentFixture[], filters: CurrentFilters) {
  return fixtures.filter(row => (!filters.round || row.round === Number(filters.round))
    && (!filters.team || row.homeId === filters.team || row.awayId === filters.team)
    && (!filters.from || row.kickoff.slice(0, 10) >= filters.from)
    && (!filters.to || row.kickoff.slice(0, 10) <= filters.to));
}
