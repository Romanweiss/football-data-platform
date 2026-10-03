import type { MatchOverview, Shootout } from '../types';
import { teamColor } from '../visuals';
import { useI18n } from '../i18n';

export function ShootoutPanel({ shootout, match }: { shootout: Shootout; match: MatchOverview }) {
  const { t, count, outcome } = useI18n();
  if (!shootout.went_to_penalties) return null;
  return <section className="panel" aria-labelledby="shootout-title" data-testid="shootout-panel"><div className="panel-heading">
    <div><span className="eyebrow">{t('decider')}</span><h2 id="shootout-title">{t('shootout')}</h2></div><span className="tag">{match.display_score}</span></div>
    <p className="chart-note">{t('runningScore', { home: match.home_team_name, away: match.away_team_name })}</p>
    <ol className="attempts">{[...shootout.attempts].sort((a, b) => a.shootout_order - b.shootout_order).map(attempt => <li key={attempt.shootout_order}>
      <span className="attempt-order">{count(attempt.shootout_order)}</span><span className="attempt-player"><strong>{attempt.player_name ?? t('unknownPlayer')}</strong>
        <small style={{ color: teamColor(attempt.team_id === match.home_team_id) }}>{attempt.team_name} · {t('attempt')} {count(attempt.team_attempt_number)}</small></span>
      <span className={`outcome ${attempt.is_goal ? 'goal' : attempt.outcome_name === 'Saved' ? 'saved' : 'missed'}`}>
        {attempt.is_goal ? '●' : attempt.outcome_name === 'Saved' ? '◆' : '×'} {outcome(attempt.outcome_name)}</span>
      <strong className="running-score">{count(attempt.home_shootout_goals_after)} – {count(attempt.away_shootout_goals_after)}</strong>
    </li>)}</ol>
  </section>;
}
