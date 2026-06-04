import { expect, test } from '@playwright/test'

test('redirects unauthenticated users to Google login when auth is required', async ({ page }) => {
  await page.route('**/api/auth/config', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ auth_required: true, google_enabled: true }),
    }),
  )
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ authenticated: false, user: null }),
    }),
  )
  await page.route('**/api/auth/google', (route) =>
    route.fulfill({
      contentType: 'text/plain',
      body: 'google auth handoff',
    }),
  )

  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeEnabled()

  await page.getByRole('button', { name: 'Continue with Google' }).click()
  await expect(page).toHaveURL(/\/api\/auth\/google$/)
})
