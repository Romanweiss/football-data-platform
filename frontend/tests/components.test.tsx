import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MatchSelector } from '../src/components/MatchSelector';
import { ShootoutPanel } from '../src/components/ShootoutPanel';
import { LoadingState, ErrorState } from '../src/components/States';
import { Analysis } from '../src/App';
import { PlayerTable } from '../src/components/PlayerTable';
import { ApiFailure } from '../src/api';
import { analysis, match, otherAnalysis, otherMatch } from './fixtures';

describe('accessible page components', () => {
  it('selects by ID and displays API match labels', () => {
    const select = vi.fn();
    render(<MatchSelector matches={[match, otherMatch]} selected={7} onSelect={select} />);
    expect(screen.getByText(match.match_label)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: 'Explore a match' }), { target: { value: '2022-12-19' } });
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Explore a match' }), { key: 'ArrowDown' });
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Explore a match' }), { key: 'Enter' });
    expect(select).toHaveBeenCalledWith(8);
  });
  it('omits the entire shootout panel when not applicable', () => {
    const { container } = render(<ShootoutPanel match={otherMatch} shootout={otherAnalysis.shootout} />);
    expect(container.innerHTML).toBe('');
  });
  it('uses authoritative running score and explicit outcomes', () => {
    render(<ShootoutPanel match={match} shootout={analysis.shootout} />);
    expect(screen.getByText('Penalty shootout')).toBeTruthy();
    expect(screen.getByText('1 – 0')).toBeTruthy();
    expect(screen.getByText('● Goal')).toBeTruthy();
  });
  it('supports focus tooltips without exposing UUID as a primary label', () => {
    render(<Analysis data={analysis} />);
    fireEvent.focus(screen.getByTestId('shot-marker'));
    expect(screen.getByTestId('shot-details').textContent).toContain('Player One');
    expect(screen.getByTestId('shot-details').textContent).toContain('0.10');
    expect(screen.queryByText(analysis.shots[0].event_id)).toBeNull();
  });
  it('reports unplottable coordinates instead of silently dropping shots', () => {
    render(<Analysis data={{ ...analysis, shots: [{ ...analysis.shots[0], start_x: null }] }} />);
    expect(screen.getByText(/1 shots not plotted/)).toBeTruthy();
    expect(screen.queryAllByTestId('shot-marker')).toHaveLength(0);
  });
  it('draws a complete midfield circle and real corners without changing shot coordinates', () => {
    const { container } = render(<Analysis data={analysis} />);
    const pitch = container.querySelector('.pitch-svg')!;
    expect(pitch.getAttribute('viewBox')).toBe('-50 0 420 432');
    const circle = pitch.querySelector('.center-circle')!;
    expect(['cx', 'cy', 'r'].map(attr => circle.getAttribute(attr))).toEqual(['60', '40', '10']);
    expect(pitch.querySelector('.halfway-line')?.getAttribute('d')).toBe('M60 0V80');
    expect(pitch.querySelector('.center-mark')?.getAttribute('cx')).toBe('60');
    expect([...pitch.querySelectorAll('.corner-arc')].map(arc => arc.getAttribute('d'))).toEqual([
      'M119 0 A1 1 0 0 0 120 1', 'M120 79 A1 1 0 0 0 119 80',
    ]);
    expect(pitch.querySelector('.penalty-arc')?.getAttribute('d')).toBe('M102 32 A10 10 0 0 0 102 48');
    const marker = screen.getByTestId('shot-marker').querySelector('.event-dot')!;
    expect(marker.getAttribute('cx')).toBe('281');
    expect(marker.getAttribute('cy')).toBe('216');
    expect(pitch.querySelectorAll('[tabindex]')).toHaveLength(analysis.shots.length);
  });
  it('retains zero-activity players and filters locally', () => {
    render(<PlayerTable players={analysis.players} teams={analysis.teams} />);
    expect(screen.queryByText('Unused Player')).toBeNull();
    expect((screen.getByLabelText('Squad coverage') as HTMLSelectElement).value).toBe('active');
    fireEvent.change(screen.getByLabelText('Squad coverage'), { target: { value: 'all' } });
    expect(screen.getByText('Unused Player')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Filter players by team'), { target: { value: '20' } });
    expect(screen.getByText('Unused Player')).toBeTruthy();
    expect(screen.queryByText('Player One')).toBeNull();
  });
  it('renders intentional loading state', () => {
    render(<LoadingState />);
    expect(screen.getByRole('status').textContent).toContain('Loading match analysis');
  });
  it.each([[404, 'Match not found'], [503, 'Data service temporarily unavailable'], [500, 'Unable to load this view']])('renders safe status %i with retry', (status, title) => {
    const retry = vi.fn();
    render(<ErrorState error={new ApiFailure(Number(status))} retry={retry} />);
    expect(screen.getByRole('alert').textContent).toContain(title);
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
