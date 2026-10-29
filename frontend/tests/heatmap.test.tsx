import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PressureHeatmap, PressurePitch, pressureColor } from '../src/components/PressureHeatmap';
import { ApiFailure, fetchHeatmap, fetchPressureCoordinates, parseHeatmap } from '../src/api';
import { fetchAnalysis, fetchCompetitions, fetchMatches, fetchSeasons } from '../src/api';
import App from '../src/App';
import { I18nProvider, translate } from '../src/i18n';
import { analysis, match, otherAnalysis, otherMatch, pressureMap, pressureCoordinates } from './fixtures';

vi.mock('../src/api', async original => ({ ...await original<typeof import('../src/api')>(), fetchHeatmap: vi.fn(), fetchPressureCoordinates: vi.fn(),
  fetchAnalysis: vi.fn(), fetchCompetitions: vi.fn(), fetchMatches: vi.fn(), fetchSeasons: vi.fn() }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

it('renders all 96 full-pitch cells without clipping, smoothing or result-relative colors', () => {
  const before = JSON.stringify(pressureMap);
  const { container, rerender } = render(<PressurePitch data={pressureMap} />);
  expect(container.querySelector('.pressure-pitch')?.getAttribute('viewBox')).toBe('-4 -4 128 88');
  const cells = screen.getAllByTestId('pressure-cell');
  expect(cells).toHaveLength(96);
  expect(['x', 'y', 'width', 'height'].map(k => cells[95].getAttribute(k))).toEqual(['110', '70', '10', '10']);
  const color = cells[13].getAttribute('fill');
  rerender(<PressurePitch data={{ ...pressureMap, total_count: 303, eligible_event_total: 303,
    cells: pressureMap.cells.map((c, i) => i === 95 ? { ...c, count: 300 } : c) }} />);
  expect(screen.getAllByTestId('pressure-cell')[13].getAttribute('fill')).toBe(color);
  expect(pressureColor(16)).toBe(pressureColor(300));
  expect(new Set([0, 1, 2, 4, 8, 16].map(pressureColor)).size).toBe(6);
  expect(screen.getByLabelText('Pressure events per cell — fixed scale').textContent).toContain('16+');
  expect(JSON.stringify(pressureMap)).toBe(before);
});

it('provides one roving tab stop, spatial keyboard navigation, hover and exact boundary descriptions', () => {
  render(<PressurePitch data={pressureMap} />);
  const cells = screen.getAllByTestId('pressure-cell');
  fireEvent.focus(cells[0]);
  fireEvent.keyDown(cells[0], { key: 'ArrowDown' });
  expect(document.activeElement).toBe(cells[12]);
  fireEvent.keyDown(cells[12], { key: 'ArrowRight' });
  expect(document.activeElement).toBe(cells[13]);
  expect(screen.getByTestId('pressure-details').textContent).toContain('Pressure events: 2');
  fireEvent.keyDown(cells[13], { key: 'End' });
  fireEvent.keyDown(cells[95], { key: ' ' });
  expect(cells[95].getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByTestId('pressure-details').textContent).toContain('X [110, 120]');
  expect(screen.getByTestId('pressure-details').textContent).toContain('Y [70, 80]');
  fireEvent.keyDown(cells[95], { key: 'ArrowDown' });
  expect(document.activeElement).toBe(cells[95]);
  fireEvent.keyDown(cells[95], { key: 'Escape' });
  expect(cells[95].getAttribute('aria-pressed')).toBe('false');
  fireEvent.mouseEnter(cells[0]);
  expect(screen.getByTestId('pressure-details').textContent).toContain('X [0, 10)');
  expect(cells.filter(c => c.tabIndex === 0)).toHaveLength(1);
});

it('loads only on request, uses scoped filters and cancels a late previous response', async () => {
  let resolve!: (data: typeof pressureMap) => void;
  vi.mocked(fetchHeatmap).mockReturnValueOnce(new Promise(done => { resolve = done; }))
    .mockResolvedValue({ ...pressureMap, total_count: 0, eligible_event_total: 0, cells: pressureMap.cells.map(c => ({ ...c, count: 0 })) });
  render(<PressureHeatmap analysis={analysis} />);
  expect(fetchHeatmap).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Grid' }));
  fireEvent.click(screen.getByText('Load pressure heatmap'));
  await screen.findByText('Loading pressure events…');
  expect(fetchHeatmap).toHaveBeenLastCalledWith({ competitionId: 11, seasonId: 22 }, 7, { team_id: 10, period: 1 }, expect.anything());
  const signal = vi.mocked(fetchHeatmap).mock.calls[0][3];
  fireEvent.change(screen.getByLabelText('Pressure team'), { target: { value: '20' } });
  await screen.findByText('No Pressure events match these filters.');
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(pressureMap));
  expect(screen.getByTestId('pressure-counts').textContent).toContain('Mapped: 0');
  fireEvent.change(screen.getByLabelText('Pressure period'), { target: { value: '' } });
  await waitFor(() => expect(fetchHeatmap).toHaveBeenLastCalledWith(expect.anything(), 7, { team_id: 20 }, expect.anything()));
});

it('shows safe errors and supports retry without silently showing empty data', async () => {
  vi.mocked(fetchHeatmap).mockRejectedValueOnce(new ApiFailure(503)).mockResolvedValue(pressureMap);
  render(<PressureHeatmap analysis={analysis} />);
  fireEvent.click(screen.getByRole('button', { name: 'Grid' }));
  fireEvent.click(screen.getByText('Load pressure heatmap'));
  expect((await screen.findByRole('alert')).textContent).toContain('Data service temporarily unavailable');
  expect(screen.queryByText('No Pressure events match these filters.')).toBeNull();
  fireEvent.click(screen.getByText('Try again'));
  await screen.findByTestId('pressure-counts');
});

it('distinguishes all-excluded coordinates from an empty event result', () => {
  render(<PressurePitch data={{ ...pressureMap, total_count: 3, eligible_event_total: 0,
    excluded: { count: 3, reasons: { missing_coordinates: 1, non_finite_coordinates: 1, out_of_bounds_coordinates: 1 } },
    cells: pressureMap.cells.map(c => ({ ...c, count: 0 })) }} />);
  expect(screen.getByText('No Pressure events with usable coordinates; see excluded counts.')).toBeTruthy();
  expect(screen.getByText(/Missing coordinates: 1/).textContent).toContain('Non-finite coordinates: 1');
});

it.each(['en', 'ru', 'es'] as const)('keeps native accessible filters and semantics in %s', lang => {
  localStorage.setItem('touchline.language', lang);
  render(<I18nProvider><PressureHeatmap analysis={analysis} /></I18nProvider>);
  expect(screen.getByLabelText(translate(lang, 'pressureTeam'))).toBeTruthy();
  expect(screen.getByLabelText(translate(lang, 'pressurePeriod'))).toBeTruthy();
  expect(screen.getByText(translate(lang, 'pressureNote'))).toBeTruthy();
});

it('validates fixed grid, intensity, coordinates, complete unique cells and counts', () => {
  expect(parseHeatmap(pressureMap)).toBe(pressureMap);
  const bad = [{ ...pressureMap, total_count: 1 }, { ...pressureMap, cells: pressureMap.cells.slice(1) },
    { ...pressureMap, cells: pressureMap.cells.map((c, i) => i === 13 ? { ...c, column: 0 } : c) },
    { ...pressureMap, cells: pressureMap.cells.map((c, i) => i === 13 ? { ...c, count: NaN } : c) },
    { ...pressureMap, coordinate_system: { ...pressureMap.coordinate_system, tracking: true } },
    { ...pressureMap, intensity_scale: { ...pressureMap.intensity_scale, lower_bounds: [0, 10] } },
    { ...pressureMap, grid: { ...pressureMap.grid, columns: 24 } },
    { ...pressureMap, metric: { ...pressureMap.metric, smoothing: 'gaussian' } },
    { ...pressureMap, filters: { ...pressureMap.filters, type: 'pass' } }];
  for (const data of bad) expect(() => parseHeatmap(data)).toThrow(ApiFailure);
});

it.each(['grid', 'smooth'])('never displays a late previous-match %s heatmap and removes shootout on match navigation', async mode => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  const reader = mode === 'grid' ? fetchHeatmap : fetchPressureCoordinates;
  const fixture = mode === 'grid' ? pressureMap : pressureCoordinates;
  let finishOld!: (data: typeof pressureMap) => void;
  vi.mocked(fetchCompetitions).mockResolvedValue([{ competition_id: 11 }]);
  vi.mocked(fetchSeasons).mockResolvedValue([{ season_id: 22 }]);
  vi.mocked(fetchMatches).mockResolvedValue([match, otherMatch]);
  vi.mocked(fetchAnalysis).mockImplementation(async (_context, id) => id === 7 ? analysis : otherAnalysis);
  const emptyData = { ...pressureCoordinates, match_id: 8, total_count: 0, eligible_event_total: 0, points: [],
    cells: pressureMap.cells.map(cell => ({ ...cell, count: 0 })) };
  vi.mocked(reader).mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; })).mockResolvedValue(emptyData);
  window.history.replaceState({}, '', '/competitions/11/seasons/22/matches/7');
  render(<App />);
  await screen.findByTestId('shootout-panel');
  if (mode === 'grid') fireEvent.click(screen.getByRole('button', { name: 'Grid' }));
  fireEvent.click(screen.getByText('Load pressure heatmap'));
  await waitFor(() => expect(reader).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(reader).mock.calls[0][3];
  const selector = screen.getByRole('combobox', { name: 'Explore a match' });
  fireEvent.focus(selector);
  fireEvent.change(selector, { target: { value: '2022-12-19' } });
  await waitFor(() => expect(document.querySelectorAll('[role="option"][data-match-id="8"]')).toHaveLength(1));
  fireEvent.keyDown(selector, { key: 'Enter' });
  await waitFor(() => expect(window.location.pathname).toBe('/competitions/11/seasons/22/matches/8'));
  await screen.findByTestId('match-header');
  expect(signal.aborted).toBe(true);
  expect(screen.queryByTestId('shootout-panel')).toBeNull();
  expect(screen.queryByTestId('pressure-cell')).toBeNull();
  if (mode === 'grid') fireEvent.click(screen.getByRole('button', { name: 'Grid' }));
  fireEvent.click(screen.getByText('Load pressure heatmap'));
  await screen.findByText('No Pressure events match these filters.');
  await act(async () => finishOld(fixture));
  expect(screen.getByTestId('pressure-counts').textContent).toContain('Mapped: 0');
  expect(screen.queryByTestId('shootout-panel')).toBeNull();
  expect(window.location.pathname).toBe('/competitions/11/seasons/22/matches/8');
});

it('binds the canonical request and rejects wrong context, match and filter responses', async () => {
  const actual = await vi.importActual<typeof import('../src/api')>('../src/api');
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => pressureMap });
  vi.stubGlobal('fetch', fetch);
  const signal = new AbortController().signal;
  const context = { competitionId: 11, seasonId: 22 };
  await actual.fetchHeatmap(context, 7, { team_id: 10, period: 1 }, signal);
  expect(fetch).toHaveBeenCalledWith('/api/v1/competitions/11/seasons/22/matches/7/event-heatmap?type=pressure&team_id=10&period=1',
    { signal, headers: { Accept: 'application/json' } });
  for (const wrong of [{ ...pressureMap, competition_id: 12 }, { ...pressureMap, season_id: 23 },
    { ...pressureMap, match_id: 8 }, { ...pressureMap, filters: { ...pressureMap.filters, team_id: 20 } },
    { ...pressureMap, filters: { ...pressureMap.filters, period: 2 } }]) {
    fetch.mockResolvedValueOnce({ ok: true, json: async () => wrong });
    await expect(actual.fetchHeatmap(context, 7, { team_id: 10, period: 1 }, signal)).rejects.toThrow(ApiFailure);
  }
  fetch.mockClear();
  for (const filters of [{ period: 0 }, { period: 6 }, { period: 1.5 }, { team_id: 0 }, { team_id: 2 ** 32 }])
    await expect(actual.fetchHeatmap(context, 7, filters, signal)).rejects.toThrow(ApiFailure);
  expect(fetch).not.toHaveBeenCalled();
});
