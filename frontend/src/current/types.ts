/** UI-facing, provider-neutral prototype DTOs. No StatsBomb/vendor identifiers. */
export interface CurrentCompetition { id: string; slug: string; name: string }
export interface CurrentSeason { id: string; competitionId: string; startYear: number; label: string }
export interface CurrentParticipant { id: string; name: string; shortName: string }
export interface CurrentFixture {
  id: string; seasonId: string; round: number; kickoff: string;
  homeId: string; awayId: string; status: 'FINISHED' | 'TIMED';
  score: { home: number; away: number } | null;
}
export type StandingZone = 'top8' | 'playoff' | 'outside';
export interface CurrentStanding {
  participantId: string; position: number; played: number; won: number; drawn: number;
  lost: number; goalsFor: number; goalsAgainst: number; goalDifference: number; points: number;
  zone: StandingZone;
}
export interface CurrentFreshness { kind: 'fixed-demo-clock'; asOf: string; sourceRevision: null }
export interface CurrentCoverage {
  phase: 'league_phase'; participants: number; fixtures: number; matchesPerTeam: number;
  completeForPhase: boolean; completeForCompetition: false;
}
export interface CurrentCapabilities {
  fixtures: true; results: true; standings: true;
  eventCoordinates: false; xg: false; lineups: false; playerStatistics: false;
}
export interface CurrentLeague {
  schemaVersion: 1; dataKind: 'synthetic'; competition: CurrentCompetition; season: CurrentSeason;
  participants: CurrentParticipant[]; fixtures: CurrentFixture[]; standings: CurrentStanding[];
  freshness: CurrentFreshness; coverage: CurrentCoverage; capabilities: CurrentCapabilities;
}
export interface CurrentCompetitionCard {
  competition: CurrentCompetition; season: CurrentSeason; participants: number; fixtures: number; dataKind: 'synthetic';
}
/** Replace this adapter, not the page, when separately approved Django serving exists. */
export interface CurrentSource {
  catalog(signal: AbortSignal): Promise<CurrentCompetitionCard[]>;
  league(slug: string, year: number, signal: AbortSignal): Promise<CurrentLeague>;
}
