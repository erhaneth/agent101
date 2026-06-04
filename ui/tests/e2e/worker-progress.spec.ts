import { expect, test } from '@playwright/test'
import { spawn } from 'node:child_process'

function startSimulatedWorker(jobId: string) {
  const worker = spawn('../.venv/bin/python', ['../scripts/simulate_e2e_worker.py', jobId], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PYTHONPATH: process.env.PYTHONPATH ?? '..',
    },
    stdio: 'inherit',
  })
  const done = new Promise<void>((resolve, reject) => {
    worker.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`simulated worker exited with ${code}`))
    })
    worker.on('error', reject)
  })
  return { done }
}

test('shows active worker progress and renders the completed report', async ({ page }) => {
  await page.goto('/')

  const goal = `E2E active worker progress ${Date.now()}`
  await page.getByLabel('Your question').fill(goal)
  await page.getByRole('button', { name: 'Research' }).click()
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/)

  const jobId = page.url().split('/jobs/')[1]
  const worker = startSimulatedWorker(jobId)

  await expect(page.getByText('In progress')).toBeVisible()
  await expect(page.locator('.pipeline-compact-label').filter({ hasText: 'Searching the web' })).toBeVisible()
  await expect(page.getByText(/steps complete/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Synthetic E2E Report' })).toBeVisible()
  await expect(
    page.getByText('This deterministic report proves the browser can follow active worker progress'),
  ).toBeVisible()

  await worker.done
})
