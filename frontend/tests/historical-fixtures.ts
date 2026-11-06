/** Artificial PET-3B HTTP responses for tests ONLY. Never imported by src. */
import type { HistoricalCoverage, HistoricalEnvelope, HistoricalFixture, HistoricalFilters, HistoricalOverview,
  HistoricalPage, HistoricalParticipant, HistoricalQuality, HistoricalQuery, HistoricalSection, HistoricalSource } from '../src/historical/types';
import { HISTORICAL_API, HISTORICAL_SEASON_API } from '../src/historical/source';

export const mockId = (kind: string, n: number) => `uefa:${kind}:${n.toString(16).padStart(64, '0')}`;
export function historicalFixtureFactory() {
  const envelope: HistoricalEnvelope = {
    competition: { state: 'known', id: mockId('competition', 1), slug: 'uefa-champions-league', name: 'UEFA Champions League' },
    season: { state: 'known', id: mockId('season', 1), start_year: 2024, label: '2024/25' },
    provenance: { provider: 'openfootball', repository: 'https://github.com/openfootball/football.json', path: '2024-25/uefa.cl.json',
      source_revision: { kind: 'git_commit', value: 'a'.repeat(40) }, provider_revision: { state: 'unsupported', value: null },
      source_sha256: 'b'.repeat(64), batch_id: 'c'.repeat(64), semantic_fingerprint: 'd'.repeat(64), license: 'CC0-1.0', normalized_schema_version: 2 },
    coverage: { source: 'UNKNOWN', results: 'INCOMPLETE', claim: 'source_records_only_not_verified_complete_results' },
    source_capabilities: { fixtures: 'declared', results: 'declared', standings: 'unavailable', event_coordinates: 'unavailable' },
    capabilities: { fixtures: 'known', source_reported_results: 'known', verified_regulation_scores: 'unsupported', standings: 'unsupported', events: 'unsupported' },
    freshness: { mode: 'pinned_historical', last_observed_at: { state: 'unknown', value: null } },
  };
  const participants: HistoricalParticipant[] = Array.from({ length: 36 }, (_, i) => ({ state: 'known', id: mockId('participant', i + 1), name: `Fixture Club ${String(i + 1).padStart(2, '0')}` }));
  const fixtures: HistoricalFixture[] = [], coverage: HistoricalCoverage[] = [], quality: HistoricalQuality[] = [];
  const groupSizes = [18, 18, 18, 18, 18, 18, 18, 18, 8, 8, 8, 8, 12, 1];
  // 14 groups summing to 189; these are artificial schedules, not UEFA draws.
  let index = 0;
  groupSizes.forEach((size, round) => {
    const stageIndex = round < 8 ? 1 : round < 10 ? 2 : 3;
    const stage = { state: 'known' as const, id: mockId('stage', stageIndex), name: `Test stage ${stageIndex}`, kind: round < 8 ? 'league_phase' as const : 'knockout' as const };
    const rows: HistoricalFixture[] = [];
    for (let j = 0; j < size; j++, index++) {
      const unknown = index === 188, ambiguous = index === 186 || index === 187;
      const day = new Date(Date.UTC(2024, 8, 1 + index));
      const row: HistoricalFixture = { id: mockId('fixture', index + 1), match_date: day.toISOString().slice(0, 10),
        kickoff_utc: { state: 'unknown', value: null }, home: participants[index % 36], away: participants[(index + 7) % 36], stage,
        round: { state: 'known', id: mockId('round', round + 1), name: `Test round ${round + 1}` },
        status: unknown ? 'unknown' : 'finished', status_origin: unknown ? 'unscored_unknown' : 'source_score',
        result_availability: unknown ? 'MISSING' : 'REPORTED',
        source_reported_score: { ht: index < 10 || unknown ? { state: 'unknown', value: null } : { state: 'known', value: [0, 0] },
          ft: unknown ? { state: 'unknown', value: null } : { state: 'known', value: [index % 4, (index + 1) % 3] },
          et: ambiguous ? { state: 'known', value: [1, 1] } : { state: 'unknown', value: null },
          p: ambiguous ? { state: 'known', value: [4, 4] } : { state: 'unknown', value: null } },
        canonical_regulation_score: { state: 'unsupported', value: null },
        score_semantics: { scope: 'source_reported_only', ft_period_verified: false,
          quality: unknown ? 'MISSING_RESULT' : ambiguous ? 'AMBIGUOUS_SOURCE_COMPONENTS' : 'REPORTED_FULL_TIME_UNKNOWN_PERIOD', source_score_state: unknown ? 'unknown' : 'reported' },
        provenance: envelope.provenance };
      rows.push(row); fixtures.push(row);
      const codes = ['KICKOFF_UTC_UNKNOWN', ...(unknown ? ['RESULT_MISSING'] : ['REGULATION_SCORE_UNKNOWN']),
        ...(index < 10 ? ['HALF_TIME_SCORE_MISSING'] : []), ...(ambiguous ? ['EXTRA_TIME_SEMANTICS_UNKNOWN', 'PENALTY_SEMANTICS_UNKNOWN', 'TIED_PENALTY_PAIR'] : [])];
      for (const code of codes) quality.push({ fixture_id: row.id, code, severity: 'NON_FATAL' });
    }
    coverage.push({ stage_id: stage.id, round_id: mockId('round', round + 1), stage_name: stage.name, round_name: `Test round ${round + 1}`, stage_kind: stage.kind,
      fixture_count: rows.length, reported_result_count: rows.filter(f => f.result_availability === 'REPORTED').length,
      unknown_result_count: rows.filter(f => f.result_availability === 'MISSING').length, ambiguous_component_count: rows.filter(f => f.score_semantics.quality === 'AMBIGUOUS_SOURCE_COMPONENTS').length,
      date_min: rows[0].match_date, date_max: rows.at(-1)!.match_date });
  });
  const overview: HistoricalOverview = { ...envelope, summary: { fixture_records: fixtures.length, participant_records: participants.length, source_stages: 3, coverage_records: coverage.length,
    non_fatal_limitations: quality.length, source_reported_ft: 188, unknown_results: 1, ambiguous_components: 2 },
    links: { fixtures: HISTORICAL_SEASON_API + '/fixtures', participants: HISTORICAL_SEASON_API + '/participants', coverage: HISTORICAL_SEASON_API + '/coverage', quality: HISTORICAL_SEASON_API + '/quality' } };
  function page<K extends HistoricalSection>(section: K, query: HistoricalQuery) {
    const filters: HistoricalFilters = Object.fromEntries(['team_id', 'stage_id', 'round_id'].filter(k => query[k as keyof HistoricalFilters] !== undefined).map(k => [k, query[k as keyof HistoricalFilters]]));
    const selected = fixtures.filter(f => (!query.team_id || [f.home.id, f.away.id].includes(query.team_id)) && (!query.stage_id || f.stage.id === query.stage_id) && (!query.round_id || f.round.id === query.round_id));
    const ids = new Set(selected.map(f => f.id));
    const data = section === 'fixtures' ? selected : section === 'participants' ? participants : section === 'coverage' ? coverage : quality.filter(q => ids.has(q.fixture_id)).sort((a, b) => a.fixture_id.localeCompare(b.fixture_id) || a.code.localeCompare(b.code));
    const rows = data.slice(query.offset, query.offset + query.limit);
    return { ...envelope, filters, pagination: { limit: query.limit, offset: query.offset, total: data.length, returned: rows.length,
      next_offset: query.offset + rows.length < data.length ? query.offset + rows.length : null }, [section]: rows,
      ...(section === 'quality' ? { diagnostic_counts: (data as HistoricalQuality[]).reduce<Record<string, number>>((counts, q) => { counts[q.code] = (counts[q.code] ?? 0) + 1; return counts; }, {}) } : {}) } as unknown as HistoricalPage<any, K>;
  }
  const source: HistoricalSource = {
    catalog: async () => [overview], overview: async () => overview,
    participants: async () => page('participants', { limit: 100, offset: 0 }) as Awaited<ReturnType<HistoricalSource['participants']>>,
    coverage: async () => page('coverage', { limit: 100, offset: 0 }) as Awaited<ReturnType<HistoricalSource['coverage']>>,
    fixtures: async q => page('fixtures', q) as Awaited<ReturnType<HistoricalSource['fixtures']>>,
    quality: async q => page('quality', q) as Awaited<ReturnType<HistoricalSource['quality']>>,
  };
  function response(url: URL): unknown {
    if (url.pathname === HISTORICAL_API) return { competitions: [overview] };
    if (url.pathname === HISTORICAL_SEASON_API) return overview;
    const section = url.pathname.slice(HISTORICAL_SEASON_API.length + 1) as HistoricalSection;
    if (!['fixtures', 'participants', 'coverage', 'quality'].includes(section)) throw new Error('Unexpected test API route');
    return page(section, { ...Object.fromEntries(url.searchParams), limit: Number(url.searchParams.get('limit') ?? 50), offset: Number(url.searchParams.get('offset') ?? 0) });
  }
  return { envelope, overview, participants, fixtures, coverage, quality, page, source, response };
}
