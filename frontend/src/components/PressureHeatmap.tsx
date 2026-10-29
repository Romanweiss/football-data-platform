import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchHeatmap, fetchPressureCoordinates } from '../api';
import type { MatchAnalysisResponse, PressureHeatmapResponse, PressureCoordinatesResponse } from '../types';
import { densityColor, pressureDensity } from '../pressureDensity';
import { useI18n } from '../i18n';
import { useResource } from '../useResource';
import { ErrorState } from './States';

export const PRESSURE_COLORS = ['#18312e', '#30534b', '#47796a', '#79ac8c', '#b9d49e', '#f2df9d'];
export function pressureColor(count: number) {
  return PRESSURE_COLORS[count >= 16 ? 5 : count >= 8 ? 4 : count >= 4 ? 3 : count >= 2 ? 2 : count >= 1 ? 1 : 0];
}

export function PressureHeatmap({ analysis }: { analysis: MatchAnalysisResponse }) {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(false);
  const [mode, setMode] = useState<'smooth' | 'grid'>('smooth');
  const [team, setTeam] = useState(String(analysis.match.home_team_id));
  const [period, setPeriod] = useState('1');
  const context = { competitionId: analysis.match.competition_id, seasonId: analysis.match.season_id };
  const filters = { ...(team ? { team_id: Number(team) } : {}), ...(period ? { period: Number(period) } : {}) };
  const identity = `${context.competitionId}/${context.seasonId}/${analysis.match.match_id}/${team}/${period}/${mode}`;
  const resource = useResource(enabled ? identity : null, signal =>
    (mode === 'smooth' ? fetchPressureCoordinates : fetchHeatmap)(context, analysis.match.match_id, filters, signal));
  return <section className="panel pressure-panel" aria-labelledby="pressure-title" data-testid="pressure-heatmap">
    <div className="panel-heading"><h2 id="pressure-title">{t('pressureTitle')}</h2></div>
    <p className="chart-note">{t('pressureNote')}</p>
    <div className="pressure-filters">
      <div className="pressure-modes" role="group" aria-label={t('pressureMode')}>
        {(['smooth', 'grid'] as const).map(value => <button key={value} aria-pressed={mode === value}
          onClick={() => setMode(value)}>{t(value === 'smooth' ? 'pressureSmooth' : 'pressureGrid')}</button>)}
      </div>
      <label>{t('pressureTeam')}<select value={team} onChange={event => setTeam(event.target.value)}>
        <option value="">{t('pressureAllTeams')}</option>
        {analysis.teams.map(row => <option key={row.team_id} value={row.team_id}>{row.team_name}</option>)}
      </select></label>
      <label>{t('pressurePeriod')}<select value={period} onChange={event => setPeriod(event.target.value)}>
        <option value="">{t('allPeriods')}</option>
        {[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{t('passPeriodOption', { period: value })}</option>)}
      </select></label>
    </div>
    {!enabled ? <button onClick={() => setEnabled(true)}>{t('loadPressure')}</button>
      : resource.state.status === 'loading' ? <p role="status">{t('pressureLoading')}</p>
      : resource.state.status === 'error' ? <ErrorState error={resource.state.error} retry={resource.retry} />
      : <PressurePitch key={identity} data={resource.state.data} smooth={mode === 'smooth'} />}
  </section>;
}

function DensityImage({ data }: { data: PressureCoordinatesResponse }) {
  const density = useMemo(() => pressureDensity(data.points), [data.points]);
  const [url, setUrl] = useState('');
  useEffect(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 120; canvas.height = 80;
    const context = canvas.getContext('2d');
    if (!context) return;
    const pixels = context.createImageData(120, 80);
    density.forEach((value, i) => pixels.data.set(densityColor(value), i * 4));
    context.putImageData(pixels, 0, 0); setUrl(canvas.toDataURL());
  }, [density]);
  return <image data-testid="pressure-density" x="0" y="0" width="120" height="80" href={url || undefined} aria-hidden="true" />;
}

export function PressurePitch({ data, smooth = false }: { data: PressureHeatmapResponse; smooth?: boolean }) {
  const { t, count } = useI18n();
  const [cursor, setCursor] = useState(0);
  const [hovered, setHovered] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const nodes = useRef<(SVGRectElement | null)[]>([]);
  const active = data.cells[hovered ?? cursor];
  const range = (start: number, end: number, outer: number) => `[${start}, ${end}${end === outer ? ']' : ')'}`;
  const description = (index: number) => {
    const cell = data.cells[index];
    return t('pressureCell', { x: range(cell.column * 10, (cell.column + 1) * 10, 120),
      y: range(cell.row * 10, (cell.row + 1) * 10, 80), count: count(cell.count) });
  };
  function keyDown(event: React.KeyboardEvent, index: number) {
    const column = index % 12;
    let next = index;
    if (event.key === 'ArrowRight') next += column < 11 ? 1 : 0;
    else if (event.key === 'ArrowLeft') next -= column > 0 ? 1 : 0;
    else if (event.key === 'ArrowDown') next = index < 84 ? index + 12 : index;
    else if (event.key === 'ArrowUp') next = index >= 12 ? index - 12 : index;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = 95;
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(index); return; }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setSelected(null); return; }
    else return;
    event.preventDefault(); setCursor(next); nodes.current[next]?.focus();
  }
  return <>
    <div className="pressure-counts" role="status" data-testid="pressure-counts">
      <strong>{t('pressureTotal', { count: count(data.total_count) })}</strong>
      <span>{t('pressureEligible', { count: count(data.eligible_event_total) })}</span>
      <span>{t('excludedPasses', { count: count(data.excluded.count) })}</span>
    </div>
    {data.excluded.count > 0 && <p className="chart-note">{t('missingCoordinates')}: {count(data.excluded.reasons.missing_coordinates)} · {t('nonFiniteCoordinates')}: {count(data.excluded.reasons.non_finite_coordinates)} · {t('outOfBoundsCoordinates')}: {count(data.excluded.reasons.out_of_bounds_coordinates)}</p>}
    {data.eligible_event_total === 0 && <p className="chart-note">{t(data.total_count === 0 ? 'pressureEmpty' : 'pressureNoCoordinates')}</p>}
    <details className="pressure-method"><summary>{t('pressureMethod')}</summary>
      <p className="chart-note" id="pressure-scale">{t(smooth ? 'pressureSmoothMethod' : 'pressureScale')}</p>
      <p className="chart-note">{t('pressureKeyboard')}</p>
    </details>
    {smooth ? <div className="pressure-density-legend" aria-label={t('pressureDensityLegend')}>
      <span>{t('pressureDensityLegend')}</span><div className="pressure-gradient" style={{ background: `linear-gradient(to right, ${Array.from({ length: 21 }, (_, i) => {
        const [r, g, b, a] = densityColor(Math.expm1(i / 20 * Math.log1p(16)));
        return `rgba(${r},${g},${b},${a / 255}) ${i * 5}%`;
      }).join(',')})` }} />
      <div className="pressure-ticks">{[0, 1, 4, 16].map(n => <span key={n}
        style={{ left: `${Math.log1p(n) / Math.log1p(16) * 100}%` }}>{n === 16 ? '16+' : n}</span>)}</div>
    </div> : <ul className="pressure-legend" aria-label={t('pressureLegend')}>
      {['0', '1', '2–3', '4–7', '8–15', '16+'].map((label, i) => <li key={label}>
        <span className="pressure-swatch" style={{ backgroundColor: PRESSURE_COLORS[i] }} aria-hidden="true" />{label}</li>)}
    </ul>}
    <svg className={`pressure-pitch${smooth ? ' pressure-smooth' : ''}`} viewBox="-4 -4 128 88" role="group" aria-label={t('pressureTitle')} aria-describedby="pressure-grid-help">
      {smooth && <DensityImage data={data as PressureCoordinatesResponse} />}
      {data.cells.map((cell, index) => <rect key={index} ref={node => { nodes.current[index] = node; }}
        x={cell.column * 10} y={cell.row * 10} width="10" height="10" fill={smooth ? 'transparent' : pressureColor(cell.count)}
        className="pressure-cell" data-testid="pressure-cell" data-column={cell.column} data-row={cell.row} data-count={cell.count}
        data-selected={selected === index} role="button" tabIndex={cursor === index ? 0 : -1}
        aria-pressed={selected === index} aria-label={description(index)} aria-describedby="pressure-cell-details"
        onMouseEnter={() => setHovered(index)} onMouseLeave={() => setHovered(null)} onFocus={() => { setCursor(index); setHovered(null); }}
        onClick={event => { setCursor(index); setSelected(index); event.currentTarget.focus(); }} onKeyDown={event => keyDown(event, index)} />)}
      <g className="pressure-markings" aria-hidden="true">
        <rect x="0" y="0" width="120" height="80" />
        <path d="M60 0V80 M0 18H18V62H0 M120 18H102V62H120 M0 30H6V50H0 M120 30H114V50H120 M0 36H-2V44H0 M120 36H122V44H120" />
        <circle cx="60" cy="40" r="10" /><circle cx="60" cy="40" r="0.4" />
        <circle cx="12" cy="40" r="0.4" /><circle cx="108" cy="40" r="0.4" />
        <path d="M18 32 A10 10 0 0 1 18 48 M102 32 A10 10 0 0 0 102 48 M0 1A1 1 0 0 0 1 0 M119 0A1 1 0 0 0 120 1 M120 79A1 1 0 0 0 119 80 M1 80A1 1 0 0 0 0 79" />
      </g>
    </svg>
    <p className="pressure-cell-details" id="pressure-cell-details" role="status" aria-live="polite" data-testid="pressure-details">
      {t('pressureCell', { x: range(active.column * 10, (active.column + 1) * 10, 120),
        y: range(active.row * 10, (active.row + 1) * 10, 80), count: count(active.count) })}
    </p>
    <p className="chart-note" id="pressure-grid-help">{t('pressureInspect')}</p>
  </>;
}
