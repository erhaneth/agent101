# FactCrafter Evaluation Harness

This folder contains behavior evals for the research agent.

Unit tests answer: "Did the code work?"

Evals answer: "Did the agent behave well on realistic research tasks?"

## Files

- `questions.jsonl` — benchmark cases with expected quality checks.
- `run_eval.py` — runs selected cases and saves artifacts.
- `runs/` — generated run outputs, ignored by git if you choose to ignore it later.

## Run

List cases without spending API calls:

```bash
.venv/bin/python evals/run_eval.py --dry-run
```

Run the smoke case:

```bash
.venv/bin/python evals/run_eval.py --tag smoke --limit 1
```

Run one case:

```bash
.venv/bin/python evals/run_eval.py --case-id citation_quality_trust
```

Run all cases:

```bash
.venv/bin/python evals/run_eval.py
```

## What Gets Scored

Each case can check:

- grounding pass/fail
- minimum grounding score
- citation integrity
- whether semantic claim verification ran
- minimum verified finding count
- minimum retained claim count
- required report sections
- disallowed source domains

## Artifacts

Every run writes:

```text
evals/runs/<run_id>/
  summary.json
  summary.md
  <case_id>/
    case.json
    state.json
    evaluation.json
    score.json
    report.md
```

Use these artifacts to compare regressions after changing prompts, source filters, graph routing, or evaluators.
