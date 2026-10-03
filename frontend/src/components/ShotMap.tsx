import type { MatchOverview, Shot } from '../types';
import { formatClock, markerRadius, PITCH, shotToSvg, teamColor } from '../visuals';
import { useI18n } from '../i18n';
import { shotEvents } from '../shotInteraction';
import type { ShotInteraction } from '../shotInteraction';

export function ShotMap({ shots, match, interaction }: { shots: Shot[]; match: MatchOverview; interaction: ShotInteraction }) {
  const { t, xg, count, outcome } = useI18n();
  const positioned = shots.map(shot => ({ shot, point: shotToSvg(shot.start_x, shot.start_y) }));
  const omitted = positioned.filter(p => p.point === null).length;
  // Extend only the artwork window: shotToSvg and its plotted coordinate range stay unchanged.
  const midfieldExtension = 10 * PITCH.scale;
  return <section className="panel shot-panel" aria-labelledby="shots-title"><div className="panel-heading">
    <div><span className="eyebrow">{t('locations')}</span><h2 id="shots-title">{t('pitch')}</h2></div>
    <span className="tag" data-testid="shot-count">{t('normalShots', { count: count(shots.length) })}</span></div>
    <div className="shot-legend"><span><i className="dot" style={{ background: teamColor(true) }} />{match.home_team_name}</span>
      <span><i className="dot" style={{ background: teamColor(false) }} />{match.away_team_name}</span><span>◎ {t('goal')}</span></div>
    <div className="pitch-layout"><svg viewBox={`${-midfieldExtension} 0 ${PITCH.width + midfieldExtension} ${PITCH.height}`} className="pitch-svg" role="group" aria-label={t('pitchAria')}>
      <title>{t('pitchTitle')}</title>
      <g transform={`translate(${PITCH.pad - PITCH.minX * PITCH.scale},${PITCH.pad}) scale(${PITCH.scale})`} className="pitch-lines">
        <rect x="45" y="0" width="75" height="80" className="pitch-grass" />
        {/* The left edge is a cropped field window, not a goal line or corner. */}
        <path d="M45 0H120V80H45" />
        <path d="M60 0V80" className="halfway-line" />
        <circle cx="60" cy="40" r="10" className="center-circle" />
        <circle cx="60" cy="40" r="0.45" className="pitch-spot center-mark" />
        <path d="M120 18H102V62H120 M120 30H114V50H120 M120 36H122V44H120" />
        <circle cx="108" cy="40" r="0.45" className="pitch-spot" />
        <path d="M102 32 A10 10 0 0 0 102 48" className="penalty-arc" />
        <path d="M119 0 A1 1 0 0 0 120 1" className="corner-arc" />
        <path d="M120 79 A1 1 0 0 0 119 80" className="corner-arc" />
      </g>
      {positioned.map(({ shot, point }) => {
        if (!point) return null;
        const selected = interaction.selectedShotId === shot.event_id;
        const hovered = interaction.hoveredShotId === shot.event_id;
        return <g key={shot.event_id} tabIndex={0} role="button"
          aria-label={t('shotAria', { player: shot.player_name ?? t('unknownPlayer'), team: shot.team_name,
            time: formatClock(shot.minute, shot.second), xg: xg(shot.statsbomb_xg), outcome: outcome(shot.outcome_name) })}
          aria-pressed={selected} aria-describedby={interaction.activeShotId === shot.event_id ? 'shot-details-content' : undefined}
          data-testid="shot-marker" data-event-id={shot.event_id} data-period={shot.period}
          data-state={selected ? 'selected' : hovered ? 'hovered' : 'normal'} className="shot-marker"
          {...shotEvents(shot.event_id, interaction)}>
          <circle className="event-dot" cx={point.x} cy={point.y} r={markerRadius(shot.statsbomb_xg)} fill={teamColor(shot.team_id === match.home_team_id)} fillOpacity="0.65" stroke={teamColor(shot.team_id === match.home_team_id)} strokeWidth="1.2" />
          {shot.is_goal && <circle cx={point.x} cy={point.y} r={markerRadius(shot.statsbomb_xg) + 2.2} fill="none" stroke="#fff" strokeWidth="1.6" />}
          <circle className="interaction-ring" cx={point.x} cy={point.y} r={markerRadius(shot.statsbomb_xg) + (selected ? 6 : 4)}
            fill="none" stroke="white" strokeWidth="1.7" strokeDasharray={selected ? '3 2' : undefined} visibility={selected || hovered ? 'visible' : 'hidden'} />
        </g>;
      })}
    </svg></div>
    <p className="chart-note">{t('shotHint')}<br />{t('pitchNote')}</p>
    {omitted > 0 && <p role="status" className="chart-note">{t('omitted', { count: count(omitted) })}</p>}
  </section>;
}
