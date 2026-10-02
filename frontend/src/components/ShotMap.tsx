import { useState } from 'react';
import type { MatchOverview, Shot } from '../types';
import { formatClock, formatXg, markerRadius, PITCH, shotToSvg, teamColor } from '../visuals';

export function ShotMap({ shots, match }: { shots: Shot[]; match: MatchOverview }) {
  const [active, setActive] = useState<Shot | null>(null);
  const positioned = shots.map(shot => ({ shot, point: shotToSvg(shot.start_x, shot.start_y) }));
  const omitted = positioned.filter(p => p.point === null).length;
  return <section className="panel shot-panel" aria-labelledby="shots-title"><div className="panel-heading">
    <div><span className="eyebrow">03 / SHOT LOCATIONS</span><h2 id="shots-title">On the pitch</h2></div>
    <span className="tag" data-testid="shot-count">{shots.length} normal shots</span></div>
    <div className="shot-legend"><span><i className="dot" style={{ background: teamColor(true) }} />{match.home_team_name}</span>
      <span><i className="dot" style={{ background: teamColor(false) }} />{match.away_team_name}</span><span>◎ Goal</span></div>
    <div className="pitch-layout"><svg viewBox={`0 0 ${PITCH.width} ${PITCH.height}`} className="pitch-svg" role="group" aria-label="Normal shots on the attacking half pitch">
      <title>StatsBomb attacking half. Goal to the right; Y increases downwards.</title>
      <g transform={`translate(${PITCH.pad - PITCH.minX * PITCH.scale},${PITCH.pad}) scale(${PITCH.scale})`} className="pitch-lines">
        <rect x="55" y="0" width="65" height="80" className="pitch-grass" />
        <path d="M55 0H120V80H55 M60 0V80" />
        <path d="M120 18H102V62H120 M120 30H114V50H120 M120 36H122V44H120" />
        <circle cx="108" cy="40" r="0.45" className="pitch-spot" />
        <path d="M102 32 A10 10 0 0 0 102 48 M60 30 A10 10 0 0 1 60 50" />
      </g>
      {positioned.map(({ shot, point }) => point && <g key={shot.event_id} tabIndex={0} role="button"
        aria-label={`${shot.player_name ?? 'Unknown player'}, ${shot.team_name}, ${formatClock(shot.minute, shot.second)}, ${formatXg(shot.statsbomb_xg)} xG, ${shot.outcome_name ?? 'Unknown outcome'}`}
        aria-describedby={active?.event_id === shot.event_id ? 'shot-tooltip' : undefined}
        data-testid="shot-marker" data-period={shot.period} className="shot-marker"
        onMouseEnter={() => setActive(shot)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(shot)} onBlur={() => setActive(null)}
        onClick={() => setActive(shot)} onKeyDown={event => { if (event.key === 'Escape') setActive(null); if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setActive(shot); } }}>
        <circle cx={point.x} cy={point.y} r={markerRadius(shot.statsbomb_xg)} fill={teamColor(shot.team_id === match.home_team_id)} fillOpacity="0.65" stroke={teamColor(shot.team_id === match.home_team_id)} strokeWidth="1.2" />
        {shot.is_goal && <circle cx={point.x} cy={point.y} r={markerRadius(shot.statsbomb_xg) + 2.2} fill="none" stroke="#fff" strokeWidth="1.6" />}
      </g>)}
    </svg>
    <div className="shot-detail" id="shot-tooltip" role="status" aria-live="polite">
      {active ? <><strong>{active.player_name ?? 'Unknown player'}</strong><span>{active.team_name} · {formatClock(active.minute, active.second)}</span>
        <div><b>{formatXg(active.statsbomb_xg)} xG</b><span>{active.outcome_name ?? 'Unknown outcome'}</span></div><small>{active.shot_label}</small></>
        : <><strong>Every chance, in context.</strong><span>Hover, focus or tap a shot to explore.</span><small>Larger circles = higher xG. White rings = goals.</small></>}
    </div></div>
    <p className="chart-note">Attacking towards the right → · Source coordinates preserved.</p>
    {omitted > 0 && <p role="status" className="chart-note">{omitted} shots not plotted: missing coordinates or outside the displayed x=55–120, y=0–80 area.</p>}
  </section>;
}
