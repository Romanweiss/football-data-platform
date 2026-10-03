import { ApiFailure } from '../api';
import { useI18n } from '../i18n';

export function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n();
  return <div className="state-panel" role="status"><span className="loading-dot" />{label ?? t('loadingMatch')}</div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  const { t } = useI18n();
  const status = error instanceof ApiFailure ? error.status : 0;
  const title = t(status === 404 ? 'notFound' : status === 503 ? 'unavailable' : 'unexpected');
  return <div className="state-panel error-state" role="alert"><h2>{title}</h2>
    <p>{t(status === 404 ? 'chooseOther' : 'retryHint')}</p>
    <button onClick={retry}>{t('retry')}</button></div>;
}
