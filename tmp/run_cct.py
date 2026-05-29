#!/usr/bin/env python3
"""
One-shot runner for the Conditional Cash Transfer scientific_academic query.
Run with: HITL_REVIEW_MODE=off python tmp/run_cct.py
"""
import sys
from pathlib import Path

# Ensure we can import "team" when run as a script (PYTHONPATH not required)
ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from dotenv import load_dotenv

# Load .env exactly like main.py does
load_dotenv(ROOT / ".env")

from team.main import run_research_state

GOAL = (
    "According to rigorous evaluations, how effective have conditional cash transfer programs "
    "(like Mexico’s Progresa/Oportunidades or Brazil’s Bolsa Família) been at improving "
    "education, health, and poverty outcomes in developing countries?"
)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 STARTING CCT RESEARCH RUN (scientific_academic, HITL=off)")
    print(f"Goal: {GOAL}")
    print("=" * 70 + "\n")

    # Force artifact saving
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
