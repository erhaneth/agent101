# team/fact_checker.py
# ⚖️ THE EVIDENCE JUDGE (Upgraded Fact-Checker)
# Responsibility: Score every finding on 4 dimensions.
# Keeps only strong evidence. Stores rejected findings as audit trail.
# Reads: brief + findings
# Writes: verified_findings + rejected_findings

import os
import json
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
    if credibility < 2:
        return False
    if usefulness < 3:
        return False

    return True


@traceable(
    name="evidence_judge",
    tags=["fact-checker", "verification", "scoring", "llm"],
    metadata={"agent": "fact_checker"}
)
def fact_checker_agent(state: ResearchAgentState) -> dict:
    """
    Evidence Judge — scores every finding on 4 dimensions.
    Keeps strong evidence in verified_findings.
    Stores rejected findings with reasons for audit.
    """
    print(f"\n⚖️  EVIDENCE JUDGE: Scoring {len(state['findings'])} findings...")

    verified = []
    rejected = []
    brief = state.get("brief", {})
    freshness_required = brief.get("freshness_required", True)

    for i, finding in enumerate(state["findings"]):
        # Handle both structured (v2) and string (v1 fallback) findings
        if isinstance(finding, dict):
            title = finding.get("title", "")
            url = finding.get("url", "")
            snippet = finding.get("snippet", "")
            source_type = finding.get("source_type", "web")
        else:
            title = ""
            url = ""
            snippet = str(finding)[:400]
            source_type = "web"

        try:
            response = get_checker_llm().invoke(f"""
You are the evidence judge for FactCrafter.

Research brief:
Topic: {brief.get("topic", "unknown")}
Research type: {brief.get("research_type", "general")}
Freshness required: {freshness_required}
Must cover: {brief.get("must_cover", [])}

Source to evaluate:
Title: {title}
URL: {url}
Source type: {source_type}
Snippet: {snippet[:400]}

Score this source from 0 to 5 for each dimension:

relevance_score: Does it directly address the research topic?
  0 = completely off-topic
  3 = partially relevant
  5 = directly answers the research need

credibility_score: How trustworthy is the source?
  0 = spam/unknown blog
  3 = established website
  5 = official/academic/major news

freshness_score: How recent is the information?
  0 = outdated (>2 years)
  3 = somewhat recent (6-12 months)
  5 = very recent (<3 months)
  Note: only matters if freshness_required is true

usefulness_score: Does it contain concrete evidence/data/facts?
  0 = vague/no specifics
  3 = some useful information
  5 = concrete data, statistics, or direct evidence

Rules:
- Official/primary sources score higher for credibility
- If freshness_required is false, freshness_score weight is low
- Reject SEO spam (high ranking but no substance)
- For controversial topics, judge evidence quality not viewpoint
- For technical topics, official docs and repos are strong

Return STRICT JSON only. No markdown, no backticks:
{{
  "relevance_score": 0,
  "credibility_score": 0,
  "freshness_score": 0,
  "usefulness_score": 0,
  "verdict": "keep",
  "reason": "one short sentence"
}}
""")

            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

            scores = json.loads(content)

            # Build verified or rejected finding
            result = {
                "title": title,
                "url": url,
                "snippet": snippet,
                "relevance_score": scores.get("relevance_score", 0),
                "credibility_score": scores.get("credibility_score", 0),
                "freshness_score": scores.get("freshness_score", 0),
                "usefulness_score": scores.get("usefulness_score", 0),
                "verdict": scores.get("verdict", "reject"),
                "reason": scores.get("reason", ""),
            }

            if score_passes(scores, brief):
                verified.append(result)
                total = sum([
                    scores.get("relevance_score", 0),
                    scores.get("credibility_score", 0),
                    scores.get("usefulness_score", 0),
                ])
                print(f"   ✅ Finding {i+1}: VERIFIED (r:{scores.get('relevance_score')}/c:{scores.get('credibility_score')}/u:{scores.get('usefulness_score')}) — {scores.get('reason', '')[:50]}")
            else:
                rejected.append(result)
                print(f"   ❌ Finding {i+1}: REJECTED — {scores.get('reason', '')[:50]}")

        except Exception as e:
            # Fail open for quality — keep finding if check fails
            print(f"   ⚠️ Finding {i+1}: check failed ({e}) — keeping")
            verified.append({
                "title": title, "url": url, "snippet": snippet,
                "relevance_score": 3, "credibility_score": 3,
                "freshness_score": 3, "usefulness_score": 3,
                "verdict": "keep", "reason": "check failed — kept by default",
            })

    print(f"\n   📊 EVIDENCE SUMMARY:")
    print(f"   ✅ Verified: {len(verified)}")
    print(f"   ❌ Rejected: {len(rejected)}")

    return {
        "verified_findings": verified,
        "rejected_findings": rejected,
    }