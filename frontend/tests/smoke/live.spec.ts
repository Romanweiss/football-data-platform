import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { AxeBuilder } from '@axe-core/playwright';

test.use({ locale: 'en-GB' });
async function chooseMatch(page: Page, id: string) {
  await page.getByRole('combobox', { name: 'Explore a match' }).click();
  await page.locator(`[role="option"][data-match-id="${id}"]`).click();
}

test('four live matches, same-origin requests, switching, refresh and responsive SVG', async ({ page, baseURL }) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on('request', req => { if (['xhr', 'fetch'].includes(req.resourceType())) requests.push(req.url()); });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/matches/3869685');
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
  await expect(page.getByTestId('shot-marker')).toHaveCount(30);
  await expect(page.getByTestId('xg-final-779')).toHaveText('2.76');
  await expect(page.getByTestId('xg-final-771')).toHaveText('2.27');
  await expect(page.getByTestId('shootout-panel').locator('li')).toHaveCount(8);
  await expect(page.getByTestId('match-header')).toContainText('3-3 (4-2 pens)');
  expect(await page.getByTestId('shot-marker').evaluateAll(nodes => nodes.every(node => node.getAttribute('data-period') !== '5'))).toBe(true);
  await page.getByTestId('shot-marker').first().focus();
  await expect(page.getByTestId('shot-details')).toContainText('xG');
  const beforeFilter = requests.length;
  await page.getByLabel('Filter players by team').selectOption('779');
  expect(requests).toHaveLength(beforeFilter);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: 'test-results/final-desktop.png', fullPage: true });
  for (const [id, pens] of [['3869321', true], ['3857265', false], ['3869684', false]] as const) {
    await chooseMatch(page, id);
    await expect(page).toHaveURL(new RegExp(`/matches/${id}$`));
    await expect(page.getByTestId('match-header')).toBeVisible();
    await expect(page.getByTestId('shootout-panel')).toHaveCount(pens ? 1 : 0);
    await page.reload();
    await expect(page.getByTestId('match-header')).toBeVisible();
  }
  expect(requests.every(url => new URL(url).origin === new URL(baseURL!).origin && new URL(url).pathname.startsWith('/api/v1/'))).toBe(true);
  expect(requests.every(url => url.endsWith('/analysis') || url.endsWith('/matches'))).toBe(true);
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('match-header')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/match-mobile.png', fullPage: true });
});

test('root initial choice, browser history and intentional error states', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/matches\/\d+$/);
  await expect(page.getByTestId('match-header')).toBeVisible();
  await chooseMatch(page, '3869685');
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
  await chooseMatch(page, '3857265');
  await expect(page.getByTestId('shootout-panel')).toHaveCount(0);
  await page.goBack();
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
  await page.goto('/matches/999999999');
  await expect(page.getByRole('alert')).toContainText('Match not found');
  await page.route('**/api/v1/matches/3869685/analysis', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'clickhouse_unavailable', message: 'not displayed' } }) }));
  await page.goto('/matches/3869685');
  await expect(page.getByRole('alert')).toContainText('Data service temporarily unavailable');
  await page.unroute('**/api/v1/matches/3869685/analysis');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
});

test('search, cross-highlights, persistent selection, localization and history', async ({ page }) => {
  await page.goto('/matches/3857265');
  await expect(page.getByTestId('match-header')).toBeVisible();
  const calls: string[] = [];
  page.on('request', req => { if (req.url().includes('/api/')) calls.push(req.url()); });
  const combo = page.getByRole('combobox', { name: 'Explore a match' });
  await combo.fill('arg');
  await expect(page.getByRole('listbox').getByRole('option')).toHaveCount(7);
  expect(calls).toHaveLength(0);
  await page.locator('[role="option"][data-match-id="3869685"]').click();
  await expect(page).toHaveURL(/\/matches\/3869685$/);
  await expect(page.getByTestId('race-point')).toHaveCount(30);
  const point = page.getByTestId('race-point').first();
  const id = await point.getAttribute('data-event-id');
  const marker = page.locator(`[data-testid="shot-marker"][data-event-id="${id}"]`);
  await point.hover();
  await expect(marker).toHaveAttribute('data-state', 'hovered');
  await point.click();
  await page.getByRole('heading', { name: 'The xG race' }).hover();
  await expect(marker).toHaveAttribute('data-state', 'selected');
  await expect(page.getByTestId('shot-details')).toContainText('Selected shot');
  const count = calls.length;
  await page.getByTestId('language-selector').selectOption('ru');
  await expect(page.getByRole('heading', { name: 'Анализ матча.' })).toBeVisible();
  await expect(page.getByTestId('shot-details')).toContainText('Выбранный удар');
  await expect(page.getByTestId('xg-final-779')).toHaveText('2,76');
  await expect(page).toHaveURL(/\/matches\/3869685$/);
  expect(calls).toHaveLength(count);
  await page.reload();
  await expect(page.getByTestId('language-selector')).toHaveValue('ru');
  await expect(page.getByTestId('match-header')).toContainText('Argentina');
  await page.getByTestId('language-selector').selectOption('es');
  await expect(page.getByRole('heading', { name: 'Análisis del partido.' })).toBeVisible();
  await expect(page.getByTestId('shootout-panel')).toContainText('Tanda de penaltis');
  await page.goBack();
  await expect(page).toHaveURL(/\/matches\/3857265$/);
  await expect(page.getByTestId('shootout-panel')).toHaveCount(0);
  const penaltyId = '5ee0aff8-6137-437a-84a3-320adf30aed6';
  const penalty = page.locator(`[data-testid="shot-marker"][data-event-id="${penaltyId}"]`);
  await penalty.focus();
  await penalty.press('Enter');
  await expect(page.locator(`[data-testid="race-point"][data-event-id="${penaltyId}"]`)).toHaveAttribute('data-state', 'selected');
  await expect(page.getByTestId('shot-details')).toContainText('Robert Lewandowski');
  await expect(page.getByTestId('shot-details')).toContainText('57:23');
  await penalty.press('Escape');
  await expect(penalty).toHaveAttribute('aria-pressed', 'false');
  await page.goForward();
  await expect(page).toHaveURL(/\/matches\/3869685$/);
  await expect(page.getByTestId('shot-count')).toContainText('30');
});

test('keyboard-only search and localized empty/loading/error states', async ({ page }) => {
  await page.goto('/matches/3857265');
  await expect(page.getByTestId('match-header')).toBeVisible();
  const combo = page.getByRole('combobox', { name: 'Explore a match' });
  await combo.focus();
  await combo.pressSequentially('2022-12-18');
  await expect(page.getByRole('listbox').getByRole('option')).toHaveCount(1);
  await combo.press('ArrowDown');
  await combo.press('Enter');
  await expect(page).toHaveURL(/\/matches\/3869685$/);
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
  await combo.click();
  await combo.fill('nowhere');
  await expect(page.getByText('No matches found', { exact: true })).toBeVisible();
  await combo.press('Escape');
  await expect(combo).toHaveAttribute('aria-expanded', 'false');
  await combo.click();
  await page.getByRole('heading', { name: 'Match analysis.' }).click();
  await expect(combo).toHaveAttribute('aria-expanded', 'false');
  const point = page.getByTestId('race-point').first();
  await point.focus();
  await point.press('Space');
  await expect(page.getByTestId('shot-details')).toContainText('Selected shot');
  await point.press('Escape');
  await expect(point).toHaveAttribute('aria-pressed', 'false');
  await page.route('**/api/v1/matches/3869685/analysis', route => route.fulfill({ status: 503, body: '{}' }));
  await page.reload();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.getByTestId('language-selector').selectOption('ru');
  await expect(page.getByRole('alert')).toContainText('Сервис данных временно недоступен');
  await expect(page).toHaveURL(/\/matches\/3869685$/);
  await page.unroute('**/api/v1/matches/3869685/analysis');
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByTestId('shot-count')).toContainText('30');
});

for (const [width, height] of [[1440, 900], [1024, 768], [768, 1024], [390, 844]]) {
  test(`responsive and automated accessibility ${width}x${height}`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width, height });
    await page.goto('/matches/3869685');
    await expect(page.getByTestId('match-header')).toBeVisible();
    for (const lang of ['en', 'ru', 'es']) {
      await page.getByTestId('language-selector').selectOption(lang);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await expect(page.getByTestId('language-selector')).toBeVisible();
      const combo = page.locator('input[role="combobox"]');
      await combo.fill('arg');
      await expect(page.getByRole('listbox').getByRole('option')).toHaveCount(7);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      const results = await new AxeBuilder({ page }).analyze();
      expect(results.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) }))).toEqual([]);
      await combo.press('Escape');
      await page.getByTestId('race-point').first().focus();
      await page.keyboard.press('Enter');
      const selected = await new AxeBuilder({ page }).analyze();
      expect(selected.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) }))).toEqual([]);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `test-results/stage5c-${width}-${lang}.png`, fullPage: true });
      if (lang === 'ru') await page.locator('.visual-grid').screenshot({ path: `test-results/stage5c-visuals-${width}.png` });
    }
    if (width === 390) expect(await page.locator('.table-scroll').evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
  });
}

for (const [width, height] of [[1440, 900], [390, 844]]) {
  test(`final UX polish: real markers, roster options and native selects ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto('/matches/3869685');
    await expect(page.getByTestId('race-point')).toHaveCount(30);
    const race = page.locator('.race-svg');
    await expect(race.locator('circle:not(.hit-target):not(.interaction-ring)')).toHaveCount(30);
    await expect(race.locator('.hit-target')).toHaveCount(30);
    await expect(race.locator('[tabindex="0"]')).toHaveCount(30);
    await expect(race.locator('path')).toHaveCount(2);
    const coverage = page.getByRole('combobox', { name: 'Squad coverage' });
    const team = page.getByRole('combobox', { name: 'Filter players by team' });
    const language = page.getByRole('combobox', { name: 'Language', exact: true });
    await expect(coverage).toHaveValue('active');
    const activeCount = await page.locator('tbody tr').count();
    expect(activeCount).toBeGreaterThan(0);
    expect(await page.locator('tbody tr td:last-child').allTextContents()).not.toContain('0');
    await coverage.selectOption('all');
    expect(await page.locator('tbody tr').count()).toBeGreaterThan(activeCount);
    expect(await page.locator('tbody tr td:last-child').allTextContents()).toContain('0');
    await coverage.selectOption('active');
    await expect(page.locator('tbody tr')).toHaveCount(activeCount);
    for (const select of [language, team, coverage]) {
      await expect(select).toHaveCSS('appearance', 'none');
      await expect(select).toHaveCSS('border-radius', '7px');
      expect(await select.evaluate(node => getComputedStyle(node).backgroundImage)).toContain('linear-gradient');
      expect(await select.evaluate(node => parseFloat(getComputedStyle(node).paddingRight))).toBeGreaterThanOrEqual(32);
      await select.focus();
      await page.keyboard.press('Tab');
      await page.keyboard.press('Shift+Tab');
      await expect(select).toBeFocused();
      await expect(select).toHaveCSS('outline-style', 'solid');
      const box = (await select.boundingBox())!;
      await select.click({ position: { x: box.width - 16, y: box.height / 2 } });
      await page.keyboard.press('Escape');
      await expect(select).toBeFocused();
    }
    expect((await language.boundingBox())!.width).toBeLessThan(90);
    await page.locator('.player-filters').screenshot({ path: `test-results/polish-filters-${width}.png` });
    await page.locator('.app-header').screenshot({ path: `test-results/polish-header-${width}.png` });
    await page.getByTestId('race-point').first().focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('shot-details')).toContainText('Selected shot');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const pitch = page.locator('.pitch-svg');
    await expect(pitch.locator('.corner-arc')).toHaveCount(2);
    await expect(page.getByTestId('shot-marker')).toHaveCount(30);
    const bounds = (await pitch.boundingBox())!;
    const center = (await pitch.locator('.center-circle').boundingBox())!;
    expect(center.x).toBeGreaterThan(bounds.x);
    expect(center.x + center.width).toBeLessThan(bounds.x + bounds.width);
    expect(center.y).toBeGreaterThan(bounds.y);
    expect(center.y + center.height).toBeLessThan(bounds.y + bounds.height);
    expect(Math.abs(center.width - center.height)).toBeLessThan(1);
    await expect(pitch.locator('.pitch-lines')).toHaveCSS('pointer-events', 'none');
    const selectedId = await page.getByTestId('race-point').first().getAttribute('data-event-id');
    const selectedMarker = pitch.locator(`[data-event-id="${selectedId}"]`);
    await expect(selectedMarker).toHaveAttribute('data-state', 'selected');
    await expect(selectedMarker.locator('.interaction-ring')).toHaveAttribute('visibility', 'visible');
    await pitch.screenshot({ path: `test-results/polish-pitch-${width}.png` });
  });
}

test('browser language fallback and mobile tap interaction', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ locale: 'ru-RU', viewport: { width: 390, height: 844 }, hasTouch: true });
  try {
    const page = await context.newPage();
    await page.goto(`${baseURL}/matches/3857265`);
    await expect(page.getByTestId('language-selector')).toHaveValue('ru');
    const combo = page.getByRole('combobox', { name: 'Выбрать матч' });
    await combo.tap();
    await combo.fill('2022-12-18');
    await page.locator('[role="option"][data-match-id="3869685"]').tap();
    await expect(page.getByTestId('shot-count')).toContainText('30');
    const point = page.getByTestId('race-point').first();
    await point.tap();
    await expect(point).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('shot-details')).toContainText('Выбранный удар');
    await page.getByRole('button', { name: 'Снять выбор удара' }).tap();
    await expect(point).toHaveAttribute('aria-pressed', 'false');
  } finally { await context.close(); }
  const fallback = await browser.newContext({ locale: 'de-DE' });
  try {
    const page = await fallback.newPage();
    await page.goto(`${baseURL}/`);
    await expect(page.getByTestId('language-selector')).toHaveValue('en');
  } finally { await fallback.close(); }
});
