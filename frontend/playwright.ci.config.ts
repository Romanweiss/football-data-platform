import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/smoke', testMatch: ['**/context.spec.ts', '**/pass-map.spec.ts', '**/pressure-heatmap.spec.ts'],
  grep: /synthetic contexts:/,
  workers: 1, retries: 0, timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:15174', browserName: 'chromium', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
  ],
  // A separate port and fresh preview server: no running developer backend is used.
  webServer: {
    command: 'npm exec vite -- preview --host 127.0.0.1 --port 15174 --strictPort',
    url: 'http://127.0.0.1:15174', reuseExistingServer: false, timeout: 30_000,
  },
});
