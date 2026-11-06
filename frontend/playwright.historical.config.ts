import { defineConfig } from '@playwright/test';

// Opt-in local-only browser acceptance against an already prepared isolated API.
if (process.env.PET3C_ISOLATED_BROWSER !== 'true') throw new Error('Explicit isolated historical browser confirmation required');
export default defineConfig({
  testDir: './tests', testMatch: 'historical-live.spec.ts', workers: 1, retries: 0, timeout: 120_000,
  expect: { timeout: 15_000 }, // local docker-exec read-only relay, not a performance assertion
  use: { baseURL: 'http://127.0.0.1:15176', browserName: 'chromium', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
  ],
});
