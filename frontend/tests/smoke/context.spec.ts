import { expect, test } from '@playwright/test';
import { analysis, match } from '../fixtures';

test.use({ locale: 'en-GB' });
test('synthetic contexts: scoped search, reused match ID, history, locale and refresh', async ({ page }) => {
  // Browser-only synthetic API. No second dataset is written or presented as live.
  const contexts = [{ c: 11, s: 22 }, { c: 11, s: 23 }, { c: 90, s: 8 }];
  const calls: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    calls.push(path);
    let body: unknown;
    if (path === '/competitions') body = { competitions: [{ competition_id: 11 }, { competition_id: 90 }] };
    else {
      const part = /^\/competitions\/(\d+)\/seasons(?:\/(\d+)\/matches(?:\/7(\/analysis)?)?)?$/.exec(path);
      if (!part) throw Error('Unexpected synthetic API path');
      const competitionId = Number(part[1]), seasonId = Number(part[2]);
      if (!part[2]) body = { seasons: contexts.filter(c => c.c === competitionId).map(c => ({ season_id: c.s })) };
      else {
        expect(contexts.some(c => c.c === competitionId && c.s === seasonId)).toBe(true);
        const row = { ...match, competition_id: competitionId, season_id: seasonId,
          home_team_name: `Home ${competitionId}-${seasonId}`, match_label: `Synthetic ${competitionId}-${seasonId}` };
        body = part[3] ? { ...analysis, match: row } : { matches: [row] };
      }
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  await expect(page).toHaveURL('/competitions/11/seasons/22/matches/7');
  await expect(page.getByTestId('match-header')).toContainText('Home 11-22');
  await page.getByRole('combobox', { name: 'Season', exact: true }).selectOption('23');
  await expect(page).toHaveURL('/competitions/11/seasons/23/matches/7');
  await page.getByRole('combobox', { name: 'Competition', exact: true }).selectOption('90');
  await expect(page).toHaveURL('/competitions/90/seasons/8/matches/7');
  await expect(page.getByTestId('match-header')).toContainText('Home 90-8');
  const before = calls.length;
  await page.getByRole('combobox', { name: 'Explore a match' }).fill('Home 11');
  await expect(page.getByText('No matches found', { exact: true })).toBeVisible();
  expect(calls.length).toBe(before);
  await page.getByRole('combobox', { name: 'Explore a match' }).press('Escape');
  await page.goBack();
  await expect(page).toHaveURL('/competitions/11/seasons/23/matches/7');
  await expect(page.getByTestId('match-header')).toContainText('Home 11-23');
  await page.goForward();
  await expect(page.getByTestId('match-header')).toContainText('Home 90-8');
  await page.getByTestId('language-selector').selectOption('es');
  await page.reload();
  await expect(page).toHaveURL('/competitions/90/seasons/8/matches/7');
  await expect(page.getByRole('combobox', { name: 'Competición', exact: true })).toHaveValue('90');
  await expect(page.getByRole('combobox', { name: 'Temporada', exact: true })).toHaveValue('8');
  await expect(page.getByRole('heading', { name: 'Análisis del partido.' })).toBeVisible();
});

test('live catalog and legacy URL resolve to the canonical WC2022 context', async ({ page }) => {
  await page.goto('/matches/3869685');
  await expect(page).toHaveURL('/competitions/43/seasons/106/matches/3869685');
  await expect(page.getByTestId('shot-count')).toHaveText('30 normal shots');
  await expect(page.getByRole('combobox', { name: 'Competition', exact: true })).toHaveValue('43');
  await expect(page.getByRole('combobox', { name: 'Season', exact: true })).toHaveValue('106');
  await page.reload();
  await expect(page.getByTestId('xg-final-779')).toHaveText('2.76');
  await expect(page.getByTestId('xg-final-771')).toHaveText('2.27');
});
