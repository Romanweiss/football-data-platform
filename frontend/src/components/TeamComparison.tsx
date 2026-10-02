import type { TeamMatchStats } from '../types';
import { formatCount, formatXg, teamColor } from '../visuals';

const metrics = [['Goals', 'goals_for'], ['Shots', 'shot_count'], ['Expected goals', 'shot_xg'],
  ['Pass attempts', 'pass_attempts'], ['Under pressure', 'under_pressure_events'], ['Counterpress', 'counterpress_events']] as const;
export function TeamComparison({ teams }: { teams: TeamMatchStats[] }) {
  const ordered = [...teams].sort((a, b) => Number(b.is_home) - Number(a.is_home));
  return <section className="panel comparison" aria-labelledby="comparison-title"><div className="panel-heading">
    <div><span className="eyebrow">01 / PERFORMANCE</span><h2 id="comparison-title">Team comparison</h2></div>
    <span className="muted">Shootout excluded</span></div>
    <div className="comparison-head"><span style={{ color: teamColor(true) }}>{ordered[0]?.team_name}</span>
      <span>Match totals</span><span style={{ color: teamColor(false) }}>{ordered[1]?.team_name}</span></div>
    {metrics.map(([label, key]) => <div className="comparison-row" key={key}>
      <strong style={{ color: teamColor(true) }}>{key === 'shot_xg' ? formatXg(ordered[0][key]) : formatCount(ordered[0][key])}</strong>
      <span>{label}</span><strong style={{ color: teamColor(false) }}>{key === 'shot_xg' ? formatXg(ordered[1][key]) : formatCount(ordered[1][key])}</strong>
    </div>)}
  </section>;
}
