import { expect, test } from '@playwright/test';
import { AxeBuilder } from '@axe-core/playwright';
import { analysis, match, pressureMap, pressureCoordinates } from '../fixtures';

test.use({ locale: 'en-GB' });

test('live pressure visuals: England and Iran original-coordinate Smooth and exact Grid', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await page.goto('/competitions/43/seasons/106/matches/3857271');
  await expect(page.getByTestId('match-header')).toBeVisible();
  await page.getByRole('button', { name: 'Load pressure heatmap' }).click();
  const panel = page.getByTestId('pressure-heatmap');
  for (const [team, name] of [[768, 'England'], [797, 'Iran']] as const) {
    await page.getByRole('combobox', { name: 'Pressure team', exact: true }).selectOption(String(team));
    const path = `/api/v1/competitions/43/seasons/106/matches/3857271/event-heatmap`;
    const query = `?type=pressure&team_id=${team}&period=1`;
    const rawResponse = await page.request.get(path + '/coordinates' + query);
    expect(rawResponse.status()).toBe(200);
    const raw = await rawResponse.json();
    const grid = await (await page.request.get(path + query)).json();
    expect(raw.points).toHaveLength(grid.eligible_event_total);
    expect(raw.cells).toEqual(grid.cells);
    expect(raw.excluded).toEqual(grid.excluded);
    for (const mode of ['Smooth Heatmap', 'Grid']) {
      await page.getByRole('button', { name: mode, exact: true }).focus();
      await page.keyboard.press('Enter');
      await expect(page.getByTestId('pressure-counts')).toContainText(`Mapped: ${raw.points.length}`);
      if (mode === 'Smooth Heatmap') await expect(page.getByTestId('pressure-density')).toHaveAttribute('href', /^data:image\/png/);
      else await expect(page.getByTestId('pressure-density')).toHaveCount(0);
      await expect(page.getByTestId('pressure-cell')).toHaveCount(96);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).include('[data-testid="pressure-heatmap"]').analyze()).violations).toEqual([]);
      await page.getByTestId('pressure-cell').first().focus();
      await page.keyboard.press('ArrowRight');
      await expect(page.getByTestId('pressure-details')).toContainText('X [10, 20)');
      await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
      await page.mouse.move(0, 0);
      await panel.screenshot({ path: `test-results/stage9b2c/${name}-${mode === 'Grid' ? 'grid' : 'smooth'}-${testInfo.project.name}.png` });
    }
    await page.getByRole('button', { name: 'Smooth Heatmap', exact: true }).click();
    for (const lang of ['ru', 'es', 'en']) {
      await page.getByTestId('language-selector').selectOption(lang);
      await expect(page.getByTestId('pressure-density')).toHaveAttribute('href', /^data:image\/png/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).include('[data-testid="pressure-heatmap"]').analyze()).violations).toEqual([]);
    }
  }
});
test('synthetic contexts: pressure grid, stable scale, keyboard, errors and locales', async ({ page }) => {
  let mode = 'normal';
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const calls: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: unknown;
    if (path.endsWith('/competitions')) body = { competitions: [{ competition_id: 11 }] };
    else if (path.endsWith('/seasons')) body = { seasons: [{ season_id: 22 }] };
    else if (path.endsWith('/matches')) body = { matches: [match] };
    else if (path.endsWith('/analysis')) body = analysis;
    else if (path.endsWith('/event-heatmap') || path.endsWith('/event-heatmap/coordinates')) {
      calls.push(url.search);
      if (mode === 'error') return route.fulfill({ status: 503, json: { error: { code: 'clickhouse_unavailable', message: 'synthetic' } } });
      if (mode === 'loading') await gate;
      const empty = url.searchParams.get('period') === '5';
      body = { ...pressureCoordinates, filters: { type: 'pressure', team_id: Number(url.searchParams.get('team_id')), period: Number(url.searchParams.get('period')) },
        ...(empty ? { total_count: 0, eligible_event_total: 0, points: [], cells: pressureMap.cells.map(c => ({ ...c, count: 0 })) } : {}) };
    } else throw Error('Unexpected synthetic pressure path');
    await route.fulfill({ json: body });
  });
  await page.goto('/competitions/11/seasons/22/matches/7');
  await expect(page.getByTestId('shot-marker')).toHaveCount(1);
  expect(calls).toHaveLength(0);
  mode = 'loading';
  await page.getByRole('button', { name: 'Load pressure heatmap' }).click();
  await expect(page.getByText('Loading pressure events…')).toBeVisible();
  release(); mode = 'normal';
  await expect(page.getByTestId('pressure-cell')).toHaveCount(96);
  await expect(page.getByTestId('pressure-counts')).toContainText('Mapped: 19');
  await expect(page.getByTestId('pressure-density')).toHaveAttribute('href', /^data:image\/png/);
  await expect(page.getByRole('button', { name: 'Smooth Heatmap', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect((await new AxeBuilder({ page }).include('[data-testid="pressure-heatmap"]').analyze()).violations).toEqual([]);
  await page.getByRole('button', { name: 'Grid', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('pressure-density')).toHaveCount(0);
  const cells = page.getByTestId('pressure-cell');
  await cells.first().focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('pressure-details')).toContainText('Pressure events: 2');
  await page.keyboard.press('End'); await page.keyboard.press('Space');
  await expect(cells.last()).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('pressure-details')).toContainText('X [110, 120]');
  const legend = await page.locator('.pressure-legend').innerText();
  await page.getByRole('combobox', { name: 'Pressure period', exact: true }).selectOption('5');
  await expect(page.getByText('No Pressure events match these filters.')).toBeVisible();
  expect(await page.locator('.pressure-legend').innerText()).toBe(legend);
  mode = 'error';
  await page.getByRole('combobox', { name: 'Pressure team', exact: true }).selectOption('20');
  await expect(page.getByTestId('pressure-heatmap').getByRole('alert')).toBeVisible();
  mode = 'normal';
  await page.getByTestId('pressure-heatmap').getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByTestId('pressure-cell')).toHaveCount(96);
  for (const lang of ['ru', 'es', 'en']) {
    const before = calls.length;
    await page.getByTestId('language-selector').selectOption(lang);
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    expect(calls).toHaveLength(before);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).include('[data-testid="pressure-heatmap"]').analyze()).violations).toEqual([]);
  }
  await expect(page.getByTestId('shot-marker')).toHaveCount(1);
  await expect(page.getByTestId('race-point')).toHaveCount(1);
  await expect(page.getByTestId('shootout-panel')).toBeVisible();
});

for (const [competition, season, matchId, team, expected] of [[9, 281, 3895052, 904, 63], [43, 106, 3869685, 779, 59]]) {
  test(`live pressure ${competition}/${season}: scoped cells reconcile and interactions remain`, async ({ page }, testInfo) => {
    test.setTimeout(60000);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const route = `/competitions/${competition}/seasons/${season}/matches/${matchId}`;
    await page.goto(route);
    await expect(page.getByTestId('match-header')).toBeVisible();
    await page.getByRole('button', { name: 'Grid', exact: true }).click();
    await page.getByRole('button', { name: 'Load pressure heatmap' }).click();
    await expect(page.getByTestId('pressure-cell')).toHaveCount(96);
    await expect(page.getByTestId('pressure-counts')).toContainText(`Mapped: ${expected}`);
    const response = await page.request.get(`/api/v1${route}/event-heatmap?type=pressure&team_id=${team}&period=1`);
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.total_count).toBe(expected);
    expect(data.excluded.count).toBe(0);
    for (const cell of data.cells)
      await expect(page.locator(`[data-testid="pressure-cell"][data-column="${cell.column}"][data-row="${cell.row}"]`)).toHaveAttribute('data-count', String(cell.count));
    const cells = page.getByTestId('pressure-cell');
    await cells.nth(13).hover();
    await expect(page.getByTestId('pressure-details')).toContainText('X [10, 20)');
    await cells.first().focus(); await page.keyboard.press('End'); await page.keyboard.press('Enter');
    await expect(cells.last()).toHaveAttribute('aria-pressed', 'true');
    expect(await cells.evaluateAll(nodes => nodes.filter(n => n.getAttribute('tabindex') === '0').length)).toBe(1);
    // Capture one populated cell after the keyboard checks, with the pointer
    // outside the field so screenshot scrolling cannot change hover details.
    const populated = data.cells.find((cell: { count: number }) => cell.count > 0);
    const example = page.locator(`[data-testid="pressure-cell"][data-column="${populated.column}"][data-row="${populated.row}"]`);
    await example.focus(); await example.press('Enter');
    await example.evaluate(node => (node as SVGElement).blur());
    await page.mouse.move(0, 0);
    const base = `test-results/stage9b2/pressure-${competition}-${testInfo.project.name}`;
    await page.getByTestId('pressure-heatmap').screenshot({ path: base + '.png' });
    await page.screenshot({ path: base + '-page.png', fullPage: true });
    await page.getByRole('combobox', { name: 'Pressure period', exact: true }).selectOption('5');
    await expect(page.getByText('No Pressure events match these filters.')).toBeVisible();
    for (const lang of ['ru', 'es', 'en']) {
      await page.getByTestId('language-selector').selectOption(lang);
      await expect(page.locator('html')).toHaveAttribute('lang', lang);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    expect((await new AxeBuilder({ page }).analyze()).violations.map(v => v.id)).toEqual([]);
    await expect(page.getByTestId('shot-marker')).toHaveCount(competition === 9 ? 25 : 30);
    await expect(page.getByTestId('race-point')).toHaveCount(competition === 9 ? 25 : 30);
    await expect(page.getByTestId('shootout-panel')).toHaveCount(competition === 9 ? 0 : 1);
    expect(errors).toEqual([]);
  });
}
