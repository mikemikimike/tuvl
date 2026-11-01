import { defineConfig, devices } from '@playwright/test'

// Smoke tests against a running `tuvl dev --auto-login` (see scripts/insight-smoke.sh).
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.TUVL_SMOKE_URL ?? 'http://127.0.0.1:8890',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, testIgnore: /code-source|writes-/ },
    // saving Python reloads the dev server, which would cut a run another test has open: these go last
    { name: 'writes-files', use: { ...devices['Desktop Chrome'] }, testMatch: /code-source|writes-/, dependencies: ['chromium'] },
  ],
})
