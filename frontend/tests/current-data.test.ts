import { expect, it } from 'vitest';
import { createSyntheticLeague } from '../src/current/synthetic';
import { syntheticCurrentSource } from '../src/current/source';
import { currentFilterSearch, filterCurrentFixtures, readCurrentFilters } from '../src/current/filters';
import { readRoute, CURRENT_PATH, CURRENT_UCL_PATH } from '../src/routes';
import { currentMessages } from '../src/current/messages';

it('creates 36 invented teams and 144 unique fixture slots deterministically without shared mutation', () => {
  const a = createSyntheticLeague(), b = createSyntheticLeague();
  expect(a).toEqual(b);
  expect(a.participants).toHaveLength(36);
  expect(a.fixtures).toHaveLength(144);
  expect(new Set(a.participants.map(t => t.id)).size).toBe(36);
  expect(new Set(a.fixtures.map(t => t.id)).size).toBe(144);
  expect(a.participants.every(t => t.name.startsWith('Demo · '))).toBe(true);
  a.participants[0].name = 'Modified in test';
  expect(createSyntheticLeague()).toEqual(b);
  expect(createSyntheticLeague(9).fixtures).not.toEqual(b.fixtures);
  expect(() => createSyntheticLeague(NaN)).toThrow();
});
it('has eight unique opponents, four home/four away and one match per team per round', () => {
  const data = createSyntheticLeague();
  for (let round = 1; round <= 8; round++) {
    const rows = data.fixtures.filter(f => f.round === round);
    expect(rows).toHaveLength(18);
    expect(new Set(rows.flatMap(f => [f.homeId, f.awayId])).size).toBe(36);
  }
  for (const t of data.participants) {
    const rows = data.fixtures.filter(f => f.homeId === t.id || f.awayId === t.id);
    expect(rows).toHaveLength(8);
    expect(rows.filter(f => f.homeId === t.id)).toHaveLength(4);
    expect(new Set(rows.map(f => f.homeId === t.id ? f.awayId : f.homeId)).size).toBe(8);
  }
});
it('keeps timed scores null and computes all standing fields independently from finished fixtures', () => {
  const data = createSyntheticLeague();
  expect(data.fixtures.filter(f => f.status === 'FINISHED')).toHaveLength(54);
  expect(data.fixtures.filter(f => f.status === 'TIMED')).toHaveLength(90);
  for (const fixture of data.fixtures) {
    expect(fixture.seasonId).toBe(data.season.id);
    expect(fixture.homeId).not.toBe(fixture.awayId);
    expect(fixture.score === null).toBe(fixture.status === 'TIMED');
  }
  for (const row of data.standings) {
    const games = data.fixtures.filter(f => f.status === 'FINISHED' && (f.homeId === row.participantId || f.awayId === row.participantId));
    const pairs = games.map(f => f.homeId === row.participantId ? [f.score!.home, f.score!.away] : [f.score!.away, f.score!.home]);
    const gf = pairs.reduce((n, p) => n + p[0], 0), ga = pairs.reduce((n, p) => n + p[1], 0);
    expect(row.played).toBe(games.length);
    expect(row.won).toBe(pairs.filter(p => p[0] > p[1]).length);
    expect(row.drawn).toBe(pairs.filter(p => p[0] === p[1]).length);
    expect(row.lost).toBe(pairs.filter(p => p[0] < p[1]).length);
    expect([row.goalsFor, row.goalsAgainst, row.goalDifference, row.points]).toEqual([gf, ga, gf - ga, row.won * 3 + row.drawn]);
  }
  expect(data.standings.map(r => r.position)).toEqual(Array.from({ length: 36 }, (_, i) => i + 1));
  expect(data.standings.filter(r => r.zone === 'top8')).toHaveLength(8);
  expect(data.standings.filter(r => r.zone === 'playoff')).toHaveLength(16);
  expect(data.standings.filter(r => r.zone === 'outside')).toHaveLength(12);
});
it('has explicit synthetic provenance and no event, xG or player capability', () => {
  const data = createSyntheticLeague();
  expect(data.dataKind).toBe('synthetic');
  expect(data.freshness).toEqual({ kind: 'fixed-demo-clock', asOf: '2026-10-15T00:00:00Z', sourceRevision: null });
  expect(data.coverage.completeForCompetition).toBe(false);
  for (const field of ['xg', 'eventCoordinates', 'lineups', 'playerStatistics'] as const) expect(data.capabilities[field]).toBe(false);
});
it('filters inclusive UTC dates, team and round without changing fixture bytes or standings', () => {
  const data = createSyntheticLeague(), before = JSON.stringify(data);
  const filters = readCurrentFilters('?round=1&team=demo-team-01&from=2026-09-08&to=2026-09-08', data.participants.map(t => t.id)).filters;
  const rows = filterCurrentFixtures(data.fixtures, filters);
  expect(rows).toHaveLength(1);
  expect(rows[0].round).toBe(1);
  expect(rows[0].kickoff.slice(0, 10)).toBe('2026-09-08');
  expect(JSON.stringify(data)).toBe(before);
  expect(currentFilterSearch({ ...filters, view: 'standings' })).toContain('view=standings');
});
it('rejects malformed URL filters and impossible dates safely', () => {
  const { filters, invalid } = readCurrentFilters('?round=99&team=anything&from=2026-02-30&to=wrong&view=bad', []);
  expect(invalid).toBe(true);
  expect(filters).toEqual({ view: 'fixtures', round: '', team: '', from: '', to: '' });
});
it('recognizes new routes before historical numeric paths without breaking canonical routes', () => {
  expect(readRoute(CURRENT_PATH)).toEqual({ kind: 'current-index' });
  expect(readRoute(CURRENT_UCL_PATH + '/')).toEqual({ kind: 'current-league' });
  expect(readRoute(CURRENT_PATH + '/wrong')).toEqual({ kind: 'current-missing' });
  expect(readRoute('/competitions/43/seasons/106/matches/3869685')).toEqual({ kind: 'match', competitionId: 43, seasonId: 106, id: 3869685 });
});
it('the local adapter honors abort and rejects unsupported contexts without a network transport', async () => {
  const c = new AbortController();
  expect(await syntheticCurrentSource.catalog(c.signal)).toHaveLength(1);
  expect((await syntheticCurrentSource.league('uefa-champions-league', 2026, c.signal)).fixtures).toHaveLength(144);
  await expect(syntheticCurrentSource.league('other', 2026, c.signal)).rejects.toThrow();
  c.abort();
  await expect(syntheticCurrentSource.catalog(c.signal)).rejects.toThrow();
});
it('all three current-section dictionaries have identical keys and placeholders', () => {
  for (const dictionary of Object.values(currentMessages)) {
    expect(Object.keys(dictionary).sort()).toEqual(Object.keys(currentMessages.en).sort());
    for (const key of Object.keys(currentMessages.en) as (keyof typeof currentMessages.en)[])
      expect(dictionary[key].match(/\{\w+\}/g) ?? []).toEqual(currentMessages.en[key].match(/\{\w+\}/g) ?? []);
  }
});
