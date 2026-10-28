import type { Competition, Season } from '../types';
import { useI18n } from '../i18n';
import { competitionLabel, seasonLabel } from '../contextLabels';

export function ContextSelector({ competitions, seasons, competitionId, seasonId, onCompetition, onSeason }: {
  competitions: Competition[]; seasons: Season[]; competitionId: number | null; seasonId: number | null;
  onCompetition: (id: number) => void; onSeason: (id: number) => void;
}) {
  const { t } = useI18n();
  return <div className="context-selectors">
    <label>{t('competition')}<select value={competitionId ?? ''} disabled={!competitions.length}
      onChange={event => onCompetition(Number(event.target.value))}>
      <option value="" disabled>{t('selectCompetition')}</option>
      {competitionId !== null && !competitions.some(row => row.competition_id === competitionId)
        && <option value={competitionId}>{t('competitionId', { id: competitionId })}</option>}
      {competitions.map(row => <option key={row.competition_id} value={row.competition_id}>{competitionLabel(row.competition_id, t)}</option>)}
    </select></label>
    <label>{t('season')}<select value={seasonId ?? ''} disabled={!seasons.length}
      onChange={event => onSeason(Number(event.target.value))}>
      <option value="" disabled>{t('selectSeason')}</option>
      {seasonId !== null && !seasons.some(row => row.season_id === seasonId)
        && <option value={seasonId}>{t('seasonId', { id: seasonId })}</option>}
      {seasons.map(row => <option key={row.season_id} value={row.season_id}>{seasonLabel(competitionId, row.season_id, t)}</option>)}
    </select></label>
  </div>;
}
