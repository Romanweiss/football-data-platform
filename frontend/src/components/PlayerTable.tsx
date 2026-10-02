import { useState } from 'react';
import type { PlayerMatchStats, TeamMatchStats } from '../types';
import { formatCount, formatXg, sortPlayers, teamColor } from '../visuals';

export function PlayerTable({ players, teams }: { players: PlayerMatchStats[]; teams: TeamMatchStats[] }) {
  const [team, setTeam] = useState('all');
  const rows = sortPlayers(players.filter(player => team === 'all' || player.team_id === Number(team)));
  return <section className="panel" aria-labelledby="players-title"><div className="panel-heading">
    <div><span className="eyebrow">04 / SQUAD PERFORMANCE</span><h2 id="players-title">Player contributions</h2></div>
    <div><label className="sr-only" htmlFor="player-team">Filter players by team</label><select id="player-team" value={team} onChange={event => setTeam(event.target.value)}>
      <option value="all">Both teams</option>{teams.map(t => <option key={t.team_id} value={t.team_id}>{t.team_name}</option>)}
    </select></div></div>
    <div className="table-scroll"><table><caption className="sr-only">Squad players ordered by xG, shots and event count</caption>
      <thead><tr><th scope="col">Player</th><th scope="col">Team</th><th scope="col">Shots</th><th scope="col">xG</th><th scope="col">Passes</th><th scope="col">Events</th></tr></thead>
      <tbody>{rows.map(p => <tr key={`${p.team_id}-${p.player_id}`}><th scope="row">{p.player_name}</th>
        <td><i className="dot" style={{ background: teamColor(p.is_home) }} />{p.team_name}</td><td>{formatCount(p.shot_count)}</td><td>{formatXg(p.shot_xg)}</td><td>{formatCount(p.pass_attempts)}</td><td>{formatCount(p.event_count)}</td></tr>)}</tbody>
    </table></div><p className="chart-note">{rows.length} squad players · Zero-activity players included · Sorted by xG, then shots and events</p>
  </section>;
}
