import { expect, test } from '@playwright/test'

test('creates and cancels a queued research job', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: /ask anything/i })).toBeVisible()

  const goal = `E2E production readiness smoke ${Date.now()}`
  await page.getByLabel('Your question').fill(goal)
  await page.getByRole('button', { name: 'Research' }).click()

  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/)
  await expect(page.getByRole('heading', { name: goal })).toBeVisible()
  await expect(page.getByText('Starting…')).toBeVisible()

  await page.getByRole('button', { name: 'Cancel queued job' }).click()

  await expect(page.getByText('Canceled', { exact: true })).toBeVisible()
  await expect(page.getByText('This job was canceled before it started.')).toBeVisible()
})
