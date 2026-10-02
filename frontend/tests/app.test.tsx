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
  fireEvent.change(screen.getByLabelText('Explore a match'), { target: { value: '8' } });
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
  fireEvent.change(screen.getByLabelText('Explore a match'), { target: { value: '8' } });
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
