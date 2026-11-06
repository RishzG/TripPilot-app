import { expect, type Page, test } from '@playwright/test';

async function signIn(page: Page, persona: string) {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: `Continue as ${persona}`, exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/new$/);
}

test('organiser can cancel or confirm deletion before anyone else joins', async ({
  page,
}) => {
  await signIn(page, 'Priya');
  await page.getByLabel('Trip name').fill('Disposable empty workspace');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/[0-9a-f-]{36}$/);
  const tripUrl = page.url();
  await page.getByRole('button', { name: 'Preferences', exact: true }).click();
  await expect(page.getByLabel('Starting city')).toHaveValue('');
  await expect(page.getByLabel('Starting city')).toHaveAttribute(
    'placeholder',
    'Ex. Chicago, IL',
  );
  await page.getByLabel('Your trip budget (USD)').fill('-1');
  await page
    .getByRole('button', { name: 'Save preferences', exact: true })
    .click();
  await expect(
    page.getByText('Budget cannot be negative.', { exact: true }),
  ).toBeVisible();
  await page.getByLabel('Your trip budget (USD)').fill('');
  await page.getByRole('button', { name: 'Group', exact: true }).click();
  await page
    .getByRole('button', { name: 'Delete workspace', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Keep workspace', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { level: 1, name: 'Disposable empty workspace' }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Delete workspace', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Yes, delete workspace', exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  const missing = await page.request.get(
    new URL(tripUrl).pathname.replace('/trips/', '/api/trips/'),
  );
  expect(missing.status()).toBe(404);
});

test('preferences persist, update the group live, and keep budget and diet private', async ({
  page,
  browser,
  baseURL,
  viewport,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await signIn(page, 'Maya');
  await page.getByLabel('Trip name').fill('Planning workspace');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { level: 1, name: 'Planning workspace' }),
  ).toBeVisible();
  const tripUrl = page.url();
  await page.getByRole('button', { name: 'Group', exact: true }).click();
  const inviteField = page.getByLabel('Invite link address');
  await expect(inviteField).toHaveValue(/\/join\/[^/]+$/);
  const invite = await inviteField.inputValue();
  const friendContext = await browser.newContext({ baseURL, viewport });
  try {
    const friend = await friendContext.newPage();
    await signIn(friend, 'Sam');
    await friend.goto(new URL(invite).pathname);
    await friend
      .getByRole('button', { name: 'Join trip', exact: true })
      .click();
    await friend
      .getByRole('button', { name: 'Preferences', exact: true })
      .click();
    await expect(friend.getByLabel('Starting city')).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Delete workspace', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Delete workspace', exact: true }),
    ).toBeDisabled();
    await expect(
      friend.getByRole('button', { name: 'Delete workspace', exact: true }),
    ).toHaveCount(0);
    await friend.getByLabel('Starting city').fill('Boston');
    await friend
      .getByLabel('Interests', { exact: true })
      .fill('Museums and easy walks');
    await friend.getByLabel('Travel pace').selectOption('relaxed');
    await friend.getByLabel('Your trip budget (USD)').fill('421.37');
    await friend.getByLabel('Dietary notes').fill('Private allergy details');
    await friend
      .getByRole('button', { name: 'Save preferences', exact: true })
      .click();
    await expect(
      friend.getByRole('region', { name: 'Group chat workspace' }),
    ).toBeFocused();
    await expect(
      friend.getByRole('heading', { name: 'Group chat', exact: true }),
    ).toBeInViewport();
    await friend
      .getByRole('button', { name: 'Preferences', exact: true })
      .click();
    await friend.getByText('Group preferences', { exact: true }).click();
    const ownSummary = friend.getByRole('list', { name: 'Group preferences' });
    await expect(ownSummary).toContainText('Boston');
    await expect(ownSummary).toContainText('Museums and easy walks');
    await expect(ownSummary).toContainText('Relaxed pace');
    await friend.reload();
    await expect(friend.getByLabel('Your trip budget (USD)')).toHaveValue(
      '421.37',
    );
    await expect(friend.getByLabel('Dietary notes')).toHaveValue(
      'Private allergy details',
    );

    await page
      .getByRole('button', { name: 'Preferences', exact: true })
      .click();
    await page.getByText('Group preferences', { exact: true }).click();
    const shared = page.getByRole('list', { name: 'Group preferences' });
    await expect(shared).toContainText('Boston');
    await expect(shared).toContainText('Museums and easy walks');
    await expect(page.getByLabel('Your trip budget (USD)')).toHaveValue('');
    await expect(page.getByLabel('Dietary notes')).toHaveValue('');
    const response = await page.request.get(
      new URL(tripUrl).pathname.replace('/trips/', '/api/trips/') +
        '/preferences',
    );
    const raw = await response.text();
    expect(raw).not.toContain('42137');
    expect(raw).not.toContain('Private allergy details');

    // A second update proves SSE invalidation, rather than only initial page load.
    await friend.getByLabel('Starting city').fill('Cambridge');
    await friend
      .getByRole('button', { name: 'Save preferences', exact: true })
      .click();
    await expect(shared).toContainText('Cambridge');
    const size = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      viewport: innerWidth,
    }));
    expect(size.scroll).toBeLessThanOrEqual(size.viewport);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: `test-results/travel-preferences-${viewport?.width}.png`,
      fullPage: true,
    });
    expect(errors).toEqual([]);
    await friend.getByRole('button', { name: 'Group', exact: true }).click();
    await friend
      .getByRole('button', { name: 'Leave trip', exact: true })
      .click();
    await page.getByRole('button', { name: 'Group', exact: true }).click();
    await friend
      .getByRole('button', { name: 'Leave trip', exact: true })
      .click();
    await expect(
      page.getByRole('button', { name: 'Delete workspace', exact: true }),
    ).toBeEnabled();
    await page
      .getByRole('button', { name: 'Delete workspace', exact: true })
      .click();
    await page
      .getByRole('button', { name: 'Yes, delete workspace', exact: true })
      .click();
    await expect(page).toHaveURL(/\/$/);
  } finally {
    await friendContext.close();
  }
});
