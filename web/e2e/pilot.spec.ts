import { expect, test } from '@playwright/test';

test('organiser turns public chat into a sourced Pilot draft', async ({
  page,
}) => {
  await page.goto('/demo');
  await page
    .getByRole('button', { name: 'Continue as Maya', exact: true })
    .click();
  await page.getByLabel('Trip name').fill('London Pilot check');
  await page
    .getByRole('button', { name: 'Start the trip', exact: true })
    .click();
  await page
    .getByLabel('Message the group')
    .fill('Art, fashion and design, then a park walk');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('log')).toContainText('then a park walk');

  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await page.getByRole('button', { name: 'Set trip details' }).click();
  await page.getByLabel('Destination').fill('London');
  await page.getByLabel('Start date').fill('2026-12-01');
  await page.getByLabel('End date').fill('2026-12-02');
  await page.getByRole('button', { name: 'Save trip details' }).click();
  await page.getByRole('button', { name: 'Start Pilot' }).click();
  await page
    .getByRole('button', { name: 'Open Pilot draft v1' })
    .click({ timeout: 15_000 });
  await expect(
    page.getByRole('heading', { name: 'V&A South Kensington', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('link', {
      name: 'V&A South Kensington visitor information',
    }),
  ).toHaveAttribute('href', 'https://www.vam.ac.uk/south-kensington');
  await expect(
    page.getByRole('heading', { name: 'Hyde Park lakeside walk', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('1 item has no estimate yet.')).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('link', { name: 'Hyde Park visitor information' }),
  ).toBeVisible();
  await expect(page.getByText('Draft v1 of 1')).toBeVisible();
});
