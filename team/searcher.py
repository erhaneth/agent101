# team/searcher.py
# 🔍 THE SEARCHER AGENT (The Field Agent)
# Responsibility: Execute search queries. Return structured evidence.
# Reads: plan, searches_done
# Writes: findings, searches_done

import os
from urllib.parse import urlparse

from langsmith import traceable
from tavily import TavilyClient

from team.state import ResearchAgentState


def get_search_client():
    """Lazy load — after .env is loaded."""
    return TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def classify_source_type(url: str, title: str) -> str:
    """Simple source classifier — gives evidence judge useful context."""
    text = f"{url} {title}".lower()
    host = urlparse(url).netloc.lower()
    if any(domain in host for domain in ["facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com"]):
        return "social"
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


def should_skip_source(url: str, title: str, snippet: str) -> tuple[bool, str]:
    """Reject sources that are too weak to become evidence."""
    host = urlparse(url).netloc.lower()
    blocked_domains = [
        "facebook.com", "instagram.com", "tiktok.com",
        "x.com", "twitter.com", "pinterest.com", "reddit.com",
        "youtube.com", "youtu.be",
        "medium.com",
    ]
    if any(domain in host for domain in blocked_domains):
        return True, "social or forum source"

    if "linkedin.com/posts" in url or "linkedin.com/pulse" in url:
        return True, "LinkedIn post"

    if len(snippet.strip()) < 80:
        return True, "snippet too thin"

    return False, ""


def search_days_for_brief(brief: dict) -> int | None:
    """Choose Tavily freshness window from the research brief."""
    if not brief.get("freshness_required", True):
        return None

    research_type = brief.get("research_type", "")
    if research_type in {"current_events", "market_analysis", "product_comparison", "policy_legal"}:
        return 365

    return 30


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
    brief = state.get("brief", {})
    days = search_days_for_brief(brief)

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
            search_kwargs = {
                "query": query,
                "search_depth": "basic",
                "max_results": 3,
            }
            if days is not None:
                search_kwargs["days"] = days

            response = client.search(**search_kwargs)

            for result in response.get("results", []):
                title = result.get("title", "")
                url = result.get("url", "")
                snippet = result.get("content", "")[:500]
                should_skip, reason = should_skip_source(url, title, snippet)
                if should_skip:
                    print(f"      ↳ skipped {url[:60]}... ({reason})")
                    continue

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
            searches_done.append(query)

    print(f"   📦 Total findings: {len(findings)}")
    return {
        "findings": findings,
        "searches_done": searches_done,
    }
