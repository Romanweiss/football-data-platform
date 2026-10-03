import type { TeamMatchStats } from '../types';
import { teamColor } from '../visuals';
import { useI18n } from '../i18n';

const metrics = [['goals', 'goals_for'], ['shots', 'shot_count'], ['expectedGoals', 'shot_xg'],
  ['passes', 'pass_attempts'], ['pressure', 'under_pressure_events'], ['counterpress', 'counterpress_events']] as const;
export function TeamComparison({ teams }: { teams: TeamMatchStats[] }) {
  const { t, xg, count } = useI18n();
  const ordered = [...teams].sort((a, b) => Number(b.is_home) - Number(a.is_home));
  return <section className="panel comparison" aria-labelledby="comparison-title"><div className="panel-heading">
    <div><span className="eyebrow">{t('performance')}</span><h2 id="comparison-title">{t('comparison')}</h2></div>
    <span className="muted">{t('shootoutExcluded')}</span></div>
    <div className="comparison-head"><span style={{ color: teamColor(true) }}>{ordered[0]?.team_name}</span>
      <span>{t('totals')}</span><span style={{ color: teamColor(false) }}>{ordered[1]?.team_name}</span></div>
    {metrics.map(([label, key]) => <div className="comparison-row" key={key}>
      <strong style={{ color: teamColor(true) }}>{key === 'shot_xg' ? xg(ordered[0][key]) : count(ordered[0][key])}</strong>
      <span>{t(label)}</span><strong style={{ color: teamColor(false) }}>{key === 'shot_xg' ? xg(ordered[1][key]) : count(ordered[1][key])}</strong>
    </div>)}
  </section>;
}
