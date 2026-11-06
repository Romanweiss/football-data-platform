import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { historicalFixtureFactory } from '../historical-fixtures';
import { HISTORICAL_API } from '../../src/historical/source';

const path = '/competitions/historical/uefa-champions-league/2024';
test.use({ locale: 'en-GB' });
test('synthetic contexts: historical API UI, pagination, unknown, ambiguity, filters, history, locales and accessibility', async ({ page }, info) => {
  const f = historicalFixtureFactory(), calls: string[] = [], errors: string[] = [];
  page.on('pageerror', e => errors.push(e.name));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    expect(url.origin).toBe('http://127.0.0.1:15174');
    if (!url.pathname.startsWith('/api/')) return route.continue();
    expect(url.pathname.startsWith(HISTORICAL_API)).toBe(true);
    calls.push(url.pathname + url.search); await route.fulfill({ json: f.response(url) });
  });
  await page.goto('/competitions/historical');
  await page.getByRole('link', { name: 'Open 2024/25 results' }).click();
  await expect(page.getByTestId('historical-fixture')).toHaveCount(50);
  await expect(page.getByTestId('historical-count')).toContainText('189');
  expect(calls).toHaveLength(5); // catalog + overview/participants/coverage + exactly one page
  await expect(page.getByText('DEMO DATA — SYNTHETIC', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'Standings', exact: true })).toHaveCount(0);
  const sizes = await page.locator('.historical-shell main button,.historical-shell select,.historical-shell summary,.historical-shell .workspace-nav a')
    .evaluateAll(nodes => nodes.filter(n => n.getBoundingClientRect().width).map(n => n.getBoundingClientRect().height));
  expect(sizes.every(height => height >= 44)).toBe(true);
  await page.screenshot({ path: info.outputPath('historical-mocked-fixtures.png'), fullPage: true });
  await page.getByRole('button', { name: 'Next page' }).focus(); await page.keyboard.press('Enter');
  await expect(page.getByTestId('historical-count')).toContainText('offset 50');
  await expect(page.getByRole('tabpanel')).toBeFocused();
  await page.goBack(); await expect(page.getByTestId('historical-count')).toContainText('offset 0');
  await page.goForward(); await expect(page.getByTestId('historical-count')).toContainText('offset 50');
  await page.getByRole('combobox', { name: 'Stage', exact: true }).selectOption(f.coverage[0].stage_id);
  await expect(page.getByTestId('historical-count')).toContainText('144');
  await page.getByRole('combobox', { name: 'Round', exact: true }).selectOption(f.coverage[0].round_id);
  await expect(page.getByTestId('historical-fixture')).toHaveCount(18);
  await page.getByRole('combobox', { name: 'Team', exact: true }).selectOption(f.participants[0].id);
  await expect(page.getByTestId('historical-fixture')).toHaveCount(1);
  await page.reload(); await expect(page.getByTestId('historical-fixture')).toHaveCount(1);
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.getByTestId('historical-fixture')).toHaveCount(50);
  await page.getByRole('tab', { name: 'Participants', exact: true }).click();
  await expect(page.getByRole('tabpanel').getByRole('button')).toHaveCount(36);
  await page.getByRole('button', { name: 'Fixture Club 01', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Team', exact: true })).toHaveValue(f.participants[0].id);
  await expect(page.getByTestId('historical-count')).toBeVisible();
  await expect(page.getByRole('tabpanel')).toBeFocused();
  await page.goto(path + '?offset=150'); await expect(page.getByTestId('historical-fixture')).toHaveCount(39);
  await expect(page.getByText('UNKNOWN — result not provided', { exact: true })).toBeVisible();
  await expect(page.locator('[data-quality="AMBIGUOUS_SOURCE_COMPONENTS"]')).toHaveCount(2);
  const unknown = page.locator('[data-quality="MISSING_RESULT"]');
  expect(await unknown.locator('.current-team-line strong').allTextContents()).toEqual(['—', '—']);
  await unknown.getByText('Source score components', { exact: true }).click();
  await expect(unknown.getByText(/No result is inferred/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('historical-mocked-unknown.png'), fullPage: true });
  const fixtures = page.getByRole('tab', { name: 'Fixtures & results', exact: true });
  await fixtures.focus(); await page.keyboard.press('End');
  await expect(page.getByRole('tab', { name: 'Coverage & limits', exact: true })).toBeFocused();
  await expect(page.getByText(/Standings unavailable/)).toBeVisible();
  await page.keyboard.press('ArrowLeft'); await expect(page.getByTestId('historical-count')).toContainText('394');
  await expect(page.locator('.historical-quality li')).toHaveCount(50);
  await page.getByRole('button', { name: 'Next page' }).click(); await expect(page.getByTestId('historical-count')).toContainText('offset 50');
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
  await page.getByTestId('language-selector').selectOption('ru');
  await expect(page.getByRole('tab', { name: 'Качество данных', exact: true })).toBeVisible();
  await expect(page.getByText('НЕПОЛНЫЕ', { exact: true })).toBeVisible();
  await page.getByTestId('language-selector').selectOption('es');
  await expect(page.getByRole('tab', { name: 'Calidad de datos', exact: true })).toBeVisible();
  await expect(page.getByText('INCOMPLETO', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('synthetic contexts: historical network failure retries explicitly without data fallback', async ({ page }) => {
  const f = historicalFixtureFactory(); let fail = true;
  await page.route('**/api/v1/competitions/historical**', route => fail ? route.abort('failed') : route.fulfill({ json: f.response(new URL(route.request().url())) }));
  await page.goto(path);
  await expect(page.getByRole('alert')).toContainText('Unable to load or validate historical data.');
  await expect(page.getByTestId('historical-fixture')).toHaveCount(0);
  await expect(page.getByText('DEMO DATA — SYNTHETIC', { exact: true })).toHaveCount(0);
  fail = false; await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByTestId('historical-fixture')).toHaveCount(50);
});
test('synthetic contexts: historical failure states never fall back to demo, retry and late responses are safe', async ({ page }) => {
  const f = historicalFixtureFactory(); let status = 503;
  await page.route('**/api/v1/competitions/historical**', async route => {
    if (status !== 200) return route.fulfill({ status, json: { error: { code: 'historical_not_ready' } } });
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/fixtures') && !url.searchParams.has('team_id')) await new Promise(resolve => setTimeout(resolve, 350));
    await route.fulfill({ json: f.response(url) }).catch(() => {}); // intentionally aborted browser request
  });
  await page.goto(path); await expect(page.getByRole('alert')).toContainText('Historical dataset is not available in this environment.');
  await expect(page.getByTestId('historical-fixture')).toHaveCount(0);
  for (const nextStatus of [400, 404]) { status = nextStatus; await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByRole('alert')).toContainText(nextStatus === 400 ? 'Invalid historical filters' : 'was not found'); }
  status = 200; await page.getByRole('button', { name: 'Try again' }).click();
  await page.getByRole('combobox', { name: 'Team', exact: true }).selectOption(f.participants[0].id);
  await expect(page.getByTestId('historical-count')).toBeVisible();
  await page.waitForTimeout(450); // intentionally let the old, uncancellable response finish
  for (const row of await page.getByTestId('historical-fixture').allTextContents()) expect(row).toContain('Fixture Club 01');
  await page.goto(path + '?offset=1000'); await expect(page.getByText('No records match these filters.', { exact: true })).toBeVisible();
  await page.goto(path + '?team_id=bad'); await expect(page.getByRole('alert')).toContainText('Invalid historical filters');
});
