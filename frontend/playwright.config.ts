import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/smoke', workers: 1, retries: 0, timeout: 30_000,
  use: {
    baseURL: process.env.WEB_BASE_URL || 'http://127.0.0.1:15173',
    channel: process.env.PLAYWRIGHT_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium'),
    viewport: { width: 1440, height: 1100 }, screenshot: 'only-on-failure',
  },
});
