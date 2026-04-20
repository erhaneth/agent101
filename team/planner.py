# team/planner.py
# THE PLANNER (The Architect)
# Reads the goal, detects its intent (compare / explain / survey / analyze),
# and produces 3 diversified search queries targeted at different angles.

import os
from datetime import datetime
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import is_quota_or_model_error, fallback_plan_queries

PLANNER_MODEL_NAME = os.getenv("PLANNER_MODEL", "gemini-2.5-flash-lite")

planner_llm = ChatGoogleGenerativeAI(
    model=PLANNER_MODEL_NAME,
    max_retries=3,
    request_timeout=30,
)


@traceable(
    name="planner_agent",
    tags=["planner", "planning", "llm"],
    metadata={"agent": "planner", "model": PLANNER_MODEL_NAME},
)
def planner_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Reads the goal, creates 3 diversified search queries covering different angles.
    Writes results to state['plan'].
    """
    print(f"\n📋 PLANNER: Designing research plan for: {state['goal']}")

    try:
        year = datetime.now().year
        response = planner_llm.invoke(f"""
You are an expert research planner. Output ONLY the 3 search queries — nothing else.

Goal: {state['goal']}

Internally (do NOT output this step) classify the goal as one of:
COMPARE, EXPLAIN, SURVEY, ANALYZE.

Then produce EXACTLY 3 search queries, each targeting a DIFFERENT angle:
  - COMPARE → (1) list of candidates  (2) specs/pricing/features  (3) expert reviews or rankings
  - EXPLAIN → (1) definition/basics   (2) how it works / mechanism (3) examples or case studies
  - SURVEY  → (1) landscape overview  (2) key players or categories (3) recent developments
  - ANALYZE → (1) data/statistics     (2) expert analysis           (3) counterpoints or limits

Output rules (strict):
  - Exactly 3 lines. Each line is ONE search query.
  - Each query MUST include the year {year}.
  - If the goal contains a HARD CONSTRAINT (e.g. "under $40k", "compact",
    "US only", "open-source", "for beginners"), EVERY one of the 3 queries
    MUST include that exact constraint phrase verbatim. Do not paraphrase
    it (e.g. do not turn "under $40k" into "affordable" — keep "under $40k").
  - Do NOT output the classification label (no "COMPARE", "EXPLAIN", etc).
  - No numbering, no markdown, no quotes, no blank lines, no commentary.
  - Each query must read like a natural Google search (5–12 words).

Your response must match this shape exactly:
<query 1>
<query 2>
<query 3>
""")
        _LABELS = {"COMPARE", "EXPLAIN", "SURVEY", "ANALYZE"}
        raw_lines = [
            q.strip().strip('"').strip("'").lstrip("-•*0123456789. ").strip()
            for q in response.content.strip().split("\n")
            if q.strip()
        ]
        # Drop stray classification labels and too-short lines
        state["plan"] = [
            q for q in raw_lines
            if q.upper() not in _LABELS and len(q.split()) >= 3
        ][:3]
        if not state["plan"]:
            raise ValueError("Planner returned no valid queries")

    except Exception as e:
        if is_quota_or_model_error(e):
            print(f"   ⚠️ Planner unavailable ({PLANNER_MODEL_NAME}). Using fallback.")
            state["plan"] = fallback_plan_queries(state["goal"])
        else:
            raise

    print(f"   ✅ Plan created: {state['plan']}")
    return state
