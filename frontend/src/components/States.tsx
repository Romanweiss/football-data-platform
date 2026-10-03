import { ApiFailure } from '../api';
import { useI18n } from '../i18n';

export function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n();
  return <div className="state-panel" role="status"><span className="loading-dot" />{label ?? t('loadingMatch')}</div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  const { t } = useI18n();
  const status = error instanceof ApiFailure ? error.status : 0;
  const code = error instanceof ApiFailure ? error.code : '';
  const title = t(code === 'competition_not_found' ? 'competitionNotFound' : code === 'season_not_found' ? 'seasonNotFound'
    : code === 'ambiguous_match' ? 'ambiguousMatch' : status === 400 ? 'invalidRequest'
    : status === 404 ? 'notFound' : status === 503 ? 'unavailable' : 'unexpected');
  return <div className="state-panel error-state" role="alert"><h2>{title}</h2>
    <p>{t(status === 404 ? 'chooseOther' : 'retryHint')}</p>
    <button onClick={retry}>{t('retry')}</button></div>;
}
