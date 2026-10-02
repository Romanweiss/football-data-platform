import { ApiFailure } from '../api';

export function LoadingState({ label = 'Loading match analysis…' }: { label?: string }) {
  return <div className="state-panel" role="status"><span className="loading-dot" />{label}</div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  const status = error instanceof ApiFailure ? error.status : 0;
  const title = status === 404 ? 'Match not found' : status === 503
    ? 'Data service temporarily unavailable' : 'Unable to load this view';
  return <div className="state-panel error-state" role="alert"><h2>{title}</h2>
    <p>{status === 404 ? 'Choose another match from the tournament.' : 'Your data is safe. Please try again in a moment.'}</p>
    <button onClick={retry}>Try again</button></div>;
}
