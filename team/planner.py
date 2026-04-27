# team/planner.py
# THE PLANNER (The Architect)
#----- OLD VERSION (before refactor) -----
# Resposibility: Take the goal and create 3 targeted search queries to research the topic. This is the "brainstorming" phase where we decide what to look for.
# Input: Goal from the Notebook. Output: 3 specific search queries saved back to the Notebook.
# This is the first node in our agent's workflow. It sets the direction for the entire research process. A good plan leads to better findings and a stronger final report.
# This agent only creates the plan. It does not execute searches or write the report. It focuses on understanding the goal and breaking it down into actionable search queries.
# Has its own LLM instance so it can be tuned independently.
# NEW VERSION (after refactor) 
# Responsibility: Create 8 targeted search queries from the research brief.
# Not 3 generic queries — 8 purposeful ones with strategy per research type.
# Reads: brief. Writes: plan.

# team/planner.py
# 📋 THE PLANNER AGENT (The Architect)
# Responsibility: Create 8 targeted search queries from the research brief.
# Not 3 generic queries — 8 purposeful ones with strategy per research type.
# Reads: brief. Writes: plan.

import os
import json
from datetime import datetime

from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import fallback_plan_queries


PLANNER_MODEL = os.getenv("PLANNER_MODEL", "gemini-2.5-flash-lite")


def get_planner_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("PLANNER_MODEL", "gemini-2.5-flash-lite"),
        max_retries=3,
        request_timeout=30,
        temperature=0.0,
    )


@traceable(
    name="planner_agent",
    tags=["planner", "planning", "llm"],
    metadata={"agent": "planner"}
)
def planner_agent(state: ResearchAgentState) -> dict:
    """
    Planner Agent — creates 8 targeted search queries from the research brief.
    Each query has a purpose and priority.
    Strategy varies by research type.
    Writes result to state['plan'].
    """
    print(f"\n📋 PLANNER: Creating research plan...")
    print(f"   Research type: {state['brief'].get('research_type', 'unknown')}")

    year = datetime.now().year  # ← inside function, after .env is loaded

    try:
        response = get_planner_llm().invoke(f"""
You are the search planner for FactCrafter, a general-purpose research agent.

Current year: {year}

Research brief:
{json.dumps(state["brief"], indent=2)}

Create exactly 8 targeted search queries.

Strategy by research_type:
- current_events: prioritize recent news, official statements, timeline
- market_analysis: prioritize data, statistics, trends, competitors
- product_comparison: prioritize specs, pricing, reviews, alternatives
- local_regional_analysis: prioritize local sources, official data, regional news
- technical_research: prioritize official docs, GitHub, changelogs, papers
- scientific_academic: prioritize papers, institutions, research organizations
- historical_background: prioritize encyclopedias, archives, academic sources
- policy_legal: prioritize official laws, government sources, legal analysis
- company_person_profile: prioritize official sites, filings, news, interviews
- general_explainer: prioritize clear explanations, authoritative sources

Rules:
- Each query must have a clear unique purpose
- If freshness_required is true, include {year} in time-sensitive queries
- Cover: overview, primary source, recent data, expert analysis,
  criticism/risks, comparison/context, statistics, deep dive
- Avoid vague or duplicate queries
- For must_cover topics in the brief, create specific queries

Return STRICT JSON only. No markdown, no backticks:
[
  {{"query": "...", "purpose": "overview", "priority": 1}},
  {{"query": "...", "purpose": "primary source", "priority": 1}},
  {{"query": "...", "purpose": "recent data", "priority": 2}},
  {{"query": "...", "purpose": "expert analysis", "priority": 2}},
  {{"query": "...", "purpose": "criticism risks", "priority": 3}},
  {{"query": "...", "purpose": "comparison context", "priority": 3}},
  {{"query": "...", "purpose": "statistics", "priority": 2}},
  {{"query": "...", "purpose": "deep dive", "priority": 3}}
]
""")

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        plan = json.loads(content)

        # Sort by priority
        plan = sorted(plan, key=lambda x: x.get("priority", 99))

        print(f"   ✅ Created {len(plan)} queries")
        for q in plan:
            print(f"   [{q['priority']}] {q['purpose']}: {q['query'][:60]}...")

        return {"plan": plan}

    except Exception as e:
        print(f"   ⚠️ Planner failed ({e}) — using fallback plan")
        return {"plan": fallback_plan_queries(state["goal"])}