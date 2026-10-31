import { expect, type Page, test } from '@playwright/test';

const BANNER = 'Sandbox — no real money';
const TRIP_NAME = 'Phone test trip';

/** The sandbox banner is on every screen (D-41): assert it wherever the test looks at the app. */
async function expectBanner(page: Page) {
  await expect(
    page.getByRole('status').filter({ hasText: BANNER }),
  ).toBeVisible();
}

/** Sign in as a demo persona from /demo (DEMO_MODE on) and wait for the post-sign-in page. */
async function signInAs(page: Page, name: string) {
  await page.goto('/demo');
  await expectBanner(page);
  await expect(
    page.getByRole('heading', { level: 1, name: 'Try the demo' }),
  ).toBeVisible();
  await page.getByRole('button', { name: `Continue as ${name}` }).click();
  await expect(page).toHaveURL(/\/trips\/new$/);
  await expectBanner(page);
}

async function expectBothMembers(page: Page) {
  const members = page.getByRole('list', { name: "Who's in" });
  await expect(members).toContainText('Maya');
  await expect(members).toContainText('Sam');
}

test('Maya starts a trip and Sam joins from the invite on a phone', async ({
  page,
  browser,
}) => {
  const { baseURL, viewport, isMobile, hasTouch } = test.info().project.use;

  // Maya starts the trip.
  await signInAs(page, 'Maya');
  await page.getByLabel('Trip name').fill(TRIP_NAME);
  await page.getByRole('button', { name: 'Start the trip' }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);
  await expect(
    page.getByRole('heading', { level: 1, name: TRIP_NAME }),
  ).toBeVisible();
  await expectBanner(page);
  await expect(page.getByText('1 of 12 in')).toBeVisible();

  // She reads the invite link from the invite card once it has loaded.
  const inviteField = page.getByLabel('Invite link address');
  await expect(inviteField).toHaveValue(/\/join\/[^/]+$/);
  const invitePath = new URL(await inviteField.inputValue()).pathname;

  // Sam is a second browser: a separate context with its own cookies and the same phone viewport.
  const samContext = await browser.newContext({
    baseURL,
    viewport,
    isMobile,
    hasTouch,
  });
  try {
    const sam = await samContext.newPage();
    await signInAs(sam, 'Sam');

    await sam.goto(invitePath);
    await expectBanner(sam);
    await expect(
      sam.getByRole('heading', { name: `Join ${TRIP_NAME}?` }),
    ).toBeVisible();
    await sam.getByRole('button', { name: 'Join trip' }).click();

    await expect(sam).toHaveURL(/\/trips\/[^/]+$/);
    await expect(
      sam.getByRole('heading', { level: 1, name: TRIP_NAME }),
    ).toBeVisible();
    await expectBanner(sam);
    await expectBothMembers(sam);

    // Maya sees Sam arrive live, without reloading.
    await expect(page.getByText('2 of 12 in')).toBeVisible();
    await expectBothMembers(page);
    await expectBanner(page);
  } finally {
    await samContext.close();
  }
});
