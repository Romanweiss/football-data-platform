import { expect, test } from '@playwright/test';
import { analysis, match } from '../fixtures';

test.use({ locale: 'en-GB' });

for (const [competition, season, matchId, matchCount] of [[43, 106, 3869685, 64], [9, 281, 3895052, 34]]) {
  test(`live delivery context ${competition}/${season}: canonical UI, history and EN/RU/ES`, async ({ page, baseURL }, testInfo) => {
    test.skip(process.env.WEB_DELIVERY_MODE !== 'production', 'Opt-in live production acceptance');
    test.setTimeout(60_000);
    const context = `/competitions/${competition}/seasons/${season}`;
    const path = `${context}/matches/${matchId}`;
    const response = await page.request.get(`/api/v1${path}/analysis`);
    expect(response.status()).toBe(200);
    const live = await response.json();
    const matches = await (await page.request.get(`/api/v1${context}/matches`)).json();
    expect(matches.matches).toHaveLength(matchCount);
    const second = matches.matches.find((row: { match_id: number }) => row.match_id !== matchId);
    const requests: string[] = [];
    const errors: string[] = [];
    page.on('request', request => {
      if (['fetch', 'xhr'].includes(request.resourceType())) requests.push(request.url());
    });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(path);
    await expect(page.getByTestId('match-header')).toContainText(live.match.home_team_name);
    await expect(page.getByRole('combobox', { name: 'Competition', exact: true })).toHaveValue(String(competition));
    await expect(page.getByRole('combobox', { name: 'Season', exact: true })).toHaveValue(String(season));
    // Season selection navigates to the context landing route, which chooses
    // its first available match; it does not preserve the previously open match.
    await page.getByRole('combobox', { name: 'Season', exact: true }).selectOption(String(season));
    await expect(page).toHaveURL(`${context}/matches/${matches.matches[0].match_id}`);
    await expect(page.getByTestId('match-header')).toContainText(matches.matches[0].home_team_name);
    await page.goto(path);
    await expect(page.getByTestId('match-header')).toContainText(live.match.home_team_name);
    await expect(page.locator('.comparison')).toBeVisible();
    await expect(page.locator('.pitch-svg')).toBeVisible();
    await expect(page.locator('.race-svg')).toBeVisible();
    await expect(page.getByTestId('shot-marker')).toHaveCount(live.shots.length);
    await expect(page.getByTestId('race-point')).toHaveCount(live.shots.length);
    await expect(page.getByTestId('shootout-panel')).toHaveCount(live.shootout.attempts.length ? 1 : 0);
    const point = page.getByTestId('race-point').first();
    const eventId = await point.getAttribute('data-event-id');
    await point.focus();
    await point.press('Enter');
    await expect(page.locator(`[data-testid="shot-marker"][data-event-id="${eventId}"]`)).toHaveAttribute('data-state', 'selected');
    await expect(page.getByTestId('shot-details')).toContainText('Selected shot');
    await page.getByRole('combobox', { name: 'Squad coverage' }).selectOption('all');
    await expect(page.locator('tbody tr')).toHaveCount(live.players.length);
    const combo = page.getByRole('combobox', { name: 'Explore a match' });
    await combo.fill(second.home_team_name);
    await page.locator(`[role="option"][data-match-id="${second.match_id}"]`).click();
    const secondPath = `${context}/matches/${second.match_id}`;
    await expect(page).toHaveURL(secondPath);
    await expect(page.getByTestId('match-header')).toContainText(second.home_team_name);
    await page.goBack();
    await expect(page).toHaveURL(path);
    await expect(page.getByTestId('match-header')).toContainText(live.match.home_team_name);
    await page.goForward();
    await expect(page).toHaveURL(secondPath);
    await page.goto(path);
    for (const [lang, heading] of [['en', 'Match analysis.'], ['ru', 'Анализ матча.'], ['es', 'Análisis del partido.']]) {
      await page.getByTestId('language-selector').selectOption(lang);
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
      await expect(page.getByTestId('match-header')).toContainText(live.match.home_team_name);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`stage8b-live-${competition}-${testInfo.project.name}-${lang}.png`), fullPage: true });
      await page.reload();
      await expect(page).toHaveURL(path);
      await expect(page.getByTestId('language-selector')).toHaveValue(lang);
      await expect(page.getByTestId('match-header')).toContainText(live.match.home_team_name);
    }
    expect(requests.every(url => new URL(url).origin === new URL(baseURL!).origin && new URL(url).pathname.startsWith('/api/v1/'))).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('production fixture visuals: built CSS, shots, roster and localization', async ({ page }, testInfo) => {
  test.skip(process.env.WEB_DELIVERY_MODE !== 'production', 'Opt-in built Nginx acceptance');
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/competitions') return route.fulfill({ json: { competitions: [{ competition_id: 11 }] } });
    if (path === '/api/v1/competitions/11/seasons') return route.fulfill({ json: { seasons: [{ season_id: 22 }] } });
    if (path === '/api/v1/competitions/11/seasons/22/matches') return route.fulfill({ json: { matches: [match] } });
    if (path === '/api/v1/competitions/11/seasons/22/matches/7/analysis') return route.fulfill({ json: analysis });
    throw Error('Unexpected fixture request');
  });
  await page.goto('/competitions/11/seasons/22/matches/7');
  await expect(page.getByTestId('match-header')).toContainText('Red FC');
  await expect(page.locator('.comparison')).toBeVisible();
  await expect(page.locator('.race-svg')).toBeVisible();
  await expect(page.locator('.pitch-svg')).toBeVisible();
  await expect(page.getByTestId('race-point')).toHaveCount(1);
  await expect(page.getByTestId('shot-marker')).toHaveCount(1);
  await page.getByTestId('race-point').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('shot-marker')).toHaveAttribute('data-state', 'selected');
  await expect(page.getByTestId('shot-details')).toContainText('Player One');
  await expect(page.getByTestId('shootout-panel')).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.getByRole('combobox', { name: 'Squad coverage' }).selectOption('all');
  await expect(page.locator('tbody tr')).toHaveCount(2);
  for (const lang of ['en', 'ru', 'es']) {
    await page.getByTestId('language-selector').selectOption(lang);
    await expect(page.getByTestId('language-selector')).toHaveValue(lang);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`stage8b-fixture-${testInfo.project.name}-${lang}.png`), fullPage: true });
  }
  await page.reload();
  await expect(page.getByTestId('match-header')).toContainText('Red FC');
  await expect(page.getByTestId('language-selector')).toHaveValue('es');
});

test('production static shell: upstream failure UX remains usable', async ({ page }) => {
  test.skip(process.env.WEB_DELIVERY_MODE !== 'production', 'Opt-in built Nginx acceptance');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const status of [502, 503]) {
    await page.route('**/api/v1/**', route => route.fulfill(status === 503
      ? { status, json: { error: { code: 'clickhouse_unavailable', message: 'synthetic' } } }
      : { status, contentType: 'text/html', body: '<html><body>Bad Gateway</body></html>' }));
    await page.goto('/competitions/43/seasons/106/matches/3869685');
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(page.getByTestId('language-selector')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.unroute('**/api/v1/**');
  }
  expect(errors).toEqual([]);
});

test('production delivery: built assets, routing, API errors and query preservation', async ({ page }) => {
  test.skip(process.env.WEB_DELIVERY_MODE !== 'production', 'Opt-in built Nginx acceptance; not a Vite assertion');
  const html = await page.request.get('/competitions/43/seasons/106/matches/3869685');
  expect(html.status()).toBe(200);
  expect(html.headers()['cache-control']).toContain('no-cache');
  expect(html.headers()['x-content-type-options']).toBe('nosniff');
  expect(html.headers()['x-frame-options']).toBe('DENY');
  const body = await html.text();
  expect(body).not.toContain('/@vite/client');
  const assets = Array.from(body.matchAll(/(?:src|href)="(\/assets\/[^"\s]+)"/g), match => match[1]);
  expect(assets.length).toBeGreaterThanOrEqual(2);
  for (const asset of assets) {
    const response = await page.request.get(asset);
    expect(response.status()).toBe(200);
    expect(response.headers()['cache-control']).toContain('max-age=31536000');
  }
  expect((await page.request.get('/assets/not-a-real-asset.js')).status()).toBe(404);
  for (const [path, status] of [
    ['/api/not-a-real-endpoint', 404], ['/api', 404],
    ['/api/v1/health?unsupported=1', 400], ['/api/v1/health', 200],
  ] as const) {
    const response = await page.request.get(path);
    expect(response.status()).toBe(status);
    expect(response.headers()['content-type']).toContain('application/json');
    expect(response.headers()['cache-control']).toBe('no-store');
  }
  const playersPath = '/api/v1/competitions/43/seasons/106/matches/3869685/players';
  const players = await page.request.get(playersPath + '?team_id=779');
  expect(players.status()).toBe(200);
  const rows = (await players.json()).players;
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.every((row: { team_id: number }) => row.team_id === 779)).toBe(true);
  expect((await page.request.get(playersPath + '?team_id=779&team_id=771')).status()).toBe(400);
});
