import { expect, test } from '@playwright/test';

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
  await expect(page.locator('#shot-tooltip')).toContainText('xG');
  const beforeFilter = requests.length;
  await page.getByLabel('Filter players by team').selectOption('779');
  expect(requests).toHaveLength(beforeFilter);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: 'test-results/final-desktop.png', fullPage: true });
  for (const [id, pens] of [['3869321', true], ['3857265', false], ['3869684', false]] as const) {
    await page.getByLabel('Explore a match').selectOption(id);
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
  await page.getByLabel('Explore a match').selectOption('3869685');
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
  await page.getByLabel('Explore a match').selectOption('3857265');
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
