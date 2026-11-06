import type { MouseEvent, ReactNode } from 'react';
import { LanguageSwitcher } from '../i18n';
import { useResource } from '../useResource';
import { CURRENT_PATH, CURRENT_UCL_PATH, HISTORICAL_PATH } from '../routes';
import { useHistoricalText } from '../historical/messages';
import { useCurrentText } from './messages';
import { currentFilterSearch, filterCurrentFixtures, readCurrentFilters } from './filters';
import type { CurrentFilters } from './filters';
import type { CurrentLeague, CurrentSource, CurrentStanding } from './types';
import './current.css';

type Navigate = (path: string) => void;
function Link({ href, navigate, children, ...rest }: { href: string; navigate: Navigate; children: ReactNode; className?: string; 'aria-current'?: 'page' }) {
  return <a href={href} {...rest} onClick={(event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault(); navigate(href);
    }
  }}>{children}</a>;
}
export function WorkspaceNav({ current, historical = false, navigate }: { current: boolean; historical?: boolean; navigate: Navigate }) {
  const { ct } = useCurrentText();
  const { ht } = useHistoricalText();
  return <nav className="workspace-nav" aria-label={ct('workspace')}>
    <Link href="/" navigate={navigate} aria-current={!current && !historical ? 'page' : undefined}>{ct('historical')}</Link>
    <Link href={CURRENT_PATH} navigate={navigate} aria-current={current ? 'page' : undefined}>{ct('nav')}</Link>
    <Link href={HISTORICAL_PATH} navigate={navigate} aria-current={historical ? 'page' : undefined}>{ht('title')}</Link>
  </nav>;
}
function State({ error = false, empty = false, retry }: { error?: boolean; empty?: boolean; retry?: () => void }) {
  const { ct } = useCurrentText();
  return <div className="state-panel" role={error ? 'alert' : 'status'}>
    <p>{ct(error ? 'error' : empty ? 'noCompetitions' : 'loading')}</p>
    {error && <button onClick={retry}>{ct('retry')}</button>}
  </div>;
}
export function CurrentCompetitions({ kind, search, navigate, source }: {
  kind: 'current-index' | 'current-league' | 'current-missing'; search: string; navigate: Navigate; source: CurrentSource;
}) {
  const { ct, count } = useCurrentText();
  const { ht } = useHistoricalText();
  const catalog = useResource(kind === 'current-index' ? 'current:catalog' : null, signal => source.catalog(signal));
  const league = useResource(kind === 'current-league' ? 'current:uefa-champions-league:2026' : null,
    signal => source.league('uefa-champions-league', 2026, signal));
  return <div className="app-shell current-shell"><a className="skip-link" href="#current-content">{ct('skip')}</a>
    <header className="app-header"><Link href="/" navigate={navigate} className="brand"><span className="brand-mark">T/</span>touchline</Link>
      <span className="current-prototype">{ct('prototype')}</span><LanguageSwitcher /></header>
    <WorkspaceNav current navigate={navigate} />
    <main id="current-content" tabIndex={-1}>
      <aside className="current-demo" aria-label={ct('demo')}><strong>{ct('demo')}</strong><p>{ct('demoNote')}</p></aside>
      {kind === 'current-index' ? <>
        <p><Link href={HISTORICAL_PATH} navigate={navigate}>{ht('catalogLink')}</Link></p>
        <div className="page-heading"><div><span className="eyebrow">{ct('eyebrow')}</span><h1>{ct('title')}<span className="accent">.</span></h1><p>{ct('intro')}</p></div></div>
        {catalog.state.status === 'loading' ? <State /> : catalog.state.status === 'error' ? <State error retry={catalog.retry} />
          : !catalog.state.data.length ? <State empty /> : <div className="current-catalog">{catalog.state.data.map(card =>
            <article className="panel current-card" key={card.season.id}><span className="eyebrow">{ct('league')} · {ct('demo')}</span>
              <h2>{card.competition.name}</h2><p className="current-season">{card.season.label}</p>
              <p>{count(card.participants)} {ct('teams')} · {count(card.fixtures)} {ct('matches')}</p>
              <Link href={CURRENT_UCL_PATH} navigate={navigate} className="current-cta">{ct('open')} <span aria-hidden="true">↗</span></Link>
            </article>)}</div>}
      </> : kind === 'current-missing' ? <><h1>{ct('missing')}</h1><Link href={CURRENT_PATH} navigate={navigate}>{ct('back')}</Link></>
        : league.state.status === 'loading' ? <State /> : league.state.status === 'error' ? <State error retry={league.retry} />
        : <League data={league.state.data} search={search} navigate={navigate} />}
    </main><footer><span>touchline / <strong>{ct('nav')}</strong></span><span>{ct('footer')}</span></footer>
  </div>;
}
function League({ data, search, navigate }: { data: CurrentLeague; search: string; navigate: Navigate }) {
  const { ct, count, language } = useCurrentText();
  const { filters, invalid } = readCurrentFilters(search, data.participants.map(t => t.id));
  const change = (next: Partial<CurrentFilters>) => navigate(CURRENT_UCL_PATH + currentFilterSearch({ ...filters, ...next }));
  const fixtures = filterCurrentFixtures(data.fixtures, filters);
  const datesInvalid = !!filters.from && !!filters.to && filters.from > filters.to;
  const teams = new Map(data.participants.map(t => [t.id, t]));
  const locales = { en: 'en-GB', ru: 'ru-RU', es: 'es-ES' };
  const date = (value: string) => new Intl.DateTimeFormat(locales[language], { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value));
  const time = (value: string) => new Intl.DateTimeFormat(locales[language], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC' }).format(new Date(value));
  const grouped = new Map<string, typeof fixtures>();
  for (const fixture of fixtures) {
    const key = `${fixture.round}|${fixture.kickoff.slice(0, 10)}`;
    grouped.set(key, [...(grouped.get(key) ?? []), fixture]);
  }
  return <div data-testid="current-league">
    <Link href={CURRENT_PATH} navigate={navigate} className="current-back">← {ct('back')}</Link>
    <section className="current-hero" aria-labelledby="current-title"><div><span className="eyebrow">{ct('league')} · {data.season.label}</span>
      <h1 id="current-title">{data.competition.name}<span className="accent">.</span></h1>
      <p>{ct('scope')}</p><span className="current-season">{data.season.label}</span></div>
      <dl className="current-stats">{[[ct('teams'), data.participants.length], [ct('matches'), data.fixtures.length],
        [ct('played'), data.fixtures.filter(f => f.status === 'FINISHED').length], [ct('rounds'), 8]].map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{count(Number(value))}</dd></div>)}</dl>
    </section>
    <div className="current-tabs" role="tablist" aria-label={ct('view')}>
      {(['fixtures', 'standings'] as const).map((view, i) => <button key={view} id={`current-tab-${view}`} role="tab"
        type="button" aria-selected={filters.view === view} tabIndex={filters.view === view ? 0 : -1}
        aria-controls="current-results" onClick={() => change({ view })} onKeyDown={event => {
          const target = event.key === 'Home' ? 'fixtures' : event.key === 'End' ? 'standings'
            : event.key === 'ArrowRight' || event.key === 'ArrowLeft' ? (i === 0 ? 'standings' : 'fixtures') : null;
          if (target) { event.preventDefault(); change({ view: target }); document.getElementById(`current-tab-${target}`)?.focus(); }
        }}>{ct(view)}</button>)}
    </div>
    <section className="panel current-results" id="current-results" role="tabpanel" aria-labelledby={`current-tab-${filters.view}`}>
      <div className="current-filters"><label>{ct('team')}<select value={filters.team} onChange={e => change({ team: e.target.value })}>
        <option value="">{ct('allTeams')}</option>{data.participants.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select></label>
        {filters.view === 'fixtures' && <><label>{ct('round')}<select value={filters.round} onChange={e => change({ round: e.target.value })}>
          <option value="">{ct('allRounds')}</option>{Array.from({ length: 8 }, (_, i) => <option key={i} value={i + 1}>{ct('roundN', { round: i + 1 })}</option>)}
        </select></label><label>{ct('from')}<input type="date" value={filters.from} onChange={e => change({ from: e.target.value })} /></label>
          <label>{ct('to')}<input type="date" value={filters.to} onChange={e => change({ to: e.target.value })} /></label></>}
        <button className="current-reset" onClick={() => navigate(CURRENT_UCL_PATH + currentFilterSearch({ view: filters.view, team: '', round: '', from: '', to: '' }))}>{ct('reset')}</button>
      </div>
      {invalid && <p className="coverage-note" role="status">{ct('invalid')}</p>}
      {filters.view === 'fixtures' ? <><div className="current-list-meta"><h2>{ct('fixtures')}</h2><p aria-live="polite" data-testid="current-fixture-count">{ct('shown', { shown: count(fixtures.length), total: count(data.fixtures.length) })}</p></div>
        <p className="chart-note">{ct('timezone')}</p>
        {datesInvalid && <p className="coverage-note" role="alert">{ct('dateOrder')}</p>}
        {!fixtures.length && <p className="state-panel" role="status">{ct('empty')}</p>}
        {[...grouped.entries()].map(([key, rows]) => <section className="current-matchday" key={key} aria-label={`${ct('roundN', { round: rows[0].round })} · ${date(rows[0].kickoff)}`}>
          <h3>{ct('roundN', { round: rows[0].round })}<span>{date(rows[0].kickoff)}</span></h3>
          <div className="current-fixtures">{rows.map(row => <article className="current-fixture" key={row.id} data-testid="current-fixture" data-status={row.status}>
            <div className="current-fixture-state"><span className={`current-status ${row.status.toLowerCase()}`}>{ct(row.status === 'FINISHED' ? 'finished' : 'timed')}</span>
              <time dateTime={row.kickoff}>{time(row.kickoff)} {ct('utc')}</time></div>
            <div className="current-team-line"><span className="current-team-name"><span className="current-badge" aria-hidden="true">{teams.get(row.homeId)?.shortName}</span>{teams.get(row.homeId)?.name}</span><strong>{row.score?.home ?? '—'}</strong></div>
            <div className="current-team-line"><span className="current-team-name"><span className="current-badge" aria-hidden="true">{teams.get(row.awayId)?.shortName}</span>{teams.get(row.awayId)?.name}</span><strong>{row.score?.away ?? '—'}</strong></div>
          </article>)}</div>
        </section>)}
      </> : <Standings data={data} team={filters.team} />}
    </section>
    <p className="current-freshness">{ct('fixedClock', { date: date(data.freshness.asOf) })}</p>
    <details className="current-method"><summary>{ct('method')}</summary><p>{ct('ranking')}</p><p>{ct('noEvents')}</p></details>
  </div>;
}
function Standings({ data, team }: { data: CurrentLeague; team: string }) {
  const { ct, count, language } = useCurrentText();
  const teams = new Map(data.participants.map(t => [t.id, t]));
  const rows = data.standings.filter(row => !team || row.participantId === team);
  const labels = language === 'ru' ? ['И', 'В', 'Н', 'П', 'ЗГ', 'ПГ', 'РГ', 'О']
    : language === 'es' ? ['PJ', 'G', 'E', 'P', 'GF', 'GC', 'DG', 'Pts'] : ['P', 'W', 'D', 'L', 'GF', 'GA', 'GD', 'Pts'];
  const fields = ['played', 'won', 'drawn', 'lost', 'goalsFor', 'goalsAgainst', 'goalDifference', 'points'] as const;
  const full = ['played', 'won', 'drawn', 'lost', 'gf', 'ga', 'gd', 'points'] as const;
  const zone = (r: CurrentStanding) => ct(r.zone === 'top8' ? 'top8' : r.zone === 'playoff' ? 'playoff' : 'outside');
  return <><div className="current-list-meta"><h2>{ct('standings')}</h2><p aria-live="polite">{ct('rows', { shown: count(rows.length), total: count(data.standings.length) })}</p></div>
    <p className="chart-note">{ct('tableScope')}</p>
    <ul className="current-zones">{(['top8', 'playoff', 'outside'] as const).map(z => <li key={z} data-zone={z}><span />{ct(z)}</li>)}</ul>
    <p className="current-scroll-note">{ct('scroll')}</p>
    {!rows.length ? <p className="state-panel" role="status">{ct('emptyTable')}</p> : <div className="current-table-scroll" role="region" aria-label={ct('caption')} tabIndex={0}>
      <table className="current-standings"><caption>{ct('caption')}</caption><thead><tr><th scope="col" aria-label={ct('position')}>#</th><th scope="col">{ct('team')}</th>
        {labels.map((label, i) => <th key={full[i]} scope="col" aria-label={ct(full[i])}><abbr title={ct(full[i])}>{label}</abbr></th>)}
      </tr></thead><tbody>{rows.map(row => <tr key={row.participantId} data-zone={row.zone} data-testid="current-standing">
        <td className="current-rank"><span>{row.position}</span><span className="sr-only">{zone(row)}</span></td>
        <th scope="row"><span className="current-team-name"><span className="current-badge" aria-hidden="true">{teams.get(row.participantId)?.shortName}</span>{teams.get(row.participantId)?.name}</span></th>
        {fields.map(field => <td key={field} className={field === 'points' ? 'current-points' : undefined}>{row[field] > 0 && field === 'goalDifference' ? '+' : ''}{count(row[field])}</td>)}
      </tr>)}</tbody></table>
    </div>}
  </>;
}
