# team/brief.py
# 🧭 THE BRIEF AGENT (The Intent Classifier)
# Responsibility: Classify the user's research goal before any searching begins
# Decides: what type of research is this? how fresh does it need to be?
# what must be covered? what should be avoided? how deep should the research go?
# this agent runs first - before the planner creates any queries.

import os 
import json
from datetime import datetime 
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState

# 🧠 BRIEF AGENT'S OWN BRAIN
BRIEF_MODEL = os.getenv("BRIEF_MODEL", "gemini-2.5-flash-lite")  # ← can be customized separately from planner/writer

def get_brief_llm(): 
    """Lazy load - after .env is loaded and only if this agent runs."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("BRIEF_MODEL", "gemini-2.5-flash-lite"),
        temperature=0.0,  # deterministic output for classification
        max_retries=3,  # retry attempts in case of failures
        request_timeout=30,  # seconds before timing out API calls
    )

def fallback_brief(goal: str) -> dict:
    """Emergency brief when LLM is unavailable."""
    return {
        "user_goal": goal,
        "topic": goal,
        "research_type": "general_explainer",
        "freshness_required": True,
        "target_depth": "standard",
        "must_cover": [],
        "avoid": []
    }
    
@traceable(
    name="brief_agent",
    tags=["brief", "intent", "classification", "llm"],
    metadata={"agent": "brief"}
)
def brief_agent(state: ResearchAgentState) -> dict:
    """
    Brief Agent — classifies the user's research goal.
    Runs before planning so the planner knows what strategy to use.
    Writes result to state['brief'].
    """
    print(f"\n🧭 BRIEF: Classifying research intent...")
    print(f"   Goal: {state['goal']}")

    year = datetime.now().year

    try:
        response = get_brief_llm().invoke(f"""
You are the intent analyst for FactCrafter, a general-purpose research agent.

User goal:
{state["goal"]}

Current year: {year}

Create a research brief. Classify research_type as exactly one of:
- current_events
- market_analysis
- product_comparison
- local_regional_analysis
- technical_research
- scientific_academic
- historical_background
- policy_legal
- company_person_profile
- general_explainer

Rules for freshness_required:
- Set true for: current events, markets, prices, laws, products,
  companies, people, politics, technology, statistics
- Set false for: history, science fundamentals, concepts, definitions

Rules for target_depth:
- brief: simple factual question, quick answer needed
- standard: normal research question
- deep: complex analysis, comparisons, policy, investment decisions

Return STRICT JSON only. No markdown, no explanation, no backticks:
{{
  "user_goal": "{state["goal"]}",
  "topic": "short topic label",
  "research_type": "one of the types above",
  "freshness_required": true,
  "target_depth": "standard",
  "must_cover": ["key aspect 1", "key aspect 2"],
  "avoid": ["irrelevant aspect 1"]
}}
""")

        # Clean response — remove markdown fences if present
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        brief = json.loads(content)
        print(f"   ✅ Research type: {brief['research_type']}")
        print(f"   ✅ Freshness required: {brief['freshness_required']}")
        print(f"   ✅ Must cover: {brief['must_cover']}")

        return {"brief": brief}

    except Exception as e:
        print(f"   ⚠️ Brief agent failed ({e}) — using fallback brief")
        return {"brief": fallback_brief(state["goal"])}