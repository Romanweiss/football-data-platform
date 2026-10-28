import { useId, useRef, useState } from 'react';
import { ApiFailure, fetchPasses } from '../api';
import type { MatchAnalysisResponse, PassEvent, PassMapResponse, PassStatus } from '../types';
import { useI18n } from '../i18n';
import { useResource } from '../useResource';
import { formatClock } from '../visuals';
import { ErrorState } from './States';

const STATUS_LABEL = { completed: 'completedPasses', failed: 'failedPasses', unknown: 'unknownPasses' } as const;
const COLORS: Record<PassStatus, string> = { completed: '#64d9c0', failed: '#ffb46b', unknown: '#e1d1ff' };
const coordinate = (x: number, y: number) => `${x}, ${y}`;

export function PassMap({ analysis }: { analysis: MatchAnalysisResponse }) {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(false);
  const [team, setTeam] = useState(String(analysis.match.home_team_id));
  const [player, setPlayer] = useState('');
  const [period, setPeriod] = useState('1');
  const context = { competitionId: analysis.match.competition_id, seasonId: analysis.match.season_id };
  const filters = { team_id: Number(team), ...(player ? { player_id: Number(player) } : {}),
    ...(period ? { period: Number(period) } : {}) };
  const identity = `${context.competitionId}/${context.seasonId}/${analysis.match.match_id}/${team}/${player}/${period}`;
  const resource = useResource(enabled ? identity : null,
    signal => fetchPasses(context, analysis.match.match_id, filters, signal));
  const players = analysis.players.filter(p => p.team_id === Number(team));
  return <section className="panel pass-map-panel" aria-labelledby="passes-title" data-testid="pass-map">
    <div className="panel-heading"><h2 id="passes-title">{t('passesTitle')}</h2></div>
    <p className="chart-note">{t('passMapNote')}</p>
    <div className="pass-filters">
      <label>{t('passTeam')}<select value={team} onChange={e => { setTeam(e.target.value); setPlayer(''); }}>
        {analysis.teams.map(row => <option key={row.team_id} value={row.team_id}>{row.team_name}</option>)}
      </select></label>
      <label>{t('passPlayer')}<select value={player} onChange={e => setPlayer(e.target.value)}>
        <option value="">{t('allPlayers')}</option>
        {players.map(p => <option key={p.player_id} value={p.player_id}>{p.player_name}</option>)}
      </select></label>
      <label>{t('passPeriod')}<select value={period} onChange={e => setPeriod(e.target.value)}>
        <option value="">{t('allPeriods')}</option>
        {[1, 2, 3, 4, 5].map(p => <option key={p} value={p}>{t('passPeriodOption', { period: p })}</option>)}
      </select></label>
    </div>
    {!enabled ? <button onClick={() => setEnabled(true)}>{t('loadPasses')}</button>
      : resource.state.status === 'loading' ? <p role="status">{t('passLoading')}</p>
      : resource.state.status === 'error' ? resource.state.error instanceof ApiFailure && resource.state.error.code === 'pass_result_too_large'
        ? <p role="alert">{t('passTooLarge')}</p>
        : <ErrorState error={resource.state.error} retry={resource.retry} />
      : <PassPitch key={identity} data={resource.state.data} />}
    {/* Explicit loading keeps the initial match/shot request unchanged. No hidden
        sampling: all returned passes render; the server fails above its bound. */}
    <p className="chart-note">{t('passKeyboard')}</p>
  </section>;
}

export function PassPitch({ data }: { data: PassMapResponse }) {
  const { t, count } = useI18n();
  const markerPrefix = 'pass-arrow-' + useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const nodes = useRef<(SVGGElement | null)[]>([]);
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const active = data.passes.find(p => p.event_id === (selected ?? hovered ?? focused));
  const items = data.passes.map((pass, index) => ({ pass, index }));
  // Selected line paints last so dense maps do not cover the highlighted pass.
  items.sort((a, b) => Number(a.pass.event_id === selected) - Number(b.pass.event_id === selected));
  function keyDown(event: React.KeyboardEvent, index: number, pass: PassEvent) {
    let next = index;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = Math.min(index + 1, data.passes.length - 1);
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = Math.max(index - 1, 0);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = data.passes.length - 1;
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(pass.event_id); return; }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setSelected(null); return; }
    else return;
    event.preventDefault(); setCursor(next); nodes.current[next]?.focus();
  }
  return <>
    <div className="pass-counts" role="status" data-testid="pass-counts">
      <strong>{t('passAttempts', { count: count(data.total_count) })}</strong>
      <span>{t('passesDrawn', { count: count(data.returned_count) })}</span>
      {(['completed', 'failed', 'unknown'] as const).map(status => <span key={status} style={{ color: COLORS[status] }}>
        {t(STATUS_LABEL[status])}: {count(data.outcome_counts[status])}</span>)}
      <span>{t('excludedPasses', { count: count(data.excluded.count) })}</span>
    </div>
    {data.excluded.count > 0 && <p className="chart-note">{t('missingCoordinates')}: {count(data.excluded.reasons.missing_coordinates)} · {t('nonFiniteCoordinates')}: {count(data.excluded.reasons.non_finite_coordinates)} · {t('outOfBoundsCoordinates')}: {count(data.excluded.reasons.out_of_bounds_coordinates)}</p>}
    {data.returned_count > 250 && <p className="chart-note">{t('passDense', { count: count(data.returned_count) })}</p>}
    {data.total_count === 0 && <p className="chart-note">{t('passEmpty')}</p>}
    <svg className="pass-pitch" viewBox="-4 -4 128 88" role="group" aria-label={t('passesTitle')}>
      <defs>{(['completed', 'failed', 'unknown'] as const).map(status => <marker key={status} id={`${markerPrefix}-${status}`}
        markerWidth="3" markerHeight="3" refX="2.8" refY="1.5" orient="auto" markerUnits="userSpaceOnUse">
        <path d="M0 0 L3 1.5 L0 3 Z" fill={COLORS[status]} />
      </marker>)}</defs>
      <g className="pass-field" aria-hidden="true">
        <rect x="0" y="0" width="120" height="80" rx="0.3" />
        <path d="M60 0V80 M0 18H18V62H0 M120 18H102V62H120 M0 30H6V50H0 M120 30H114V50H120 M0 36H-2V44H0 M120 36H122V44H120" />
        <circle cx="60" cy="40" r="10" /><circle cx="60" cy="40" r="0.4" className="pitch-spot" />
        <circle cx="12" cy="40" r="0.4" className="pitch-spot" /><circle cx="108" cy="40" r="0.4" className="pitch-spot" />
        <path d="M18 32 A10 10 0 0 1 18 48 M102 32 A10 10 0 0 0 102 48 M0 1A1 1 0 0 0 1 0 M119 0A1 1 0 0 0 120 1 M120 79A1 1 0 0 0 119 80 M1 80A1 1 0 0 0 0 79" />
      </g>
      {items.map(({ pass: p, index }) => <g key={p.event_id} ref={node => { nodes.current[index] = node; }}
        className="pass-event" data-testid="pass-event" data-event-id={p.event_id} data-status={p.completion_status}
        data-selected={p.event_id === selected} role="button" tabIndex={cursor === index ? 0 : -1}
        aria-pressed={p.event_id === selected} aria-describedby="pass-details-content"
        aria-label={t('passAria', { player: p.player_name ?? t('unknownPlayer'), time: formatClock(p.minute, p.second),
          status: t(STATUS_LABEL[p.completion_status]), start: coordinate(p.start_x, p.start_y), end: coordinate(p.end_x, p.end_y) })}
        onClick={() => { setCursor(index); setSelected(p.event_id); }} onMouseEnter={() => setHovered(p.event_id)}
        onMouseLeave={() => setHovered(null)} onFocus={() => { setCursor(index); setFocused(p.event_id); }} onBlur={() => setFocused(null)}
        onKeyDown={event => keyDown(event, index, p)}>
        <line x1={p.start_x} y1={p.start_y} x2={p.end_x} y2={p.end_y} className="pass-hit" />
        <line x1={p.start_x} y1={p.start_y} x2={p.end_x} y2={p.end_y} className="pass-line"
          stroke={COLORS[p.completion_status]} strokeDasharray={p.completion_status === 'failed' ? '2 1' : p.completion_status === 'unknown' ? '0.5 1' : undefined}
          markerEnd={`url(#${markerPrefix}-${p.completion_status})`} />
        <circle cx={p.start_x} cy={p.start_y} r="0.75" fill={COLORS[p.completion_status]} className="pass-start" />
        <circle cx={p.end_x} cy={p.end_y} r="0.55" fill="none" stroke={COLORS[p.completion_status]} className="pass-end" />
      </g>)}
    </svg>
    <div className="pass-details"><div className="panel-heading"><h3>{t('passDetails')}</h3>
      {selected && <button onClick={() => setSelected(null)}>{t('clearPass')}</button>}</div>
      <div id="pass-details-content" role="status" aria-live="polite" aria-atomic="true">
        {active ? <dl className="detail-grid">
          <div><dt>{t('player')}</dt><dd>{active.player_name ?? t('unknownPlayer')}</dd></div>
          <div><dt>{t('passRecipient')}</dt><dd>{active.recipient_name ?? t('unknownPlayer')}</dd></div>
          <div><dt>{t('time')}</dt><dd>{formatClock(active.minute, active.second)} · {t('passPeriodOption', { period: active.period })}</dd></div>
          <div><dt>{t('outcome')}</dt><dd>{t(STATUS_LABEL[active.completion_status])}</dd></div>
          <div><dt>{t('passOutcome')}</dt><dd>{active.outcome_name ?? '—'}</dd></div>
          <div><dt>{t('passStart')}</dt><dd>{coordinate(active.start_x, active.start_y)}</dd></div>
          <div><dt>{t('passEnd')}</dt><dd>{coordinate(active.end_x, active.end_y)}</dd></div>
        </dl> : <p className="chart-note">{t('selectPass')}</p>}
      </div>
    </div>
  </>;
}
