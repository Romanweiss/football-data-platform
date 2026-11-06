import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { ApiFailure } from '../src/api';
import { HISTORICAL_PATH, HISTORICAL_UCL_PATH } from '../src/routes';
import type { FixturePage, HistoricalSource } from '../src/historical/types';
import { historicalFixtureFactory } from './historical-fixtures';

afterEach(() => vi.restoreAllMocks());
function open(path = HISTORICAL_UCL_PATH, source: HistoricalSource = historicalFixtureFactory().source) {
  window.history.replaceState({}, '', path); return render(<App historicalSource={source} />);
}
it('navigates from catalog; loads only one fixtures page and fixed metadata; never claims demo or standings', async () => {
  const f = historicalFixtureFactory();
  const source = Object.fromEntries(Object.entries(f.source).map(([key, fn]) => [key, vi.fn(fn)])) as unknown as HistoricalSource;
  open(HISTORICAL_PATH, source);
  fireEvent.click(await screen.findByRole('link', { name: 'Open 2024/25 results' }));
  await screen.findByTestId('historical-count');
  expect(screen.getAllByTestId('historical-fixture')).toHaveLength(50);
  expect(screen.getByTestId('historical-count').textContent).toContain('189');
  for (const method of ['catalog', 'overview', 'participants', 'coverage', 'fixtures'] as const) expect(source[method]).toHaveBeenCalledTimes(1);
  expect(source.quality).not.toHaveBeenCalled();
  expect(screen.queryByText('DEMO DATA — SYNTHETIC')).toBeNull();
  expect(screen.queryByRole('tab', { name: 'Standings' })).toBeNull();
  expect(screen.queryByTestId('shot-count')).toBeNull();
});
it('pages to unknown final without substituting 0:0, preserves ambiguous components and details', async () => {
  open(HISTORICAL_UCL_PATH + '?offset=150');
  const rows = await screen.findAllByTestId('historical-fixture'); expect(rows).toHaveLength(39);
  const unknown = rows.find(r => r.dataset.quality === 'MISSING_RESULT')!;
  expect(within(unknown).getByText('UNKNOWN — result not provided')).toBeTruthy();
  expect(unknown.querySelectorAll('.current-team-line strong')[0].textContent).toBe('—');
  expect(rows.filter(r => r.dataset.quality === 'AMBIGUOUS_SOURCE_COMPONENTS')).toHaveLength(2);
  expect(screen.getByRole('button', { name: 'Next page' }).hasAttribute('disabled')).toBe(true);
});
it('filters team/stage/round, resets offset/dependent round and supports participant navigation', async () => {
  const f = historicalFixtureFactory(); open(HISTORICAL_UCL_PATH + '?offset=50', f.source);
  await screen.findByTestId('historical-count');
  fireEvent.change(screen.getByLabelText('Round'), { target: { value: f.coverage[0].round_id } });
  await waitFor(() => expect(screen.getAllByTestId('historical-fixture')).toHaveLength(18));
  expect(window.location.search).not.toContain('offset');
  fireEvent.change(screen.getByLabelText('Stage'), { target: { value: f.coverage[13].stage_id } });
  await waitFor(() => expect((screen.getByLabelText('Round') as HTMLSelectElement).value).toBe(''));
  fireEvent.click(screen.getByRole('tab', { name: 'Participants' }));
  expect(within(screen.getByRole('tabpanel')).getAllByRole('button')).toHaveLength(36);
  fireEvent.click(within(screen.getByRole('tabpanel')).getByRole('button', { name: 'Fixture Club 01' }));
  await screen.findByTestId('historical-count');
  expect((screen.getByLabelText('Team') as HTMLSelectElement).value).toBe(f.participants[0].id);
  expect(screen.getAllByTestId('historical-fixture').every(r => r.textContent?.includes('Fixture Club 01'))).toBe(true);
});
it('URL history/popstate and keyboard tabs keep controls, quality pagination and content synchronized', async () => {
  open(); await screen.findByTestId('historical-count');
  const tab = screen.getByRole('tab', { name: 'Fixtures & results' }); tab.focus();
  fireEvent.keyDown(tab, { key: 'End' });
  expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Coverage & limits' }));
  expect(screen.getByText(/Standings unavailable/)).toBeTruthy();
  act(() => { window.history.pushState({}, '', HISTORICAL_UCL_PATH + '?view=quality'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await screen.findByTestId('historical-count');
  expect(screen.getByTestId('historical-count').textContent).toContain('394');
  expect(screen.getByRole('tabpanel').querySelectorAll('.historical-quality li')).toHaveLength(50);
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
  await waitFor(() => expect(screen.getByTestId('historical-count').textContent).toContain('offset 50'));
});
it.each([400, 404, 503])('distinct safe HTTP %i state never renders source native errors or fixtures', async status => {
  open(HISTORICAL_UCL_PATH, { ...historicalFixtureFactory().source, overview: async () => { throw new ApiFailure(status, 'private-native-payload'); } });
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain(status === 503 ? 'Historical dataset is not available in this environment.' : status === 404 ? 'was not found' : 'Invalid historical filters');
  expect(alert.textContent).not.toContain('private-native-payload'); expect(screen.queryByTestId('historical-fixture')).toBeNull();
});
it('explicit loading, empty, malformed URL, unavailable standings and non-English states', async () => {
  const f = historicalFixtureFactory();
  const first = open(HISTORICAL_UCL_PATH + '?offset=1000', f.source);
  expect(screen.getByRole('status').textContent).toContain('Loading');
  await screen.findByText('No records match these filters.');
  first.unmount(); open(HISTORICAL_UCL_PATH + '?team_id=unsafe', f.source);
  await screen.findByText('Reset URL filters');
  expect(screen.getByRole('alert').textContent).toContain('Invalid historical filters');
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'ru' } });
  expect(screen.getByRole('alert').textContent).toContain('Некорректные');
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'es' } });
  expect(screen.getByRole('alert').textContent).toContain('no válidos');
});
it('ignores late responses after filter switch even when transport ignores abort', async () => {
  const f = historicalFixtureFactory(); let finish: (page: FixturePage) => void = () => {}; let aborted: AbortSignal | undefined;
  const source: HistoricalSource = { ...f.source, fixtures: vi.fn((query, signal) => {
    if (!query.team_id) { aborted = signal; return new Promise<FixturePage>(resolve => { finish = resolve; }); }
    return f.source.fixtures(query, signal);
  }) };
  open(HISTORICAL_UCL_PATH, source); await screen.findByTestId('historical-league');
  await waitFor(() => expect(source.fixtures).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText('Team'), { target: { value: f.participants[0].id } });
  await screen.findByTestId('historical-count'); expect(aborted?.aborted).toBe(true);
  await act(async () => finish(await f.source.fixtures({ limit: 50, offset: 0 }, new AbortController().signal)));
  expect(screen.getAllByTestId('historical-fixture').every(r => r.textContent?.includes('Fixture Club 01'))).toBe(true);
});
it('keeps focus in results after pagination and participant navigation remove the triggering button', async () => {
  open(); await screen.findByTestId('historical-count');
  const next = screen.getByRole('button', { name: 'Next page' }); next.focus(); fireEvent.click(next);
  await waitFor(() => expect(screen.getByTestId('historical-count').textContent).toContain('offset 50'));
  expect(document.activeElement).toBe(screen.getByRole('tabpanel'));
  fireEvent.click(screen.getByRole('tab', { name: 'Participants' }));
  const participant = screen.getByRole('button', { name: 'Fixture Club 01' }); participant.focus(); fireEvent.click(participant);
  await screen.findByTestId('historical-count'); expect(document.activeElement).toBe(screen.getByRole('tabpanel'));
});
it('network errors show generic text and retry never substitutes a demo dataset', async () => {
  const f = historicalFixtureFactory(); let fail = true;
  open(HISTORICAL_UCL_PATH, { ...f.source, overview: async signal => {
    if (fail) throw new TypeError('native-network-detail-must-not-render');
    return f.source.overview(signal);
  } });
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('Unable to load or validate'); expect(alert.textContent).not.toContain('native-network');
  expect(screen.queryByTestId('historical-fixture')).toBeNull();
  fail = false; fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByTestId('historical-count'); expect(screen.getAllByTestId('historical-fixture')).toHaveLength(50);
});
it('aborts metadata on cross-route navigation and ignores late completion after leaving history', async () => {
  const f = historicalFixtureFactory(); let finish: (value: Awaited<ReturnType<HistoricalSource['overview']>>) => void = () => {};
  let aborted: AbortSignal | undefined;
  const source: HistoricalSource = { ...f.source, overview: signal => { aborted = signal; return new Promise(resolve => { finish = resolve; }); } };
  open(HISTORICAL_UCL_PATH, source);
  await waitFor(() => expect(aborted).toBeDefined());
  fireEvent.click(screen.getByRole('link', { name: 'Current Competitions' }));
  await screen.findByText('DEMO DATA — SYNTHETIC'); expect(aborted?.aborted).toBe(true);
  await act(async () => finish(f.overview));
  expect(screen.queryByTestId('historical-league')).toBeNull(); expect(screen.getByText('DEMO DATA — SYNTHETIC')).toBeTruthy();
});
