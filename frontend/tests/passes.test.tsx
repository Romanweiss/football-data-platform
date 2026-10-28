import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PassMap, PassPitch } from '../src/components/PassMap';
import { fetchPasses, parsePasses, ApiFailure } from '../src/api';
import { I18nProvider } from '../src/i18n';
import { competitionLabel, seasonLabel } from '../src/contextLabels';
import { translate } from '../src/i18n';
import { analysis, passMap } from './fixtures';

vi.mock('../src/api', async original => ({ ...await original<typeof import('../src/api')>(), fetchPasses: vi.fn() }));
afterEach(() => vi.resetAllMocks());

it('preserves full-pitch extremes, Float64 positions, all outcomes and direction', () => {
  const before = JSON.stringify(passMap);
  const { container } = render(<PassPitch data={passMap} />);
  expect(container.querySelector('.pass-pitch')?.getAttribute('viewBox')).toBe('-4 -4 128 88');
  expect(screen.getAllByTestId('pass-event')).toHaveLength(3);
  const [first, second, third] = screen.getAllByTestId('pass-event');
  const line = first.querySelector('.pass-line')!;
  expect(['x1', 'y1', 'x2', 'y2'].map(key => line.getAttribute(key))).toEqual(['0', '80', '120', '0']);
  expect(second.querySelector('.pass-line')?.getAttribute('x1')).toBe('5.123456789');
  expect(first.querySelector('.pass-line')?.hasAttribute('marker-end')).toBe(true);
  expect(second.querySelector('.pass-line')?.getAttribute('stroke-dasharray')).toBe('2 1');
  expect(third.getAttribute('data-status')).toBe('unknown');
  expect(screen.getByTestId('pass-counts').textContent).toContain('Unknown: 1');
  expect(JSON.stringify(passMap)).toBe(before);
});

it('uses one roving tab stop and provides keyboard selection/details/clear', () => {
  render(<PassPitch data={passMap} />);
  const events = screen.getAllByTestId('pass-event');
  expect(events.filter(e => e.tabIndex === 0)).toHaveLength(1);
  fireEvent.focus(events[0]); fireEvent.keyDown(events[0], { key: 'ArrowRight' });
  fireEvent.keyDown(events[1], { key: 'Enter' });
  expect(events[1].getAttribute('aria-pressed')).toBe('true');
  expect(document.getElementById('pass-details-content')?.textContent).toContain('Incomplete');
  fireEvent.keyDown(events[1], { key: 'End' });
  fireEvent.keyDown(events[2], { key: ' ' });
  expect(events[2].getAttribute('aria-pressed')).toBe('true');
  fireEvent.keyDown(events[2], { key: 'Escape' });
  expect(events[2].getAttribute('aria-pressed')).toBe('false');
  expect(screen.getAllByTestId('pass-event').filter(e => e.tabIndex === 0)).toHaveLength(1);
});

it('shows every dense-map pass without sampling and explains excluded rows', () => {
  const passes = Array.from({ length: 1000 }, (_, i) => ({ ...passMap.passes[0], event_id: `p-${i}`, event_index: i }));
  render(<PassPitch data={{ ...passMap, passes, total_count: 1003, returned_count: 1000,
    outcome_counts: { completed: 1003, failed: 0, unknown: 0 },
    excluded: { count: 3, reasons: { missing_coordinates: 1, non_finite_coordinates: 1, out_of_bounds_coordinates: 1 } } }} />);
  expect(screen.getAllByTestId('pass-event')).toHaveLength(1000);
  expect(screen.getByText(/All 1,000 passes are drawn/)).toBeTruthy();
  expect(screen.getByTestId('pass-counts').textContent).toContain('Excluded: 3');
  expect(screen.getByText(/Missing coordinates: 1/)).toBeTruthy();
});

it('loads explicitly, sends scoped filters and resets the player on team change', async () => {
  vi.mocked(fetchPasses).mockResolvedValue(passMap);
  render(<PassMap analysis={analysis} />);
  expect(fetchPasses).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Pass player'), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Load pass map' }));
  await screen.findByTestId('pass-counts');
  expect(fetchPasses).toHaveBeenLastCalledWith({ competitionId: 11, seasonId: 22 }, 7,
    { team_id: 10, player_id: 1, period: 1 }, expect.anything());
  fireEvent.change(screen.getByLabelText('Pass team'), { target: { value: '20' } });
  await waitFor(() => expect(fetchPasses).toHaveBeenLastCalledWith(expect.anything(), 7, { team_id: 20, period: 1 }, expect.anything()));
  expect((screen.getByLabelText('Pass player') as HTMLSelectElement).value).toBe('');
  expect(screen.queryByRole('option', { name: 'Player One' })).toBeNull();
});

it('cancels old filters and never paints a late previous response', async () => {
  let resolve!: (data: typeof passMap) => void;
  vi.mocked(fetchPasses).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue({
    ...passMap, total_count: 0, returned_count: 0, passes: [], outcome_counts: { completed: 0, failed: 0, unknown: 0 } });
  render(<PassMap analysis={analysis} />);
  fireEvent.click(screen.getByText('Load pass map'));
  await waitFor(() => expect(fetchPasses).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(fetchPasses).mock.calls[0][3];
  fireEvent.change(screen.getByLabelText('Pass period'), { target: { value: '2' } });
  await screen.findByText('No passes match these filters.');
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(passMap));
  expect(screen.queryAllByTestId('pass-event')).toHaveLength(0);
});

it('reports bounded failure safely without pretending there are no passes', async () => {
  vi.mocked(fetchPasses).mockRejectedValue(new ApiFailure(422, 'pass_result_too_large'));
  render(<PassMap analysis={analysis} />);
  fireEvent.click(screen.getByText('Load pass map'));
  expect((await screen.findByRole('alert')).textContent).toContain('no partial result');
});

it.each(['en', 'ru', 'es'] as const)('has accessible labels in %s and retains outcome distinctions', language => {
  localStorage.setItem('touchline.language', language);
  render(<I18nProvider><PassMap analysis={analysis} /></I18nProvider>);
  for (const key of ['passTeam', 'passPlayer', 'passPeriod'] as const) expect(screen.getByLabelText(translate(language, key))).toBeTruthy();
  expect(screen.getByText(translate(language, 'passMapNote'))).toBeTruthy();
});

it('uses reviewed context names only and never invents an unknown season', () => {
  const t = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) => translate('en', key, params);
  expect(competitionLabel(9, t)).toBe('Bundesliga');
  expect(competitionLabel(43, t)).toBe('World Cup');
  expect(seasonLabel(9, 281, t)).toBe('2023/24');
  expect(seasonLabel(43, 106, t)).toBe('2022');
  expect(seasonLabel(90, 281, t)).toBe('Season #281');
});

it('validates counts, metadata, finite coordinates, schema and unique pass IDs at the API boundary', () => {
  expect(parsePasses(passMap)).toBe(passMap);
  const invalid = [{ ...passMap, returned_count: 2 }, { ...passMap, total_count: 4 },
    { ...passMap, coordinate_system: { ...passMap.coordinate_system, tracking: true } },
    { ...passMap, passes: [{ ...passMap.passes[0], start_x: NaN }, ...passMap.passes.slice(1)] },
    { ...passMap, passes: [{ ...passMap.passes[0], start_x: -1 }, ...passMap.passes.slice(1)] },
    { ...passMap, passes: [passMap.passes[0], passMap.passes[0], passMap.passes[2]] }];
  for (const value of invalid) expect(() => parsePasses(value)).toThrow(ApiFailure);
});
