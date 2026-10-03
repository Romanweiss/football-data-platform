import { useEffect, useState } from 'react';
import { ApiFailure, contextPath, fetchAnalysis, fetchCompetitions, fetchLegacyMatch, fetchMatches, fetchSeasons } from './api';
import type { MatchAnalysisResponse } from './types';
import { readRoute, matchPath } from './routes';
import { useResource } from './useResource';
import { ContextSelector } from './components/ContextSelector';
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
export { readRoute } from './routes';

export default function App() { return <I18nProvider><Page /></I18nProvider>; }
function Page() {
  const { t, count } = useI18n();
  const [route, setRoute] = useState(() => readRoute(window.location.pathname));
  const competitionId = 'competitionId' in route ? route.competitionId : null;
  const seasonId = 'seasonId' in route ? route.seasonId : null;
  const selected = route.kind === 'match' ? route.id : null;
  const context = competitionId !== null && seasonId !== null ? { competitionId, seasonId } : null;
  function navigate(path: string, replace = false) {
    window.history[replace ? 'replaceState' : 'pushState']({}, '', path);
    setRoute(readRoute(path));
  }
  useEffect(() => {
    const listener = () => setRoute(readRoute(window.location.pathname));
    window.addEventListener('popstate', listener);
    return () => window.removeEventListener('popstate', listener);
  }, []);
  const catalog = useResource('competitions', fetchCompetitions);
  const seasons = useResource(competitionId === null ? null : `seasons:${competitionId}`, signal => fetchSeasons(competitionId!, signal));
  const list = useResource(context === null ? null : contextPath(context), signal => fetchMatches(context!, signal));
  const analysis = useResource(context === null || selected === null ? null : matchPath(context, selected),
    signal => fetchAnalysis(context!, selected!, signal));
  const legacy = useResource(route.kind === 'legacy' ? `legacy:${route.id}` : null,
    signal => fetchLegacyMatch(route.kind === 'legacy' ? route.id : 0, signal));
  useEffect(() => {
    if (route.kind === 'root' && catalog.state.status === 'ready' && catalog.state.data.length)
      navigate(`/competitions/${catalog.state.data[0].competition_id}`, true);
    if (route.kind === 'competition' && seasons.state.status === 'ready' && seasons.state.data.length)
      navigate(contextPath({ competitionId: route.competitionId, seasonId: seasons.state.data[0].season_id }), true);
    if (route.kind === 'context' && list.state.status === 'ready' && list.state.data.length)
      navigate(matchPath(route, list.state.data[0].match_id), true);
    if (route.kind === 'legacy' && legacy.state.status === 'ready') {
      const match = legacy.state.data;
      navigate(matchPath({ competitionId: match.competition_id, seasonId: match.season_id }, match.match_id), true);
    }
  }, [route, catalog.state, seasons.state, list.state, legacy.state]);
  const competitions = catalog.state.status === 'ready' ? catalog.state.data : [];
  const seasonRows = seasons.state.status === 'ready' ? seasons.state.data : [];
  const contextFailed = catalog.state.status === 'error' || seasons.state.status === 'error' || list.state.status === 'error';
  return <div className="app-shell"><a className="skip-link" href="#analysis">{t('skip')}</a>
    <header className="app-header"><a className="brand" href="/"><span className="brand-mark">T/</span>touchline<span className="brand-sub">{t('intelligence')}</span></a>
      <div className="tournament"><span className="status-dot" />{competitionId === null ? t('competition') : t('competitionId', { id: competitionId })}
        {seasonId !== null && <span>{t('seasonId', { id: seasonId })}</span>}<span className="tag">{t('lab')}</span></div><LanguageSwitcher /></header>
    <main><div className="page-heading"><div><span className="eyebrow">{t('eyebrow')}</span><h1>{t('title')}<span className="accent">.</span></h1>
      <p>{t('subtitle')}</p></div><div className="source-note">{t('source')}<br /><span>{list.state.status === 'ready' ? t('matchCount', { count: count(list.state.data.length) }) : t('platformContext')}</span></div></div>
      <ContextSelector competitions={competitions} seasons={seasonRows} competitionId={competitionId} seasonId={seasonId}
        onCompetition={id => navigate(`/competitions/${id}`)}
        onSeason={id => { if (competitionId !== null) navigate(contextPath({ competitionId, seasonId: id })); }} />
      {catalog.state.status === 'error' ? <ErrorState error={catalog.state.error} retry={catalog.retry} />
        : catalog.state.status === 'loading' ? <LoadingState label={t('loadingCatalog')} />
        : !competitions.length ? <p className="state-panel">{t('noCompetitions')}</p>
        : competitionId !== null && seasons.state.status === 'error' ? <ErrorState error={seasons.state.error} retry={seasons.retry} />
        : competitionId !== null && seasons.state.status === 'ready' && !seasonRows.length ? <p className="state-panel">{t('noSeasons')}</p>
        : context && (list.state.status === 'ready' ? <MatchSelector key={contextPath(context)} matches={list.state.data} selected={selected}
            onSelect={id => navigate(matchPath(context, id))} />
          : list.state.status === 'error' ? <ErrorState error={list.state.error} retry={list.retry} /> : <LoadingState label={t('loadingList')} />)}
      <div id="analysis">
        {route.kind === 'missing' ? <ErrorState error={new ApiFailure(404)} retry={catalog.retry} />
          : route.kind === 'legacy' ? legacy.state.status === 'error' ? <ErrorState error={legacy.state.error} retry={legacy.retry} /> : <LoadingState />
          : contextFailed ? null
          : selected === null ? list.state.status === 'ready' && list.state.data.length === 0 && <p className="state-panel">{t('emptyMatches')}</p>
          : analysis.state.status === 'loading' ? <LoadingState />
          : analysis.state.status === 'error' ? <ErrorState error={analysis.state.error} retry={analysis.retry} />
          : <Analysis key={matchPath(context!, selected)} data={analysis.state.data} />}
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
