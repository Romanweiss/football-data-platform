import type { MessageKey } from './locales';

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string;
// Reviewed StatsBomb contexts from Stage 9A. Presentation only, never new catalog
// entries or a source of IDs. Unknown contexts keep the existing honest ID label.
export function competitionLabel(id: number, t: Translate) {
  return id === 9 ? t('bundesliga') : id === 43 ? t('worldCup') : t('competitionId', { id });
}
export function seasonLabel(competition: number | null, season: number, t: Translate) {
  return competition === 9 && season === 281 ? '2023/24'
    : competition === 43 && season === 106 ? '2022' : t('seasonId', { id: season });
}
