import type { Shot, XgRacePoint } from '../types';
import { useI18n } from '../i18n';
import { formatClock } from '../visuals';
import type { ShotInteraction } from '../shotInteraction';
import { raceStateForShot } from '../shotInteraction';

export function ShotDetails({ shots, points, interaction }: { shots: Shot[]; points: XgRacePoint[]; interaction: ShotInteraction }) {
  const { t, xg, count, outcome } = useI18n();
  const shot = shots.find(row => row.event_id === interaction.activeShotId);
  const state = shot && raceStateForShot(shot, points);
  return <section className="panel shared-shot-details" aria-labelledby="details-heading" data-testid="shot-details">
    <div className="panel-heading"><h2 id="details-heading">{t('shotDetails')}</h2>
      {interaction.selectedShotId && <button onClick={interaction.clear}>{t('clearShot')}</button>}</div>
    <div role="status" aria-live="polite" aria-atomic="true" id="shot-details-content">
      {shot ? <><span className="eyebrow">{t(interaction.selectedShotId === shot.event_id ? 'selectedShot' : 'previewShot')}</span>
        <dl className="detail-grid">
          <div><dt>{t('player')}</dt><dd>{shot.player_name ?? t('unknownPlayer')}</dd></div>
          <div><dt>{t('team')}</dt><dd>{shot.team_name}</dd></div>
          <div><dt>{t('time')}</dt><dd>{formatClock(shot.minute, shot.second)}</dd></div>
          <div><dt>{t('shotXg')}</dt><dd>{xg(shot.statsbomb_xg)}</dd></div>
          <div><dt>{t('outcome')}</dt><dd>{outcome(shot.outcome_name)}</dd></div>
          <div><dt>{t('cumulative')}</dt><dd>{state ? xg(state.cumulative_xg) : '—'}</dd></div>
          <div><dt>{t('period')}</dt><dd>{count(shot.period)}{shot.is_extra_time ? ` · ${t('extraTime')}` : ''}</dd></div>
        </dl></> : <p className="chart-note">{t('inspectShot')}</p>}
    </div>
  </section>;
}
