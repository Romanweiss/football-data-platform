import type { PressurePoint } from './types';

// Fixed across matches, teams and periods. Values are events / 100 StatsBomb².
export const DENSITY = { width: 120, height: 80, bandwidth: 6, area: 100, ceiling: 16 } as const;
export function pressureDensity(points: PressurePoint[]): Float64Array {
  const result = new Float64Array(DENSITY.width * DENSITY.height);
  for (const point of points) {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.x > 120 || point.y < 0 || point.y > 80)
      throw new Error('Invalid Pressure coordinates');
    const axis = (length: number, position: number) => {
      const weights = Array.from({ length }, (_, i) => Math.exp(-0.5 * ((i + 0.5 - position) / DENSITY.bandwidth) ** 2));
      const sum = weights.reduce((a, b) => a + b, 0);
      return weights.map(w => w / sum);
    };
    // Discrete boundary correction: every real event contributes exactly one
    // unit of mass on the pitch, including events on touchlines. No pseudo-events.
    const xs = axis(120, point.x), ys = axis(80, point.y);
    for (let y = 0; y < 80; y++) for (let x = 0; x < 120; x++) result[y * 120 + x] += xs[x] * ys[y] * DENSITY.area;
  }
  return result;
}

const stops = [[33, 168, 151], [119, 209, 117], [247, 221, 91], [250, 139, 61], [239, 67, 69]];
export function densityColor(value: number): [number, number, number, number] {
  // Absolute logarithmic transfer, not a maximum computed from this selection.
  const t = Math.min(Math.log1p(Math.max(0, value)) / Math.log1p(DENSITY.ceiling), 1);
  const position = t * (stops.length - 1), index = Math.min(Math.floor(position), stops.length - 2), f = position - index;
  const rgb = stops[index].map((v, i) => Math.round(v + (stops[index + 1][i] - v) * f));
  return [rgb[0], rgb[1], rgb[2], Math.round(255 * Math.min(1, t * 1.8))];
}
