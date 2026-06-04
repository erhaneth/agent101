import { defineConfig, devices } from '@playwright/test'

const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT ?? '18100'
const frontendPort = process.env.PLAYWRIGHT_FRONTEND_PORT ?? '15173'
const backendUrl = `http://127.0.0.1:${backendPort}`
const frontendUrl = `http://127.0.0.1:${frontendPort}`
const reuseExistingServer = process.env.PLAYWRIGHT_REUSE_SERVER === '1'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? frontendUrl,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command:
        `cd .. && env AUTH_REQUIRED=false JOB_EXECUTION_MODE=external AUTH_DB_PATH="${process.env.AUTH_DB_PATH ?? 'tmp/e2e/auth.db'}" JOB_DB_PATH="${process.env.JOB_DB_PATH ?? 'tmp/e2e/jobs.db'}" ARTIFACT_DB_PATH="${process.env.ARTIFACT_DB_PATH ?? 'tmp/e2e/artifacts.db'}" .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port ${backendPort}`,
      url: `${backendUrl}/api/health`,
      reuseExistingServer,
      timeout: 30_000,
    },
    {
      command:
        `env VITE_PROXY_TARGET=${backendUrl} npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: frontendUrl,
      reuseExistingServer,
      timeout: 30_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
