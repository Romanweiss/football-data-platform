import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import * as api from '../src/api';
import { CURRENT_PATH, CURRENT_UCL_PATH } from '../src/routes';
import { syntheticCurrentSource } from '../src/current/source';
import { createSyntheticLeague } from '../src/current/synthetic';
import type { CurrentLeague, CurrentSource } from '../src/current/types';

vi.mock('../src/api', async original => ({ ...await original<typeof import('../src/api')>(),
  fetchCompetitions: vi.fn(), fetchSeasons: vi.fn(), fetchMatches: vi.fn(), fetchAnalysis: vi.fn() }));
afterEach(() => vi.resetAllMocks());
function open(path = CURRENT_UCL_PATH, source: CurrentSource = syntheticCurrentSource) {
  window.history.replaceState({}, '', path);
  return render(<App currentSource={source} />);
}
it('index and league navigation show synthetic provenance without calling the historical API', async () => {
  open(CURRENT_PATH);
  expect(await screen.findByRole('heading', { name: 'Current competitions.' })).toBeTruthy();
  fireEvent.click(await screen.findByRole('link', { name: /Open league overview/ }));
  await screen.findByTestId('current-league');
  expect(window.location.pathname).toBe(CURRENT_UCL_PATH);
  expect(screen.getByText('DEMO DATA — SYNTHETIC')).toBeTruthy();
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(144);
  for (const method of [api.fetchCompetitions, api.fetchSeasons, api.fetchMatches, api.fetchAnalysis]) expect(method).not.toHaveBeenCalled();
  expect(screen.queryByTestId('shot-count')).toBeNull();
  expect(screen.queryByTestId('shootout-panel')).toBeNull();
});
it('filters by round, team and dates and has an explicit empty/date-error state', async () => {
  open(); await screen.findByTestId('current-league');
  fireEvent.change(screen.getByLabelText('Matchday'), { target: { value: '1' } });
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(18);
  fireEvent.change(screen.getByLabelText('Team'), { target: { value: 'demo-team-01' } });
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(1);
  fireEvent.change(screen.getByLabelText('From date (UTC)'), { target: { value: '2027-01-01' } });
  expect(screen.queryAllByTestId('current-fixture')).toHaveLength(0);
  expect(screen.getByText('No demo fixtures match these filters.')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('To date (UTC)'), { target: { value: '2026-01-01' } });
  expect(screen.getByRole('alert').textContent).toContain('end date');
  fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(144);
  expect(window.location.search).toBe('');
});
it('keeps original standings and zones when filtering; tab keyboard and history use URL state', async () => {
  open(CURRENT_UCL_PATH + '?round=1'); await screen.findByTestId('current-league');
  const tab = screen.getByRole('tab', { name: 'Fixtures & results' });
  tab.focus(); fireEvent.keyDown(tab, { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: 'Standings' }).getAttribute('aria-selected')).toBe('true');
  expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Standings' }));
  expect(screen.getAllByTestId('current-standing')).toHaveLength(36);
  const expected = createSyntheticLeague().standings.find(r => r.participantId === 'demo-team-01')!;
  fireEvent.change(screen.getByLabelText('Team'), { target: { value: 'demo-team-01' } });
  const rows = screen.getAllByTestId('current-standing');
  expect(rows).toHaveLength(1);
  expect(within(rows[0]).getAllByRole('cell')[0].textContent).toContain(String(expected.position));
  expect(rows[0].getAttribute('data-zone')).toBe(expected.zone);
  act(() => { window.history.replaceState({}, '', CURRENT_UCL_PATH + '?round=2'); window.dispatchEvent(new PopStateEvent('popstate')); });
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(18);
  expect((screen.getByLabelText('Matchday') as HTMLSelectElement).value).toBe('2');
});
it('deep-link filters and language survive remount and never alter the synthetic source', async () => {
  const source = { ...syntheticCurrentSource, league: vi.fn(syntheticCurrentSource.league) };
  const first = open(CURRENT_UCL_PATH + '?view=standings&team=demo-team-01', source);
  await screen.findByTestId('current-league');
  expect(screen.getAllByTestId('current-standing')).toHaveLength(1);
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'ru' } });
  expect(screen.getByText('ДЕМО-ДАННЫЕ — СИНТЕТИЧЕСКИЕ')).toBeTruthy();
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'es' } });
  expect(screen.getByText('DATOS DEMO — SINTÉTICOS')).toBeTruthy();
  expect(screen.getByRole('tab', { name: 'Clasificación' })).toBeTruthy();
  expect(source.league).toHaveBeenCalledTimes(1);
  first.unmount(); render(<App currentSource={source} />);
  await screen.findByTestId('current-league');
  expect((screen.getByTestId('language-selector') as HTMLSelectElement).value).toBe('es');
  expect(screen.getAllByTestId('current-standing')).toHaveLength(1);
});
it('loading and error/retry are safe; late responses from the previous attempt cannot replace newer data', async () => {
  let finish!: (data: CurrentLeague) => void;
  const pending = new Promise<CurrentLeague>(resolve => { finish = resolve; });
  const source: CurrentSource = { ...syntheticCurrentSource, league: vi.fn()
    .mockImplementationOnce(() => pending).mockResolvedValue(createSyntheticLeague()) };
  open(CURRENT_UCL_PATH, source);
  expect(screen.getByRole('status').textContent).toContain('Loading synthetic');
  const signal = vi.mocked(source.league).mock.calls[0][2];
  fireEvent.click(screen.getByRole('link', { name: /^Current Competitions$/ }));
  fireEvent.click(await screen.findByRole('link', { name: /Open league overview/ }));
  await screen.findByTestId('current-league');
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ ...createSyntheticLeague(), fixtures: [] }));
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(144);
});
it('never exposes raw source errors and supports empty catalog/retry', async () => {
  const source = { ...syntheticCurrentSource, catalog: vi.fn().mockRejectedValueOnce(new Error('sensitive-fixture'))
    .mockResolvedValue([]) };
  open(CURRENT_PATH, source);
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).not.toContain('sensitive-fixture');
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
  await screen.findByText('No demo competitions available.');
});
it('league failure has a localized safe retry instead of presenting invented results', async () => {
  const source = { ...syntheticCurrentSource, league: vi.fn().mockRejectedValueOnce(new Error('hidden-source-detail'))
    .mockResolvedValue(createSyntheticLeague()) };
  open(CURRENT_UCL_PATH, source);
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('Unable to load the demo.');
  expect(alert.textContent).not.toContain('hidden-source-detail');
  expect(screen.queryByTestId('current-league')).toBeNull();
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
  await screen.findByTestId('current-league');
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(144);
});
it('unsupported current routes stay local and invalid filter values are not reflected', async () => {
  const first = open(CURRENT_PATH + '/unsupported');
  expect(screen.getByRole('heading', { name: 'This demo competition is not available.' })).toBeTruthy();
  expect(api.fetchCompetitions).not.toHaveBeenCalled();
  first.unmount();
  open(CURRENT_UCL_PATH + '?round=99&team=unknown');
  await screen.findByTestId('current-league');
  expect(screen.getByText('Some URL filters were invalid and have been ignored.')).toBeTruthy();
  expect(screen.getAllByTestId('current-fixture')).toHaveLength(144);
});
