import type { Shot, TeamMatchStats, XgRacePoint } from '../types';
import { formatClock, stepPath, teamColor } from '../visuals';
import { useI18n } from '../i18n';
import { shotEvents } from '../shotInteraction';
import type { ShotInteraction } from '../shotInteraction';

export function XgRace({ points, teams, shots, interaction }: {
  points: XgRacePoint[]; teams: TeamMatchStats[]; shots: Shot[]; interaction: ShotInteraction;
}) {
  const { t, xg, count, outcome } = useI18n();
  const lastOrder = Math.max(1, ...points.map(p => p.event_order));
  const top = Math.max(1, Math.ceil(Math.max(0, ...points.map(p => p.cumulative_xg)) * 2) / 2);
  const x = (order: number) => 48 + ((order - 1) / Math.max(1, lastOrder - 1)) * 544;
  const y = (value: number) => 260 - (value / top) * 220;
  const series = teams.map(team => ({ team, points: points.filter(p => p.team_id === team.team_id).sort((a, b) => a.event_order - b.event_order) }));
  const ticks = [...new Set([1, Math.ceil(lastOrder / 2), lastOrder])];
  const shotsById = new Map(shots.map(shot => [shot.event_id, shot]));
  return <section className="panel race-panel" aria-labelledby="race-title"><div className="panel-heading">
    <div><span className="eyebrow">{t('chanceQuality')}</span><h2 id="race-title">{t('race')}</h2></div><span className="muted">{t('cumulative')}</span></div>
    <div className="race-legend">{series.map(({ team, points: values }) => <div key={team.team_id}>
      <span className="dot" style={{ background: teamColor(team.is_home) }} /><span>{team.team_name}</span>
      <strong data-testid={`xg-final-${team.team_id}`}>{values.length ? xg(values[values.length - 1].cumulative_xg) : '—'}</strong>
    </div>)}</div>
    {points.length === 0 ? <p className="empty">{t('noShots')}</p> : <svg className="race-svg" viewBox="0 0 620 314" role="group" aria-label={t('raceAria')}>
      {[0, 1, 2, 3, 4].map(i => <g key={i}><line x1="48" x2="592" y1={y(top * i / 4)} y2={y(top * i / 4)} className="gridline" />
        <text x="36" y={y(top * i / 4) + 4} textAnchor="end">{xg(top * i / 4)}</text></g>)}
      {ticks.map(tick => <text key={tick} x={x(tick)} y="282" textAnchor="middle">{count(tick)}</text>)}
      <text x="320" y="307" textAnchor="middle">{t('shotOrder')}</text>
      {series.map(({ team, points: values }) => <g key={team.team_id}>
        <path d={stepPath(values, x, y)} fill="none" stroke={teamColor(team.is_home)} strokeWidth="2.8" strokeDasharray={team.is_home ? undefined : '7 3'} />
      </g>)}
      {/* Opponent plateaus are states, not additional shots. Both series stay intact. */}
      {points.map(point => {
        const shot = shotsById.get(point.event_id);
        if (!shot || shot.team_id !== point.team_id) return null;
        const selected = interaction.selectedShotId === shot.event_id;
        const hovered = interaction.hoveredShotId === shot.event_id;
        return <g key={shot.event_id} role="button" tabIndex={0} className="race-point"
          data-testid="race-point" data-event-id={shot.event_id} data-state={selected ? 'selected' : hovered ? 'hovered' : 'normal'}
          aria-pressed={selected} aria-label={t('shotAria', { player: shot.player_name ?? t('unknownPlayer'), team: shot.team_name,
            time: formatClock(shot.minute, shot.second), xg: xg(shot.statsbomb_xg), outcome: outcome(shot.outcome_name) }) + `, ${t('cumulative')} ${xg(point.cumulative_xg)}`}
          aria-describedby={interaction.activeShotId === shot.event_id ? 'shot-details-content' : undefined}
          {...shotEvents(shot.event_id, interaction)}>
          <circle className="hit-target" cx={x(point.event_order)} cy={y(point.cumulative_xg)} r="12" fill="transparent" />
          <circle className="event-dot" cx={x(point.event_order)} cy={y(point.cumulative_xg)} r="3" fill={teamColor(point.is_home)} />
          <circle className="interaction-ring" cx={x(point.event_order)} cy={y(point.cumulative_xg)} r={selected ? 8 : 6}
            fill="none" stroke="white" strokeWidth="1.7" strokeDasharray={selected ? '3 2' : undefined} visibility={selected || hovered ? 'visible' : 'hidden'} />
        </g>;
      })}
    </svg>}
    <p className="chart-note">{t('raceAxis')}<br />{t('raceNote')}</p>
  </section>;
}
