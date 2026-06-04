# FactCrafter

FactCrafter is an evidence-first AI research agent that turns a user question into a structured, source-backed report.

Instead of relying on one model to search and write everything, FactCrafter uses a team of specialized agents to plan research, collect evidence, verify sources, extract supported claims, and write the final answer only from those claims.

---

## How It Works

```text
User Goal
  → Brief Agent
  → Planner Agent
  → Searcher Agent
  → Source Fetcher Agent
  → Fact Checker Agent
  → Claim Builder Agent
  → Claim Verifier Agent
  → Human Review Gate
  → Writer Agent
  → Post-Writer Citation Verifier
  → Report Repair Agent (if needed)
  → Evaluator Agent
  → Final Report
```

### Agent Roles

* **Brief Agent** — classifies the user’s research goal, topic, freshness needs, and depth.
* **Planner Agent** — creates targeted search queries based on the brief.
* **Searcher Agent** — collects web evidence using Tavily.
* **Source Fetcher Agent** — fetches and parses HTML/PDF source text before scoring.
* **Fact Checker Agent** — scores sources for relevance, credibility, freshness, and usefulness.
* **Claim Builder Agent** — extracts evidence-backed claims from verified findings.
* **Claim Verifier Agent** — checks whether each cited source excerpt actually supports each claim.
* **Human Review Gate** — pauses high-stakes topics before writing when an interactive reviewer is available.
* **Writer Agent** — writes the final report using only supported claims.
* **Post-Writer Citation Verifier** — checks whether final report sentences are actually supported by their inline citations.
* **Report Repair Agent** — removes or softens unsupported final-report wording, then sends the report back through citation verification.
* **Evaluator Agent** — checks citation grounding and citation-link integrity before output.

---

## Features

* Multi-agent LangGraph workflow
* Source-backed research reports
* Source fetching and HTML/PDF parsing before evidence scoring
* Deterministic source quality ranking plus LLM evidence judging
* Evidence scoring and rejected-source tracking
* Claim-based writing to reduce hallucinations
* Semantic claim verification before writing
* Post-writer citation verification against cited source text
* Citation repair loop for unsupported final-report wording
* Human-in-the-loop review gate for high-stakes topics
* Behavior evaluation harness with saved run artifacts
* Per-run audit artifacts for normal research runs
* File-based caching for Tavily search and source fetch/parse results
* Input and output guardrails
* LangSmith tracing support
* Fallbacks for model/API failures
* Token budget trimming before final writing

---

## Tech Stack

* Python
* LangGraph
* LangChain
* Google Gemini
* Tavily Search API
* requests
* pypdf
* LangSmith
* python-dotenv

---

## Project Structure

```text
.
├── agent.py              # Older single-file prototype
├── evals/
│   ├── questions.jsonl   # Behavior eval cases
│   ├── run_eval.py       # Eval runner and artifact writer
│   └── README.md
├── README.md
├── team/
│   ├── brief.py          # Research intent classifier
│   ├── planner.py        # Search planner
│   ├── searcher.py       # Tavily search agent
│   ├── sourcefetcher.py  # Fetches/parses source pages and PDFs
│   ├── sourcequality.py  # Deterministic source quality ranking
│   ├── factchecker.py    # Evidence scoring
│   ├── claimbuilder.py   # Supported claim extraction
│   ├── claimverifier.py  # Semantic claim/source support checks
│   ├── humanreview.py    # Human review gate for high-stakes topics
│   ├── writer.py         # Final report writer
│   ├── reportverifier.py # Post-writer citation/source support checks
│   ├── reportrepair.py   # Repairs unsupported final-report wording
│   ├── evaluator.py      # Citation grounding evaluation
│   ├── artifacts.py      # Per-run audit artifact writer
│   ├── cache.py          # File cache for search/fetch calls
│   ├── guardrails.py     # Input/output checks
│   ├── graph.py          # LangGraph workflow
│   ├── main.py           # CLI entry point
│   ├── state.py          # Shared state types
│   └── utils.py          # Shared fallbacks
└── .gitignore
```

---

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd <your-repo-name>
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate   # macOS/Linux
venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```bash
pip install langgraph langchain langchain-google-genai tavily-python langsmith python-dotenv
```

### 4. Create `.env`

```env
GOOGLE_API_KEY=your_google_gemini_api_key
TAVILY_API_KEY=your_tavily_api_key
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=factcrafter

BRIEF_MODEL=gemini-3.1-flash-lite
PLANNER_MODEL=gemini-3.1-flash-lite
CHECKER_MODEL=gemini-3.1-flash-lite
CLAIM_MODEL=gemini-3.1-flash-lite
WRITER_MODEL=gemini-3.1-flash-lite
GEMINI_MODEL=gemini-3.1-flash-lite
```

LangSmith is optional but useful for debugging runs.

---

## Usage

Run the CLI:

```bash
python -m team.main
```

Then enter a research question:

```text
Compare electric cars under $40k right now.
```

Or call it from Python:

```python
from team.main import run_research

report = run_research("Compare electric cars under $40k right now.")
print(report)
```

---

## Evaluation Harness

List eval cases without spending API calls:

```bash
.venv/bin/python evals/run_eval.py --dry-run
```

Run the smoke eval:

```bash
.venv/bin/python evals/run_eval.py --tag smoke --limit 1
```

Each eval run saves artifacts under `evals/runs/<run_id>/`, including the report, final state, grounding evaluation, and pass/fail checks.

---

## Deployment Smoke Check

After deploying the web API, verify the hosted service:

```bash
scripts/smoke.sh https://api.your-production-domain.com
```

The smoke check verifies `/api/health`, `/api/ready`, `/api/metrics`, and the `X-Request-ID` response header. During early staging setup, you can allow degraded readiness while databases or artifact storage are still being wired:

```bash
scripts/smoke.sh https://api.your-production-domain.com --allow-degraded-ready
```

GitHub Actions also includes a hosted smoke workflow. Configure repository secret `FACTCRAFTER_SMOKE_URL` to run it automatically after successful `CI` runs on `main`, or trigger **Hosted Smoke** manually with a `base_url` input.

Run a lightweight API load probe against staging or a local dev-auth server:

```bash
scripts/load-probe.sh https://api.your-production-domain.com --requests 60 --concurrency 6
```

For local or staging environments where job creation is safe and authenticated, include the queued create/cancel flow:

```bash
scripts/load-probe.sh http://127.0.0.1:8000 --requests 40 --concurrency 4 --include-job-flow
```

## Production Config Validation

Before promoting a deployment, validate the production environment:

```bash
.venv/bin/python scripts/validate_config.py --env-file .env.production --strict-warnings
```

The validator checks production-only requirements such as secure auth cookies, HTTPS auth URLs, safe CORS origins, Google OAuth/API keys, external worker mode, shared Postgres-backed auth/job storage, durable artifact storage, job limits, alert webhook URL, and hosted smoke URL.

`render.yaml` declares the production shape for Render: API web service, external worker, shared `factcrafter-postgres` database, `/api/ready` health checks, OAuth credential prompts, and Postgres-backed auth/job/artifact storage. After creating the Blueprint, fill the secret prompts in Render and export the resolved production env into `.env.production` before running the validator/release gate.

Run the full production release gate when a deployment is ready to promote:

```bash
scripts/release-gate.sh --env-file .env.production --base-url https://api.your-production-domain.com
```

This runs config validation, hosted smoke checks, and the load probe in sequence. The release gate rejects local or example hosts, and `--base-url` must match `FACTCRAFTER_SMOKE_URL` in the production env file so the config you validate is the deployment you probe. Use `--dry-run` to preview the commands, and add `--include-job-flow` only for staging environments where creating and canceling queued jobs is safe.

## Browser E2E Check

Install the Playwright browser once:

```bash
cd ui
npx playwright install chromium
```

Run the browser E2E gate:

```bash
scripts/e2e.sh
```

This starts isolated local FastAPI and Vite servers with dev auth enabled and external-worker mode. The current E2E suite creates a queued research job through the UI, cancels it through the real API, opens a seeded saved report from the library, verifies report/facts/sources rendering, approves an awaiting human review, follows simulated worker progress through a completed report, and checks auth-required Google-login handoff UI. Include it in the full local gate with:

```bash
RUN_E2E=1 scripts/check.sh
```

---

## Worker Operations

Run the external worker:

```bash
python worker.py
```

Verify worker job-store connectivity without claiming work:

```bash
python worker.py --healthcheck
```

Each worker process runs one research job at a time. Increase production concurrency by running additional worker processes or services against the same `JOB_DATABASE_URL`.

Job cancellation is cooperative. Queued jobs are canceled before worker claim; running jobs store a shared cancel request and workers stop before guardrail work or between streamed graph updates.

---

## Run Artifacts

Normal research runs save an audit trail under `runs/<run_id>/` by default.

Each run folder includes:

```text
input.json
guardrails.json
brief.json
plan.json
findings.json
verified_findings.json
rejected_findings.json
claims.json
claim_verifications.json
rejected_claims.json
human_review.json
report_verification.json
report_verifications.json
report_repair_history.json
evaluation.json
report.md
summary.json
summary.md
state.json
```

Disable artifact writing:

```bash
SAVE_RUN_ARTIFACTS=false .venv/bin/python -m team.main
```

Change the artifact directory:

```bash
RUN_ARTIFACT_DIR=/tmp/factcrafter-runs .venv/bin/python -m team.main
```

---

## Caching

FactCrafter caches expensive external calls by default:

- Tavily search responses
- fetched and parsed source pages/PDFs

Default cache directory:

```text
.cache/factcrafter/
```

Disable caching:

```bash
FACTCRAFTER_CACHE_ENABLED=false .venv/bin/python -m team.main
```

Change the cache directory:

```bash
FACTCRAFTER_CACHE_DIR=/tmp/factcrafter-cache .venv/bin/python -m team.main
```

Tune TTLs:

```bash
FACTCRAFTER_SEARCH_CACHE_TTL_SECONDS=86400
FACTCRAFTER_SOURCE_CACHE_TTL_SECONDS=604800
```

---

## Human Review

High-stakes topics such as legal, tax, medical, financial, safety, and eligibility questions cross a human review gate before writing.

Default behavior:

- interactive CLI: asks the user to approve verified claims before writing
- noninteractive runs: blocks writing and records that no reviewer was available

Modes:

```bash
HITL_REVIEW_MODE=auto      # default; review only high-stakes topics
HITL_REVIEW_MODE=always    # always review
HITL_REVIEW_MODE=required  # block if no interactive reviewer is available
HITL_REVIEW_MODE=off       # disable review gate
```

---

## Post-Writer Citation Verification

After the writer creates the report, FactCrafter runs one more semantic check over the final answer.

This verifier extracts citation-bearing factual blocks from the report body, looks up the verified source text behind each inline citation, and labels each cited report item as:

- `supported`
- `partial`
- `unsupported`

If the final report cites a URL that was not part of verified evidence, or if cited source text does not support the final wording, the report is routed through one repair attempt by default. The repair agent removes or softens unsupported wording, then the verifier checks the revised report again. If it still fails, the grounding gate fails.

Useful knobs:

```bash
REPORT_VERIFIER_MODEL=gemini-3.1-flash-lite
REPORT_VERIFIER_MAX_ITEMS=12
REPORT_REPAIR_MODEL=gemini-3.1-flash-lite
REPORT_REPAIR_MAX_ATTEMPTS=1
```

---

## Output Format

FactCrafter writes reports in this structure:

```markdown
## Direct Answer
## Key Findings
## Evidence-Based Analysis
## Uncertainties and Limitations
## Conclusion
## Sources
```

---

## Current Limitations

* The claim verifier checks semantic support against available source excerpts, but does not yet verify each claim across multiple independent full documents.
* Search freshness is currently strict and may not fit historical or evergreen topics.
* Guardrail keyword rules may block some legitimate research requests.
* The current interface is CLI-based.
* Report quality depends on the quality of search snippets and external APIs.

---

## Roadmap

* Web UI
* Saved reports
* PDF/DOCX export
* Source viewer per claim
* Multi-source claim verification
* Dynamic freshness by research type
* Factuality and citation evals
* User accounts and billing
* Research templates for agencies, consultants, real estate, policy, and market analysis

---

## Disclaimer

FactCrafter is an AI-assisted research tool. Review outputs before using them for legal, financial, medical, investment, or other high-stakes decisions.
