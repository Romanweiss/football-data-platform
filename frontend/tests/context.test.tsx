import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App, { readRoute } from '../src/App';
import { fetchAnalysis, fetchMatches, fetchCompetitions, fetchSeasons, fetchLegacyMatch, ApiFailure } from '../src/api';
import { analysis, match } from './fixtures';

vi.mock('../src/api', async importOriginal => ({ ...await importOriginal<typeof import('../src/api')>(),
  fetchAnalysis: vi.fn(), fetchMatches: vi.fn(), fetchCompetitions: vi.fn(), fetchSeasons: vi.fn(), fetchLegacyMatch: vi.fn() }));
beforeEach(() => {
  vi.mocked(fetchCompetitions).mockResolvedValue([{ competition_id: 11 }, { competition_id: 90 }]);
  vi.mocked(fetchSeasons).mockImplementation(async id => id === 11 ? [{ season_id: 22 }, { season_id: 23 }] : [{ season_id: 8 }]);
  vi.mocked(fetchMatches).mockImplementation(async c => [{ ...match, competition_id: c.competitionId, season_id: c.seasonId,
    home_team_name: `Team ${c.competitionId}-${c.seasonId}` }]);
  vi.mocked(fetchAnalysis).mockImplementation(async c => ({ ...analysis, match: { ...match,
    competition_id: c.competitionId, season_id: c.seasonId, home_team_name: `Team ${c.competitionId}-${c.seasonId}` } }));
  vi.mocked(fetchLegacyMatch).mockResolvedValue(match);
});
afterEach(() => vi.resetAllMocks());
it('scopes selection to competition and season, retains language and resets shot state for reused match IDs', async () => {
  window.history.replaceState({}, '', '/');
  render(<App />);
  await waitFor(() => expect(window.location.pathname).toBe('/competitions/11/seasons/22/matches/7'));
  fireEvent.click(await screen.findByTestId('race-point'));
  fireEvent.change(screen.getByRole('combobox', { name: 'Season' }), { target: { value: '23' } });
  await waitFor(() => expect(window.location.pathname).toBe('/competitions/11/seasons/23/matches/7'));
  await screen.findByTestId('race-point');
  expect(screen.getByTestId('shot-details').textContent).toContain('Hover or select');
  expect(fetchMatches).toHaveBeenLastCalledWith({ competitionId: 11, seasonId: 23 }, expect.anything());
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'ru' } });
  fireEvent.change(screen.getByRole('combobox', { name: 'Соревнование' }), { target: { value: '90' } });
  await waitFor(() => expect(window.location.pathname).toBe('/competitions/90/seasons/8/matches/7'));
  await screen.findByTestId('match-header');
  expect(screen.getByTestId('match-header').textContent).toContain('Team 90-8');
  expect(screen.getByRole('heading', { name: 'Анализ матча.' })).toBeTruthy();
  expect(fetchSeasons).toHaveBeenLastCalledWith(90, expect.anything());
  const calls = vi.mocked(fetchMatches).mock.calls.length;
  fireEvent.change(screen.getByRole('combobox', { name: 'Выбрать матч' }), { target: { value: 'Team 90' } });
  expect(screen.getAllByRole('option').some(row => row.textContent?.includes('Team 11'))).toBe(false);
  expect(fetchMatches).toHaveBeenCalledTimes(calls);
});
it('canonical deep links and popstate restore full context, not just match ID', async () => {
  window.history.replaceState({}, '', '/competitions/90/seasons/8/matches/7');
  render(<App />);
  expect((await screen.findByTestId('match-header')).textContent).toContain('Team 90-8');
  act(() => { window.history.replaceState({}, '', '/competitions/11/seasons/23/matches/7'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await waitFor(() => expect(screen.getByTestId('match-header').textContent).toContain('Team 11-23'));
});
it('legacy routes resolve once and replace the URL without an assumed context', async () => {
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  await screen.findByTestId('match-header');
  expect(window.location.pathname).toBe('/competitions/11/seasons/22/matches/7');
  expect(fetchLegacyMatch).toHaveBeenCalledTimes(1);
  expect(fetchAnalysis).toHaveBeenCalledTimes(1);
});
it('ambiguous legacy identity displays a safe localized error', async () => {
  vi.mocked(fetchLegacyMatch).mockRejectedValue(new ApiFailure(409, 'ambiguous_match'));
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  expect((await screen.findByRole('alert')).textContent).toContain('ambiguous');
  expect(fetchAnalysis).not.toHaveBeenCalled();
});
it('does not invent contexts for empty catalogs', async () => {
  vi.mocked(fetchCompetitions).mockResolvedValue([]);
  window.history.replaceState({}, '', '/');
  render(<App />);
  await screen.findByText('No competitions available.');
  expect(fetchSeasons).not.toHaveBeenCalled();
  expect(fetchMatches).not.toHaveBeenCalled();
  expect(window.location.pathname).toBe('/');
});
it('handles an empty season list without inventing a season', async () => {
  vi.mocked(fetchSeasons).mockResolvedValue([]);
  window.history.replaceState({}, '', '/competitions/90');
  render(<App />);
  await screen.findByText('No seasons available.');
  expect(fetchMatches).not.toHaveBeenCalled();
});
it('rejects malformed canonical route IDs', () => {
  expect(readRoute('/competitions/11/seasons/22/matches/7')).toEqual({ kind: 'match', competitionId: 11, seasonId: 22, id: 7 });
  for (const path of ['/competitions/0', '/competitions/11/seasons/no', '/competitions/4294967296', '/competitions/11/seasons/22/matches/0'])
    expect(readRoute(path)).toEqual({ kind: 'missing' });
});
it('aborts pending context requests and ignores late responses from the previous competition', async () => {
  let finish!: (rows: { season_id: number }[]) => void;
  vi.mocked(fetchSeasons).mockImplementation(id => id === 11 ? new Promise(resolve => { finish = resolve; }) : Promise.resolve([{ season_id: 8 }]));
  window.history.replaceState({}, '', '/competitions/11');
  render(<App />);
  await waitFor(() => expect(fetchSeasons).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(fetchSeasons).mock.calls[0][1];
  fireEvent.change(screen.getByRole('combobox', { name: 'Competition' }), { target: { value: '90' } });
  await screen.findByTestId('match-header');
  expect(signal.aborted).toBe(true);
  await act(async () => finish([{ season_id: 22 }]));
  expect(window.location.pathname).toBe('/competitions/90/seasons/8/matches/7');
  expect(screen.getByTestId('match-header').textContent).toContain('Team 90-8');
  expect(fetchMatches).not.toHaveBeenCalledWith({ competitionId: 11, seasonId: 22 }, expect.anything());
});
