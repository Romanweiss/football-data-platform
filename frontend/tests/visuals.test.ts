import { describe, expect, it } from 'vitest';
import { formatClock, formatCount, formatDate, formatXg, markerRadius, shotToSvg, sortPlayers, stepPath, teamColor } from '../src/visuals';
import { analysis } from './fixtures';

describe('pure presentation geometry', () => {
  it('preserves raw axes, equal scales, half-pitch padding and x=59 coverage', () => {
    expect(shotToSvg(55, 0)).toEqual({ x: 16, y: 16 });
    expect(shotToSvg(120, 80)).toEqual({ x: 341, y: 416 });
    expect(shotToSvg(108, 40)).toEqual({ x: 281, y: 216 });
    expect(shotToSvg(59, 40)).toEqual({ x: 36, y: 216 });
    expect(shotToSvg(60, 1)!.y - shotToSvg(60, 0)!.y).toBe(5);
    expect(shotToSvg(61, 0)!.x - shotToSvg(60, 0)!.x).toBe(5);
  });
  it('never substitutes/clips missing or out-of-viewport coordinates', () => {
    for (const [x, y] of [[null, 40], [90, null], [NaN, 40], [54, 40], [121, 40], [90, -1], [90, 81]]) {
      expect(shotToSvg(x, y)).toBeNull();
    }
  });
  it('bounds marker radius while preserving monotonic xG encoding', () => {
    expect(markerRadius(0)).toBe(3);
    expect(markerRadius(1)).toBe(11);
    expect(markerRadius(-1)).toBe(3);
    expect(markerRadius(9)).toBe(11);
    expect(markerRadius(0.1)).toBeLessThan(markerRadius(0.5));
    expect(markerRadius(NaN)).toBe(3);
  });
  it('renders H/V steps without interpolation, summing, mutation or fake anchors', () => {
    const p = analysis.xg_race[0];
    const points = [{ ...p, event_order: 2, cumulative_xg: 0.3 }, { ...p, event_order: 1, cumulative_xg: 0.1 }];
    expect(stepPath(points, n => n * 10, n => n * 100)).toBe('M10,10 H20V30');
    expect(points[0].event_order).toBe(2);
    expect(stepPath([], n => n, n => n)).toBe('');
  });
});
describe('display only', () => {
  it('formats xG/counts/time/date without modifying numerical input', () => {
    const xg = 2.758305926;
    expect(formatXg(xg)).toBe('2.76');
    expect(xg).toBe(2.758305926);
    expect(formatClock(122, 4)).toBe('122:04');
    expect(formatDate('2022-12-18')).toBe('18 Dec 2022');
    expect(formatCount(3244)).toBe('3,244');
  });
  it('sorts a copy, deterministically retains zero-activity players', () => {
    const players = [...analysis.players].reverse();
    const sorted = sortPlayers(players);
    expect(sorted[0].player_id).toBe(1);
    expect(sorted[1].event_count).toBe(0);
    expect(players[0].player_id).toBe(2);
    const p = analysis.players[0];
    expect(sortPlayers([{ ...p, player_id: 9 }, { ...p, player_id: 8 }]).map(r => r.player_id)).toEqual([8, 9]);
  });
  it('uses home/away colors, independent of country names', () => {
    expect(teamColor(true)).not.toBe(teamColor(false));
    expect(teamColor(true)).toBe('#64d9c0');
  });
});
