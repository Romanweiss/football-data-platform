import type { MatchOverview } from '../types';

export function MatchSelector({ matches, selected, onSelect }: {
  matches: MatchOverview[]; selected: number | null; onSelect: (id: number) => void;
}) {
  return <div className="match-selector"><label htmlFor="match-selector">Explore a match</label>
    <select id="match-selector" value={selected ?? ''} onChange={event => onSelect(Number(event.target.value))}>
      <option value="" disabled>Select a match</option>
      {selected !== null && !matches.some(m => m.match_id === selected) && <option value={selected}>Unknown match</option>}
      {matches.map(match => <option key={match.match_id} value={match.match_id}>{match.match_label}</option>)}
    </select><span className="muted">{matches.length} matches · chronological</span>
  </div>;
}
