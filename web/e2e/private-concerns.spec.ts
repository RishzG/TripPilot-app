import { type Browser, expect, type Page, test } from '@playwright/test';

async function signIn(page: Page, persona: string) {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: `Continue as ${persona}`, exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/new$/);
}

async function joinAs(
  browser: Browser,
  persona: string,
  invitePath: string,
  baseURL: string | undefined,
  viewport: { width: number; height: number } | null,
) {
  const context = await browser.newContext({ baseURL, viewport });
  const page = await context.newPage();
  await signIn(page, persona);
  await page.goto(invitePath);
  await page.getByRole('button', { name: 'Join trip', exact: true }).click();
  await expect(page.getByLabel('Message the group')).toBeVisible();
  return { context, page };
}

test('private concerns stay private and update every member live', async ({
  page,
  browser,
  baseURL,
  viewport,
}) => {
  // Three signed-in people take longer than the default 30 s.
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await signIn(page, 'Maya');
  await page.getByLabel('Trip name').fill('Concerns check');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/[0-9a-f-]{36}$/);
  const apiPath = new URL(page.url()).pathname.replace(
    '/trips/',
    '/api/trips/',
  );
  await page.getByRole('button', { name: 'Group', exact: true }).click();
  const field = page.getByLabel('Invite link address');
  await expect(field).toHaveValue(/\/join\/[^/]+$/);
  const invitePath = new URL(await field.inputValue()).pathname;

  const sam = await joinAs(browser, 'Sam', invitePath, baseURL, viewport);
  const ana = await joinAs(browser, 'Ana', invitePath, baseURL, viewport);
  try {
    const concernText = 'The boat tour is more than I want to spend';
    const leaderText = 'Leader concern: early flights';
    // Sam and Ana are already on Chat, where the concerns tile is open beside the chat.
    await page.getByRole('button', { name: 'Chat', exact: true }).click();

    // Sam shares a concern; the leader sees it live without a name, Ana sees nothing.
    await sam.page.getByLabel('Share a private concern').fill(concernText);
    await sam.page
      .getByRole('button', { name: 'Send privately', exact: true })
      .click();
    const anonymous = page.getByRole('region', {
      name: 'From the group (anonymous)',
    });
    await expect(anonymous).toContainText(concernText);
    await expect(anonymous).not.toContainText('Sam');
    await expect(ana.page.getByText(concernText)).toHaveCount(0);

    // The leader's own concern stays in their own list, never in the anonymous one.
    await page.getByLabel('Share a private concern').fill(leaderText);
    await page
      .getByRole('button', { name: 'Send privately', exact: true })
      .click();
    const yours = page.getByRole('region', { name: 'Your concerns' });
    await expect(yours).toContainText(leaderText);
    await expect(yours).toContainText('You');
    await expect(anonymous).not.toContainText(leaderText);
    await expect(anonymous).toContainText(concernText);
    await expect(ana.page.getByText(leaderText)).toHaveCount(0);
    await expect(ana.page.getByText(concernText)).toHaveCount(0);
    const anaView = await (
      await ana.page.request.get(`${apiPath}/concerns`)
    ).json();
    expect(anaView).toEqual({ mine: [], anonymous: null });
    const leaderView = await (
      await page.request.get(`${apiPath}/concerns`)
    ).json();
    expect(
      leaderView.mine.map((item: { content: string }) => item.content),
    ).toEqual([leaderText]);
    expect(
      leaderView.anonymous.map((item: { content: string }) => item.content),
    ).toEqual([concernText]);
    expect(Object.keys(leaderView.anonymous[0]).sort()).toEqual([
      'content',
      'submitted_on',
    ]);

    // Withdrawing removes it from the leader's list live.
    await sam.page.getByRole('button', { name: /^Withdraw concern/ }).click();
    await expect(anonymous).not.toContainText(concernText);
    await expect(anonymous).toContainText('Nothing from the group yet.');

    expect(errors).toEqual([]);
  } finally {
    await sam.context.close();
    await ana.context.close();
  }
});
