import { expect, test } from '@playwright/test'

test('approves an awaiting human review from the job page', async ({ page }) => {
  await page.goto('/jobs/11111111-1111-4111-8111-111111111111')

  await expect(page.getByRole('heading', { name: 'Human review approval E2E fixture' })).toBeVisible()
  await expect(page.getByText('Needs your OK')).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'Quick check before we write' })).toBeVisible()
  await expect(
    page.getByText('Human review approval should unblock the web workflow.'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Looks good — write report' }).click()

  await expect(page.getByRole('dialog', { name: 'Quick check before we write' })).toBeHidden()
  await expect(page.getByText('In progress')).toBeVisible()
})
