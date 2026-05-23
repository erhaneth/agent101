# team/anchors.py
# ⚓ LANDMARK ANCHOR FINDER
# Before the planner generates generic queries, ask: what canonical works,
# benchmarks, or named studies would a domain expert expect cited?
#
# Anchor queries get prepended to the plan at priority 1, so the searcher
# hits known landmarks before falling back to generic overview queries.

from __future__ import annotations

import json
import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable

from team.state import ResearchAgentState
from team.utils import strip_json_fences


def get_anchor_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("ANCHOR_MODEL", os.getenv("PLANNER_MODEL", "gemini-3.1-flash-lite")),
        max_retries=2,
        request_timeout=30,
        temperature=0.0,
    )


@traceable(
    name="anchor_agent",
    tags=["anchors", "landmarks", "research"],
    metadata={"agent": "anchors"},
)
def anchor_agent(state: ResearchAgentState) -> dict:
    """
    Identify canonical works for the topic before broad searching.

    Returns a list of {name, query} dicts. The planner reads these and prepends
    anchor queries to the plan. If nothing canonical applies (very niche or
    very recent topics), returns an empty list and the pipeline proceeds normally.
    """
    brief = state.get("brief", {})
    goal = state.get("goal", "")

    print(f"\n⚓ ANCHOR FINDER: Identifying canonical works for the topic...")

    try:
        response = get_anchor_llm().invoke(f"""
You are a domain-expert research librarian.

User question:
{goal}

Topic: {brief.get("topic", goal)}
Research type: {brief.get("research_type", "general")}

Identify 3-5 canonical works, landmark studies, or named benchmarks that a
domain expert would cite to ANSWER this specific question — not just works
that are related to the topic area.

Rules:
- Name SPECIFIC artifacts: study names, paper titles, benchmark names,
  author names, organization reports.
- Each anchor must directly inform the user's question. A benchmark that
  measures hallucination is only an anchor if the user asked HOW TO measure
  hallucination. If the user asked which approach reduces hallucination more,
  the anchor must be a comparative study, not a measurement framework.
- Prefer comparative studies, head-to-head benchmarks, and enterprise reports
  over methodology papers. Methodology papers belong as anchors only when the
  user is asking about methodology.
- If the question asks "when does X outperform Y" or "what are tradeoffs",
  anchors must be works that report comparison results — not works that
  describe how comparisons are done.
- Do NOT list generic categories like "academic papers" or "industry reports."
- Only include works you are confident exist. If uncertain, skip it.
- If the question has no obvious canonical works (very recent, very niche,
  or purely opinion-based), return an empty list.

Return STRICT JSON only. No markdown, no backticks:
[
  {{"name": "Stanford legal RAG study (Magesh et al.)", "query": "Stanford Magesh legal RAG hallucination study"}},
  {{"name": "Vectara HHEM leaderboard", "query": "Vectara HHEM hallucination evaluation leaderboard"}}
]
""")
        content = strip_json_fences(response)
        anchors = json.loads(content) if content else []
        if not isinstance(anchors, list):
            anchors = []

        # Filter to entries with both name and query
        anchors = [
            {"name": str(a.get("name", "")).strip(), "query": str(a.get("query", "")).strip()}
            for a in anchors
            if isinstance(a, dict) and a.get("name") and a.get("query")
        ]

        print(f"   ✅ Found {len(anchors)} canonical anchor(s)")
        for anchor in anchors[:5]:
            print(f"   - {anchor['name']}")
        return {"anchors": anchors}
    except Exception as error:
        print(f"   ⚠️ Anchor finder failed ({error}) — proceeding without anchors")
        return {"anchors": []}
