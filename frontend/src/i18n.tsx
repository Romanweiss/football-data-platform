import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { dictionaries } from './locales';
import type { Language, MessageKey } from './locales';
import { formatCount, formatDate, formatXg } from './visuals';

export const LANGUAGE_KEY = 'touchline.language';
const locales = { en: 'en-GB', ru: 'ru-RU', es: 'es-ES' };
const isLanguage = (value: string | null): value is Language => value === 'en' || value === 'ru' || value === 'es';
export function resolveLanguage(stored: string | null, browser: readonly string[]): Language {
  if (isLanguage(stored)) return stored;
  for (const tag of browser) {
    const language = tag.toLowerCase().split('-')[0];
    if (isLanguage(language)) return language;
  }
  return 'en';
}
export function translate(language: Language, key: MessageKey, params: Record<string, string | number> = {}): string {
  return dictionaries[language][key].replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`));
}
const stages: Record<string, MessageKey> = { 'Group Stage': 'groupStage', 'Round of 16': 'round16',
  'Quarter-finals': 'quarterFinal', 'Semi-finals': 'semiFinal', '3rd Place Final': 'thirdPlace', Final: 'final' };
const methods: Record<string, MessageKey> = { REGULATION: 'regulation', EXTRA_TIME: 'extraTime', PENALTIES: 'penalties', DRAW: 'draw' };
const outcomes: Record<string, MessageKey> = { Goal: 'goal', Saved: 'saved', 'Off T': 'offTarget', Blocked: 'blocked',
  Post: 'post', Wayward: 'wayward', 'Saved to Post': 'savedPost', 'Saved Off Target': 'savedOffTarget' };
function localeTools(language: Language) {
  const t = (key: MessageKey, params?: Record<string, string | number>) => translate(language, key, params);
  return { language, t, xg: (n: number) => formatXg(n, locales[language]), count: (n: number) => formatCount(n, locales[language]),
    date: (s: string) => formatDate(s, locales[language]),
    stage: (s: string) => stages[s] ? t(stages[s]) : s,
    method: (s: string) => methods[s] ? t(methods[s]) : s,
    outcome: (s: string | null) => s === null ? t('unknownOutcome') : outcomes[s] ? t(outcomes[s]) : s };
}
const I18nContext = createContext({ ...localeTools('en'), setLanguage: (_language: Language) => {} });
export const useI18n = () => useContext(I18nContext);
export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => {
    let stored = null;
    try { stored = localStorage.getItem(LANGUAGE_KEY); } catch { /* Storage may be disabled. */ }
    return resolveLanguage(stored, navigator.languages?.length ? navigator.languages : [navigator.language]);
  });
  useEffect(() => {
    document.documentElement.lang = language;
    document.title = `Touchline — ${translate(language, 'title')}`;
  }, [language]);
  const value = useMemo(() => ({ ...localeTools(language), setLanguage: (next: Language) => {
    setLanguage(next);
    try { localStorage.setItem(LANGUAGE_KEY, next); } catch { /* In-memory switch still works. */ }
  } }), [language]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
export function LanguageSwitcher() {
  const { language, setLanguage, t } = useI18n();
  return <label className="language-switch"><span className="sr-only">{t('language')}</span>
    <select data-testid="language-selector" value={language} onChange={event => {
      if (isLanguage(event.target.value)) setLanguage(event.target.value);
    }}>{(['en', 'ru', 'es'] as const).map(code => <option key={code} value={code}>{code.toUpperCase()}</option>)}</select>
  </label>;
}
