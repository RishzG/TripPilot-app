import { defineConfig } from '@playwright/test';

/**
 * End-to-end smoke on a phone viewport (D-44). It drives the docker compose stack on
 * http://localhost:8000 with DEMO_MODE on, so the sign-in is the demo persona picker and no real
 * PayPal login is involved. Traces are off and screenshots are kept only for a failure, written to
 * the git-ignored test-results folder (T-01-65).
 *
 * Run it at the phase gate: `docker compose up -d --build`, then `npm --prefix web run e2e`.
 * The browser binary is installed once by hand with `npx playwright install chromium`.
 */
export default defineConfig({
  testDir: 'e2e',
  outputDir: 'test-results',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:8000',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'phone',
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
