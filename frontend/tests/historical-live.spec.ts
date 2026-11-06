/** Opt-in read-only browser check: isolated published Django + verified real Gold. */
import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { HISTORICAL_SEASON_API } from '../src/historical/source';

const path = '/competitions/historical/uefa-champions-league/2024';
test.use({ locale: 'en-GB' });
test('real isolated historical Gold: 189/36, filters, unknown, ambiguity, metadata and accessibility', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.name));
  page.on('request', r => { expect(new URL(r.url()).origin).toBe('http://127.0.0.1:15176'); });
  const overviewResponse = await page.request.get(HISTORICAL_SEASON_API);
  expect(overviewResponse.status()).toBe(200);
  const overview = await overviewResponse.json();
  expect(overview.summary).toMatchObject({ fixture_records: 189, participant_records: 36, source_reported_ft: 188, unknown_results: 1, ambiguous_components: 2, non_fatal_limitations: 394 });
  expect(overview.provenance.source_sha256).toBe('12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6');
  const ids = new Set<string>(); let unknown = 0, ambiguous = 0;
  for (const offset of [0, 50, 100, 150]) {
    const response = await page.request.get(`${HISTORICAL_SEASON_API}/fixtures?limit=50&offset=${offset}`);
    expect(response.status()).toBe(200); const data = await response.json();
    expect(data.provenance.batch_id).toBe(overview.provenance.batch_id);
    for (const row of data.fixtures) { expect(ids.has(row.id)).toBe(false); ids.add(row.id);
      unknown += Number(row.result_availability === 'MISSING'); ambiguous += Number(row.score_semantics.quality === 'AMBIGUOUS_SOURCE_COMPONENTS'); }
  }
  expect(ids.size).toBe(189); expect(unknown).toBe(1); expect(ambiguous).toBe(2);
  await page.goto(path + '?limit=25');
  await expect(page.getByTestId('historical-fixture')).toHaveCount(25);
  await expect(page.getByTestId('historical-count')).toContainText('189');
  await expect(page.getByText('INCOMPLETE', { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('historical-real-overview.png'), fullPage: false });
  await page.getByRole('combobox', { name: 'Stage', exact: true }).selectOption({ label: 'League phase' });
  await expect(page.getByTestId('historical-count')).toContainText('144');
  const teamSelect = page.getByRole('combobox', { name: 'Team', exact: true });
  const selectedTeam = await teamSelect.locator('option').nth(1).getAttribute('value');
  const selectedName = await teamSelect.locator('option').nth(1).textContent();
  await teamSelect.selectOption(selectedTeam!);
  await expect(page.getByTestId('historical-count')).toBeVisible();
  for (const text of await page.getByTestId('historical-fixture').allTextContents()) expect(text).toContain(selectedName!);
  await page.getByRole('tab', { name: 'Participants', exact: true }).click();
  await expect(page.getByRole('tabpanel').getByRole('button')).toHaveCount(36);
  await page.goto(path + '?offset=150'); await expect(page.getByTestId('historical-fixture')).toHaveCount(39);
  const final = page.locator('[data-quality="MISSING_RESULT"]');
  await expect(final).toContainText('Paris Saint-Germain'); await expect(final).toContainText('Internazionale');
  expect(await final.locator('.current-team-line strong').allTextContents()).toEqual(['—', '—']);
  await final.getByText('Source score components', { exact: true }).click();
  await final.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('historical-real-unknown-final.png'), fullPage: false });
  await expect(page.locator('[data-quality="AMBIGUOUS_SOURCE_COMPONENTS"]')).toHaveCount(2);
  await page.locator('[data-quality="AMBIGUOUS_SOURCE_COMPONENTS"]').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('historical-real-ambiguity.png'), fullPage: false });
  await page.getByRole('tab', { name: 'Data quality', exact: true }).click();
  await expect(page.getByTestId('historical-count')).toContainText('394');
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
  await page.getByRole('tab', { name: 'Coverage & limits', exact: true }).click();
  await expect(page.getByText(/Standings unavailable/)).toBeVisible();
  await page.getByTestId('language-selector').selectOption('ru');
  await expect(page.getByRole('heading', { name: 'Покрытие и ограничения' })).toBeVisible();
  await page.getByTestId('language-selector').selectOption('es');
  await expect(page.getByRole('heading', { name: 'Cobertura y límites' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
