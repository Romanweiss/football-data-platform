import type { PlayerMatchStats, XgRacePoint } from './types';

export const COLORS = { home: '#64d9c0', away: '#ffb46b' } as const;
export const teamColor = (isHome: boolean) => isHome ? COLORS.home : COLORS.away;
export const formatXg = (value: number, locale = 'en-GB') => new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
export const formatCount = (value: number, locale = 'en-GB') => new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
export const formatClock = (minute: number, second: number) => `${minute}:${String(second).padStart(2, '0')}`;
export const formatDate = (value: string, locale = 'en-GB') => new Intl.DateTimeFormat(locale, {
  day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
}).format(new Date(value + 'T00:00:00Z'));

// Same scale on both axes, no flipping. Extra 55..60 strip retains the x=59 shot.
export const PITCH = { minX: 55, maxX: 120, minY: 0, maxY: 80, scale: 5, pad: 16,
  width: 370, height: 432 } as const;
export function shotToSvg(x: number | null, y: number | null): { x: number; y: number } | null {
  if (x === null || y === null || !Number.isFinite(x) || !Number.isFinite(y)
      || x < PITCH.minX || x > PITCH.maxX || y < 0 || y > 80) return null;
  return { x: PITCH.pad + (x - PITCH.minX) * PITCH.scale, y: PITCH.pad + y * PITCH.scale };
}
export function markerRadius(xg: number): number {
  return 3 + 8 * Math.sqrt(Math.min(1, Math.max(0, Number.isFinite(xg) ? xg : 0)));
}
export function stepPath(points: readonly XgRacePoint[], x: (value: number) => number, y: (value: number) => number): string {
  const sorted = [...points].sort((a, b) => a.event_order - b.event_order);
  return sorted.map((p, i) => i === 0 ? `M${x(p.event_order)},${y(p.cumulative_xg)}`
    : `H${x(p.event_order)}V${y(p.cumulative_xg)}`).join(' ');
}
export function sortPlayers(players: readonly PlayerMatchStats[]): PlayerMatchStats[] {
  return [...players].sort((a, b) => b.shot_xg - a.shot_xg || b.shot_count - a.shot_count
    || b.event_count - a.event_count || a.team_id - b.team_id || a.player_id - b.player_id);
}
