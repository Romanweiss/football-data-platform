import { expect, test } from '@playwright/test';
import { AxeBuilder } from '@axe-core/playwright';
import { analysis, match, passMap } from '../fixtures';

test.use({ locale: 'en-GB' });
test('synthetic contexts: pass map coordinates, filters, keyboard, languages and no overflow', async ({ page }) => {
  const requests: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    let body: unknown;
    if (path === '/competitions') body = { competitions: [{ competition_id: 11 }] };
    else if (path === '/competitions/11/seasons') body = { seasons: [{ season_id: 22 }] };
    else if (path === '/competitions/11/seasons/22/matches') body = { matches: [match] };
    else if (path.endsWith('/analysis')) body = analysis;
    else if (path.endsWith('/passes')) {
      requests.push(url.search);
      const empty = url.searchParams.get('period') === '2';
      body = { ...passMap,
        filters: { team_id: Number(url.searchParams.get('team_id')), player_id: url.searchParams.has('player_id') ? Number(url.searchParams.get('player_id')) : null,
          period: url.searchParams.has('period') ? Number(url.searchParams.get('period')) : null },
        ...(empty ? { passes: [], total_count: 0, returned_count: 0, outcome_counts: { completed: 0, failed: 0, unknown: 0 } } : {}) };
    } else throw new Error('Unexpected synthetic API path');
    await route.fulfill({ json: body });
  });
  await page.goto('/competitions/11/seasons/22/matches/7');
  await expect(page.getByTestId('shot-marker')).toHaveCount(1);
  expect(requests).toHaveLength(0);
  await page.getByRole('button', { name: 'Load pass map' }).click();
  await expect(page.getByTestId('pass-event')).toHaveCount(3);
  const first = page.getByTestId('pass-event').first();
  // Passes 1/3 deliberately share a segment in opposite directions. Exercise
  // pointer selection on the distinct pass, and reach every overlap by keyboard.
  const distinct = page.locator('[data-testid="pass-event"][data-event-id="pass-2"]');
  await distinct.locator('.pass-start').click();
  await expect(distinct).toHaveAttribute('aria-pressed', 'true');
  await first.focus(); await first.press('ArrowRight'); await page.keyboard.press('Enter');
  await expect(page.locator('.pass-details')).toContainText('Incomplete');
  await expect(page.locator('[data-testid="pass-event"][aria-pressed="true"]')).toHaveCount(1);
  expect(await page.getByTestId('pass-event').evaluateAll(nodes => nodes.filter(n => n.getAttribute('tabindex') === '0').length)).toBe(1);
  await page.keyboard.press('Escape');
  await page.getByRole('combobox', { name: 'Pass player', exact: true }).selectOption('1');
  await expect(page.getByTestId('pass-event')).toHaveCount(3);
  expect(requests.at(-1)).toContain('player_id=1');
  for (const lang of ['ru', 'es', 'en']) {
    const before = requests.length;
    await page.getByTestId('language-selector').selectOption(lang);
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    expect(requests).toHaveLength(before);
  }
  await page.getByRole('combobox', { name: 'Pass period', exact: true }).selectOption('2');
  await expect(page.getByText('No passes match these filters.')).toBeVisible();
  await page.getByRole('combobox', { name: 'Pass period', exact: true }).selectOption('1');
  await expect(page.getByTestId('pass-event')).toHaveCount(3);
  await expect(page.getByTestId('race-point')).toHaveCount(1);
  await expect(page.getByTestId('shootout-panel')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).include('[data-testid="pass-map"]').analyze();
  expect(accessibility.violations).toEqual([]);
});

for (const [width, height] of [[1440, 900], [390, 844]]) {
  test(`live pass map Xhaka period one and shot regression ${width}x${height}`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width, height });
    await page.goto('/competitions/9/seasons/281/matches/3895052');
    await expect(page.getByTestId('coverage-note')).toHaveText('Partial coverage: Bayer Leverkusen matches only (34/306)');
    await expect(page.getByRole('combobox', { name: 'Competition', exact: true }).locator('option:checked')).toHaveText('Bundesliga');
    await expect(page.getByRole('combobox', { name: 'Season', exact: true }).locator('option:checked')).toHaveText('2023/24');
    await page.getByRole('combobox', { name: 'Pass player', exact: true }).selectOption('3500');
    await page.getByRole('button', { name: 'Load pass map' }).click();
    await expect(page.getByTestId('pass-event')).toHaveCount(31);
    await expect(page.getByTestId('pass-counts')).toContainText('Completed: 27');
    await expect(page.getByTestId('pass-counts')).toContainText('Failed: 4');
    const passes = await (await page.request.get('/api/v1/competitions/9/seasons/281/matches/3895052/passes?team_id=904&player_id=3500&period=1')).json();
    for (const row of passes.passes) {
      const line = page.locator(`[data-testid="pass-event"][data-event-id="${row.event_id}"] .pass-line`);
      for (const [attr, value] of [['x1', row.start_x], ['y1', row.start_y], ['x2', row.end_x], ['y2', row.end_y]])
        await expect(line).toHaveAttribute(String(attr), String(value));
    }
    const first = page.getByTestId('pass-event').first();
    await first.focus(); await first.press('Enter');
    await expect(page.locator('.pass-details')).toContainText('Granit Xhaka');
    await expect(page.locator('[data-testid="pass-event"][aria-pressed="true"]')).toHaveCount(1);
    await expect(page.getByTestId('shot-marker')).toHaveCount(25);
    await expect(page.getByTestId('race-point')).toHaveCount(25);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/stage9b-pass-map-${width}.png`, fullPage: true });
    await page.getByTestId('pass-map').screenshot({ path: `test-results/stage9b-pass-map-detail-${width}.png` });
    const accessibility = await new AxeBuilder({ page }).include('[data-testid="pass-map"]').analyze();
    expect(accessibility.violations).toEqual([]);
  });
}
