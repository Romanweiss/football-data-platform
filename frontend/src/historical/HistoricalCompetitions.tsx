import type { MouseEvent, ReactNode } from 'react';
import { ApiFailure } from '../api';
import { LanguageSwitcher } from '../i18n';
import { WorkspaceNav } from '../current/CurrentCompetitions';
import { HISTORICAL_PATH, HISTORICAL_UCL_PATH } from '../routes';
import { useResource } from '../useResource';
import { historicalSearch, readHistoricalSelection } from './filters';
import type { HistoricalSelection, HistoricalView } from './filters';
import { loadHistoricalContext, sameHistoricalContext } from './source';
import { useHistoricalText } from './messages';
import type { HistoricalContext, HistoricalFixture, HistoricalOverview, HistoricalPagination, HistoricalSource } from './types';
import '../current/current.css';
import './historical.css';

type Navigate = (path: string) => void;
function focusResults() { document.getElementById('historical-results')?.focus({ preventScroll: true }); }
function Link({ href, navigate, children, className }: { href: string; navigate: Navigate; children: ReactNode; className?: string }) {
  return <a href={href} className={className} onClick={(e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) { e.preventDefault(); navigate(href); }
  }}>{children}</a>;
}
function State({ error, retry, empty = false }: { error?: unknown; retry?: () => void; empty?: boolean }) {
  const { ht } = useHistoricalText();
  const code = error instanceof ApiFailure ? error.status : 0;
  return <div className="state-panel" role={error ? 'alert' : 'status'}>
    <p>{ht(error ? code === 503 ? 'unavailable' : code === 404 ? 'notFound' : code === 400 ? 'badRequest' : 'error' : empty ? 'empty' : 'loading')}</p>
    {!!error && retry && <button type="button" onClick={retry}>{ht('retry')}</button>}
  </div>;
}
function Badges() {
  const { ht } = useHistoricalText();
  return <div className="historical-badges"><span>OpenFootball</span><span>{ht('historical')}</span><span>2024/25</span>
    <span className="historical-warning">{ht('incomplete')}</span><span>{ht('resultsOnly')}</span></div>;
}
export function HistoricalCompetitions({ kind, search, navigate, source }: {
  kind: 'historical-index' | 'historical-league' | 'historical-missing'; search: string; navigate: Navigate; source: HistoricalSource;
}) {
  const { ht } = useHistoricalText();
  const catalog = useResource(kind === 'historical-index' ? 'historical:catalog' : null, signal => source.catalog(signal));
  const context = useResource(kind === 'historical-league' ? 'historical:2024:context' : null, signal => loadHistoricalContext(source, signal));
  return <div className="app-shell current-shell historical-shell"><a className="skip-link" href="#historical-content">{ht('skip')}</a>
    <header className="app-header"><Link href="/" navigate={navigate} className="brand"><span className="brand-mark">T/</span>touchline</Link><LanguageSwitcher /></header>
    <WorkspaceNav current={false} historical navigate={navigate} />
    <main id="historical-content" tabIndex={-1}>
      {kind === 'historical-index' ? <><div className="page-heading"><div><span className="eyebrow">OpenFootball · CC0-1.0</span>
        <h1>{ht('title')}<span className="accent">.</span></h1><p>{ht('intro')}</p></div></div>
        {catalog.state.status === 'loading' ? <State /> : catalog.state.status === 'error' ? <State error={catalog.state.error} retry={catalog.retry} />
          : !catalog.state.data.length ? <p className="state-panel">{ht('emptyCatalog')}</p>
          : <div className="current-catalog">{catalog.state.data.map(card => <article className="panel current-card" key={card.season.id}>
            <Badges /><h2>{card.competition.name}</h2><p>{card.season.label}</p><p>{ht('scope')}</p>
            <p>{card.summary.fixture_records} {ht('matches')} · {card.summary.participant_records} {ht('teams')}</p>
            <Link href={HISTORICAL_UCL_PATH} navigate={navigate} className="current-cta">{ht('open')}</Link>
          </article>)}</div>}</>
        : kind === 'historical-missing' ? <><State error={new ApiFailure(404)} /><Link href={HISTORICAL_PATH} navigate={navigate}>{ht('back')}</Link></>
        : context.state.status === 'loading' ? <State /> : context.state.status === 'error' ? <State error={context.state.error} retry={context.retry} />
        : <League context={context.state.data} source={source} search={search} navigate={navigate} />}
    </main><footer><span>touchline / {ht('title')}</span><span>{ht('footer')}</span></footer>
  </div>;
}
function League({ context, source, search, navigate }: { context: HistoricalContext; source: HistoricalSource; search: string; navigate: Navigate }) {
  const { ht, count, language, diagnostic } = useHistoricalText();
  const selection = readHistoricalSelection(search, context);
  const dataKey = selection ? `${context.overview.provenance.batch_id}:${historicalSearch(selection)}` : null;
  const fixtures = useResource(selection?.view === 'fixtures' ? 'historical:fixtures:' + dataKey : null, async signal => {
    const page = await source.fixtures(selection!, signal); sameHistoricalContext(context.overview, page); return page;
  });
  const quality = useResource(selection?.view === 'quality' ? 'historical:quality:' + dataKey : null, async signal => {
    const page = await source.quality(selection!, signal); sameHistoricalContext(context.overview, page); return page;
  });
  const change = (next: Partial<HistoricalSelection>) => navigate(HISTORICAL_UCL_PATH + historicalSearch({ ...selection!, offset: 0, ...next }));
  const summary = context.overview.summary;
  const locales = { en: 'en-GB', ru: 'ru-RU', es: 'es-ES' };
  const date = (s: string) => new Intl.DateTimeFormat(locales[language], { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(s + 'T12:00:00Z'));
  const stages = [...new Map(context.coverage.map(r => [r.stage_id, r.stage_name])).entries()];
  const rounds = context.coverage.filter(r => !selection?.stage_id || r.stage_id === selection.stage_id);
  const views: HistoricalView[] = ['fixtures', 'participants', 'quality', 'capabilities'];
  return <div data-testid="historical-league">
    <Link href={HISTORICAL_PATH} navigate={navigate} className="current-back">← {ht('back')}</Link>
    <section className="current-hero" aria-labelledby="historical-title"><div><Badges />
      <h1 id="historical-title">{context.overview.competition.name}<span className="accent">.</span></h1><p>{ht('scope')}</p></div>
      <dl className="current-stats">{[[ht('matches'), summary.fixture_records], [ht('teams'), summary.participant_records],
        [ht('reported'), summary.source_reported_ft], [ht('missing'), summary.unknown_results]].map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{count(Number(value))}</dd></div>)}</dl>
    </section>
    {!selection ? <><State error={new ApiFailure(400)} /><Link href={HISTORICAL_UCL_PATH} navigate={navigate}>{ht('resetUrl')}</Link></> : <>
      <div role="tablist" aria-label={ht('view')} className="current-tabs historical-tabs">{views.map((view, i) =>
        <button key={view} type="button" role="tab" id={`historical-tab-${view}`} aria-selected={selection.view === view}
          tabIndex={selection.view === view ? 0 : -1} aria-controls="historical-results" onClick={() => change({ view })} onKeyDown={e => {
            const index = e.key === 'Home' ? 0 : e.key === 'End' ? views.length - 1 : e.key === 'ArrowRight' ? (i + 1) % views.length
              : e.key === 'ArrowLeft' ? (i + views.length - 1) % views.length : -1;
            if (index >= 0) { e.preventDefault(); change({ view: views[index] }); document.getElementById(`historical-tab-${views[index]}`)?.focus(); }
          }}>{ht(view)}</button>)}</div>
      <section id="historical-results" role="tabpanel" tabIndex={-1} aria-labelledby={`historical-tab-${selection.view}`} className="panel current-results">
        {(selection.view === 'fixtures' || selection.view === 'quality') && <div className="current-filters historical-filters">
          <label>{ht('team')}<select value={selection.team_id ?? ''} onChange={e => change({ team_id: e.target.value || undefined })}>
            <option value="">{ht('allTeams')}</option>{[...context.participants].sort((a, b) => a.name.localeCompare(b.name, language)).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label>{ht('stage')}<select value={selection.stage_id ?? ''} onChange={e => change({ stage_id: e.target.value || undefined, round_id: undefined })}>
            <option value="">{ht('allStages')}</option>{stages.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select></label>
          <label>{ht('round')}<select value={selection.round_id ?? ''} onChange={e => change({ round_id: e.target.value || undefined })}>
            <option value="">{ht('allRounds')}</option>{rounds.map(r => <option key={r.round_id} value={r.round_id}>{r.round_name}</option>)}
          </select></label>
          <label>{ht('pageSize')}<select value={selection.limit} onChange={e => change({ limit: Number(e.target.value) })}>
            {[25, 50, 100].map(n => <option key={n} value={n}>{n}</option>)}
          </select></label><button type="button" onClick={() => change({ team_id: undefined, stage_id: undefined, round_id: undefined })}>{ht('reset')}</button>
        </div>}
        {selection.view === 'fixtures' ? <><p className="historical-caution">{ht('scoreNote')}</p><p className="chart-note">{ht('dateNote')}</p>
          {fixtures.state.status === 'loading' ? <State /> : fixtures.state.status === 'error' ? <State error={fixtures.state.error} retry={fixtures.retry} /> : <>
            <Pager page={fixtures.state.data.pagination} change={change} />
            {!fixtures.state.data.fixtures.length ? <State empty /> : <div className="current-fixtures">{fixtures.state.data.fixtures.map(f =>
              <Fixture key={f.id} fixture={f} date={date(f.match_date)} onTeam={team_id => { change({ team_id }); focusResults(); }} />)}</div>}
          </>}</>
          : selection.view === 'participants' ? <><p>{ht('participantNote')}</p><div className="historical-participants">{[...context.participants]
            .sort((a, b) => a.name.localeCompare(b.name, language)).map(p => <button type="button" key={p.id} onClick={() => { change({ view: 'fixtures', team_id: p.id, stage_id: undefined, round_id: undefined }); focusResults(); }}>{p.name}</button>)}</div></>
          : selection.view === 'quality' ? <><p>{ht('qualityNote')}</p>{quality.state.status === 'loading' ? <State />
            : quality.state.status === 'error' ? <State error={quality.state.error} retry={quality.retry} /> : <>
              <dl className="historical-diagnostics">{Object.entries(quality.state.data.diagnostic_counts).map(([code, n]) => <div key={code}><dt>{diagnostic(code)}<br /><code>{code}</code></dt><dd>{count(n)}</dd></div>)}</dl>
              <Pager page={quality.state.data.pagination} change={change} />
              {!quality.state.data.quality.length ? <State empty /> : <ul className="historical-quality">{quality.state.data.quality.map(q =>
                <li key={q.fixture_id + q.code}><strong>{diagnostic(q.code)}</strong><code>{q.code}</code><span>{q.severity}</span><code>{q.fixture_id}</code></li>)}</ul>}
            </>}</> : <><h2>{ht('capabilities')}</h2><p>{ht('noStandings')}</p><p>{ht('noEvents')}</p><p>{ht('noAnalytics')}</p>
              <h3>{ht('coverage')}</h3><ul className="historical-coverage">{context.coverage.map(r => <li key={r.round_id}>
                <strong>{r.stage_name} · {r.round_name}</strong><span>{count(r.fixture_count)} {ht('fixturesCount')} · {count(r.unknown_result_count)} {ht('unknownCount')}</span>
                <span>{date(r.date_min)} — {date(r.date_max)}</span></li>)}</ul></>}
      </section></>}
    <Provenance overview={context.overview} />
  </div>;
}
function Pager({ page, change }: { page: HistoricalPagination; change: (next: Partial<HistoricalSelection>) => void }) {
  const { ht, count } = useHistoricalText();
  const turnPage = (offset: number) => { change({ offset }); focusResults(); };
  return <div className="historical-pagination"><p role="status" data-testid="historical-count">{ht('shown', { shown: count(page.returned), total: count(page.total), offset: count(page.offset) })}</p>
    <div><button type="button" disabled={page.offset === 0} onClick={() => turnPage(Math.max(0, page.offset - page.limit))}>{ht('previous')}</button>
      <button type="button" disabled={page.next_offset === null} onClick={() => turnPage(page.next_offset!)}>{ht('next')}</button></div></div>;
}
function Fixture({ fixture: f, date, onTeam }: { fixture: HistoricalFixture; date: string; onTeam: (id: string) => void }) {
  const { ht } = useHistoricalText();
  const ft = f.source_reported_score.ft;
  return <article className="current-fixture historical-fixture" data-testid="historical-fixture" data-quality={f.score_semantics.quality}>
    <div className="historical-fixture-heading"><time dateTime={f.match_date}>{date}</time><span>{f.stage.name} · {f.round.name}</span></div>
    <p className="historical-score-label">{ht('sourceFT')}</p>
    <div className="current-team-line"><button type="button" className="historical-team" onClick={() => onTeam(f.home.id)}>{f.home.name}</button><strong>{ft.state === 'known' ? ft.value[0] : '—'}</strong></div>
    <div className="current-team-line"><button type="button" className="historical-team" onClick={() => onTeam(f.away.id)}>{f.away.name}</button><strong>{ft.state === 'known' ? ft.value[1] : '—'}</strong></div>
    {f.result_availability === 'MISSING' && <p className="historical-caution">{ht('unknown')}</p>}
    {f.score_semantics.quality === 'AMBIGUOUS_SOURCE_COMPONENTS' && <p className="historical-caution">{ht('ambiguous')}</p>}
    <details><summary>{ht('raw')}</summary><dl>{(['ht', 'ft', 'et', 'p'] as const).map(k => <div key={k}><dt>{k.toUpperCase()}</dt><dd>{f.source_reported_score[k].state === 'known' ? f.source_reported_score[k].value!.join(' – ') : 'UNKNOWN'}</dd></div>)}</dl>
      <p>{f.result_availability === 'MISSING' ? ht('unknownNote') : f.score_semantics.quality === 'AMBIGUOUS_SOURCE_COMPONENTS' ? ht('ambiguousNote') : ht('scoreNote')}</p>
      <code>{f.id}</code></details>
  </article>;
}
function Provenance({ overview }: { overview: HistoricalOverview }) {
  const { ht } = useHistoricalText();
  const p = overview.provenance;
  return <details className="current-method historical-provenance"><summary>{ht('method')}</summary><p>{ht('pinned')}</p><p>{ht('noAnalytics')}</p>
    <dl>{[[ht('source'), p.repository + '/' + p.path], [ht('revision'), p.source_revision.value], [ht('hash'), p.source_sha256],
      [ht('batch'), p.batch_id], [ht('fingerprint'), p.semantic_fingerprint], [ht('license'), p.license], [ht('limitations'), overview.summary.non_fatal_limitations]].map(([label, value]) =>
      <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></details>;
}
