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


from langgraph.graph import StateGraph, END

from team.state import ResearchAgentState
from team.planner import planner_agent
from team.searcher import searcher_agent
from team.writer import writer_agent

# 🚦 THE ROUTER (The Quality Manager)
# Logic: Check if we have enough quality findings.
# IF findings >= 2 → enough data, go to Writer.
# IF searches >= 3 → safety limit hit, go to Writer.
# ELSE → keep searching.
def router(state: ResearchAgentState) -> str:
    searches_done = len(state["searches_done"])
    plan_size = len(state["plan"])

    # All planned searches completed → write
    if searches_done >= plan_size:
        return "write"
    # Safety limit → write
    elif searches_done >= 3:
        return "write"
    # Still have searches to do → keep searching
    return "search"


# 💰 BUDGET GUARD
# Pure Python — no LLM, no cost, no latency.
# Trims findings before they reach the writer to control token cost.
MAX_TOKENS_ESTIMATE = 2000

def budget_check(state: ResearchAgentState) -> ResearchAgentState:
    """Guard node — trims findings if token budget exceeded."""
    total_chars = sum(len(f) for f in state["findings"])
    estimated_tokens = total_chars // 4

    if estimated_tokens > MAX_TOKENS_ESTIMATE:
        print(f"\n💰 BUDGET: ~{estimated_tokens} tokens estimated. Trimming...")
        while sum(len(f) for f in state["findings"]) // 4 > MAX_TOKENS_ESTIMATE:
            state["findings"].pop(0)
        print(f"   ✅ Trimmed to {len(state['findings'])} findings")

    return state

def build_graph() -> StateGraph:
    """
    Build and compile the multi-agent research graph.
    Returns a compiled runnable pipeline.
    
    Flow:
    planner → searcher → [router] → budget_check → writer → END
                ↑______________|
                (loops if not enough findings)
    """
    graph = StateGraph(ResearchAgentState)

    # 🧩 REGISTER ALL AGENTS AS NODES
    graph.add_node("plan", planner_agent)
    graph.add_node("search", searcher_agent)
    graph.add_node("budget_check", budget_check)
    graph.add_node("write", writer_agent)

    # 🔗 DEFINE THE FLOW
    graph.set_entry_point("plan")
    graph.add_edge("plan", "search")

    # Router decides: search more or move to budget check
    graph.add_conditional_edges("search", router, {
        "search": "search",       # loop back
        "write": "budget_check"   # enough data → check budget first
    })

    # Budget check → writer → done
    graph.add_edge("budget_check", "write")
    graph.add_edge("write", END)

    return graph.compile()

# Compile once at import time
# All other files import this directly
research_team = build_graph()


# Note: This is called dependency direction — dependencies only flow one way. Lower layers never import from higher layers.
# graph.py knows about everyone
# but nobody else knows about graph.py

# planner.py  ← knows only state + utils
# searcher.py ← knows only state
# writer.py   ← knows only state + utils
# graph.py    ← knows everyone, wires them together
# main.py     ← knows only graph