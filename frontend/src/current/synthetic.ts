import type { CurrentFixture, CurrentLeague, CurrentStanding } from './types';

const names = ['Northbridge', 'Harbour Vale', 'Copperfield', 'Westhaven', 'Rivergate', 'Stonewell',
  'Silverpine', 'Eastford', 'Cedar Vale', 'Kingsmere', 'Amber Coast', 'Brookvale', 'Ironwood',
  'Lakehaven', 'Southwick', 'Elmbridge', 'Redmont', 'Whitecliff', 'Greenhaven', 'Ashmere',
  'Bluehaven', 'Oakridge', 'Windmere', 'Golden Vale', 'Hillcrest', 'Seabrook', 'Fairhaven',
  'Cloudbridge', 'Maple Coast', 'Rosehaven', 'Brightmoor', 'Clearwater', 'Highmere', 'Pinegate',
  'Willowbrook', 'Dawnfield'];
const days = ['2026-09-08', '2026-09-22', '2026-10-13', '2026-11-03', '2026-11-24',
  '2026-12-08', '2027-01-12', '2027-01-26'];

export function createSyntheticLeague(seed = 7): CurrentLeague {
  if (!Number.isInteger(seed) || seed < 0 || seed > 65535) throw new Error('Invalid demo seed');
  const competition = { id: 'demo-ucl', slug: 'uefa-champions-league', name: 'UEFA Champions League' };
  const season = { id: 'demo-ucl-2026', competitionId: competition.id, startYear: 2026, label: '2026/27' };
  const participants = names.map((name, i) => ({ id: `demo-team-${String(i + 1).padStart(2, '0')}`,
    name: `Demo · ${name}`, shortName: `D${String(i + 1).padStart(2, '0')}` }));
  const fixtures: CurrentFixture[] = [];
  // An invented balanced bipartite schedule, NOT a reproduction of UEFA's draw/pots.
  for (let round = 0; round < 8; round++) for (let i = 0; i < 18; i++) {
    const a = participants[i].id, b = participants[18 + (i + round) % 18].id;
    const finished = round < 3;
    const day = new Date(`${days[round]}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() + Number(i >= 9));
    day.setUTCHours(i % 3 === 0 ? 17 : 20, 0, 0, 0);
    fixtures.push({ id: `demo-ucl-2026-r${round + 1}-m${i + 1}`, seasonId: season.id, round: round + 1,
      kickoff: day.toISOString(), homeId: round % 2 === 0 ? a : b, awayId: round % 2 === 0 ? b : a,
      status: finished ? 'FINISHED' : 'TIMED',
      score: finished ? { home: (round * 3 + i * 5 + seed) % 5, away: (round * 7 + i * 2 + seed) % 4 } : null });
  }
  fixtures.sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.id.localeCompare(b.id));
  const totals = new Map<string, CurrentStanding>(participants.map(team => [team.id,
    { participantId: team.id, position: 0, played: 0, won: 0, drawn: 0, lost: 0,
      goalsFor: 0, goalsAgainst: 0, goalDifference: 0, points: 0, zone: 'outside' }]));
  for (const fixture of fixtures) {
    if (fixture.status !== 'FINISHED' || fixture.score === null) continue;
    for (const [id, gf, ga] of [[fixture.homeId, fixture.score.home, fixture.score.away],
      [fixture.awayId, fixture.score.away, fixture.score.home]] as const) {
      const row = totals.get(id)!;
      row.played++; row.won += Number(gf > ga); row.drawn += Number(gf === ga); row.lost += Number(gf < ga);
      row.goalsFor += gf; row.goalsAgainst += ga; row.goalDifference += gf - ga;
      row.points += gf > ga ? 3 : Number(gf === ga);
    }
  }
  const standings = [...totals.values()].sort((a, b) => b.points - a.points || b.goalDifference - a.goalDifference
    || b.goalsFor - a.goalsFor || a.participantId.localeCompare(b.participantId));
  standings.forEach((row, i) => { row.position = i + 1; row.zone = i < 8 ? 'top8' : i < 24 ? 'playoff' : 'outside'; });
  return { schemaVersion: 1, dataKind: 'synthetic', competition, season, participants, fixtures, standings,
    freshness: { kind: 'fixed-demo-clock', asOf: '2026-10-15T00:00:00Z', sourceRevision: null },
    coverage: { phase: 'league_phase', participants: 36, fixtures: 144, matchesPerTeam: 8,
      completeForPhase: true, completeForCompetition: false },
    capabilities: { fixtures: true, results: true, standings: true, eventCoordinates: false,
      xg: false, lineups: false, playerStatistics: false } };
}
