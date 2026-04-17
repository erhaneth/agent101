# team/searcher.py
# THE SEARCHER (The Researcher)
# Responsibility: Execute the search queries created by the Planner and collect raw data. This is the "field research" phase where we gather information.
# This agent ONLY does searches and data collection. It does NOT synthesize or write the report - that is the Writer's job. This separation of concerns allows each agent to specialize and makes the overall system more robust and maintainable.
# Has its own tools and logic for searching, so it can be tuned independently from the Planner and Writer.

from langsmith import traceable
from langchain_community.tools import DuckDuckGoSearchRun

from team.state import ResearchAgentState



#  SEARCHER'S OWN TOOLS
# only the searcher has access to search tools - least privilege
search_tool = DuckDuckGoSearchRun()

# SEARCHER BUDGET
MAX_RESULT_CHARS = 300  # max chars to store per search result to control token usage

@traceable(
    name="searcher_agent",
    tags=["searcher", "searching", "data_collection", "tool-use"],
    metadata={"agent": "searcher", "tool": "DuckDuckGo"}
)
# The Searcher Agent — executes search queries from the plan, collects raw data.

def searcher_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Searcher Agent — executes each query in the plan.
    Writes raw findings to state['findings'].
    Skips already-searched queries (idempotency).
    """
    print(f"\n🔍 SEARCHER: Starting {len(state['plan'])} searches...")

    for query in state["plan"]:

        # 🔒 IDEMPOTENCY CHECK
        if query in state["searches_done"]:
            print(f"   ⏭️  Already searched: {query}")
            continue

        print(f"   🔎 Searching: {query}")
        try:
            result = search_tool.run(query)
            trimmed = result[:MAX_RESULT_CHARS]
            state["findings"].append(
                f"Query: {query}\nResult: {trimmed}"
            )
            state["searches_done"].append(query)
            print(f"   ✅ Found {len(result)} chars → trimmed to {MAX_RESULT_CHARS}")

        except Exception as e:
            print(f"   ❌ Search failed for '{query}': {e}")

    print(f"   📦 Total findings collected: {len(state['findings'])}")
    return state
    """
    Searcher Agent — executes search queries from the plan, collects raw data.
    Reads state['plan'], writes raw results to state['findings'].
    Does NOT write the final report.
    """
    print(f"\n🔍 SEARCHER: Executing research plan...")

    for query in state["plan"]:
        if query in state["searches_done"]:
            print(f"   🔁 Skipping already done query: {query}")
            continue
        print(f"\n🔍 SEARCHER: Starting {len(state['plan'])} searches...")
        for query in state["searches_done"]:
            print(f"   🔁 Skipping already done query: {query}")
            continue
        print(f"\n   🔎 Searching: {query}")

        try:
            result = search_tool.run(query)

            # Trim result to control downstream token costs
            trimmed = result[:MAX_RESULT_CHARS]

            # Write to shared notebook
            state["findings"].append(
                f"Query: {query}\nResult: {trimmed}"
            )
            state["searches_done"].append(query)
            print(f"   ✅ Found {len(result)} chars → trimmed to {MAX_RESULT_CHARS}")

        except Exception as e:
            # Search failure is non-fatal — log and continue
            print(f"   ❌ Search failed for '{query}': {e}")

    print(f"   📦 Total findings collected: {len(state['findings'])}")
    return state


# Note: Non-fatal error handling:             
# Search failure = log and continue
# Agent doesn't crash if one query fails
# Remaining queries still execute