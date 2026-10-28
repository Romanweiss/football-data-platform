import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiFailure, fetchAnalysis, fetchMatches, fetchCompetitions, fetchSeasons, parseAnalysis, parseMatches, fetchPasses } from '../src/api';
import { analysis, match, passMap } from './fixtures';

afterEach(() => vi.unstubAllGlobals());
describe('runtime API boundary', () => {
  it('binds pass filters to one same-origin request, rejects mismatched context and passes cancellation', async () => {
    const mock = vi.fn().mockResolvedValue({ ok: true, json: async () => passMap });
    vi.stubGlobal('fetch', mock);
    const signal = new AbortController().signal;
    expect(await fetchPasses({ competitionId: 11, seasonId: 22 }, 7, { team_id: 10, period: 1 }, signal)).toEqual(passMap);
    expect(mock).toHaveBeenCalledWith('/api/v1/competitions/11/seasons/22/matches/7/passes?team_id=10&period=1', expect.objectContaining({ signal }));
    await expect(fetchPasses({ competitionId: 90, seasonId: 22 }, 7, { team_id: 10, period: 1 }, signal)).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(fetchPasses({ competitionId: 11, seasonId: 22 }, 7, { team_id: 10, player_id: 1, period: 1 }, signal)).rejects.toMatchObject({ code: 'invalid_response' });
    const before = mock.mock.calls.length;
    await expect(fetchPasses({ competitionId: 11, seasonId: 22 }, 7, { period: 6 }, signal)).rejects.toMatchObject({ code: 'invalid_request' });
    expect(mock).toHaveBeenCalledTimes(before);
  });
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
    expect(await fetchAnalysis({ competitionId: 11, seasonId: 22 }, 7, controller.signal)).toEqual(analysis);
    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock).toHaveBeenCalledWith('/api/v1/competitions/11/seasons/22/matches/7/analysis', expect.objectContaining({ signal: controller.signal }));
    mock.mockResolvedValue({ ok: true, json: async () => ({ matches: [match] }) });
    await fetchMatches({ competitionId: 11, seasonId: 22 }, controller.signal);
    expect(mock).toHaveBeenLastCalledWith('/api/v1/competitions/11/seasons/22/matches', expect.anything());
  });
  it('retains status but never forwards raw server error messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: { code: 'clickhouse_unavailable', message: 'sensitive raw details' } }) }));
    await expect(fetchAnalysis({ competitionId: 11, seasonId: 22 }, 7, new AbortController().signal)).rejects.toMatchObject({ status: 503, message: 'Unable to load football data' });
  });
  it('rejects mismatched match identity', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => analysis }));
    await expect(fetchAnalysis({ competitionId: 11, seasonId: 22 }, 8, new AbortController().signal)).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('validates catalogs and rejects cross-context responses without inventing names', async () => {
    const mock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ competitions: [{ competition_id: 90 }] }) });
    vi.stubGlobal('fetch', mock);
    const signal = new AbortController().signal;
    expect(await fetchCompetitions(signal)).toEqual([{ competition_id: 90 }]);
    mock.mockResolvedValue({ ok: true, json: async () => ({ seasons: [{ season_id: 'wrong' }] }) });
    await expect(fetchSeasons(90, signal)).rejects.toMatchObject({ code: 'invalid_response' });
    mock.mockResolvedValue({ ok: true, json: async () => ({ matches: [match] }) });
    await expect(fetchMatches({ competitionId: 90, seasonId: 22 }, signal)).rejects.toMatchObject({ code: 'invalid_response' });
    mock.mockResolvedValue({ ok: true, json: async () => analysis });
    await expect(fetchAnalysis({ competitionId: 90, seasonId: 22 }, 7, signal)).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
