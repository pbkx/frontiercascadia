import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://localhost:3000', viewport: { width: 1440, height: 900 }, screenshot: 'only-on-failure' },
});
