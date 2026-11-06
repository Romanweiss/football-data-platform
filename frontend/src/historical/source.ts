/** Same-origin, bounded PET-3B reader. No normalization, secrets or demo fallback. */
import { ApiFailure } from '../api';
import type { CoveragePage, FixturePage, HistoricalContext, HistoricalEnvelope, HistoricalFilters, HistoricalOverview,
  HistoricalPage, HistoricalProvenance, HistoricalQuery, HistoricalSection, HistoricalSource, ParticipantPage, QualityPage } from './types';

export const HISTORICAL_API = '/api/v1/competitions/historical';
export const HISTORICAL_SEASON_API = HISTORICAL_API + '/uefa-champions-league/2024';
type Row = Record<string, unknown>;
const invalid = () => new ApiFailure(502, 'invalid_historical_response');
const obj = (v: unknown): v is Row => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max = 512): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const integer = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 && v <= 10000;
export const historicalId = (v: unknown, kind: string): v is string => typeof v === 'string' && new RegExp(`^uefa:${kind}:[0-9a-f]{64}$`).test(v);
const hash = (v: unknown, length = 64): v is string => typeof v === 'string' && new RegExp(`^[0-9a-f]{${length}}$`).test(v);
const missing = (v: unknown, state: string) => obj(v) && v.state === state && v.value === null;
export function historicalDate(v: unknown): v is string {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const date = new Date(v + 'T12:00:00Z');
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === v;
}
function provenance(v: unknown): v is HistoricalProvenance {
  return obj(v) && v.provider === 'openfootball' && v.repository === 'https://github.com/openfootball/football.json'
    && v.path === '2024-25/uefa.cl.json' && v.license === 'CC0-1.0' && v.normalized_schema_version === 2
    && obj(v.source_revision) && v.source_revision.kind === 'git_commit' && hash(v.source_revision.value, 40)
    && missing(v.provider_revision, 'unsupported') && hash(v.batch_id) && hash(v.source_sha256) && hash(v.semantic_fingerprint);
}
export function sameHistoricalContext(a: HistoricalEnvelope, b: Omit<HistoricalEnvelope, 'coverage'> & { coverage?: unknown }) {
  if (a.competition.id !== b.competition.id || a.season.id !== b.season.id
      || !sameProvenance(a.provenance, b.provenance)
      || (obj(b.coverage) && (a.coverage.source !== b.coverage.source || a.coverage.results !== b.coverage.results))) throw invalid();
}
function sameProvenance(a: HistoricalProvenance, b: HistoricalProvenance) {
  return a.provider === b.provider && a.repository === b.repository && a.path === b.path && a.license === b.license
    && a.normalized_schema_version === b.normalized_schema_version && a.source_revision.value === b.source_revision.value
    && a.source_revision.kind === b.source_revision.kind && a.source_sha256 === b.source_sha256 && a.batch_id === b.batch_id
    && a.semantic_fingerprint === b.semantic_fingerprint && a.provider_revision.state === b.provider_revision.state;
}
function envelope(v: unknown, coverageRows = false): boolean {
  if (!obj(v) || !obj(v.competition) || !obj(v.season) || !provenance(v.provenance) || !(coverageRows ? Array.isArray(v.coverage) : obj(v.coverage))
      || !obj(v.capabilities) || !obj(v.source_capabilities) || !obj(v.freshness)) return false;
  return v.competition.state === 'known' && historicalId(v.competition.id, 'competition') && text(v.competition.name)
    && v.competition.slug === 'uefa-champions-league' && v.season.state === 'known' && historicalId(v.season.id, 'season')
    && v.season.start_year === 2024 && v.season.label === '2024/25'
    && (coverageRows || (obj(v.coverage) && v.coverage.source === 'UNKNOWN' && v.coverage.results === 'INCOMPLETE' && text(v.coverage.claim)))
    && v.capabilities.fixtures === 'known' && v.capabilities.source_reported_results === 'known'
    && ['verified_regulation_scores', 'standings', 'events'].every(k => (v.capabilities as Row)[k] === 'unsupported')
    && v.source_capabilities.standings === 'unavailable' && v.source_capabilities.event_coordinates === 'unavailable'
    && v.freshness.mode === 'pinned_historical' && missing(v.freshness.last_observed_at, 'unknown');
}
export function parseHistoricalOverview(v: unknown): HistoricalOverview {
  if (!envelope(v) || !obj(v) || !obj(v.summary) || !obj(v.links)) throw invalid();
  const s = v.summary;
  if (!['fixture_records', 'participant_records', 'source_stages', 'coverage_records', 'non_fatal_limitations',
    'source_reported_ft', 'unknown_results', 'ambiguous_components'].every(k => integer(s[k]))
    || (s.fixture_records as number) < 1 || (s.participant_records as number) < 1
    || (s.source_reported_ft as number) + (s.unknown_results as number) !== s.fixture_records
    || (s.ambiguous_components as number) > (s.fixture_records as number)
    || !['fixtures', 'participants', 'coverage', 'quality'].every(k => (v.links as Row)[k] === HISTORICAL_SEASON_API + '/' + k)) throw invalid();
  return v as unknown as HistoricalOverview;
}
function participant(v: unknown) { return obj(v) && v.state === 'known' && historicalId(v.id, 'participant') && text(v.name, 256); }
function score(v: unknown) {
  return obj(v) && (v.state === 'known' ? Array.isArray(v.value) && v.value.length === 2 && v.value.every(n => integer(n) && n < 1000)
    : ['unknown', 'unsupported'].includes(String(v.state)) && v.value === null);
}
function fixture(v: unknown) {
  if (!obj(v) || !historicalId(v.id, 'fixture') || !historicalDate(v.match_date) || !missing(v.kickoff_utc, 'unknown')
      || !participant(v.home) || !participant(v.away) || !obj(v.stage) || !obj(v.round) || !obj(v.source_reported_score)
      || !obj(v.score_semantics) || !provenance(v.provenance)) return false;
  const scores = v.source_reported_score, semantics = v.score_semantics;
  if (obj(v.home) && obj(v.away) && v.home.id === v.away.id) return false;
  if ((v.result_availability === 'MISSING') !== (semantics.quality === 'MISSING_RESULT')) return false;
  if ((obj(scores.et) && scores.et.state === 'known' || obj(scores.p) && scores.p.state === 'known')
      && semantics.quality !== 'AMBIGUOUS_SOURCE_COMPONENTS') return false;
  return v.stage.state === 'known' && historicalId(v.stage.id, 'stage') && text(v.stage.name)
    && ['league_phase', 'knockout'].includes(String(v.stage.kind)) && v.round.state === 'known'
    && historicalId(v.round.id, 'round') && text(v.round.name) && text(v.status_origin)
    && ['finished', 'unknown'].includes(String(v.status)) && ['REPORTED', 'MISSING'].includes(String(v.result_availability))
    && ['ht', 'ft', 'et', 'p'].every(k => score(scores[k])) && missing(v.canonical_regulation_score, 'unsupported')
    && obj(scores.ft) && ((v.result_availability === 'MISSING' && scores.ft.state === 'unknown' && v.status === 'unknown')
      || (v.result_availability === 'REPORTED' && scores.ft.state === 'known'))
    && semantics.scope === 'source_reported_only' && semantics.ft_period_verified === false
    && ['MISSING_RESULT', 'REPORTED_FULL_TIME_UNKNOWN_PERIOD', 'AMBIGUOUS_SOURCE_COMPONENTS'].includes(String(semantics.quality))
    && text(semantics.source_score_state);
}
function coverage(v: unknown) {
  return obj(v) && historicalId(v.stage_id, 'stage') && historicalId(v.round_id, 'round')
    && text(v.stage_name) && text(v.round_name) && ['league_phase', 'knockout'].includes(String(v.stage_kind))
    && ['fixture_count', 'reported_result_count', 'unknown_result_count', 'ambiguous_component_count'].every(k => integer(v[k]))
    && (v.reported_result_count as number) + (v.unknown_result_count as number) === v.fixture_count
    && historicalDate(v.date_min) && historicalDate(v.date_max) && v.date_min <= v.date_max;
}
function quality(v: unknown) { return obj(v) && historicalId(v.fixture_id, 'fixture') && text(v.code, 100) && v.severity === 'NON_FATAL'; }
const guards = { fixtures: fixture, participants: participant, coverage, quality };
export function parseHistoricalPage<K extends HistoricalSection>(v: unknown, section: K): HistoricalPage<unknown, K> {
  if (!envelope(v, section === 'coverage') || !obj(v) || !obj(v.pagination) || !obj(v.filters)) throw invalid();
  const rows = v[section], p = v.pagination;
  if (!Array.isArray(rows) || rows.length > 100 || !rows.every(guards[section])
    || !['limit', 'offset', 'total', 'returned'].every(k => integer(p[k])) || (p.limit as number) < 1 || (p.limit as number) > 100
    || p.returned !== rows.length || rows.length > (p.limit as number)
    || (p.offset as number) + rows.length > Math.max(p.total as number, p.offset as number)
    || p.next_offset !== ((p.offset as number) + rows.length < (p.total as number) ? (p.offset as number) + rows.length : null)
    || ((p.offset as number) < (p.total as number) && rows.length !== Math.min(p.limit as number, (p.total as number) - (p.offset as number)))) throw invalid();
  for (const [key, value] of Object.entries(v.filters)) if (!['team_id', 'stage_id', 'round_id'].includes(key)
    || !historicalId(value, key === 'team_id' ? 'participant' : key.slice(0, -3))) throw invalid();
  const ids = rows.map((r: Row) => section === 'quality' ? `${r.fixture_id}:${r.code}` : section === 'coverage' ? `${r.stage_id}:${r.round_id}` : r.id);
  if (new Set(ids).size !== rows.length) throw invalid();
  if (section === 'fixtures' && rows.some((r: Row, i) => !sameProvenance(r.provenance as HistoricalProvenance, v.provenance as HistoricalProvenance)
    || (i > 0 && `${rows[i - 1].match_date}:${rows[i - 1].id}` >= `${r.match_date}:${r.id}`))) throw invalid();
  if (section === 'quality' && (!obj(v.diagnostic_counts) || !Object.values(v.diagnostic_counts).every(integer)
    || Object.values(v.diagnostic_counts).reduce<number>((n, x) => n + (x as number), 0) !== p.total)) throw invalid();
  return v as unknown as HistoricalPage<unknown, K>;
}
export function historicalQuery(query: HistoricalQuery): string {
  if (!integer(query.limit) || query.limit < 1 || query.limit > 100 || !integer(query.offset)) throw new ApiFailure(400, 'invalid_request');
  const params = new URLSearchParams();
  for (const k of ['team_id', 'stage_id', 'round_id'] as const) if (query[k] !== undefined) {
    if (!historicalId(query[k], k === 'team_id' ? 'participant' : k.slice(0, -3))) throw new ApiFailure(400, 'invalid_request');
    params.set(k, query[k]!);
  }
  params.set('limit', String(query.limit)); params.set('offset', String(query.offset)); return params.toString();
}
async function get(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { signal, headers: { Accept: 'application/json' }, credentials: 'same-origin', redirect: 'error', cache: 'no-store' });
  if (!response.ok) throw new ApiFailure(response.status, response.status === 503 ? 'historical_not_ready' : 'historical_request_failed');
  const max = 1024 * 1024;
  if (Number(response.headers.get('content-length')) > max) throw invalid();
  const reader = response.body?.getReader();
  let raw: string;
  if (reader) {
    let bytes = 0; const chunks: Uint8Array[] = [];
    try {
      for (;;) { const chunk = await reader.read(); if (chunk.done) break; bytes += chunk.value.length;
        if (bytes > max) { await reader.cancel(); throw invalid(); } chunks.push(chunk.value); }
      const body = new Uint8Array(bytes); let at = 0; for (const chunk of chunks) { body.set(chunk, at); at += chunk.length; }
      raw = new TextDecoder().decode(body);
    } finally { reader.releaseLock(); }
  } else { raw = await response.text(); if (new TextEncoder().encode(raw).length > max) throw invalid(); }
  try { return JSON.parse(raw); } catch { throw invalid(); }
}
async function page<K extends HistoricalSection>(section: K, query: HistoricalQuery, signal: AbortSignal) {
  const data = parseHistoricalPage(await get(`${HISTORICAL_SEASON_API}/${section}?${historicalQuery(query)}`, signal), section);
  const expected = Object.fromEntries(['team_id', 'stage_id', 'round_id'].filter(k => query[k as keyof HistoricalFilters] !== undefined)
    .map(k => [k, query[k as keyof HistoricalFilters]]));
  if (data.pagination.limit !== query.limit || data.pagination.offset !== query.offset
      || JSON.stringify(Object.entries(data.filters).sort()) !== JSON.stringify(Object.entries(expected).sort())) throw invalid();
  if (section === 'fixtures' && (data as FixturePage).fixtures.some(f => (query.team_id && ![f.home.id, f.away.id].includes(query.team_id))
    || (query.stage_id && query.stage_id !== f.stage.id) || (query.round_id && query.round_id !== f.round.id))) throw invalid();
  return data;
}
export const historicalApiSource: HistoricalSource = {
  async catalog(signal) { const data = await get(HISTORICAL_API, signal);
    if (!obj(data) || !Array.isArray(data.competitions) || data.competitions.length > 1) throw invalid();
    return data.competitions.map(parseHistoricalOverview); },
  async overview(signal) { return parseHistoricalOverview(await get(HISTORICAL_SEASON_API, signal)); },
  async participants(signal) { return await page('participants', { limit: 100, offset: 0 }, signal) as ParticipantPage; },
  async coverage(signal) { return await page('coverage', { limit: 100, offset: 0 }, signal) as CoveragePage; },
  async fixtures(query, signal) { return await page('fixtures', query, signal) as FixturePage; },
  async quality(query, signal) { return await page('quality', query, signal) as QualityPage; },
};
export async function loadHistoricalContext(source: HistoricalSource, signal: AbortSignal): Promise<HistoricalContext> {
  const [overview, participants, coverage] = await Promise.all([source.overview(signal), source.participants(signal), source.coverage(signal)]);
  sameHistoricalContext(overview, participants); sameHistoricalContext(overview, coverage);
  if (participants.pagination.next_offset !== null || coverage.pagination.next_offset !== null
    || participants.participants.length !== overview.summary.participant_records || coverage.coverage.length !== overview.summary.coverage_records
    || coverage.coverage.reduce((n, r) => n + r.fixture_count, 0) !== overview.summary.fixture_records
    || coverage.coverage.reduce((n, r) => n + r.reported_result_count, 0) !== overview.summary.source_reported_ft
    || coverage.coverage.reduce((n, r) => n + r.unknown_result_count, 0) !== overview.summary.unknown_results
    || coverage.coverage.reduce((n, r) => n + r.ambiguous_component_count, 0) !== overview.summary.ambiguous_components
    || new Set(coverage.coverage.map(r => r.stage_id)).size !== overview.summary.source_stages) throw invalid();
  return { overview, participants: participants.participants, coverage: coverage.coverage };
}
