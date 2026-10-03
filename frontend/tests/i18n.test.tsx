import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { dictionaries } from '../src/locales';
import { I18nProvider, LANGUAGE_KEY, LanguageSwitcher, resolveLanguage, translate, useI18n } from '../src/i18n';

it('resolves stored preference, supported browser base languages and English fallback', () => {
  expect(resolveLanguage('es', ['ru-RU'])).toBe('es');
  expect(resolveLanguage(null, ['ru-RU'])).toBe('ru');
  expect(resolveLanguage('invalid', ['es-MX'])).toBe('es');
  expect(resolveLanguage(null, ['de-DE', 'ru'])).toBe('ru');
  expect(resolveLanguage(null, ['de-DE'])).toBe('en');
  expect(resolveLanguage(null, [])).toBe('en');
});
it('has complete static dictionaries with matching placeholders', () => {
  for (const dict of Object.values(dictionaries)) {
    expect(Object.keys(dict).sort()).toEqual(Object.keys(dictionaries.en).sort());
    for (const key of Object.keys(dictionaries.en) as (keyof typeof dictionaries.en)[]) {
      expect(dict[key].match(/\{\w+\}/g) ?? []).toEqual(dictionaries.en[key].match(/\{\w+\}/g) ?? []);
    }
  }
  expect(translate('ru', 'title')).toBe('Анализ матча');
  expect(translate('es', 'shootout')).toBe('Tanda de penaltis');
});
function Probe() {
  const { t, xg, stage, method, date } = useI18n();
  return <><LanguageSwitcher /><p>{t('title')}|{xg(2.758305926)}|{stage('Final')}|{method('EXTRA_TIME')}|{date('2022-12-18')}|{stage('New stage')}</p></>;
}
it('persists locale, formats display values and retains unknown source labels', () => {
  const first = render(<I18nProvider><Probe /></I18nProvider>);
  fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ru' } });
  expect(localStorage.getItem(LANGUAGE_KEY)).toBe('ru');
  expect(document.documentElement.lang).toBe('ru');
  expect(screen.getByText(/Анализ матча/).textContent).toContain('2,76|Финал|Дополнительное время');
  expect(screen.getByText(/Анализ матча/).textContent).toContain('New stage');
  first.unmount();
  render(<I18nProvider><Probe /></I18nProvider>);
  expect(screen.getByLabelText('Язык')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Язык'), { target: { value: 'es' } });
  expect(screen.getByText(/Análisis del partido/)).toBeTruthy();
});
it('still switches language when storage is disabled', () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked'); });
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked'); });
  render(<I18nProvider><Probe /></I18nProvider>);
  fireEvent.change(screen.getByTestId('language-selector'), { target: { value: 'es' } });
  expect(screen.getByText(/Análisis del partido/)).toBeTruthy();
  get.mockRestore(); set.mockRestore();
});
