import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MatchSelector } from '../src/components/MatchSelector';
import { ShootoutPanel } from '../src/components/ShootoutPanel';
import { LoadingState, ErrorState } from '../src/components/States';
import { ShotMap } from '../src/components/ShotMap';
import { PlayerTable } from '../src/components/PlayerTable';
import { ApiFailure } from '../src/api';
import { analysis, match, otherAnalysis, otherMatch } from './fixtures';

describe('accessible page components', () => {
  it('selects by ID and displays API match labels', () => {
    const select = vi.fn();
    render(<MatchSelector matches={[match, otherMatch]} selected={7} onSelect={select} />);
    expect(screen.getByText(otherMatch.match_label)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Explore a match'), { target: { value: '8' } });
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
    render(<ShotMap match={match} shots={analysis.shots} />);
    fireEvent.focus(screen.getByTestId('shot-marker'));
    expect(screen.getByText('Player One')).toBeTruthy();
    expect(screen.getByText('0.10 xG')).toBeTruthy();
    expect(screen.queryByText(analysis.shots[0].event_id)).toBeNull();
  });
  it('reports unplottable coordinates instead of silently dropping shots', () => {
    render(<ShotMap match={match} shots={[{ ...analysis.shots[0], start_x: null }]} />);
    expect(screen.getByText(/1 shots not plotted/)).toBeTruthy();
    expect(screen.queryAllByTestId('shot-marker')).toHaveLength(0);
  });
  it('retains zero-activity players and filters locally', () => {
    render(<PlayerTable players={analysis.players} teams={analysis.teams} />);
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
