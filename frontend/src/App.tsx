import { useEffect, useState } from 'react';
import { ApiFailure, fetchAnalysis, fetchMatches } from './api';
import type { MatchAnalysisResponse, MatchOverview } from './types';
import { MatchSelector } from './components/MatchSelector';
import { MatchHeader } from './components/MatchHeader';
import { TeamComparison } from './components/TeamComparison';
import { XgRace } from './components/XgRace';
import { ShotMap } from './components/ShotMap';
import { PlayerTable } from './components/PlayerTable';
import { ShootoutPanel } from './components/ShootoutPanel';
import { ErrorState, LoadingState } from './components/States';
import { I18nProvider, LanguageSwitcher, useI18n } from './i18n';
import { useShotInteraction } from './shotInteraction';
import { ShotDetails } from './components/ShotDetails';

type Route = { kind: 'root' } | { kind: 'match'; id: number } | { kind: 'missing' };
export function readRoute(path: string): Route {
  if (path === '/') return { kind: 'root' };
  const match = /^\/matches\/([1-9][0-9]*)\/?$/.exec(path);
  return match && Number.isSafeInteger(Number(match[1])) ? { kind: 'match', id: Number(match[1]) } : { kind: 'missing' };
}
type Resource<T> = { status: 'loading' } | { status: 'error'; error: unknown } | { status: 'ready'; data: T };
export default function App() {
  return <I18nProvider><Page /></I18nProvider>;
}
function Page() {
  const { t } = useI18n();
  const [route, setRoute] = useState(() => readRoute(window.location.pathname));
  const [list, setList] = useState<Resource<MatchOverview[]>>({ status: 'loading' });
  const [analysis, setAnalysis] = useState<{ id: number; resource: Resource<MatchAnalysisResponse> } | null>(null);
  const [listRetry, setListRetry] = useState(0);
  const [retry, setRetry] = useState(0);
  const selected = route.kind === 'match' ? route.id : null;
  function navigate(id: number, replace = false) {
    window.history[replace ? 'replaceState' : 'pushState']({}, '', `/matches/${id}`);
    setRoute({ kind: 'match', id });
  }
  useEffect(() => {
    const listener = () => setRoute(readRoute(window.location.pathname));
    window.addEventListener('popstate', listener);
    return () => window.removeEventListener('popstate', listener);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setList({ status: 'loading' });
    void fetchMatches(controller.signal).then(data => {
      if (!controller.signal.aborted) setList({ status: 'ready', data });
    }).catch(error => { if (!controller.signal.aborted) setList({ status: 'error', error }); });
    return () => controller.abort();
  }, [listRetry]);
  useEffect(() => {
    if (route.kind === 'root' && list.status === 'ready' && list.data.length > 0) navigate(list.data[0].match_id, true);
  }, [route, list]);
  useEffect(() => {
    if (selected === null) return;
    const controller = new AbortController();
    setAnalysis({ id: selected, resource: { status: 'loading' } });
    void fetchAnalysis(selected, controller.signal).then(data => {
      if (!controller.signal.aborted) setAnalysis({ id: selected, resource: { status: 'ready', data } });
    }).catch(error => { if (!controller.signal.aborted) setAnalysis({ id: selected, resource: { status: 'error', error } }); });
    return () => controller.abort();
  }, [selected, retry]);
  const resource = analysis?.id === selected ? analysis.resource : { status: 'loading' as const };
  return <div className="app-shell"><a className="skip-link" href="#analysis">{t('skip')}</a>
    <header className="app-header"><a className="brand" href="/"><span className="brand-mark">T/</span>touchline<span className="brand-sub">{t('intelligence')}</span></a>
      <div className="tournament"><span className="status-dot" />{t('tournament')}<span className="tag">{t('lab')}</span></div><LanguageSwitcher /></header>
    <main><div className="page-heading"><div><span className="eyebrow">{t('eyebrow')}</span><h1>{t('title')}<span className="accent">.</span></h1>
      <p>{t('subtitle')}</p></div><div className="source-note">{t('source')}<br /><span>{t('tournamentNote')}</span></div></div>
      {list.status === 'ready' ? <MatchSelector matches={list.data} selected={selected} onSelect={id => navigate(id)} />
        : list.status === 'error' ? <ErrorState error={list.error} retry={() => setListRetry(v => v + 1)} /> : <LoadingState label={t('loadingList')} />}
      <div id="analysis">
        {route.kind === 'missing' ? <ErrorState error={new ApiFailure(404)} retry={() => setListRetry(v => v + 1)} />
          : selected === null ? list.status === 'ready' && list.data.length === 0 && <p className="state-panel">{t('emptyMatches')}</p>
          : resource.status === 'loading' ? <LoadingState />
          : resource.status === 'error' ? <ErrorState error={resource.error} retry={() => setRetry(v => v + 1)} />
          : <Analysis key={resource.data.match.match_id} data={resource.data} />}
      </div>
    </main><footer><span>touchline / <strong>{t('lab')}</strong></span><span>{t('footer')}</span></footer>
  </div>;
}
export function Analysis({ data }: { data: MatchAnalysisResponse }) {
  const interaction = useShotInteraction();
  return <div onKeyDown={event => { if (event.key === 'Escape' && !event.defaultPrevented) interaction.clear(); }}><MatchHeader match={data.match} /><TeamComparison teams={data.teams} />
    <div className="visual-grid"><XgRace points={data.xg_race} teams={data.teams} shots={data.shots} interaction={interaction} /><ShotMap shots={data.shots} match={data.match} interaction={interaction} /></div>
    <ShotDetails shots={data.shots} points={data.xg_race} interaction={interaction} />
    <PlayerTable players={data.players} teams={data.teams} /><ShootoutPanel shootout={data.shootout} match={data.match} /></div>;
}
