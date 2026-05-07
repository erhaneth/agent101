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
  → Fact Checker Agent
  → Claim Builder Agent
  → Writer Agent
  → Final Report
```

### Agent Roles

* **Brief Agent** — classifies the user’s research goal, topic, freshness needs, and depth.
* **Planner Agent** — creates targeted search queries based on the brief.
* **Searcher Agent** — collects web evidence using Tavily.
* **Fact Checker Agent** — scores sources for relevance, credibility, freshness, and usefulness.
* **Claim Builder Agent** — extracts evidence-backed claims from verified findings.
* **Writer Agent** — writes the final report using only supported claims.

---

## Features

* Multi-agent LangGraph workflow
* Source-backed research reports
* Evidence scoring and rejected-source tracking
* Claim-based writing to reduce hallucinations
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
* LangSmith
* python-dotenv

---

## Project Structure

```text
.
├── agent.py              # Older single-file prototype
├── README.md
├── team/
│   ├── brief.py          # Research intent classifier
│   ├── planner.py        # Search planner
│   ├── searcher.py       # Tavily search agent
│   ├── factchecker.py    # Evidence scoring
│   ├── claimbuilder.py   # Supported claim extraction
│   ├── writer.py         # Final report writer
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

BRIEF_MODEL=gemini-2.5-flash-lite
PLANNER_MODEL=gemini-2.5-flash-lite
CHECKER_MODEL=gemini-2.5-flash-lite
CLAIM_MODEL=gemini-2.5-flash-lite
WRITER_MODEL=gemini-2.5-flash-lite
GEMINI_MODEL=gemini-2.5-flash-lite
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

* The fact checker scores sources, but does not yet fully verify each claim across multiple independent sources.
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
