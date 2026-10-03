import type { MatchOverview } from '../types';
import { useI18n } from '../i18n';

export function MatchHeader({ match }: { match: MatchOverview }) {
  const { t, date, stage, method } = useI18n();
  return <section className="match-header" aria-label={t('summary')} data-testid="match-header">
    <div className="match-context"><span className="tag">{stage(match.competition_stage_name)}</span>
      <span>{date(match.match_date)}</span><span>{method(match.result_method)}</span></div>
    <div className="scoreboard">
      <div className="team-title home"><span className="eyebrow">{t('home')}</span><h2>{match.home_team_name}</h2></div>
      <div className="score"><strong>{match.display_score}</strong><span>{t('fullTime')}{match.went_to_extra_time ? ` · ${t('afterExtra')}` : ''}</span></div>
      <div className="team-title away"><span className="eyebrow">{t('away')}</span><h2>{match.away_team_name}</h2></div>
    </div>
  </section>;
}
