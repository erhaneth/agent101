# Production Readiness Review

Date: 2026-06-03

## Current Verdict

FactCrafter is a solid prototype moving toward production, but it is not production-ready yet.

The core research pipeline has meaningful hardening around source quality, claim verification, citation verification, repair, artifacts, caching, and human review. The web app now has passing backend tests, API workflow coverage, passing frontend lint/build gates, Playwright browser coverage for core flows, OAuth callback coverage, a production auth secret guard, scoped web-job runtime context, persisted job metadata, external worker mode, worker leases/retries/stale recovery, worker health checks, graceful worker stop handling, queued-job cancellation, cooperative running-job cancellation, durable web human-review coordination across web/worker processes, optional database-backed artifact mirroring, optional Postgres storage for auth/jobs, configurable job quotas/rate limits, optional failed/blocked-job alert webhooks, pinned Python production installs, scheduled dependency update configuration, readiness checks, metrics endpoint, deploy smoke checks, hosted smoke workflow automation, lightweight load probing, production config validation, release gate orchestration, request correlation IDs, structured API request logs, structured job lifecycle logs, and a CI workflow. The remaining production blockers are mostly operational: live Google OAuth verification with real credentials, alert/log dashboard configuration, configuring hosted smoke secrets/deploy hooks, and running the release gate against the real production environment.

## Verified Checks

These checks passed locally:

- `research-agent/scripts/check.sh`
- Backend: `100` unittest cases passed
- Backend: Python compile check passed for `team`, `web`, `evals`, `app.py`, `agent.py`, and `worker.py`
- Research UI: `npm run lint`
- Research UI: `npm run build`
- Research UI: `scripts/e2e.sh` Playwright Chromium checks for auth-required Google-login handoff, job creation, queued cancellation, saved-report library navigation, report rendering, facts, sources, human-review approval, active worker progress, and completed job report rendering
- Standalone Next app: `npm run lint`
- Standalone Next app: `npm run build`
- Research UI dependency audit: `npm audit --audit-level=moderate` found `0` vulnerabilities
- Standalone Next app dependency audit: `npm audit --audit-level=moderate` found `0` vulnerabilities after overriding Next's nested PostCSS dependency to the patched installed version
- Python production dependencies are pinned in `requirements.lock`, and CI/Render install from the lockfile
- `.github/dependabot.yml` schedules weekly grouped updates for Python dependencies, Research UI npm dependencies, standalone Next npm dependencies, and GitHub Actions
- `render.yaml` declares a web service, external worker, shared Render Postgres database, OAuth secret prompts, `/api/ready` health checks, and production-safe shutdown windows
- Readiness probes check auth storage, job storage, and artifact storage; Render health checks use `/api/ready`
- `/api/metrics` exposes API request counters/latency and job lifecycle counters for dashboards and monitors
- `scripts/smoke.sh` can verify a deployed API's `/api/health`, `/api/ready`, `/api/metrics`, and `X-Request-ID` behavior
- `scripts/load-probe.sh` can run concurrent lightweight read probes and optional queued job create/cancel probes against local/staging deployments
- `scripts/release-gate.sh` runs production config validation, hosted smoke checks, and load probing in sequence, rejects local/example release targets, and requires `--base-url` to match `FACTCRAFTER_SMOKE_URL`
- `.github/workflows/hosted-smoke.yml` can run hosted smoke checks manually with a URL or automatically after successful `CI` on `main` when `FACTCRAFTER_SMOKE_URL` is configured
- `scripts/validate_config.py` validates production secrets, HTTPS auth URLs, safe CORS origins, OAuth/API keys, external worker mode, shared Postgres stores, durable artifacts, job limits, alert webhook URL, and hosted smoke URL
- API responses include `X-Request-ID`; request logs are structured JSON with request id, method, path, status code, and duration
- API responses include browser security headers, and production CORS rejects local, wildcard, non-HTTPS, or placeholder origins
- Job lifecycle events are logged as structured JSON for creation, worker claim, start, step completion, review wait, finish, failure, stale recovery, and cancellation
- Queued jobs can be canceled before execution through `POST /api/jobs/{job_id}/cancel`; workers skip canceled jobs
- Running jobs can receive persisted cancel requests; workers stop cooperatively before guardrails or between graph updates
- Pending web human reviews are persisted in shared job storage so external API and worker processes can coordinate review decisions without shared memory
- `worker.py --healthcheck` verifies worker job-store connectivity without claiming work
- API workflow coverage verifies dev-auth job creation, listing, detail fetch, cancellation, SSE completion, and auth-required rejection
- Google OAuth backend coverage verifies state-cookie redirect setup, invalid-state rejection, mocked token/profile exchange, user upsert, JWT session cookie creation, and OAuth state cleanup
- Browser E2E coverage verifies auth-required Google-login handoff UI, dev-auth job creation, queued cancellation, saved-report library navigation, report/facts/sources panels, human-review approval, active worker progress, and completed job report rendering
- Optional `ALERT_WEBHOOK_URL` sends failed/blocked job alerts without crashing jobs if delivery fails

Dependency audit note:

- Standalone Next app dependency audit is clean after replacing Next's nested vulnerable PostCSS installation with the patched root `postcss@8.5.14` through npm overrides.

## Changes Made During This Pass

- Fixed React UI lint failures by splitting provider files from hooks and replacing state-driven page transitions with a CSS animation.
- Added a repeatable `scripts/check.sh` gate for backend tests, Python compile checks, UI lint, and UI build.
- Migrated the standalone Next app from removed `next lint` usage to direct ESLint with `eslint-config-next`.
- Updated standalone Next app dependencies to latest stable `next@16.2.7` and matching ESLint config.
- Suppressed a narrow, known Turbopack tracing warning for the standalone Next app after verifying the production build succeeds.
- Hardened production auth config so `AUTH_SECRET_KEY` is required in production.
- Made secure cookies default to enabled in production.
- Updated Render/env examples for production auth settings.
- Added tests for production auth secret and secure-cookie behavior.
- Replaced process-global web job environment mutation with scoped `contextvars` runtime context.
- Added a regression test for web job context scoping/restoration.
- Added a GitHub Actions CI workflow for backend checks, Research UI checks, standalone Next lint/build, and dependency audits.
- Added SQLite-backed job metadata persistence with startup restoration.
- Added tests for job store round-tripping and interrupted-job restoration.
- Added external worker mode via `JOB_EXECUTION_MODE=external`.
- Added `worker.py` to claim and run queued jobs outside the web process.
- Added optional Postgres-backed job storage via `JOB_DATABASE_URL` for shared web/worker deployments.
- Added tests for external enqueueing, queue claiming, and worker execution dispatch.
- Added optional Postgres-backed auth storage via `AUTH_DATABASE_URL`/`DATABASE_URL`.
- Added auth storage tests for configured SQLite paths and Google-user updates.
- Added optional database-backed run artifact mirroring via `ARTIFACT_DATABASE_URL`/`ARTIFACT_DB_PATH`.
- Wired the run API to read from the artifact store when configured.
- Added tests proving stored reports can be listed/read without relying on local run folders.
- Added worker lease metadata: attempt count, lock owner, lock timestamp, and heartbeat timestamp.
- Added stale-running-job recovery with retry/fail behavior controlled by `JOB_MAX_ATTEMPTS` and `JOB_STALE_AFTER_SECONDS`.
- Added tests for worker leases, stale retry, and retry-limit failure.
- Added per-user active-job limits and create-rate limits for `/api/jobs`.
- Added tests for active-job counting, concurrency rejection, and rolling-window create limits.
- Added `requirements.lock` and switched CI/Render installs to exact pinned Python dependencies.
- Updated `render.yaml` to provision shared Render Postgres storage for auth, jobs, and artifacts, prompt for OAuth credentials, use deployable paid web/worker plans, and give the worker a longer shutdown window.
- Added `/api/ready` with backing-store readiness probes and a `503` degraded response.
- Wired Render's web health check to `/api/ready`.
- Added graceful worker shutdown handling for `SIGINT`/`SIGTERM` between jobs.
- Added request correlation middleware with generated/propagated `X-Request-ID` values.
- Added browser security headers and production CORS validation to reject local/wildcard/placeholder browser origins.
- Added structured JSON API request/error logs for operational debugging.
- Added structured JSON job lifecycle logs for queue, worker, pipeline, terminal, stale-recovery, and cancellation events.
- Added persisted queued-job cancellation and a UI cancel action while jobs are still queued.
- Added canceled jobs to terminal job accounting and SSE completion handling.
- Added `scripts/smoke.py` and `scripts/smoke.sh` for repeatable deployed API smoke checks.
- Added smoke-check tests for healthy and degraded readiness behavior.
- Added `worker.py --healthcheck` for non-mutating worker/job-store health verification.
- Documented the worker concurrency policy: one job per worker process; scale by adding worker processes/services.
- Added API workflow tests for job creation, listing, detail loading, cancellation, SSE terminal events, and auth-required rejection.
- Added optional failed/blocked-job alert webhooks with delivery-failure logging.
- Added alerting tests for disabled, delivered, and failed webhook paths.
- Added persisted `cancel_requested` support for running/awaiting-review jobs.
- Added cooperative worker cancellation before expensive guardrail work and between streamed graph updates.
- Updated the UI to request cancellation for queued/running/awaiting-review jobs and show pending cancellation state.
- Added Playwright E2E infrastructure for the Research UI with isolated local FastAPI/Vite servers.
- Added a Chromium E2E test for creating and canceling a queued research job through the real UI/API path.
- Added deterministic E2E artifact seeding and a Chromium test for saved report library navigation, report rendering, facts, and sources.
- Persisted pending web human-review requests and review decisions in shared job storage for external web/worker deployments.
- Added a Chromium E2E test for approving an awaiting human review from the job page.
- Added a hosted smoke GitHub Actions workflow and regression test so deployed health/readiness checks can be automated after CI.
- Added a production config validator and tests for complete versus unsafe deployment configuration.
- Added a deterministic E2E worker simulator and Chromium test for active progress updates through completed report rendering.
- Added mocked Google OAuth callback tests and a Chromium test for auth-required Google-login handoff UI.
- Added a lightweight API load probe and tests for read-path success, endpoint failure detection, and queued job create/cancel probing.
- Added Dependabot configuration and a regression test covering Python, Research UI npm, standalone Next npm, and GitHub Actions update surfaces.
- Added a release gate wrapper and tests for command composition, dry-run behavior, and stop-on-failure behavior.
- Added release target preflight checks so final release gates cannot run against local/example hosts or a URL that differs from the configured hosted smoke target.
- Added `/api/metrics`, API/job metric counters, and tests for request/job metric reporting.

## Production Blockers

1. Worker operations

   The app now supports `JOB_EXECUTION_MODE=external`, where the API enqueues jobs and `worker.py` claims queued jobs from shared storage. Workers record leases/heartbeats, stale running jobs are retried, jobs fail after `JOB_MAX_ATTEMPTS`, `SIGINT`/`SIGTERM` request a clean stop after the current job, and `worker.py --healthcheck` verifies job-store connectivity without claiming work. Each worker process runs one job at a time; production concurrency should be controlled by the number of worker processes/services. `render.yaml` now wires both services to the same Render Postgres connection string for job storage; production still needs hosted smoke automation against the live deployment to prove that wiring after deploy.

2. Persistent data strategy

   Auth and job metadata can use Postgres via `AUTH_DATABASE_URL` and `JOB_DATABASE_URL`. Run artifacts can be mirrored to a database via `ARTIFACT_DATABASE_URL` or `ARTIFACT_DB_PATH`, while still writing local files for development and inspection. The Render blueprint now provisions a shared Postgres instance and maps all three production storage URLs to its connection string. Production still needs that configuration validated against the real deployment environment and then verified under load.

3. CI/CD gates

   A GitHub Actions workflow now runs local gates, `scripts/smoke.sh` can verify a hosted API after release, the hosted smoke workflow can run manually or after successful CI on `main` when `FACTCRAFTER_SMOKE_URL` is configured, `scripts/validate_config.py` can fail unsafe production env files before promotion, and `scripts/release-gate.sh` combines config, smoke, and load checks for promotion while rejecting local/example or mismatched release targets. Production still needs real PR protection in the remote repository and repository/deployment configuration that points the hosted smoke workflow at the live deployment URL.

4. Dependency governance

   Python production installs now use exact pins from `requirements.lock`, while `requirements.txt` remains the top-level input list. Dependabot now opens weekly grouped PRs for Python, Research UI npm, standalone Next npm, and GitHub Actions updates. Production still needs humans to review/merge those PRs and rerun audits after framework updates.

5. Rate limiting and abuse control

   `/api/jobs` now enforces `MAX_ACTIVE_JOBS_PER_USER`, `MAX_JOB_CREATES_PER_WINDOW`, and `JOB_CREATE_WINDOW_SECONDS`. Queued jobs can be canceled before worker claim, running jobs can receive cooperative cancel requests that workers honor between pipeline updates, and `scripts/load-probe.sh` can exercise lightweight concurrent read paths plus optional queued create/cancel flow. Production should still add edge/IP-level protection and billing/account quota integration if this becomes user-facing.

6. End-to-end web coverage

   Backend unit tests now include an API-level workflow covering auth-disabled dev access, job creation, listing, detail loading, queued cancellation, SSE terminal events, auth-required rejection, persisted web-review coordination across process memory, and mocked Google OAuth callback/session behavior. Playwright now covers auth-required Google-login handoff UI, dev-auth page load, job creation UX, job detail routing, queued cancellation, saved-report library navigation, report rendering, facts, sources, human-review approval, active worker progress, and completed job report rendering against real local FastAPI/Vite servers. Production still needs a live OAuth smoke with real Google credentials in the deployed environment.

7. Observability and incident response

   LangSmith tracing is configured, `/api/ready` verifies auth/job/artifact storage dependencies, `/api/metrics` exposes API/job counters, API responses carry `X-Request-ID` plus browser security headers, production CORS rejects unsafe origins, API/job lifecycle logs are emitted as structured JSON, failed/blocked jobs can send `ALERT_WEBHOOK_URL` notifications, hosted smoke automation can verify deployed health/readiness/metrics behavior, and the release gate can catch unsafe config, placeholder URLs, mismatched release targets, plus slow/erroring API paths before release. The app still needs a real production alert destination, log aggregation dashboards, SLOs, and repository/deployment configuration for post-deploy smoke/load execution.

## Recommended Path To Production

1. Deploy from `render.yaml`, confirm the web service and worker both reference the same `factcrafter-postgres` connection string, and keep `JOB_EXECUTION_MODE=external`.
2. Wire `worker.py --healthcheck` into worker monitoring and configure a real `ALERT_WEBHOOK_URL`.
3. Fill Render secret prompts for Google API, Tavily, OAuth client credentials, auth URLs, and auth secret; keep `AUTH_DATABASE_URL`, `JOB_DATABASE_URL`, and `ARTIFACT_DATABASE_URL` pointed at shared Postgres.
4. Review and merge Dependabot PRs on a weekly cadence, and rerun dependency audits after framework updates.
5. Tune job quotas/rate limits for production and add billing/account quota integration.
6. Verify live Google OAuth with real production credentials and redirect URIs.
7. Set `FACTCRAFTER_SMOKE_URL` to the real hosted API URL, run `scripts/release-gate.sh` with the same `--base-url`, then configure alert destinations, log dashboards, SLOs, and deployment-triggered smoke/load execution.
8. Enable remote branch protection so the new CI workflow blocks regressions.

## Useful References

- Next.js ESLint config docs: https://nextjs.org/docs/app/api-reference/config/eslint
- Next.js Turbopack docs: https://nextjs.org/docs/app/api-reference/turbopack
- Next.js `turbopack.ignoreIssue`: https://nextjs.org/docs/app/api-reference/config/next-config-js/turbopackIgnoreIssue
