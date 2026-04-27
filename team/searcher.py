# team/searcher.py
# 🔍 THE SEARCHER AGENT (The Field Agent)
# Responsibility: Execute search queries. Return structured evidence.
# Reads: plan, searches_done
# Writes: findings, searches_done

import os
from langsmith import traceable
from tavily import TavilyClient

from team.state import ResearchAgentState


def get_search_client():
    """Lazy load — after .env is loaded."""
    return TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def classify_source_type(url: str, title: str) -> str:
    """Simple source classifier — gives evidence judge useful context."""
    text = f"{url} {title}".lower()
    if ".gov" in text or "official" in text or "tuik" in text:
        return "official"
    if "reuters" in text or "apnews" in text or "bbc" in text or "bloomberg" in text:
        return "news"
    if "arxiv" in text or "journal" in text or "doi" in text or "pubmed" in text:
        return "academic"
    if "github" in text or "docs." in text or "developer." in text:
        return "technical"
    if "blog" in text or "medium" in text or "substack" in text:
        return "blog"
    return "web"


@traceable(
    name="searcher_agent",
    tags=["searcher", "searching", "tool-use"],
    metadata={"agent": "searcher", "tool": "tavily"}
)
def searcher_agent(state: ResearchAgentState) -> dict:
    """
    Searcher Agent — executes each query in the plan.
    Returns structured findings: title, url, snippet, source_type.
    Skips already-searched queries (idempotency).
    """
    print(f"\n🔍 SEARCHER: Starting {len(state['plan'])} searches...")

    findings = list(state["findings"])
    searches_done = list(state["searches_done"])

    for query_obj in state["plan"]:

        # Handle both dict queries (v2) and string queries (fallback)
        if isinstance(query_obj, dict):
            query = query_obj["query"]
            purpose = query_obj.get("purpose", "search")
        else:
            query = query_obj
            purpose = "search"

        # 🔒 IDEMPOTENCY CHECK
        if query in searches_done:
            print(f"   ⏭️  Already searched: {query[:50]}...")
            continue

        print(f"   🔎 [{purpose}] {query[:60]}...")

        try:
            client = get_search_client()
            response = client.search(
                query=query,
                search_depth="basic",
                max_results=3,
                days=30  # only results from last 30 days
            )

            for result in response.get("results", []):
                title = result.get("title", "")
                url = result.get("url", "")
                snippet = result.get("content", "")[:500]
                source_type = classify_source_type(url, title)

                findings.append({
                    "query": query,
                    "purpose": purpose,
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source_type": source_type,
                })

            searches_done.append(query)
            print(f"   ✅ Found {len(response.get('results', []))} results")

        except Exception as e:
            # Non-fatal — log and continue
            print(f"   ❌ Search failed for '{query[:40]}': {e}")

    print(f"   📦 Total findings: {len(findings)}")
    return {
        "findings": findings,
        "searches_done": searches_done,
    }