import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { filterMatches } from '../src/search';
import { MatchSelector } from '../src/components/MatchSelector';
import { match, otherMatch } from './fixtures';

it('searches partial names, labels, stage and date case-insensitively without mutation', () => {
  const matches = [match, { ...otherMatch, competition_stage_name: 'Semi-finals', home_team_name: 'Argentina' }];
  expect(filterMatches(matches, 'aRG')).toEqual([matches[1]]);
  expect(filterMatches(matches, 'bLu')).toEqual(matches);
  expect(filterMatches(matches, 'final')).toEqual(matches);
  expect(filterMatches(matches, '2022-12-18')).toEqual([match]);
  expect(filterMatches(matches, 'arg 2022-12-19')).toEqual([matches[1]]);
  expect(filterMatches(matches, 'финал', () => 'Финал')).toEqual(matches);
  expect(filterMatches(matches, 'missing')).toEqual([]);
  expect(matches[0]).toBe(match);
});
it('supports arrows, Enter, Escape, outside dismissal and no-results', () => {
  const select = vi.fn();
  render(<MatchSelector matches={[match, otherMatch]} selected={7} onSelect={select} />);
  const input = screen.getByRole('combobox');
  fireEvent.focus(input);
  expect(screen.getAllByRole('option')).toHaveLength(2);
  fireEvent.keyDown(input, { key: 'ArrowUp' });
  expect(screen.getAllByRole('option')[1].getAttribute('aria-selected')).toBe('true');
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(select).toHaveBeenCalledWith(8);
  fireEvent.click(input);
  fireEvent.keyDown(input, { key: 'Escape' });
  expect(input.getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(input);
  fireEvent.pointerDown(document.body);
  expect(input.getAttribute('aria-expanded')).toBe('false');
  fireEvent.change(input, { target: { value: 'nowhere' } });
  expect(screen.getByRole('status').textContent).toBe('No matches found');
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(select).toHaveBeenCalledTimes(1);
});
