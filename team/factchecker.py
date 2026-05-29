# team/fact_checker.py
# ⚖️ THE EVIDENCE JUDGE (Upgraded Fact-Checker)
# Responsibility: Score every finding on 4 dimensions.
# Keeps only strong evidence. Stores rejected findings as audit trail.
# Reads: brief + findings
# Writes: verified_findings + rejected_findings

import os
import json
from urllib.parse import urlparse

from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.sourcequality import rank_source, source_quality_passes
from team.utils import strip_json_fences


def get_checker_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("CHECKER_MODEL", "gemini-3.1-flash-lite"),
        max_retries=2,
        request_timeout=20,
        temperature=0.0,
    )


def score_passes(scores: dict, brief: dict) -> bool:
    """
    Decide if a source passes based on scores.
    Freshness weight varies by whether freshness is required.
    """
    relevance = scores.get("relevance_score", 0)
    credibility = scores.get("credibility_score", 0)
    usefulness = scores.get("usefulness_score", 0)
    verdict = scores.get("verdict", "reject")

    # Must pass minimum thresholds
    if verdict == "reject":
        return False
    if relevance < 3:
        return False
    if credibility < 3:
        return False
    if usefulness < 3:
        return False

    return True


def is_scientific_academic_brief(brief: dict) -> bool:
    return brief.get("research_type") == "scientific_academic"


def is_strong_scientific_source(url: str, source_type: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if "blog" in host or "thereader." in host or "/blog" in path:
        return False

    weak_paths = (
        "/topics/",
        "/editor-resources/",
        "/publish/article/",
        "/the-reader/",
    )
    if any(part in path for part in weak_paths):
        return False

    strong_hosts = (
        "arxiv.org",
        "pubmed.ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "doi.org",
        "nature.com",
        "science.org",
        "springer.com",
        "link.springer.com",
        "onlinelibrary.wiley.com",
        "tandfonline.com",
        "sagepub.com",
        "frontiersin.org",
        "plos.org",
        "mdpi.com",
        "sciencedirect.com",
        "jstor.org",
    )
    if any(domain in host for domain in strong_hosts):
        return "sciencedirect.com" not in host or "/science/article/" in path

    if host.endswith((".edu", ".ac.uk")):
        return True

    if path.endswith(".pdf") and source_type in {"academic", "official", "web"}:
        return True

    return source_type in {"academic", "official"}


# team/factchecker.py — source_passes_static_checks()
def source_passes_static_checks(url: str, source_type: str, brief: dict | None = None) -> tuple[bool, str]:
    brief = brief or {}
    host = urlparse(url).netloc.lower()
    blocked_domains = {
        "facebook.com", "instagram.com", "tiktok.com",
        "x.com", "twitter.com", "pinterest.com", "reddit.com",
        "youtube.com", "youtu.be",           # ← ADD
        "medium.com",                         # ← ADD
        "substack.com",                       # ← ADD
        "quora.com",
    }
    if source_type == "social" or any(domain in host for domain in blocked_domains):
        return False, "social or forum source is not strong evidence"

    # ← ADD: block LinkedIn posts specifically (profiles/companies are ok)
    if "linkedin.com/posts" in url or "linkedin.com/pulse" in url:
        return False, "LinkedIn post is not peer-reviewed evidence"

    if is_scientific_academic_brief(brief):
        weak_academic_hosts = {
            "researchgate.net",
            "academia.edu",
            "sciencedirect.com",
        }
        if any(domain in host for domain in weak_academic_hosts):
            if "sciencedirect.com" in host and "/science/article/" in url:
                return True, ""
            return False, "secondary academic profile or topic page is too weak for scientific evidence"

        if not is_strong_scientific_source(url, source_type):
            return False, "source is not strong enough for scientific-academic evidence"

    return True, ""

@traceable(
    name="evidence_judge",
    tags=["fact-checker", "verification", "scoring", "llm"],
    metadata={"agent": "fact_checker"}
)
def fact_checker_agent(state: ResearchAgentState) -> dict:
    """
    Evidence Judge — scores all findings in ONE batched LLM call.
    Keeps strong evidence in verified_findings.
    Stores rejected findings with reasons for audit.
    """
    print(f"\n⚖️  EVIDENCE JUDGE: Scoring {len(state['findings'])} findings...")

    verified = []
    rejected = []
    brief = state.get("brief", {})
    freshness_required = brief.get("freshness_required", True)

    # ── CHANGE 1: parse all findings first, outside the LLM call ──
    parsed = []
    for finding in state["findings"]:
        if isinstance(finding, dict):
            item = {
                "title": finding.get("title", ""),
                "url": finding.get("url", ""),
                "snippet": finding.get("snippet", "")[:300],
                "evidence_text": (finding.get("evidence_text") or finding.get("snippet", ""))[:1200],
                "search_cache_status": finding.get("search_cache_status", "unknown"),
                "fetched_text": finding.get("fetched_text", ""),
                "fetch_status": finding.get("fetch_status", "not_fetched"),
                "fetch_error": finding.get("fetch_error", ""),
                "cache_status": finding.get("cache_status", "unknown"),
                "http_status": finding.get("http_status", 0),
                "content_type": finding.get("content_type", ""),
                "final_url": finding.get("final_url", finding.get("url", "")),
                "source_metadata": finding.get("source_metadata", {}),
                "source_type": finding.get("source_type", "web"),
            }
            item.update(rank_source(item, brief))
            parsed.append(item)
        else:
            item = {
                "title": "", "url": "",
                "snippet": str(finding)[:300],
                "evidence_text": str(finding)[:1200],
                "search_cache_status": "unknown",
                "fetched_text": "",
                "fetch_status": "not_fetched",
                "fetch_error": "",
                "cache_status": "unknown",
                "http_status": 0,
                "content_type": "",
                "final_url": "",
                "source_metadata": {},
                "source_type": "web",
            }
            item.update(rank_source(item, brief))
            parsed.append(item)

    # ── CHANGE 2: build ONE prompt with all findings ──
    findings_block = ""
    for i, f in enumerate(parsed, 1):
        findings_block += f"""
FINDING {i}
Title: {f["title"]}
URL: {f["url"]}
Source type: {f["source_type"]}
Fetch status: {f["fetch_status"]}
Cache status: search={f["search_cache_status"]}, source={f["cache_status"]}
Source quality: {f["source_quality_score"]}/5 ({f["source_quality_category"]}) — {"; ".join(f["source_quality_reasons"][:3])}
Evidence text: {f["evidence_text"]}
"""

    try:
        response = get_checker_llm().invoke(f"""
You are the evidence judge for FactCrafter.

Research brief:
Topic: {brief.get("topic", "unknown")}
Research type: {brief.get("research_type", "general")}
Freshness required: {freshness_required}
Must cover: {brief.get("must_cover", [])}

Score EACH finding from 0 to 5 on these dimensions:

relevance_score: Does it directly address the research topic?
  0 = completely off-topic, 3 = partially relevant, 5 = directly answers the need

credibility_score: How trustworthy is the source?
  0 = spam/unknown blog, 3 = established website, 5 = official/academic/major news

usefulness_score: Does it contain concrete evidence/data/facts?
  0 = vague/no specifics, 3 = some useful info, 5 = concrete data or statistics

Rules:
- Reject SEO spam (high ranking but no substance)
- Official/primary sources score higher for credibility
- If freshness_required is false, freshness does not affect verdict
- For scientific_academic briefs: Be more accepting of high-quality primary reports from reputable research organizations (e.g. major pilot studies from well-known orgs like 4 Day Week Global, Autonomy, OECD, etc.), even if they are not traditional peer-reviewed papers. Prioritize concrete data over perfect academic formatting.

Findings to score:
{findings_block}

Return a JSON array with one entry per finding, in the same order.
STRICT JSON only — no markdown, no backticks:
[
  {{
    "finding_index": 1,
    "relevance_score": 0,
    "credibility_score": 0,
    "usefulness_score": 0,
    "verdict": "keep",
    "reason": "one short sentence"
  }}
]
""")

        content = strip_json_fences(response)

        scores_list = json.loads(content)

    except Exception as e:
        print(f"   ⚠️ Batch scoring failed ({e}) — rejecting all findings")
        return {
            "verified_findings": [],
            "rejected_findings": [
                {**p, "relevance_score": 0, "credibility_score": 0,
                 "freshness_score": 0, "usefulness_score": 0,
                 "verdict": "reject", "reason": "batch check failed"}
                for p in parsed
            ],
        }

    # ── CHANGE 3: zip scores back to parsed findings ──
    for i, (f, scores) in enumerate(zip(parsed, scores_list)):
        result = {
            "title": f["title"],
            "url": f["url"],
            "snippet": f["snippet"],
            "evidence_text": f["evidence_text"],
            "search_cache_status": f["search_cache_status"],
            "fetched_text": f["fetched_text"],
            "fetch_status": f["fetch_status"],
            "fetch_error": f["fetch_error"],
            "cache_status": f["cache_status"],
            "http_status": f["http_status"],
            "content_type": f["content_type"],
            "final_url": f["final_url"],
            "source_metadata": f["source_metadata"],
            "source_quality_score": f["source_quality_score"],
            "source_quality_category": f["source_quality_category"],
            "source_quality_reasons": f["source_quality_reasons"],
            "source_quality_hard_reject": f["source_quality_hard_reject"],
            "relevance_score": scores.get("relevance_score", 0),
            "credibility_score": scores.get("credibility_score", 0),
            "freshness_score": 0,
            "usefulness_score": scores.get("usefulness_score", 0),
            "verdict": scores.get("verdict", "reject"),
            "reason": scores.get("reason", ""),
        }

        source_ok, source_reason = source_passes_static_checks(f["url"], f["source_type"], brief)
        quality_ok, quality_reason = source_quality_passes(f, brief)

        if source_ok and quality_ok and score_passes(scores, brief):
            verified.append(result)
            print(f"   ✅ Finding {i+1}: VERIFIED (q:{f['source_quality_score']}/r:{scores.get('relevance_score')}/c:{scores.get('credibility_score')}/u:{scores.get('usefulness_score')}) — {scores.get('reason', '')[:50]}")
        else:
            if not source_ok:
                result["reason"] = source_reason
            elif not quality_ok:
                result["reason"] = quality_reason
            rejected.append(result)
            print(f"   ❌ Finding {i+1}: REJECTED — {result.get('reason', '')[:50]}")

    print(f"\n   📊 EVIDENCE SUMMARY:")
    print(f"   ✅ Verified: {len(verified)}")
    print(f"   ❌ Rejected: {len(rejected)}")

    return {
        "verified_findings": verified,
        "rejected_findings": rejected,
    }
