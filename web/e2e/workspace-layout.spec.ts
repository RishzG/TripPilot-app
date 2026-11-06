import { expect, test } from '@playwright/test';

test('desktop workspace keeps navigation, chat and plan usable and preserves drafts', async ({
  page,
  viewport,
}) => {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: 'Continue as Leo', exact: true })
    .click();
  await page.getByLabel('Trip name').fill('Weekend with friends');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/[0-9a-f-]{36}$/);
  const path = new URL(page.url()).pathname.replace('/trips/', '/api/trips/');
  try {
    const navigation = page.getByRole('navigation', {
      name: 'Trip workspace',
      exact: true,
    });
    await expect(
      navigation.getByRole('button', { name: 'Chat', exact: true }),
    ).toHaveAttribute('aria-current', 'page');
    const chat = page.getByRole('region', {
      name: 'Group chat workspace',
      exact: true,
    });
    const plan = page.locator('[aria-labelledby="empty-plan-title"]');
    await expect(
      page.getByRole('button', { name: 'Send message', exact: true }),
    ).toBeInViewport();
    await expect(plan).toHaveCount(0);
    await page
      .getByLabel('Message the group')
      .fill('A relaxed day by the lake would be nice.');
    await page
      .getByRole('button', { name: 'Send message', exact: true })
      .click();
    await expect(page.getByRole('log')).toContainText(
      'A relaxed day by the lake would be nice.',
    );
    const chatBounds = await chat.boundingBox();
    expect(chatBounds).not.toBeNull();
    expect(chatBounds?.width).toBeGreaterThan(900);
    const messageBounds = await page.getByRole('log').boundingBox();
    expect(messageBounds?.height).toBeGreaterThan(
      (chatBounds?.height ?? 0) * 0.55,
    );
    await page.getByLabel('Message the group').fill('I’d love a lake walk.');
    await page.screenshot({
      path: `test-results/workspace-layout-${viewport?.width}.png`,
      fullPage: true,
      animations: 'disabled',
    });
    await navigation.getByRole('button', { name: 'Plan', exact: true }).click();
    await expect(plan).toBeVisible();
    await expect(chat).toBeHidden();
    await expect(
      page.getByText('Nobody pays anything yet.', { exact: true }),
    ).toBeInViewport();
    await page.screenshot({
      path: `test-results/workspace-plan-${viewport?.width}.png`,
      fullPage: true,
      animations: 'disabled',
    });

    await navigation
      .getByRole('button', { name: 'Preferences', exact: true })
      .click();
    await page.getByLabel('Starting city', { exact: true }).fill('Madison');
    await expect(chat).toBeHidden();
    await navigation
      .getByRole('button', { name: 'Group', exact: true })
      .focus();
    await navigation
      .getByRole('button', { name: 'Group', exact: true })
      .press('Enter');
    await expect(
      page.getByRole('heading', { name: 'Your group', exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel('Invite link address')).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Delete workspace', exact: true }),
    ).toBeEnabled();
    await page.screenshot({
      path: `test-results/workspace-group-${viewport?.width}.png`,
      fullPage: true,
      animations: 'disabled',
    });
    await navigation.getByRole('button', { name: 'Chat', exact: true }).click();
    await expect(page.getByLabel('Message the group')).toBeVisible();
    await expect(page.getByLabel('Message the group')).toHaveValue(
      'I’d love a lake walk.',
    );
    await navigation
      .getByRole('button', { name: 'Preferences', exact: true })
      .click();
    await expect(page.getByLabel('Starting city', { exact: true })).toHaveValue(
      'Madison',
    );
    await expect(
      page.getByLabel('Starting city', { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `test-results/workspace-preferences-${viewport?.width}.png`,
      fullPage: true,
      animations: 'disabled',
    });
    await page
      .getByRole('button', { name: 'Save preferences', exact: true })
      .click();
    await expect(
      navigation.getByRole('button', { name: 'Chat', exact: true }),
    ).toHaveAttribute('aria-current', 'page');
    await expect(page.getByLabel('Message the group')).toHaveValue(
      'I’d love a lake walk.',
    );

    await navigation.getByRole('button', { name: /^Bookings/ }).click();
    await expect(
      page.getByText('Booking tools are not available yet.', { exact: false }),
    ).toBeVisible();
    await navigation.getByRole('button', { name: /^Splits/ }).click();
    await expect(
      page.getByText('Expense and payment tools are not available yet.', {
        exact: false,
      }),
    ).toBeVisible();
    await navigation
      .getByRole('button', { name: 'Trip overview', exact: true })
      .click();
    await expect(
      page.getByRole('heading', { name: 'Trip details', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Manage group', exact: true }),
    ).toHaveCount(0);
    await navigation.getByRole('button', { name: 'Plan', exact: true }).click();
    const width = await page.evaluate(() => ({
      content: document.documentElement.scrollWidth,
      window: innerWidth,
    }));
    expect(width.content).toBeLessThanOrEqual(width.window);
    await expect(chat).toBeHidden();
    await expect(plan).toBeVisible();
  } finally {
    await page.request.delete(path);
  }
});
