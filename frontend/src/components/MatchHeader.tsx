import type { MatchOverview } from '../types';
import { formatDate } from '../visuals';

export function MatchHeader({ match }: { match: MatchOverview }) {
  return <section className="match-header" aria-label="Match summary" data-testid="match-header">
    <div className="match-context"><span className="tag">{match.competition_stage_name}</span>
      <span>{formatDate(match.match_date)}</span><span>{match.result_method.replaceAll('_', ' ')}</span></div>
    <div className="scoreboard">
      <div className="team-title home"><span className="eyebrow">HOME</span><h1>{match.home_team_name}</h1></div>
      <div className="score"><strong>{match.display_score}</strong><span>FULL TIME{match.went_to_extra_time ? ' · AFTER EXTRA TIME' : ''}</span></div>
      <div className="team-title away"><span className="eyebrow">AWAY</span><h1>{match.away_team_name}</h1></div>
    </div>
  </section>;
}
