import { expect, type Page, test } from '@playwright/test';

async function signIn(page: Page, name: string) {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: `Continue as ${name}`, exact: true })
    .click();
}

test('organiser saves revisions and members see the exact split and history', async ({
  page,
  browser,
  baseURL,
  viewport,
}) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await signIn(page, 'Maya');
  await page.getByLabel('Trip name').fill('Itinerary check');
  await page.getByRole('button', { name: 'Start the trip' }).click();
  await page.getByRole('button', { name: 'Group', exact: true }).click();
  const invite = page.getByLabel('Invite link address');
  await expect(invite).toHaveValue(/\/join\/[^/]+$/);
  const invitePath = new URL(await invite.inputValue()).pathname;

  const context = await browser.newContext({ baseURL, viewport });
  try {
    const member = await context.newPage();
    member.on('pageerror', (error) => errors.push(error.message));
    await signIn(member, 'Sam');
    await member.goto(invitePath);
    await member
      .getByRole('button', { name: 'Join trip', exact: true })
      .click();
    await member.getByRole('button', { name: 'Plan', exact: true }).click();
    await expect(member.getByText('No itinerary yet')).toBeVisible();

    await expect(page.getByText('2 of 12 in')).toBeVisible();
    await page.getByRole('button', { name: 'Plan', exact: true }).click();
    await page.getByRole('button', { name: 'Create draft' }).click();
    await page.getByRole('button', { name: 'Add item' }).click();
    await page.getByLabel('Activity').fill('Museum');
    await page.getByLabel('Date', { exact: true }).fill('2026-12-01');
    await page.getByLabel('Location (optional)').fill('Old town');
    await page.getByLabel('Estimated total (USD)').fill('10.01');
    await page.getByRole('button', { name: 'Save draft version' }).click();

    const shares = member.getByRole('list', {
      name: 'Estimated shares for Museum',
    });
    await expect(shares).toContainText('$5.00');
    await expect(shares).toContainText('$5.01');
    await expect(member.getByText('Draft v1 of 1')).toBeVisible();
    await expect(
      member.getByRole('button', { name: 'Revise itinerary' }),
    ).toHaveCount(0);

    await page.getByRole('button', { name: 'Revise itinerary' }).click();
    await page.getByLabel('Estimated total (USD)').fill('12.50');
    await page.getByRole('checkbox', { name: 'Sam' }).uncheck();
    await page.getByRole('button', { name: 'Save draft version' }).click();
    await expect(member.getByText('Draft v2 of 2')).toBeVisible();
    await expect(shares).toContainText('Maya · $12.50');
    await expect(shares.getByRole('listitem')).toHaveCount(1);

    await member.reload();
    await expect(shares).toContainText('Maya · $12.50');
    await member.getByRole('button', { name: 'Previous', exact: true }).click();
    await expect(member.getByText('Draft v1 of 2')).toBeVisible();
    await expect(shares.getByRole('listitem')).toHaveCount(2);
    await expect(shares).toContainText('$5.01');
    await member
      .getByRole('button', { name: 'Latest draft', exact: true })
      .click();
    await expect(shares).toContainText('Maya · $12.50');
    expect(errors).toEqual([]);
  } finally {
    await context.close();
  }
});
