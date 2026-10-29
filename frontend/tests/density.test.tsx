import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DENSITY, densityColor, pressureDensity } from '../src/pressureDensity';
import { parsePressureCoordinates, fetchHeatmap, fetchPressureCoordinates, ApiFailure } from '../src/api';
import { PressureHeatmap } from '../src/components/PressureHeatmap';
import { analysis, pressureCoordinates, pressureMap } from './fixtures';

vi.mock('../src/api', async original => ({ ...await original<typeof import('../src/api')>(),
  fetchHeatmap: vi.fn(), fetchPressureCoordinates: vi.fn() }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); });

it('conserves all event mass including corners without generating or binning coordinates', () => {
  const points = [[0, 0], [120, 80], [60, 40], [9.99, 10.01]].map(([x, y], i) => ({ event_id: String(i), x, y }));
  const before = JSON.stringify(points), values = pressureDensity(points);
  expect(values.length).toBe(9600);
  expect(values.reduce((a, b) => a + b, 0) / DENSITY.area).toBeCloseTo(4, 10);
  expect([...values].every(v => Number.isFinite(v) && v >= 0)).toBe(true);
  expect(JSON.stringify(points)).toBe(before);
  expect(pressureDensity([]).every(v => v === 0)).toBe(true);
  expect(() => pressureDensity([{ event_id: 'bad', x: 121, y: 1 }])).toThrow();
});

it('uses actual sub-cell coordinates, fixed bandwidth and additive absolute density', () => {
  const p = { event_id: 'a', x: 41.2, y: 20.3 }, q = { ...p, x: 49.8, y: 29.9 };
  const one = pressureDensity([p]), two = pressureDensity([p, { ...p, event_id: 'b' }]);
  expect([...one]).not.toEqual([...pressureDensity([q])]); // Same 10 × 10 bin, different density.
  two.forEach((v, i) => expect(v).toBeCloseTo(2 * one[i], 12));
  expect(DENSITY.bandwidth).toBe(6);
  expect(densityColor(0)[3]).toBe(0);
  expect(densityColor(0.1)[3]).toBeGreaterThan(0);
  expect(densityColor(16)).toEqual(densityColor(100));
});

it('rejects dropped, duplicate, misplaced or invalid raw coordinates and preserves grid reconciliation', () => {
  expect(parsePressureCoordinates(pressureCoordinates)).toBe(pressureCoordinates);
  for (const wrong of [
    { ...pressureCoordinates, points: pressureCoordinates.points.slice(1) },
    { ...pressureCoordinates, response_limit: 99 },
    ...[NaN, -1, 121].map(x => ({ ...pressureCoordinates, points: pressureCoordinates.points.map((p, i) => i ? p : { ...p, x }) })),
    { ...pressureCoordinates, points: pressureCoordinates.points.map(p => ({ ...p, event_id: 'same' })) },
    { ...pressureCoordinates, points: pressureCoordinates.points.map(p => ({ ...p, x: 60 })) },
  ]) expect(() => parsePressureCoordinates(wrong)).toThrow(ApiFailure);
});

it('defaults to Smooth, preserves counts in Grid and ignores a late result after mode/filter changes', async () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  let finish!: (data: typeof pressureCoordinates) => void;
  vi.mocked(fetchPressureCoordinates).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValue(pressureCoordinates);
  vi.mocked(fetchHeatmap).mockResolvedValue(pressureMap);
  render(<PressureHeatmap analysis={analysis} />);
  expect(screen.getByRole('button', { name: 'Smooth Heatmap' }).getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(screen.getByText('Load pressure heatmap'));
  await waitFor(() => expect(fetchPressureCoordinates).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(fetchPressureCoordinates).mock.calls[0][3];
  fireEvent.click(screen.getByRole('button', { name: 'Grid' }));
  await screen.findByTestId('pressure-counts');
  expect(signal.aborted).toBe(true);
  await act(async () => finish(pressureCoordinates));
  expect(screen.queryByTestId('pressure-density')).toBeNull();
  expect(screen.getByTestId('pressure-counts').textContent).toContain('Mapped: 19');
  fireEvent.click(screen.getByRole('button', { name: 'Smooth Heatmap' }));
  await screen.findByTestId('pressure-density');
  expect(screen.getAllByTestId('pressure-cell')).toHaveLength(96);
  fireEvent.change(screen.getByLabelText('Pressure period'), { target: { value: '2' } });
  await waitFor(() => expect(fetchPressureCoordinates).toHaveBeenLastCalledWith(expect.anything(), 7,
    { team_id: 10, period: 2 }, expect.anything()));
});

it('uses only the bounded scoped coordinate route and rejects mismatched identities', async () => {
  const actual = await vi.importActual<typeof import('../src/api')>('../src/api');
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => pressureCoordinates });
  vi.stubGlobal('fetch', fetch);
  try {
    const context = { competitionId: 11, seasonId: 22 }, signal = new AbortController().signal;
    await actual.fetchPressureCoordinates(context, 7, { team_id: 10, period: 1 }, signal);
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/competitions/11/seasons/22/matches/7/event-heatmap/coordinates?type=pressure&team_id=10&period=1');
    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ...pressureCoordinates, match_id: 8 }) });
    await expect(actual.fetchPressureCoordinates(context, 7, { team_id: 10, period: 1 }, signal)).rejects.toThrow(ApiFailure);
  } finally { vi.unstubAllGlobals(); }
});
