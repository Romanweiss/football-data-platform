import type { CurrentSource } from './types';
import { createSyntheticLeague } from './synthetic';

function check(signal: AbortSignal) { if (signal.aborted) throw new DOMException('Aborted', 'AbortError'); }
/** Local-only adapter: no HTTP, credentials, cache or provider normalization. */
export const syntheticCurrentSource: CurrentSource = {
  async catalog(signal) {
    check(signal);
    const data = createSyntheticLeague();
    return [{ competition: data.competition, season: data.season, participants: data.participants.length,
      fixtures: data.fixtures.length, dataKind: 'synthetic' }];
  },
  async league(slug, year, signal) {
    check(signal);
    if (slug !== 'uefa-champions-league' || year !== 2026) throw new Error('Unknown demo context');
    return createSyntheticLeague();
  },
};
