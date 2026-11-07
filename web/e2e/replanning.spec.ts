import { expect, type Page, test } from '@playwright/test';

async function signIn(page: Page, persona: string) {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: `Continue as ${persona}`, exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/new$/);
}

test('replacement waits for fresh acceptance after a member opts out', async ({
  page,
  browser,
  baseURL,
  viewport,
}) => {
  test.setTimeout(60_000);
  await signIn(page, 'Maya');
  await page.getByLabel('Trip name').fill('Replanning check');
  await page.getByRole('button', { name: 'Start the trip' }).click();
  await page.getByRole('button', { name: 'Group', exact: true }).click();
  const invite = page.getByLabel('Invite link address');
  await expect(invite).toHaveValue(/\/join\/[^/]+$/);
  const invitePath = new URL(await invite.inputValue()).pathname;
  const samContext = await browser.newContext({ baseURL, viewport });
  const anaContext = await browser.newContext({ baseURL, viewport });
  try {
    const sam = await samContext.newPage();
    const ana = await anaContext.newPage();
    for (const [friend, name] of [
      [sam, 'Sam'],
      [ana, 'Ana'],
    ] as const) {
      await signIn(friend, name);
      await friend.goto(invitePath);
      await friend
        .getByRole('button', { name: 'Join trip', exact: true })
        .click();
      await friend.getByRole('button', { name: 'Plan', exact: true }).click();
    }

    await expect(page.getByText('3 of 12 in')).toBeVisible();
    await page.getByRole('button', { name: 'Plan', exact: true }).click();
    await page.getByRole('button', { name: 'Create draft' }).click();
    await page.getByRole('button', { name: 'Add item' }).click();
    await page.getByLabel('Activity').fill('Museum visit');
    await page.getByLabel('Date', { exact: true }).fill('2026-12-01');
    await page.getByLabel('Estimated total (USD)').fill('0');
    await page.getByRole('button', { name: 'Save draft version' }).click();
    await page.getByRole('button', { name: 'Set as current plan' }).click();

    await page
      .getByRole('button', { name: 'Propose activity replacement' })
      .click();
    await page
      .getByLabel('Replacement activity', { exact: true })
      .fill('Guided tour');
    await page.getByLabel('Replacement estimate (USD)').fill('100.01');
    await page
      .getByRole('button', { name: 'Send replacement proposal' })
      .click();
    const comparison = page.getByRole('region', {
      name: 'Activity replacement proposal',
    });
    await expect(comparison).toContainText('Museum visit');
    await expect(comparison).toContainText('Guided tour');
    await page
      .getByRole('button', { name: 'Accept revision', exact: true })
      .click();
    await expect(comparison).toContainText('1 of 3 affected members accepted');
    await sam
      .getByRole('button', { name: 'Opt out of activity', exact: true })
      .click();

    await expect(comparison).toContainText('0 of 2 affected members accepted');
    await expect(comparison).toContainText('$50.00');
    await expect(comparison).toContainText('$50.01');
    await expect(comparison.getByRole('row', { name: /Sam/ })).toContainText(
      'Opted out',
    );
    await expect(page.getByText('Current version v1 of 1')).toBeVisible();

    await ana
      .getByRole('button', { name: 'Accept revision', exact: true })
      .click();
    await expect(comparison).toContainText('1 of 2 affected members accepted');
    await expect(page.getByText('Current version v1 of 1')).toBeVisible();
    await page
      .getByRole('button', { name: 'Accept revision', exact: true })
      .click();
    await expect(comparison).toContainText('Applied to plan v2');
    await expect(sam.getByText('Current version v2 of 2')).toBeVisible();
    const shares = sam.getByRole('list', {
      name: 'Estimated shares for Guided tour',
    });
    await expect(shares.getByRole('listitem')).toHaveCount(2);
    await expect(shares).not.toContainText('Sam');
    await sam.getByRole('button', { name: 'Previous', exact: true }).click();
    await expect(
      sam.getByRole('heading', { name: 'Museum visit', exact: true }),
    ).toBeVisible();
    await expect(
      sam
        .getByRole('list', { name: 'Estimated shares for Museum visit' })
        .getByRole('listitem'),
    ).toHaveCount(3);
  } finally {
    await samContext.close();
    await anaContext.close();
  }
});
