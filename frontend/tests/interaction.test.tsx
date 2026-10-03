import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { Analysis } from '../src/App';
import { analysis } from './fixtures';
import { raceStateForShot } from '../src/shotInteraction';

it('joins shooting-team cumulative state, never the opponent plateau', () => {
  expect(raceStateForShot(analysis.shots[0], [...analysis.xg_race].reverse())?.cumulative_xg).toBe(0.1);
  render(<Analysis data={analysis} />);
  expect(screen.getAllByTestId('race-point')).toHaveLength(1);
});
it('draws only real shot dots and hit targets while preserving all cumulative path states', () => {
  const awayShot = { ...analysis.shots[0], event_id: 'away-shot', team_id: 20, team_name: 'Blue FC', statsbomb_xg: 0.2 };
  const points = [...analysis.xg_race,
    { ...analysis.xg_race[0], event_id: awayShot.event_id, event_order: 2 },
    { ...analysis.xg_race[1], event_id: awayShot.event_id, event_order: 2, cumulative_xg: 0.2 }];
  const data = { ...analysis, shots: [...analysis.shots, awayShot], xg_race: points };
  const snapshot = JSON.stringify(data);
  const { container } = render(<Analysis data={data} />);
  const race = container.querySelector('.race-svg')!;
  expect(race.querySelectorAll('circle:not(.hit-target):not(.interaction-ring)')).toHaveLength(2);
  expect(race.querySelectorAll('.hit-target')).toHaveLength(2);
  expect(race.querySelectorAll('[tabindex="0"]')).toHaveLength(2);
  expect(race.querySelectorAll('[role="button"]')).toHaveLength(2);
  const [home, away] = screen.getAllByTestId('race-point');
  expect(home.getAttribute('data-event-id')).toBe(analysis.shots[0].event_id);
  expect(home.getAttribute('aria-label')).toContain('Red FC');
  expect(away.getAttribute('data-event-id')).toBe(awayShot.event_id);
  expect(away.getAttribute('aria-label')).toContain('Blue FC');
  expect([...race.querySelectorAll('path')].map(path => path.getAttribute('d'))).toEqual([
    'M48,238 H592V238', 'M48,260 H592V216',
  ]);
  expect(JSON.stringify(data)).toBe(snapshot);
});
it('synchronizes hover, persistent keyboard/click selection and clear in both directions', () => {
  const snapshot = JSON.stringify(analysis);
  render(<Analysis data={analysis} />);
  const race = screen.getByTestId('race-point'), pitch = screen.getByTestId('shot-marker');
  fireEvent.mouseEnter(race);
  expect(pitch.getAttribute('data-state')).toBe('hovered');
  const details = screen.getByTestId('shot-details');
  for (const text of ['Player One', 'Red FC', '4:04', '0.10', 'Goal', 'Cumulative xG']) expect(details.textContent).toContain(text);
  expect(details.textContent).not.toContain(analysis.shots[0].event_id);
  fireEvent.mouseLeave(race);
  expect(details.textContent).toContain('Hover or select');
  fireEvent.focus(race);
  fireEvent.keyDown(race, { key: 'Enter' });
  fireEvent.blur(race);
  expect(pitch.getAttribute('data-state')).toBe('selected');
  expect(race.getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(within(details).getByRole('button'));
  expect(pitch.getAttribute('data-state')).toBe('normal');
  fireEvent.mouseEnter(pitch);
  expect(race.getAttribute('data-state')).toBe('hovered');
  fireEvent.click(pitch);
  fireEvent.mouseLeave(pitch);
  expect(race.getAttribute('data-state')).toBe('selected');
  fireEvent.keyDown(pitch, { key: 'Escape' });
  expect(race.getAttribute('data-state')).toBe('normal');
  expect(details.textContent).toContain('Hover or select');
  expect(JSON.stringify(analysis)).toBe(snapshot);
});
it('temporary hover does not discard a different persistent selection', () => {
  const second = { ...analysis.shots[0], event_id: 'second', player_name: 'Second Player', period: 3, is_extra_time: true };
  render(<Analysis data={{ ...analysis, shots: [...analysis.shots, second] }} />);
  const [first, next] = screen.getAllByTestId('shot-marker');
  fireEvent.click(first);
  fireEvent.mouseEnter(next);
  expect(screen.getByTestId('shot-details').textContent).toContain('Second Player');
  expect(screen.getByTestId('shot-details').textContent).toContain('Extra time');
  fireEvent.mouseLeave(next);
  expect(screen.getByTestId('shot-details').textContent).toContain('Player One');
});
it('player search and activity filter keep original full-squad data intact', () => {
  render(<Analysis data={analysis} />);
  expect((screen.getByLabelText('Squad coverage') as HTMLSelectElement).value).toBe('active');
  expect(screen.queryByText('Unused Player')).toBeNull();
  fireEvent.change(screen.getByLabelText('Squad coverage'), { target: { value: 'all' } });
  expect(screen.getByText('Unused Player')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search players'), { target: { value: 'unused' } });
  expect(screen.getByText('Unused Player')).toBeTruthy();
  expect(analysis.players).toHaveLength(2);
});
