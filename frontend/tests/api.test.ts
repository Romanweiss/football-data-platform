import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiFailure, fetchAnalysis, fetchMatches, parseAnalysis, parseMatches } from '../src/api';
import { analysis, match } from './fixtures';

afterEach(() => vi.unstubAllGlobals());
describe('runtime API boundary', () => {
  it('accepts the exact API shape and preserves nullable fields and numeric precision', () => {
    const data = structuredClone(analysis);
    data.shots[0].player_id = null;
    data.shots[0].player_name = null;
    data.shots[0].start_x = null;
    data.shots[0].statsbomb_xg = 0.123456789;
    expect(parseAnalysis(data)).toBe(data);
    expect(parseMatches({ matches: [match] })).toEqual([match]);
  });
  it('fails closed on wrong JSON types, missing fields and period-5 normal shots', () => {
    expect(() => parseAnalysis({})).toThrow(ApiFailure);
    expect(() => parseMatches({ matches: [{ ...match, match_id: '7' }] })).toThrow(ApiFailure);
    expect(() => parseAnalysis({ ...analysis, shots: [{ ...analysis.shots[0], period: 5 }] })).toThrow(ApiFailure);
    expect(() => parseAnalysis({ ...analysis, shots: [{ ...analysis.shots[0], statsbomb_xg: '0.1' }] })).toThrow(ApiFailure);
    expect(() => parseAnalysis({ ...analysis, teams: [] })).toThrow(ApiFailure);
  });
  it('uses one same-origin composite request and passes cancellation through', async () => {
    const mock = vi.fn().mockResolvedValue({ ok: true, json: async () => analysis });
    vi.stubGlobal('fetch', mock);
    const controller = new AbortController();
    expect(await fetchAnalysis(7, controller.signal)).toEqual(analysis);
    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock).toHaveBeenCalledWith('/api/v1/matches/7/analysis', expect.objectContaining({ signal: controller.signal }));
    mock.mockResolvedValue({ ok: true, json: async () => ({ matches: [match] }) });
    await fetchMatches(controller.signal);
    expect(mock).toHaveBeenLastCalledWith('/api/v1/competitions/43/seasons/106/matches', expect.anything());
  });
  it('retains status but never forwards raw server error messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: { code: 'clickhouse_unavailable', message: 'sensitive raw details' } }) }));
    await expect(fetchAnalysis(7, new AbortController().signal)).rejects.toMatchObject({ status: 503, message: 'Unable to load football data' });
  });
  it('rejects mismatched match identity', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => analysis }));
    await expect(fetchAnalysis(8, new AbortController().signal)).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
