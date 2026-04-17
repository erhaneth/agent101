import os
from dotenv import load_dotenv
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
# END = LangGraph's special signal that the pipeline is finished.
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.tools import DuckDuckGoSearchRun
from datetime import datetime
from langsmith import traceable

load_dotenv()

# 🧩 THE LOGIC BREAKDOWN 
# 1. THE SHARED MEMORY (The State)
# Before any work starts, we need a "Shared Notebook" that every agent can see. 
# Without this, the Planner wouldn't be able to tell the Searcher what to look for.
class ResearchAgentState(TypedDict):
    goal: str           # Goal: What are we trying to do?
    plan: List[str]     # Plan: A list of steps (queries) created by the Brain.
    searches_done: List[str] # Checklist: So we don't repeat ourselves.
    findings: List[str] # Findings: Where we store the raw data from the web.
    report: str         # Report: The final polished product.

# 🧠 THE BRAIN
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    max_retries=3,
    request_timeout=30,
)
# 💰 TOKEN BUDGET — hard limit per run
MAX_TOKENS_PER_RUN = 2000  # adjust as needed

def check_token_budget(state: ResearchAgentState) -> ResearchAgentState:
    """Guard node — stops the run if token budget is exceeded."""
    # LangSmith tracks cumulative tokens automatically
    # This is a manual safety check based on findings size
    total_chars = sum(len(f) for f in state["findings"])
    estimated_tokens = total_chars // 4  # rough estimate: 4 chars per token
    
    if estimated_tokens > MAX_TOKENS_PER_RUN:
        print(f"\n⚠️ TOKEN BUDGET EXCEEDED: ~{estimated_tokens} tokens")
        print(f"   Trimming findings to fit budget...")
        # Trim oldest findings first
        while sum(len(f) for f in state["findings"]) // 4 > MAX_TOKENS_PER_RUN:
            state["findings"].pop(0)
    
    return state
# 🛠️ UTILITY FUNCTIONS (The Safety Net)
# Logic: These functions act as the "Emergency Protocol" if the LLM is unavailable.
def _is_quota_or_model_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "resource_exhausted" in msg
        or "quota" in msg
        or "429" in msg
        or "not_found" in msg
        or "model" in msg and "not found" in msg
    )


def _fallback_plan_queries(goal: str) -> List[str]:
    return [
        goal,
        f"recent research {goal}",
        f"industry applications {goal}"
    ]


def _fallback_report(goal: str, findings: List[str]) -> str:
    lines = [
        f"Goal: {goal}",
        "",
        "Gemini API call could not be completed (quota/model issue), so this report was generated from collected search snippets.",
        "",
        "Key findings:",
    ]
    if not findings:
        lines.append("- No findings were collected.")
    else:
        for item in findings[:5]:
            preview = item.replace("\n", " ")
            lines.append(f"- {preview[:240]}")
    lines.extend([
        "",
        "Next step:",
        "- Enable Gemini quota/billing (or wait for reset) and rerun to get an LLM-written synthesized report.",
    ])
    return "\n".join(lines)

# 🛠️ THE TOOL
search_tool = DuckDuckGoSearchRun()

# 📋 NODE 1 — THE PLANNER (The Architect) - The "Workers" in your team
# Logic: Take the Goal from the Notebook. Ask the LLM: "What 3 things should we Google?"
# Save those into the Plan section and hand the Notebook to the Searcher.
@traceable(name="plan_node", tags=["planning"])
def plan_node(state: ResearchAgentState) -> ResearchAgentState:
    print(f"\n📋 Planning research for: {state['goal']}")
    try:
        year = datetime.now().year
        response = llm.invoke(f"""
            Goal: {state['goal']}
            Create exactly 3 specific search queries to research this topic.
            Each query MUST include the year {year} to get latest results.
            Return only the queries, one per line, no numbering.
        """)
        state["plan"] = [q.strip() for q in response.content.strip().split("\n") if q.strip()][:3]
    except Exception as e:
        if _is_quota_or_model_error(e):
            print(f"   ⚠️ Gemini unavailable ({MODEL_NAME}). Using fallback planner.")
            state["plan"] = _fallback_plan_queries(state["goal"])
        else:
            raise
    print(f"   Plan: {state['plan']}")
    return state

# 🔍 NODE 2 — THE SEARCHER (The Field Agent)
# Logic: Look at the Plan. Find the first item not in "Searches Done".
# Run search, write results to "Findings", and mark as finished.
@traceable(name="search_node", tags=["searching"])
def search_node(state: ResearchAgentState) -> ResearchAgentState:
    for query in state["plan"]:
        # 🔒 Idempotency check: Find item not in checklist
        if query in state["searches_done"]:
            print(f"   ⏭️ Skipping already searched: {query}")
            continue
        print(f"\n🔍 Searching: {query}")
        try:
            result = search_tool.run(query)
            # Write results into the Findings section
            state["findings"].append(f"Query: {query}\nResult: {result[:200]}")
            state["searches_done"].append(query)
            print(f"   ✅ Found {len(result)} chars of data")
        except Exception as e:
            print(f"   ❌ Search failed: {e}")
    return state


# ✍️ NODE 3 — THE WRITER (The Editor)
# Logic: Read all snippets in Findings. Ask LLM to summarize into a report.
# Save text to the Report section and end the process.
def write_node(state: ResearchAgentState) -> ResearchAgentState:
    print(f"\n✍️ Writing report...")
    findings_text = "\n\n".join(state["findings"])
    try:
        response = llm.invoke(f"""
            Goal: {state['goal']}
            
            Research findings:
            {findings_text}
            
            Write a clear, well-structured 400-word report based on these findings. Make sure its organized, concise, and directly addresses the goal. Use bullet points if helpful.
        """)
        state["report"] = response.content
    except Exception as e:
        if _is_quota_or_model_error(e):
            print(f"   ⚠️ Gemini unavailable ({MODEL_NAME}). Using fallback report writer.")
            state["report"] = _fallback_report(state["goal"], state["findings"])
        else:
            raise
    return state


# 🚦 THE ROUTER (The Quality Manager)
# Logic: Check if we have enough quality findings.
# IF findings >= 2 → enough data, go to Writer.
# IF searches >= 3 → safety limit hit, go to Writer.
# ELSE → keep searching.
def router(state: ResearchAgentState) -> str:
    if len(state["findings"]) >= 2 and len(state["searches_done"]) > 0:
        return "write"
    elif len(state["searches_done"]) >= 3:
        return "write"  # Safety limit / Tasks done
    return "search"

# 🕸️ BUILD THE GRAPH
# This defines how the team communicates and loops.
graph = StateGraph(ResearchAgentState)

graph.add_node("plan", plan_node)
graph.add_node("search", search_node)
graph.add_node("write", write_node)
graph.add_node("budget_check", check_token_budget)

graph.set_entry_point("plan")
graph.add_edge("plan", "search")
graph.add_conditional_edges("search", router, {
    "search": "search",
    "write": "budget_check"
})
graph.add_edge("budget_check", "write")
graph.add_edge("write", END)

# Locks the graph into a runnable pipeline.
# After this, no more nodes or edges can be added.
app = graph.compile()

# 🚀 RUN IT
if __name__ == "__main__":
    # This is the INITIAL STATE — the notebook starts empty.
    # Every node will read from and write to this same dictionary.
    result = app.invoke({
        "goal": "Diyarbakır'daki satilan evler hakkında güncel bilgiler topla ve rapor hazırla",
        "plan": [], # Empty — Planner fills this
        "searches_done": [], # Empty — Searcher fills this
        "findings": [], # Empty — Searcher fills this
        "report": ""    # Empty — Writer fills this
    },
    config={
        "tags": ["research", "development"],     # filter by tag
        "metadata": {
            "user_id": "agent-learner",         # who ran this
            "version": "1.0",                   # agent version
            "environment": "development",       # dev vs prod
            "model": MODEL_NAME
        }
    }
    )
    print("\n" + "="*50)
    print("📄 FINAL REPORT")
    print("="*50)
    print(result["report"])
