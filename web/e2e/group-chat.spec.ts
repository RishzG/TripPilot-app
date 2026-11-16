import { expect, type Page, test } from '@playwright/test';

async function signIn(page: Page, persona: string) {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: `Continue as ${persona}`, exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/new$/);
}

test('group chat persists, updates live, retries once and loads older history', async ({
  page,
  browser,
  baseURL,
  viewport,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await signIn(page, 'Maya');
  await page.getByLabel('Trip name').fill('Chat browser check');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/[0-9a-f-]{36}$/);
  const tripPath = new URL(page.url()).pathname;
  const apiPath = tripPath.replace('/trips/', '/api/trips/');
  await page.getByRole('button', { name: 'Group', exact: true }).click();
  const field = page.getByLabel('Invite link address');
  await expect(field).toHaveValue(/\/join\/[^/]+$/);
  const invitePath = new URL(await field.inputValue()).pathname;
  await page.getByRole('button', { name: 'Chat', exact: true }).click();
  const friendContext = await browser.newContext({ baseURL, viewport });
  const friend = await friendContext.newPage();
  try {
    await signIn(friend, 'Sam');
    await friend.goto(invitePath);
    await friend
      .getByRole('button', { name: 'Join trip', exact: true })
      .click();
    await expect(friend.getByLabel('Message the group')).toBeVisible();
    await page
      .getByLabel('Message the group')
      .fill('Let’s visit the museum.\nThen get lunch.');
    await page
      .getByRole('button', { name: 'Send message', exact: true })
      .click();
    const samLog = friend.getByRole('log', { name: 'Group messages' });
    await expect(samLog).toContainText('Let’s visit the museum.');
    await expect(samLog).toContainText('Maya');
    await friend
      .getByLabel('Message the group')
      .fill('Sounds good! I prefer a relaxed afternoon.');
    await friend
      .getByRole('button', { name: 'Send message', exact: true })
      .click();
    await expect(page.getByRole('log')).toContainText(
      'Sounds good! I prefer a relaxed afternoon.',
    );
    // Each session puts its own bubble on the right, regardless of who sent first.
    const mayaLog = page.getByRole('log', { name: 'Group messages' });
    for (const [log, own, incoming] of [
      [mayaLog, 'Let’s visit the museum.', 'Sounds good!'],
      [samLog, 'Sounds good!', 'Let’s visit the museum.'],
    ] as const) {
      await expect(log.getByText('You', { exact: true })).toHaveCount(0);
      const outgoingRow = log.getByRole('listitem').filter({ hasText: own });
      const incomingRow = log
        .getByRole('listitem')
        .filter({ hasText: incoming });
      await expect(outgoingRow.locator('[aria-hidden="true"]')).toHaveCount(0);
      await expect(incomingRow.locator('[aria-hidden="true"]')).toHaveCount(1);
      await expect(log.getByRole('listitem')).toHaveCount(3);
      await expect(outgoingRow.locator('time')).toBeVisible();
      await expect(incomingRow.locator('time')).toBeVisible();
      await expect(async () => {
        const ownBox = await log.getByText(own).boundingBox();
        const incomingBox = await log.getByText(incoming).boundingBox();
        expect(ownBox?.x ?? 0).toBeGreaterThan(incomingBox?.x ?? 0);
      }).toPass({ timeout: 5000 });
    }
    await page.getByRole('button', { name: 'Plan', exact: true }).click();
    await page.screenshot({
      path: `test-results/workspace-${viewport?.width}.png`,
      fullPage: true,
      animations: 'disabled',
    });
    await page.getByRole('button', { name: 'Chat', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Group chat', exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByRole('log')).toContainText(
      'Let’s visit the museum.',
    );

    // Commit the first POST, but discard its response to simulate an ambiguous network failure.
    let discardResponse = true;
    await page.route('**/api/trips/*/messages*', async (route) => {
      if (route.request().method() === 'POST' && discardResponse) {
        discardResponse = false;
        await route.fetch();
        await route.abort('failed');
      } else {
        await route.continue();
      }
    });
    await page.getByLabel('Message the group').fill('Retry this message once.');
    await page
      .getByRole('button', { name: 'Send message', exact: true })
      .click();
    await expect(
      page.getByText(
        'Couldn’t send your message. Your draft is still here; try again.',
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.getByLabel('Message the group')).toHaveValue(
      'Retry this message once.',
    );
    await page
      .getByRole('button', { name: 'Send message', exact: true })
      .click();
    await expect(page.getByLabel('Message the group')).toHaveValue('');
    const persisted = await page.request.get(`${apiPath}/messages`);
    expect(
      (await persisted.json()).messages.filter(
        (m: { content: string }) => m.content === 'Retry this message once.',
      ),
    ).toHaveLength(1);
    await page.unroute('**/api/trips/*/messages*');

    for (let index = 0; index < 31; index++) {
      const seeded = await page.request.post(`${apiPath}/messages`, {
        data: {
          content: `History message ${index}`,
          client_message_id: crypto.randomUUID(),
        },
      });
      expect(seeded.status()).toBe(201);
    }
    await page.reload();
    await page
      .getByRole('button', { name: 'Load older messages', exact: true })
      .click();
    await expect(page.getByRole('log')).toContainText(
      'Let’s visit the museum.',
    );
    await expect(
      page
        .getByRole('log')
        .getByText('Retry this message once.', { exact: true }),
    ).toHaveCount(1);
    await page
      .locator('[data-slot="card"]')
      .filter({
        has: page.getByRole('heading', { name: 'Group chat', exact: true }),
      })
      .screenshot({ path: `test-results/group-chat-${viewport?.width}.png` });
    expect(errors).toEqual([]);
  } finally {
    await friend.request.post(`${apiPath}/leave`);
    await friendContext.close();
    await page.request.delete(apiPath);
  }
});
