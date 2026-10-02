import type { MatchOverview, Shootout } from '../types';
import { teamColor } from '../visuals';

export function ShootoutPanel({ shootout, match }: { shootout: Shootout; match: MatchOverview }) {
  if (!shootout.went_to_penalties) return null;
  return <section className="panel" aria-labelledby="shootout-title" data-testid="shootout-panel"><div className="panel-heading">
    <div><span className="eyebrow">05 / THE DECIDER</span><h2 id="shootout-title">Penalty shootout</h2></div><span className="tag">{match.display_score}</span></div>
    <p className="chart-note">Running score: {match.home_team_name} – {match.away_team_name}. Separate from normal performance metrics.</p>
    <ol className="attempts">{[...shootout.attempts].sort((a, b) => a.shootout_order - b.shootout_order).map(attempt => <li key={attempt.shootout_order}>
      <span className="attempt-order">{attempt.shootout_order}</span><span className="attempt-player"><strong>{attempt.player_name ?? 'Unknown player'}</strong>
        <small style={{ color: teamColor(attempt.team_id === match.home_team_id) }}>{attempt.team_name} · attempt {attempt.team_attempt_number}</small></span>
      <span className={`outcome ${attempt.is_goal ? 'goal' : attempt.outcome_name === 'Saved' ? 'saved' : 'missed'}`}>
        {attempt.is_goal ? '●' : attempt.outcome_name === 'Saved' ? '◆' : '×'} {attempt.outcome_name ?? 'Unknown outcome'}</span>
      <strong className="running-score">{attempt.home_shootout_goals_after} – {attempt.away_shootout_goals_after}</strong>
    </li>)}</ol>
  </section>;
}
