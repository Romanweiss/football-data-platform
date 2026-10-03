import { useEffect, useState } from 'react';

export type Resource<T> = { status: 'loading' } | { status: 'error'; error: unknown } | { status: 'ready'; data: T };
// Keys include the full context. Late responses cannot leak into another context,
// even when an underlying transport ignores cancellation.
export function useResource<T>(key: string | null, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [record, setRecord] = useState<{ key: string; state: Resource<T> } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    setRecord({ key, state: { status: 'loading' } });
    void fetcher(controller.signal).then(data => {
      if (!controller.signal.aborted) setRecord({ key, state: { status: 'ready', data } });
    }).catch(error => {
      if (!controller.signal.aborted) setRecord({ key, state: { status: 'error', error } });
    });
    return () => controller.abort();
    // The request identity is the key, not a render-created callback or locale.
  }, [key, attempt]);
  const state: Resource<T> = key !== null && record?.key === key ? record.state : { status: 'loading' };
  return { state, retry: () => setAttempt(n => n + 1) };
}
