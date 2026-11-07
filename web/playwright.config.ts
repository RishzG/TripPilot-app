import { defineConfig } from '@playwright/test';

/**
 * End-to-end smoke: the retained phone join test (D-44), plus planning-workspace tests at
 * the recorded 1366x768 and 1920x1080 desktop sizes. It drives the docker compose stack on
 * http://localhost:8000 with DEMO_MODE on, so the sign-in is the demo persona picker and no real
 * PayPal login is involved. Traces are off and screenshots are kept only for a failure, written to
 * the git-ignored test-results folder (T-01-65).
 *
 * Run it at the phase gate: `docker compose up -d --build`, then `npm --prefix web run e2e`.
 * Desktop planning checks: append `-- --project desktop-laptop --project desktop-wide`.
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
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:8000',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'phone',
      testMatch: 'phone-join.spec.ts',
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: 'desktop-laptop',
      testMatch: [
        'travel-preferences.spec.ts',
        'group-chat.spec.ts',
        'workspace-layout.spec.ts',
        'private-concerns.spec.ts',
        'itinerary.spec.ts',
        'pilot.spec.ts',
      ],
      use: { viewport: { width: 1366, height: 768 } },
    },
    {
      name: 'desktop-wide',
      testMatch: [
        'travel-preferences.spec.ts',
        'group-chat.spec.ts',
        'workspace-layout.spec.ts',
        'private-concerns.spec.ts',
        'itinerary.spec.ts',
        'pilot.spec.ts',
      ],
      use: { viewport: { width: 1920, height: 1080 } },
    },
  ],
});
