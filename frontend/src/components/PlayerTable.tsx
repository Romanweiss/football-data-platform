import { useState } from 'react';
import type { PlayerMatchStats, TeamMatchStats } from '../types';
import { sortPlayers, teamColor } from '../visuals';
import { useI18n } from '../i18n';
import { normalizeSearch } from '../search';

export function PlayerTable({ players, teams }: { players: PlayerMatchStats[]; teams: TeamMatchStats[] }) {
  const { t, count, xg } = useI18n();
  const [team, setTeam] = useState('all');
  const [query, setQuery] = useState('');
  const [coverage, setCoverage] = useState('active');
  const rows = sortPlayers(players.filter(player => (team === 'all' || player.team_id === Number(team))
    && normalizeSearch(player.player_name).includes(normalizeSearch(query))
    && (coverage === 'all' || player.event_count > 0)));
  return <section className="panel" aria-labelledby="players-title"><div className="panel-heading">
    <div><span className="eyebrow">{t('squad')}</span><h2 id="players-title">{t('players')}</h2></div></div>
    <div className="player-filters">
      <label>{t('playerSearch')}<input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label>{t('teamFilter')}<select value={team} onChange={event => setTeam(event.target.value)}>
        <option value="all">{t('bothTeams')}</option>{teams.map(row => <option key={row.team_id} value={row.team_id}>{row.team_name}</option>)}
      </select></label>
      <label>{t('activityFilter')}<select value={coverage} onChange={event => setCoverage(event.target.value)}>
        <option value="all">{t('allSquad')}</option><option value="active">{t('activeOnly')}</option>
      </select></label>
    </div>
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t('tableCaption')}><table><caption className="sr-only">{t('tableCaption')}</caption>
      <thead><tr><th scope="col">{t('player')}</th><th scope="col">{t('team')}</th><th scope="col">{t('shots')}</th><th scope="col">xG</th><th scope="col">{t('passesShort')}</th><th scope="col">{t('events')}</th></tr></thead>
      <tbody>{rows.map(p => <tr key={`${p.team_id}-${p.player_id}`}><th scope="row">{p.player_name}</th>
        <td><i className="dot" style={{ background: teamColor(p.is_home) }} />{p.team_name}</td><td>{count(p.shot_count)}</td><td>{xg(p.shot_xg)}</td><td>{count(p.pass_attempts)}</td><td>{count(p.event_count)}</td></tr>)}</tbody>
    </table></div>
    {rows.length === 0 && <p role="status" className="chart-note">{t('noPlayers')}</p>}
    <p className="chart-note">{t('playerNote', { count: count(rows.length), total: count(players.length) })}</p>
  </section>;
}
