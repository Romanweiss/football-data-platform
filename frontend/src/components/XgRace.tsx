import type { TeamMatchStats, XgRacePoint } from '../types';
import { formatClock, formatXg, stepPath, teamColor } from '../visuals';

export function XgRace({ points, teams }: { points: XgRacePoint[]; teams: TeamMatchStats[] }) {
  const lastOrder = Math.max(1, ...points.map(p => p.event_order));
  const top = Math.max(1, Math.ceil(Math.max(0, ...points.map(p => p.cumulative_xg)) * 2) / 2);
  const x = (order: number) => 48 + ((order - 1) / Math.max(1, lastOrder - 1)) * 544;
  const y = (xg: number) => 260 - (xg / top) * 220;
  const series = teams.map(team => ({ team, points: points.filter(p => p.team_id === team.team_id).sort((a, b) => a.event_order - b.event_order) }));
  const ticks = [...new Set([1, Math.ceil(lastOrder / 2), lastOrder])];
  return <section className="panel race-panel" aria-labelledby="race-title"><div className="panel-heading">
    <div><span className="eyebrow">02 / CHANCE QUALITY</span><h2 id="race-title">The xG race</h2></div><span className="muted">Cumulative xG</span></div>
    <div className="race-legend">{series.map(({ team, points: values }) => <div key={team.team_id}>
      <span className="dot" style={{ background: teamColor(team.is_home) }} /><span>{team.team_name}</span>
      <strong data-testid={`xg-final-${team.team_id}`}>{values.length ? formatXg(values[values.length - 1].cumulative_xg) : '—'}</strong>
    </div>)}</div>
    {points.length === 0 ? <p className="empty">No normal-shot events in this match.</p> : <svg className="race-svg" viewBox="0 0 620 314" role="img" aria-label="Cumulative expected goals by ordered normal shots">
      {[0, 1, 2, 3, 4].map(i => <g key={i}><line x1="48" x2="592" y1={y(top * i / 4)} y2={y(top * i / 4)} className="gridline" />
        <text x="36" y={y(top * i / 4) + 4} textAnchor="end">{formatXg(top * i / 4)}</text></g>)}
      {ticks.map(tick => <text key={tick} x={x(tick)} y="282" textAnchor="middle">{tick}</text>)}
      <text x="320" y="307" textAnchor="middle">Ordered normal shots · not elapsed minutes</text>
      {series.map(({ team, points: values }) => <g key={team.team_id}>
        <path d={stepPath(values, x, y)} fill="none" stroke={teamColor(team.is_home)} strokeWidth="2.8" strokeDasharray={team.is_home ? undefined : '7 3'} />
        {values.map(point => <circle key={point.event_id} cx={x(point.event_order)} cy={y(point.cumulative_xg)} r="3" fill={teamColor(team.is_home)}>
          <title>{team.team_name} · shot {point.event_order} · {formatClock(point.minute, point.second)} · {formatXg(point.cumulative_xg)} xG</title>
        </circle>)}
      </g>)}
    </svg>}
    <p className="chart-note">Steps follow actual shot order. Extra time included; penalty shootout excluded.</p>
  </section>;
}
