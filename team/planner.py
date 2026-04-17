# team/planner.py
# THE PLANNER (The Architect)
# Resposibility: Take the goal and create 3 targeted search queries to research the topic. This is the "brainstorming" phase where we decide what to look for.
# Input: Goal from the Notebook. Output: 3 specific search queries saved back to the Notebook.
# This is the first node in our agent's workflow. It sets the direction for the entire research process. A good plan leads to better findings and a stronger final report.
# This agent only creates the plan. It does not execute searches or write the report. It focuses on understanding the goal and breaking it down into actionable search queries.
# Has its own LLM instance so it can be tuned independently.

import os 
from datetime import datetime
from dotenv import load_dotenv
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import is_quota_or_model_error, fallback_plan_queries

# THE PLANNER'S BRAIN
# Could use a different model or settings than the Writer for cost/performance balance.

PLANNER_MODEL_NAME = os.getenv("PLANNER_MODEL", "gemini-2.5-flash-lite")

planner_llm = ChatGoogleGenerativeAI(
    model=PLANNER_MODEL_NAME,
    max_retries=3,
    request_timeout=30,
)


@traceable(
    name="planner_agent",
    tags=["planner", "planning", "llm"],
    metadata={"agent": "planner", "model": PLANNER_MODEL_NAME}
)
def planner_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Planner Agent — reads the goal, creates 3 targeted search queries.
    Writes results to state['plan']. Never searches or writes.
    """
    print(f"\n📋 PLANNER: Designing research plan for: {state['goal']}")

    try:
        year = datetime.now().year
        response = planner_llm.invoke(f"""
            You are a research planning expert.
            Goal: {state['goal']}

            Create exactly 3 specific search queries to research this topic.
            Each query MUST include the year {year} to get latest results.
            Return only the queries, one per line, no numbering, no extra text.
        """)
        state["plan"] = [
            q.strip()
            for q in response.content.strip().split("\n")
            if q.strip()
        ][:3]

    except Exception as e:
        if is_quota_or_model_error(e):
            print(f"   ⚠️ Planner unavailable ({PLANNER_MODEL}). Using fallback.")
            state["plan"] = fallback_plan_queries(state["goal"])
        else:
            raise

    print(f"   ✅ Plan created: {state['plan']}")
    return state
    """
    Planner Agent — reads the goal, creates 3 search queries.
    Writes results to state['plan'].
    """
    print(f"\n📋 PLANNER: Designing research plan for: {state['goal']}")

    try:
        year = datetime.now().year
        response = planner_llm.invoke(f"""
            You are a research planning expert.
            Goal: {state['goal']}

            Create exactly 3 specific search queries to research this topic.
            Each query MUST include the year {year} to get latest results.
            Return only the queries, one per line, no numbering, no extra text.
        """)
        state["plan"] = [
            q.strip()
            for q in response.content.strip().split("\n")
            if q.strip()
        ][:3]

    except Exception as e:
        if is_quota_or_model_error(e):
            print(f"   ⚠️ Planner LLM unavailable. Using fallback.")
            state["plan"] = fallback_plan_queries(state["goal"])
        else:
            raise

    print(f"   ✅ Plan created: {state['plan']}")
    return state


    """Takes the goal and creates a plan of 3 search queries to find relevant information."""
    print(f"\n🧠 PLANNER AGENT STARTED - Goal: {state['goal']}")
    
    try:
        prompt = f"""You are a research assistant. Your task is to create a plan to achieve the following goal: "{state['goal']}". 
        Break down this goal into 3 specific search queries that would help you research this topic effectively. 
        Return only the list of queries without any additional text or formatting."""
        
        response = planner_llm.generate([{"role": "system", "content": prompt}])
        queries_text = response.generations[0][0].text.strip()
        queries = [q.strip("- ").strip() for q in queries_text.split("\n") if q.strip()]
        
        if not queries:
            raise ValueError("LLM did not return any queries.")
        
        state["plan"] = queries
        print(f"   ✅ Planner created {len(queries)} queries.")
    
    except Exception as e:
        print(f"   ⚠️ Planner LLM unavailable. Using fallback: {e}")
        if is_quota_or_model_error(e):
            print("   Using fallback plan due to LLM issue.")
            state["plan"] = fallback_plan_queries(state["goal"])
        else:
            raise e  # re-raise if it's an unexpected error
        print(f"   ✅ Plan created: {state['plan']}")
    return state