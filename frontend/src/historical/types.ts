/** PET-3B JSON DTOs, not CurrentLeague (no synthetic standings/UTC kickoff). */
export interface HistoricalProvenance {
  provider: 'openfootball'; repository: string; path: '2024-25/uefa.cl.json';
  source_revision: { kind: 'git_commit'; value: string };
  provider_revision: { state: 'unsupported'; value: null };
  source_sha256: string; batch_id: string; semantic_fingerprint: string; license: 'CC0-1.0'; normalized_schema_version: 2;
}
export interface HistoricalParticipant { state: 'known'; id: string; name: string }
export type HistoricalScore = { state: 'known'; value: [number, number] } | { state: 'unknown' | 'unsupported'; value: null };
export interface HistoricalEnvelope {
  competition: { state: 'known'; id: string; slug: 'uefa-champions-league'; name: string };
  season: { state: 'known'; id: string; start_year: 2024; label: '2024/25' };
  provenance: HistoricalProvenance;
  coverage: { source: 'UNKNOWN'; results: 'INCOMPLETE'; claim: string };
  source_capabilities: Record<string, string>;
  capabilities: { fixtures: 'known'; source_reported_results: 'known'; verified_regulation_scores: 'unsupported'; standings: 'unsupported'; events: 'unsupported' };
  freshness: { mode: 'pinned_historical'; last_observed_at: { state: 'unknown'; value: null } };
}
export interface HistoricalOverview extends HistoricalEnvelope {
  summary: { fixture_records: number; participant_records: number; source_stages: number; coverage_records: number;
    non_fatal_limitations: number; source_reported_ft: number; unknown_results: number; ambiguous_components: number };
  links: Record<'fixtures' | 'participants' | 'coverage' | 'quality', string>;
}
export interface HistoricalFixture {
  id: string; match_date: string; kickoff_utc: { state: 'unknown'; value: null };
  home: HistoricalParticipant; away: HistoricalParticipant;
  stage: { state: 'known'; id: string; name: string; kind: 'league_phase' | 'knockout' };
  round: { state: 'known'; id: string; name: string };
  status: 'finished' | 'unknown'; status_origin: string; result_availability: 'REPORTED' | 'MISSING';
  source_reported_score: Record<'ht' | 'ft' | 'et' | 'p', HistoricalScore>;
  canonical_regulation_score: { state: 'unsupported'; value: null };
  score_semantics: { scope: 'source_reported_only'; ft_period_verified: false;
    quality: 'MISSING_RESULT' | 'REPORTED_FULL_TIME_UNKNOWN_PERIOD' | 'AMBIGUOUS_SOURCE_COMPONENTS'; source_score_state: string };
  provenance: HistoricalProvenance;
}
export interface HistoricalCoverage {
  stage_id: string; round_id: string; stage_name: string; round_name: string; stage_kind: 'league_phase' | 'knockout';
  fixture_count: number; reported_result_count: number; unknown_result_count: number; ambiguous_component_count: number;
  date_min: string; date_max: string;
}
export interface HistoricalQuality { fixture_id: string; code: string; severity: 'NON_FATAL' }
export interface HistoricalFilters { team_id?: string; stage_id?: string; round_id?: string }
export interface HistoricalQuery extends HistoricalFilters { limit: number; offset: number }
export interface HistoricalPagination { limit: number; offset: number; total: number; returned: number; next_offset: number | null }
export type HistoricalSection = 'fixtures' | 'participants' | 'coverage' | 'quality';
// PET-3B /coverage replaces the envelope's `coverage` object with row data.
export type HistoricalPage<T, K extends HistoricalSection> = (K extends 'coverage' ? Omit<HistoricalEnvelope, 'coverage'> : HistoricalEnvelope)
  & { filters: HistoricalFilters; pagination: HistoricalPagination } & Record<K, T[]>;
export type FixturePage = HistoricalPage<HistoricalFixture, 'fixtures'>;
export type ParticipantPage = HistoricalPage<HistoricalParticipant, 'participants'>;
export type CoveragePage = HistoricalPage<HistoricalCoverage, 'coverage'>;
export type QualityPage = HistoricalPage<HistoricalQuality, 'quality'> & { diagnostic_counts: Record<string, number> };
export interface HistoricalSource {
  catalog(signal: AbortSignal): Promise<HistoricalOverview[]>;
  overview(signal: AbortSignal): Promise<HistoricalOverview>;
  participants(signal: AbortSignal): Promise<ParticipantPage>;
  coverage(signal: AbortSignal): Promise<CoveragePage>;
  fixtures(query: HistoricalQuery, signal: AbortSignal): Promise<FixturePage>;
  quality(query: HistoricalQuery, signal: AbortSignal): Promise<QualityPage>;
}
export interface HistoricalContext { overview: HistoricalOverview; participants: HistoricalParticipant[]; coverage: HistoricalCoverage[] }
