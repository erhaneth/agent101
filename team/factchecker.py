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


def get_checker_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("CHECKER_MODEL", "gemini-2.5-flash-lite"),
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


# team/factchecker.py — source_passes_static_checks()
def source_passes_static_checks(url: str, source_type: str) -> tuple[bool, str]:
    host = urlparse(url).netloc.lower()
    blocked_domains = {
        "facebook.com", "instagram.com", "tiktok.com",
        "x.com", "twitter.com", "pinterest.com", "reddit.com",
        "youtube.com", "youtu.be",           # ← ADD
        "medium.com",                         # ← ADD
        "substack.com",                       # ← ADD
    }
    if source_type == "social" or any(domain in host for domain in blocked_domains):
        return False, "social or forum source is not strong evidence"

    # ← ADD: block LinkedIn posts specifically (profiles/companies are ok)
    if "linkedin.com/posts" in url or "linkedin.com/pulse" in url:
        return False, "LinkedIn post is not peer-reviewed evidence"

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
            parsed.append({
                "title": finding.get("title", ""),
                "url": finding.get("url", ""),
                "snippet": finding.get("snippet", "")[:300],
                "source_type": finding.get("source_type", "web"),
            })
        else:
            parsed.append({
                "title": "", "url": "",
                "snippet": str(finding)[:300],
                "source_type": "web",
            })

    # ── CHANGE 2: build ONE prompt with all findings ──
    findings_block = ""
    for i, f in enumerate(parsed, 1):
        findings_block += f"""
FINDING {i}
Title: {f["title"]}
URL: {f["url"]}
Source type: {f["source_type"]}
Snippet: {f["snippet"]}
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

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

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
            "relevance_score": scores.get("relevance_score", 0),
            "credibility_score": scores.get("credibility_score", 0),
            "freshness_score": 0,
            "usefulness_score": scores.get("usefulness_score", 0),
            "verdict": scores.get("verdict", "reject"),
            "reason": scores.get("reason", ""),
        }

        source_ok, source_reason = source_passes_static_checks(f["url"], f["source_type"])

        if source_ok and score_passes(scores, brief):
            verified.append(result)
            print(f"   ✅ Finding {i+1}: VERIFIED (r:{scores.get('relevance_score')}/c:{scores.get('credibility_score')}/u:{scores.get('usefulness_score')}) — {scores.get('reason', '')[:50]}")
        else:
            if not source_ok:
                result["reason"] = source_reason
            rejected.append(result)
            print(f"   ❌ Finding {i+1}: REJECTED — {result.get('reason', '')[:50]}")

    print(f"\n   📊 EVIDENCE SUMMARY:")
    print(f"   ✅ Verified: {len(verified)}")
    print(f"   ❌ Rejected: {len(rejected)}")

    return {
        "verified_findings": verified,
        "rejected_findings": rejected,
    }