import { expect, test } from '@playwright/test';
import type { components } from '../src/lib/api-types';

test('a shared sample plan can be selected and revised only after affected members accept', async ({
  page,
  browser,
  baseURL,
  viewport,
}) => {
  test.setTimeout(90_000);
  page.setDefaultTimeout(10_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/demo');
  await page
    .getByRole('button', { name: 'Continue as Maya', exact: true })
    .click();
  await page.getByLabel('Trip name').fill('Shared planning check');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await expect(page).toHaveURL(/\/trips\/[0-9a-f-]{36}$/);
  const tripPath = new URL(page.url()).pathname;
  const apiPath = tripPath.replace('/trips/', '/api/trips/');
  const invite = await (await page.request.get(`${apiPath}/invite`)).json();
  const memberContext = await browser.newContext({ baseURL, viewport });
  const member = await memberContext.newPage();
  member.on('pageerror', (error) => errors.push(error.message));
  try {
    await member.goto('/demo');
    await member
      .getByRole('button', { name: 'Continue as Sam', exact: true })
      .click();
    await expect(member).toHaveURL(/\/trips\/new$/);
    await member.goto(new URL(invite.url).pathname);
    await member
      .getByRole('button', { name: 'Join trip', exact: true })
      .click();
    await expect(member.getByLabel('Message the group')).toBeVisible();
    await page
      .getByRole('navigation', { name: 'Trip workspace', exact: true })
      .getByRole('button', { name: 'Plan', exact: true })
      .click();
    await page.getByLabel('Destination', { exact: true }).fill('Chicago');
    await page.getByLabel('Start date', { exact: true }).fill('2026-11-07');
    await page.getByLabel('End date', { exact: true }).fill('2026-11-07');
    await page
      .getByLabel('Trip timezone', { exact: false })
      .fill('America/Chicago');
    await page.getByRole('button', { name: 'Save trip details' }).click();
    await expect(
      page
        .getByRole('region', { name: 'Shared trip details' })
        .locator('summary'),
    ).toContainText('Chicago · 2026-11-07');
    await page.getByRole('button', { name: 'Load Chicago sample' }).click();
    await expect(
      page.getByText('Illustrative Chicago sample.', { exact: true }),
    ).toBeVisible();
    const state: components['schemas']['PlanningView'] = await (
      await page.request.get(`${apiPath}/planning`, { timeout: 5000 })
    ).json();
    const original = state.versions.find(
      (version) => version.title === 'Chicago sample day',
    );
    expect(original).toBeTruthy();
    await page
      .getByRole('combobox', { name: 'Plan version', exact: true })
      .selectOption(original?.id ?? '');
    await page.getByRole('button', { name: 'Select sample for demo' }).click();
    await expect(
      page.getByText('Selected plan', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByTitle('Itinerary map: Millennium Park'),
    ).toBeVisible();
    await page.screenshot({
      path: `test-results/planning-selected-${viewport?.width}.png`,
      fullPage: true,
    });
    await page
      .getByRole('button', { name: 'Cancel / find alternatives' })
      .nth(1)
      .click();
    const alternatives = page.getByRole('region', {
      name: 'Cancellation alternatives',
    });
    await expect(alternatives).toContainText('Chicago Cultural Center');
    await alternatives
      .getByRole('button', { name: 'Propose alternative' })
      .click();
    const changes = page.getByRole('region', { name: 'Plan change proposals' });
    await expect(changes).toContainText('Awaiting response');
    await changes.getByRole('button', { name: 'Accept this revision' }).click();
    await expect(
      changes.getByRole('button', { name: 'Apply accepted revision' }),
    ).toBeDisabled();
    await member
      .getByRole('navigation', { name: 'Trip workspace', exact: true })
      .getByRole('button', { name: 'Plan', exact: true })
      .click();
    const memberChanges = member.getByRole('region', {
      name: 'Plan change proposals',
    });
    await memberChanges
      .getByRole('button', { name: 'Review revision' })
      .click();
    await expect(
      member.getByRole('heading', {
        name: '2. Chicago Cultural Center',
        exact: true,
      }),
    ).toBeVisible();
    await memberChanges
      .getByRole('button', { name: 'Accept this revision' })
      .click();
    await expect(
      changes.getByRole('button', { name: 'Apply accepted revision' }),
    ).toBeEnabled();
    await changes
      .getByRole('button', { name: 'Apply accepted revision' })
      .click();
    await expect(changes.getByText('accepted', { exact: true })).toBeVisible();
    const final: components['schemas']['PlanningView'] = await (
      await page.request.get(`${apiPath}/planning`, { timeout: 5000 })
    ).json();
    const selected = final.versions.find(
      (version) => version.id === final.selected_id,
    );
    expect(selected?.items[0]?.id).toBe(original?.items[0]?.id);
    expect(selected?.total_cents).toBe(0);
    expect(
      final.versions.find((version) => version.id === original?.id)?.items[1]
        ?.title,
    ).toBe('Art Institute visit');
    expect(errors).toEqual([]);
    await page.screenshot({
      path: `test-results/planning-revised-${viewport?.width}.png`,
      fullPage: true,
    });
  } finally {
    await member.request
      .post(`${apiPath}/leave`, { timeout: 3000 })
      .catch(() => undefined);
    await page.request
      .delete(apiPath, { timeout: 3000 })
      .catch(() => undefined);
    await memberContext.close();
  }
});
