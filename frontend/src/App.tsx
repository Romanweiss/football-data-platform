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

type Route = { kind: 'root' } | { kind: 'match'; id: number } | { kind: 'missing' };
export function readRoute(path: string): Route {
  if (path === '/') return { kind: 'root' };
  const match = /^\/matches\/([1-9][0-9]*)\/?$/.exec(path);
  return match && Number.isSafeInteger(Number(match[1])) ? { kind: 'match', id: Number(match[1]) } : { kind: 'missing' };
}
type Resource<T> = { status: 'loading' } | { status: 'error'; error: unknown } | { status: 'ready'; data: T };
export default function App() {
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
  return <div className="app-shell"><a className="skip-link" href="#analysis">Skip to match analysis</a>
    <header className="app-header"><a className="brand" href="/"><span className="brand-mark">T/</span>touchline<span className="brand-sub">FOOTBALL INTELLIGENCE</span></a>
      <div className="tournament"><span className="status-dot" />WORLD CUP 2022<span className="tag">MATCH LAB</span></div></header>
    <main><div className="page-heading"><div><span className="eyebrow">THE GAME, IN DETAIL</span><h1>Match analysis<span className="accent">.</span></h1>
      <p>From the first chance to the final whistle.</p></div><div className="source-note">STATS BOMB OPEN DATA<br /><span>64 matches · one tournament</span></div></div>
      {list.status === 'ready' ? <MatchSelector matches={list.data} selected={selected} onSelect={id => navigate(id)} />
        : list.status === 'error' ? <ErrorState error={list.error} retry={() => setListRetry(v => v + 1)} /> : <LoadingState label="Loading tournament matches…" />}
      <div id="analysis">
        {route.kind === 'missing' ? <ErrorState error={new ApiFailure(404)} retry={() => setListRetry(v => v + 1)} />
          : selected === null ? list.status === 'ready' && list.data.length === 0 && <p className="state-panel">No matches available.</p>
          : resource.status === 'loading' ? <LoadingState />
          : resource.status === 'error' ? <ErrorState error={resource.error} retry={() => setRetry(v => v + 1)} />
          : <Analysis key={resource.data.match.match_id} data={resource.data} />}
      </div>
    </main><footer><span>touchline / <strong>Match Lab</strong></span><span>Read-only analytics · StatsBomb Open Data · Local development</span></footer>
  </div>;
}
function Analysis({ data }: { data: MatchAnalysisResponse }) {
  return <><MatchHeader match={data.match} /><TeamComparison teams={data.teams} />
    <div className="visual-grid"><XgRace points={data.xg_race} teams={data.teams} /><ShotMap shots={data.shots} match={data.match} /></div>
    <PlayerTable players={data.players} teams={data.teams} /><ShootoutPanel shootout={data.shootout} match={data.match} /></>;
}
