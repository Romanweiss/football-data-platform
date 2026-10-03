import type { MatchOverview } from './types';

export const normalizeSearch = (value: string) => value.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();
export function filterMatches(matches: readonly MatchOverview[], query: string, stage: (value: string) => string = value => value): MatchOverview[] {
  const terms = normalizeSearch(query).split(/\s+/).filter(Boolean);
  return matches.filter(match => {
    const text = normalizeSearch([match.home_team_name, match.away_team_name, match.match_label,
      match.competition_stage_name, stage(match.competition_stage_name), match.match_date].join(' '));
    return terms.every(term => text.includes(term));
  });
}
