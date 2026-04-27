# team/claimbuilder.py
# 🔗 THE CLAIM BUILDER AGENT
# Responsibility: Extract only claims supported by verified evidence.
# Every claim must have source URLs, confidence level, and caveats.
# The writer reads claims — not raw findings. It cannot invent.
# Reads: brief + verified_findings
# Writes: claims

import os
import json
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState


def get_claim_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("CLAIM_MODEL", "gemini-2.5-flash-lite"),
        max_retries=3,
        request_timeout=30,
        temperature=0.0,  # deterministic — no invention
    )


def format_verified_sources(findings: list) -> str:
    """Format verified findings for the claim builder prompt."""
    blocks = []
    for i, f in enumerate(findings, start=1):
        blocks.append(f"""
SOURCE {i}
Title: {f.get("title", "unknown")}
URL: {f.get("url", "")}
Snippet: {f.get("snippet", "")[:400]}
Credibility: {f.get("credibility_score", 0)}/5
Reason kept: {f.get("reason", "")}
""")
    return "\n".join(blocks)


def fallback_claims(verified_findings: list, goal: str) -> list:
    """Emergency claims when LLM is unavailable."""
    claims = []
    for f in verified_findings[:3]:
        if f.get("snippet"):
            claims.append({
                "claim": f.get("snippet", "")[:200],
                "support_urls": [f.get("url", "")],
                "confidence": "low",
                "caveat": "Generated from raw snippet — LLM claim builder unavailable"
            })
    return claims


@traceable(
    name="claim_builder_agent",
    tags=["claims", "grounding", "llm"],
    metadata={"agent": "claim_builder"}
)
def claim_builder_agent(state: ResearchAgentState) -> dict:
    """
    Claim Builder Agent — extracts evidence-backed claims.
    Every claim must be supported by at least one source URL.
    Writer reads these claims — not raw findings.
    This is the layer that prevents the writer from inventing.
    """
    print(f"\n🔗 CLAIM BUILDER: Extracting claims from {len(state['verified_findings'])} verified sources...")

    if not state["verified_findings"]:
        print("   ⚠️ No verified findings — using fallback claims")
        return {"claims": fallback_claims(state["findings"], state["goal"])}

    sources_text = format_verified_sources(state["verified_findings"])
    brief = state.get("brief", {})

    try:
        response = get_claim_llm().invoke(f"""
You are the claim builder for FactCrafter, an evidence-first research agent.

Research brief:
Topic: {brief.get("topic", state["goal"])}
Research type: {brief.get("research_type", "general")}
Must cover: {brief.get("must_cover", [])}

Verified sources:
{sources_text}

Extract supported claims only.

Rules:
- Every claim must be directly supported by at least one source URL above
- Do not invent facts not present in the sources
- Do not make predictions unless the source explicitly supports them
- Use confidence: high (strong direct evidence), medium (implied/partial), low (weak/indirect)
- Add caveats where evidence is incomplete, conflicting, or outdated
- Prefer concrete claims over vague ones
- If sources disagree, create a claim explaining the disagreement
- If evidence is thin, say so with a caveat
- Aim for 5-10 claims covering the must_cover topics

Return STRICT JSON only. No markdown, no backticks:
[
  {{
    "claim": "specific factual statement",
    "support_urls": ["url1", "url2"],
    "confidence": "high",
    "caveat": null
  }},
  {{
    "claim": "another supported claim",
    "support_urls": ["url1"],
    "confidence": "medium",
    "caveat": "Based on limited data from a single source"
  }}
]
""")

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        claims = json.loads(content)

        print(f"   ✅ Extracted {len(claims)} supported claims")
        for i, claim in enumerate(claims[:3]):  # show first 3
            conf = claim.get("confidence", "?")
            text = claim.get("claim", "")[:70]
            print(f"   [{conf}] {text}...")

        return {"claims": claims}

    except Exception as e:
        print(f"   ⚠️ Claim builder failed ({e}) — using fallback")
        return {"claims": fallback_claims(state["verified_findings"], state["goal"])}