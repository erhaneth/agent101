import { expect, test } from '@playwright/test'

test('opens a saved report from the library and inspects facts and sources', async ({ page }) => {
  await page.goto('/runs')

  await expect(page.getByRole('heading', { name: 'Your reports' })).toBeVisible()
  await expect(page.getByText('1 saved report')).toBeVisible()

  await page.getByLabel('Search reports').fill('production readiness')
  await page.getByRole('button', { name: /Production readiness checklist for FactCrafter/i }).click()

  await expect(page).toHaveURL(/\/runs\/20260603T120000Z-production-readiness-fixture$/)
  await expect(
    page.getByRole('heading', { name: 'Production readiness checklist for FactCrafter' }),
  ).toBeVisible()
  await expect(page.getByText('96% source-backed')).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Production Readiness Checklist', exact: true }),
  ).toBeVisible()

  await page.getByRole('tab', { name: 'Facts (2)' }).click()
  await expect(
    page.getByText('Production readiness requires shared durable storage for jobs and artifacts.'),
  ).toBeVisible()

  await page.getByRole('tab', { name: 'Sources (2)' }).click()
  await expect(page.getByRole('link', { name: 'FastAPI deployment checklist' })).toBeVisible()
})
