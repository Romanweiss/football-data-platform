import { defineConfig } from '@playwright/test';
import smoke from './playwright.config';

// Opt-in live acceptance against the already started production-like stack.
// No server startup, ETL, secret reads or automatic data changes.
process.env.WEB_DELIVERY_MODE = 'production';
export default defineConfig({
  ...smoke,
  outputDir: './test-results/delivery',
  use: { ...smoke.use, baseURL: process.env.WEB_BASE_URL || 'http://127.0.0.1:18090',
    viewport: { width: 1440, height: 900 } },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
  ],
});
