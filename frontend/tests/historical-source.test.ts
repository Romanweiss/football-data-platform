import { afterEach, expect, it, vi } from 'vitest';
import { ApiFailure } from '../src/api';
import { historicalApiSource, historicalDate, historicalQuery, loadHistoricalContext, parseHistoricalOverview, parseHistoricalPage, sameHistoricalContext } from '../src/historical/source';
import { historicalSearch, readHistoricalSelection } from '../src/historical/filters';
import { readRoute, HISTORICAL_UCL_PATH } from '../src/routes';
import { historicalFixtureFactory, mockId } from './historical-fixtures';

afterEach(() => vi.unstubAllGlobals());
const signal = () => new AbortController().signal;
it('artificial contract reconciles 189/36/14/394, unknown and ambiguous without copying source results', async () => {
  const f = historicalFixtureFactory();
  expect(f.fixtures).toHaveLength(189); expect(f.quality).toHaveLength(394); expect(f.participants).toHaveLength(36);
  expect(parseHistoricalOverview(f.overview)).toEqual(f.overview);
  expect(await loadHistoricalContext(f.source, signal())).toMatchObject({ participants: { length: 36 }, coverage: { length: 14 } });
  const ids = new Set<string>();
  for (let offset = 0; offset < 189; offset += 50) {
    const page = f.page('fixtures', { limit: 50, offset }); parseHistoricalPage(page, 'fixtures');
    for (const row of page.fixtures!) ids.add(row.id);
  }
  expect(ids.size).toBe(189); expect(f.fixtures.filter(x => x.result_availability === 'MISSING')).toHaveLength(1);
  expect(f.fixtures.filter(x => x.score_semantics.quality === 'AMBIGUOUS_SOURCE_COMPONENTS')).toHaveLength(2);
});
it('rejects malformed IDs, score shapes, unsafe counts, pagination, duplicate rows, unverified capabilities and context mixing', () => {
  const f = historicalFixtureFactory();
  for (const mutate of [
    (v: any) => { v.fixtures[0].id = 'statsbomb:1'; },
    (v: any) => { v.fixtures[0].source_reported_score.ft.value = [null, 0]; },
    (v: any) => { v.fixtures[0].score_semantics.ft_period_verified = true; },
    (v: any) => { v.fixtures[0].match_date = '2024-02-30'; },
    (v: any) => { v.pagination.total = -1; }, (v: any) => { v.pagination.next_offset = 90; },
    (v: any) => { v.fixtures[1] = v.fixtures[0]; },
    (v: any) => { v.capabilities.standings = 'known'; },
    (v: any) => { v.fixtures[0].provenance = { ...v.fixtures[0].provenance, batch_id: 'e'.repeat(64) }; },
  ]) { const page = structuredClone(f.page('fixtures', { limit: 50, offset: 0 })); mutate(page); expect(() => parseHistoricalPage(page, 'fixtures')).toThrow(); }
  expect(() => parseHistoricalOverview({ ...f.overview, summary: { ...f.overview.summary, unknown_results: 4 } })).toThrow();
  expect(() => sameHistoricalContext(f.envelope, { ...f.envelope, provenance: { ...f.envelope.provenance, batch_id: 'e'.repeat(64) } })).toThrow();
  expect(() => sameHistoricalContext(f.envelope, { ...f.envelope, provenance: Object.fromEntries(Object.entries(f.envelope.provenance).reverse()) as any })).not.toThrow();
});
it('fails closed on metadata fence/count disagreement and incomplete metadata pagination', async () => {
  const f = historicalFixtureFactory();
  await expect(loadHistoricalContext({ ...f.source, coverage: async () => ({ ...await f.source.coverage(signal()), coverage: [] }) }, signal())).rejects.toThrow();
  await expect(loadHistoricalContext({ ...f.source, participants: async () => ({ ...await f.source.participants(signal()), pagination: { limit: 25, offset: 0, returned: 25, total: 36, next_offset: 25 } }) }, signal())).rejects.toThrow();
});
it('same-origin requests use bounded server pages, abort signal, declared filters and no demo fallback', async () => {
  const f = historicalFixtureFactory();
  const fetcher = vi.fn(async (path: string) => new Response(JSON.stringify(f.response(new URL(path, 'http://local')))));
  vi.stubGlobal('fetch', fetcher);
  const s = signal();
  expect((await historicalApiSource.catalog(s))[0].summary.fixture_records).toBe(189);
  await loadHistoricalContext(historicalApiSource, s);
  const q = { limit: 25, offset: 0, team_id: mockId('participant', 1) };
  const result = await historicalApiSource.fixtures(q, s);
  expect(result.fixtures.every(x => [x.home.id, x.away.id].includes(q.team_id))).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(5);
  for (const [path, options] of fetcher.mock.calls as unknown as [string, RequestInit][]) {
    expect(path.startsWith('/api/v1/competitions/historical')).toBe(true); expect(options.signal).toBe(s); expect(options.credentials).toBe('same-origin');
  }
});
it.each([400, 404, 503])('HTTP %i never parses native error bodies or silently supplies fixtures', async status => {
  const body = vi.fn(); vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status, text: body })));
  await expect(historicalApiSource.overview(signal())).rejects.toMatchObject({ status }); expect(body).not.toHaveBeenCalled();
});
it('rejects oversized, invalid JSON and incorrectly echoed filters', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { headers: { 'content-length': '1048577' } })));
  await expect(historicalApiSource.overview(signal())).rejects.toBeInstanceOf(ApiFailure);
  vi.stubGlobal('fetch', vi.fn(async () => new Response('not json')));
  await expect(historicalApiSource.overview(signal())).rejects.toBeInstanceOf(ApiFailure);
  const f = historicalFixtureFactory();
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(f.page('fixtures', { limit: 50, offset: 0 })))));
  await expect(historicalApiSource.fixtures({ limit: 50, offset: 0, team_id: mockId('participant', 1) }, signal())).rejects.toThrow();
});
it('validates URL selection, scope, duplicates and dependent filters; standings links explain unavailability', async () => {
  const f = historicalFixtureFactory(), context = await loadHistoricalContext(f.source, signal());
  expect(readRoute(HISTORICAL_UCL_PATH)).toEqual({ kind: 'historical-league' });
  expect(readRoute('/competitions/historical/uefa-champions-league/2026')).toEqual({ kind: 'historical-missing' });
  const s = { view: 'fixtures' as const, team_id: f.participants[0].id, stage_id: f.coverage[0].stage_id, round_id: f.coverage[0].round_id, limit: 25, offset: 25 };
  expect(readHistoricalSelection(historicalSearch(s), context)).toEqual(s);
  expect(readHistoricalSelection('?view=standings')?.view).toBe('capabilities');
  for (const search of ['?team_id=1', '?offset=-1', '?limit=5000', '?view=shots', '?offset=0&offset=1', '?token=abc', '?team_id=' + mockId('participant', 99), '?stage_id=' + f.coverage[0].stage_id + '&round_id=' + f.coverage[13].round_id]) expect(readHistoricalSelection(search, context)).toBeNull();
  expect(() => historicalQuery({ limit: 101, offset: 0 })).toThrow();
  expect(historicalDate('2024-02-29')).toBe(true); expect(historicalDate('2025-02-29')).toBe(false);
});
it('rejects a streaming response larger than 1 MiB without trusting Content-Length', async () => {
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(1048577)); }, cancel });
  vi.stubGlobal('fetch', vi.fn(async () => new Response(stream)));
  await expect(historicalApiSource.overview(signal())).rejects.toBeInstanceOf(ApiFailure);
  expect(cancel).toHaveBeenCalledOnce();
});
it('rejects fixtures outside echoed filters and inconsistent missing/ambiguous score states', async () => {
  const f = historicalFixtureFactory(), query = { limit: 25, offset: 0, team_id: mockId('participant', 1) };
  const page = f.page('fixtures', { limit: 25, offset: 0 }); page.filters = { team_id: query.team_id };
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(page))));
  await expect(historicalApiSource.fixtures(query, signal())).rejects.toThrow();
  for (const mutate of [
    (v: any) => { v.fixtures[0].result_availability = 'MISSING'; },
    (v: any) => { v.fixtures[0].source_reported_score.et = { state: 'known', value: [1, 1] }; },
    (v: any) => { v.fixtures[0].source_reported_score.ft.value = [null, null]; },
    (v: any) => { v.fixtures[0].away = v.fixtures[0].home; },
  ]) { const value = structuredClone(f.page('fixtures', { limit: 25, offset: 0 })); mutate(value); expect(() => parseHistoricalPage(value, 'fixtures')).toThrow(); }
});
