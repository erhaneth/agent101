# team/searcher.py
# THE SEARCHER (The Researcher)
# Executes planner queries, collects structured results (snippet + URL) from DuckDuckGo.
# Each result becomes one finding so the writer can cite sources individually.

from langsmith import traceable
from langchain_community.tools import DuckDuckGoSearchResults

from team.state import ResearchAgentState


search_tool = DuckDuckGoSearchResults(output_format="list", num_results=4)

MAX_SNIPPET_CHARS = 1000     # per-snippet cap (was 300 — too aggressive)
MAX_RESULTS_PER_QUERY = 3    # keep top 3 per query


@traceable(
    name="searcher_agent",
    tags=["searcher", "searching", "data_collection", "tool-use"],
    metadata={"agent": "searcher", "tool": "DuckDuckGo"},
)
def searcher_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Executes each query in the plan. Each search result becomes one finding
    formatted as:  [SOURCE n] Title — URL\nQuery: ...\nSnippet: ...
    Idempotent: skips queries already in searches_done.
    """
    print(f"\n🔍 SEARCHER: Starting {len(state['plan'])} searches...")

    source_counter = len(state["findings"]) + 1

    for query in state["plan"]:
        if query in state["searches_done"]:
            print(f"   ⏭️  Already searched: {query}")
            continue

        print(f"   🔎 Searching: {query}")
        try:
            results = search_tool.run(query)
        except Exception as e:
            print(f"   ❌ Search failed for '{query}': {e}")
            continue

        # DuckDuckGoSearchResults(output_format="list") → list[dict]
        # Keys: 'snippet', 'title', 'link'
        if not isinstance(results, list):
            print(f"   ⚠️ Unexpected result type for '{query}': {type(results)}")
            continue

        kept = 0
        seen_links = {f for f in state["findings"] if "URL:" in f}
        for r in results[:MAX_RESULTS_PER_QUERY]:
            title = (r.get("title") or "Untitled").strip()
            link = (r.get("link") or "").strip()
            snippet = (r.get("snippet") or "").strip()[:MAX_SNIPPET_CHARS]

            if not snippet:
                continue
            # Simple dedup — skip if we already have this URL
            if link and any(link in f for f in state["findings"]):
                continue

            state["findings"].append(
                f"[SOURCE {source_counter}] {title}\n"
                f"URL: {link}\n"
                f"Query: {query}\n"
                f"Snippet: {snippet}"
            )
            source_counter += 1
            kept += 1

        state["searches_done"].append(query)
        print(f"   ✅ Kept {kept} results for this query")

    print(f"   📦 Total findings collected: {len(state['findings'])}")
    return state
