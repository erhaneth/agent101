# team/graph.py
# 🕸️ THE GRAPH (The Team Wiring)
# This file defines HOW the team works together.
# No business logic here — only structure and routing.
# This is where we define the structure of our team and how they communicate.
# We create a graph where each node is an agent (Planner, Searcher, Writer)
# and edges define the flow of information and tasks between them.
# The Router node is a special decision point that checks the state and decides whether we need more searching or if we have enough to start writing.
# This graph allows for dynamic workflows — we can loop back to searching if we don't have enough findings, or move forward to writing when we're ready.
# The graph is built using the StateGraph class, which manages the nodes and edges, and
#  compiles it into a runnable pipeline.

# team/graph.py
# 🕸️ THE GRAPH (Team Wiring)
# Connects all agents into one pipeline.
# Pipeline: brief → plan → search → fact_check → claim_build → budget_check → write → END
# No business logic here — only structure and routing.

from langgraph.graph import StateGraph, END

from team.state import ResearchAgentState
from team.brief import brief_agent
from team.planner import planner_agent
from team.searcher import searcher_agent
from team.factchecker import fact_checker_agent
from team.claimbuilder import claim_builder_agent
from team.writer import writer_agent


# 🚦 ROUTER
def router(state: ResearchAgentState) -> str:
    """
    Decides: search more or move forward.
    Compares searches_done count to plan size.
    """
    searches_done = len(state["searches_done"])
    plan_size = len(state["plan"])

    if searches_done >= plan_size:
        return "fact_check"   # all planned searches done
    elif searches_done >= 8:
        return "fact_check"   # hard safety limit
    return "search"           # keep searching


# 💰 BUDGET CHECK
MAX_TOKENS_ESTIMATE = 4000  # increased for structured findings

def budget_check(state: ResearchAgentState) -> dict:
    """
    Guard node — trims findings if token budget exceeded.
    Pure Python: no LLM, no cost, 0.00s latency.
    Trims oldest findings first.
    """
    findings = list(state["findings"])

    # Estimate tokens from all snippet text
    total_chars = sum(
        len(f.get("snippet", "") if isinstance(f, dict) else str(f))
        for f in findings
    )
    estimated_tokens = total_chars // 4

    if estimated_tokens > MAX_TOKENS_ESTIMATE:
        print(f"\n💰 BUDGET: ~{estimated_tokens} tokens estimated. Trimming...")
        while findings:
            total_chars = sum(
                len(f.get("snippet", "") if isinstance(f, dict) else str(f))
                for f in findings
            )
            if total_chars // 4 <= MAX_TOKENS_ESTIMATE:
                break
            findings.pop(0)  # trim oldest first
        print(f"   ✅ Trimmed to {len(findings)} findings")

    return {"findings": findings}


def build_graph() -> StateGraph:
    """
    Build and compile the FactCrafter pipeline.

    Flow:
    brief → plan → search → [router] → fact_check
                     ↑___________|
                                 ↓
                          claim_build → budget_check → write → END
    """
    graph = StateGraph(ResearchAgentState)

    # 🧩 REGISTER ALL NODES
    graph.add_node("brief", brief_agent)
    graph.add_node("plan", planner_agent)
    graph.add_node("search", searcher_agent)
    graph.add_node("fact_check", fact_checker_agent)
    graph.add_node("claim_build", claim_builder_agent)
    graph.add_node("budget_check", budget_check)
    graph.add_node("write", writer_agent)

    # 🔗 DEFINE THE FLOW
    graph.set_entry_point("brief")
    graph.add_edge("brief", "plan")
    graph.add_edge("plan", "search")

    # Router decides: search more or move to fact_check
    graph.add_conditional_edges("search", router, {
        "search": "search",
        "fact_check": "fact_check",
    })

    graph.add_edge("fact_check", "claim_build")
    graph.add_edge("claim_build", "budget_check")
    graph.add_edge("budget_check", "write")
    graph.add_edge("write", END)

    return graph.compile()


# Compile once at import time
research_team = build_graph()