import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App, { readRoute } from '../src/App';
import { fetchAnalysis, fetchMatches } from '../src/api';
import { analysis, match, otherAnalysis, otherMatch } from './fixtures';

vi.mock('../src/api', async importOriginal => ({ ...await importOriginal<typeof import('../src/api')>(), fetchAnalysis: vi.fn(), fetchMatches: vi.fn() }));
beforeEach(() => {
  vi.mocked(fetchMatches).mockResolvedValue([match, otherMatch]);
  vi.mocked(fetchAnalysis).mockImplementation(async id => id === 7 ? analysis : otherAnalysis);
});
afterEach(() => vi.resetAllMocks());
it('uses a deterministic root selection rather than a hardcoded final', async () => {
  window.history.replaceState({}, '', '/');
  render(<App />);
  await waitFor(() => expect(window.location.pathname).toBe('/matches/7'));
  await screen.findByTestId('match-header');
  expect(fetchAnalysis).toHaveBeenCalledTimes(1);
});
it('updates URL, supports history, and hides shootout on switching', async () => {
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  await screen.findByTestId('shootout-panel');
  fireEvent.change(screen.getByRole('combobox', { name: 'Explore a match' }), { target: { value: '2022-12-19' } });
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Explore a match' }), { key: 'Enter' });
  await waitFor(() => expect(screen.queryByTestId('shootout-panel')).toBeNull());
  expect(window.location.pathname).toBe('/matches/8');
  await screen.findByTestId('match-header');
  act(() => { window.history.replaceState({}, '', '/matches/7'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await screen.findByTestId('shootout-panel');
});
it('aborts old requests and ignores late responses even when transport ignores abort', async () => {
  let resolveOld!: (value: typeof analysis) => void;
  const old = new Promise<typeof analysis>(resolve => { resolveOld = resolve; });
  vi.mocked(fetchAnalysis).mockImplementation(id => id === 7 ? old : Promise.resolve(otherAnalysis));
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  await screen.findByLabelText('Explore a match');
  const signal = vi.mocked(fetchAnalysis).mock.calls[0][1];
  fireEvent.change(screen.getByRole('combobox', { name: 'Explore a match' }), { target: { value: '2022-12-19' } });
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Explore a match' }), { key: 'Enter' });
  await screen.findByTestId('match-header');
  expect(signal.aborted).toBe(true);
  await act(async () => resolveOld(analysis));
  expect(screen.queryByTestId('shootout-panel')).toBeNull();
  expect(window.location.pathname).toBe('/matches/8');
});
it('resolves deep links and rejects malformed paths', () => {
  expect(readRoute('/matches/3869685')).toEqual({ kind: 'match', id: 3869685 });
  for (const path of ['/wrong', '/matches/-1', '/matches/1x', '/matches/999999999999999999']) {
    expect(readRoute(path)).toEqual({ kind: 'missing' });
  }
});

it('language changes preserve selected shot and route without new requests', async () => {
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  fireEvent.click(await screen.findByTestId('race-point'));
  const requests = vi.mocked(fetchAnalysis).mock.calls.length;
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'ru' } });
  expect(screen.getByRole('heading', { name: 'Анализ матча.' })).toBeTruthy();
  expect(screen.getByTestId('shot-details').textContent).toContain('Выбранный удар');
  expect(screen.getByTestId('shot-details').textContent).toContain('Player One');
  expect(screen.getByTestId('xg-final-10').textContent).toBe('0,10');
  expect(window.location.pathname).toBe('/matches/7');
  expect(fetchAnalysis).toHaveBeenCalledTimes(requests);
  expect(fetchMatches).toHaveBeenCalledTimes(1);
});
it('translates current error without losing it and retry remains functional', async () => {
  vi.mocked(fetchAnalysis).mockRejectedValueOnce(new Error('not displayed'));
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  await screen.findByRole('alert');
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'es' } });
  expect(screen.getByRole('alert').textContent).toContain('No se pudo cargar');
  expect(screen.getByRole('alert').textContent).not.toContain('not displayed');
  expect(fetchAnalysis).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
  await screen.findByTestId('match-header');
  expect(fetchAnalysis).toHaveBeenCalledTimes(2);
});

it('translates pending loading state without restarting its request', async () => {
  let finish!: (value: typeof analysis) => void;
  vi.mocked(fetchAnalysis).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  window.history.replaceState({}, '', '/matches/7');
  render(<App />);
  await screen.findByRole('combobox', { name: 'Explore a match' });
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'ru' } });
  expect(screen.getByRole('status').textContent).toContain('Загружаем анализ матча');
  expect(fetchAnalysis).toHaveBeenCalledTimes(1);
  await act(async () => finish(analysis));
  expect(screen.getByTestId('match-header')).toBeTruthy();
});
