#!/usr/bin/env python3
"""
Runner for Agentic Engineering Jobs research question.
Run with: HITL_REVIEW_MODE=off python tmp/run_agentic_jobs.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from team.main import run_research_state

GOAL = (
    "According to real 2026 job postings at AI-native companies, big tech, and startups, "
    "what are the most common technical skills, years of experience, tools, and salary ranges "
    "for roles titled 'Agentic Engineer', 'AI Agent Engineer', 'Multi-Agent Systems Engineer', "
    "or similar positions focused on building and operating production LLM agents and agentic workflows? "
    "What does day-to-day work in these roles actually look like, and which companies are hiring most aggressively?"
)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 STARTING AGENTIC ENGINEERING JOBS RESEARCH RUN")
    print(f"Goal: {GOAL}")
    print("=" * 70 + "\n")

    result = run_research_state(GOAL, save_artifacts=True)

    print("\n" + "=" * 70)
    print("🏁 RUN COMPLETE")
    print("=" * 70)
    print(f"Grounding gate passed: {result.get('grounding_gate_passed')}")
    hr = result.get("human_review", {}) or {}
    print(f"Human review: required={hr.get('required')} approved={hr.get('approved')} decision={hr.get('decision')}")
    print(f"Artifact dir: {result.get('artifact_dir')}")
    eval_data = result.get("evaluation", {}) or {}
    print(f"Grounding score: {eval_data.get('grounding_score')}/100")
    print(f"Block citation rate: {eval_data.get('block_citation_rate')}")
    print("=" * 70 + "\n")
