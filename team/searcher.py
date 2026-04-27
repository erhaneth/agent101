# team/searcher.py
# 🔍 THE SEARCHER AGENT (The Field Agent)
# Responsibility: Execute search queries from the plan. Store findings.
# This agent ONLY searches — it never plans or writes.
# Has its own tools — completely independent from other agents.

import os
from langsmith import traceable
from tavily import TavilyClient

from team.state import ResearchAgentState

# 🛠️ SEARCHER'S OWN TOOLS
# Only the searcher has access to search tools — least privilege
def get_search_client():
    """Lazy load — after .env is loaded."""
    return TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# 💰 SEARCHER BUDGET
MAX_RESULT_CHARS = 300  # trim each result to control write_node token cost

@traceable(
    name="searcher_agent",
    tags=["searcher", "searching", "tool-use"],
    metadata={"agent": "searcher", "tool": "tavily"}
)
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
            client = get_search_client()
            response = client.search(
                query=query,
                search_depth="basic",
                max_results=3,
                days=30        # ← only results from last 30 days
            )
            result = "\n".join([r["content"] for r in response["results"]])
            trimmed = result[:MAX_RESULT_CHARS]

            state["findings"].append(
                f"Query: {query}\nResult: {trimmed}"
            )
            state["searches_done"].append(query)
            print(f"   ✅ Found {len(result)} chars → trimmed to {MAX_RESULT_CHARS}")

        except Exception as e:
            # Search failure is non-fatal — log and continue
            print(f"   ❌ Search failed for '{query}': {e}")

    print(f"   📦 Total findings collected: {len(state['findings'])}")
    return {"findings": state["findings"], "searches_done": state["searches_done"]}