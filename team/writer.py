# team/writer.py
# ✍️ THE WRITER AGENT (The Editor)
# Responsibility: Organize supported claims into a readable report.
# Reads: brief + claims (NOT raw findings)
# Writes: report
# CRITICAL: Writer never invents. It only organizes supported claims.

import os
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import fallback_report


def get_writer_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("WRITER_MODEL", "gemini-2.5-flash-lite"),
        max_retries=3,
        request_timeout=60,
    )


def format_claims(claims: list) -> str:
    """Format claims for the writer prompt."""
    if not claims:
        return "No supported claims available."
    blocks = []
    for i, claim in enumerate(claims, start=1):
        urls = "\n  ".join(claim.get("support_urls", []))
        caveat = claim.get("caveat", "")
        conf = claim.get("confidence", "medium")
        blocks.append(f"""
CLAIM {i} [{conf} confidence]
{claim.get("claim", "")}
Sources:
  {urls}
{"Caveat: " + caveat if caveat else ""}
""")
    return "\n".join(blocks)


@traceable(
    name="writer_agent",
    tags=["writer", "writing", "llm"],
    metadata={"agent": "writer"}
)
def writer_agent(state: ResearchAgentState) -> dict:
    """
    Writer Agent — organizes supported claims into a structured report.
    Reads from state['claims'] — never raw findings.
    Separates fact, interpretation, uncertainty.
    Includes source URLs next to important claims.
    """
    print(f"\n✍️  WRITER: Synthesizing {len(state['claims'])} supported claims...")

    brief = state.get("brief", {})
    claims_text = format_claims(state["claims"])

    # Fallback if no claims
    if not state["claims"]:
        print("   ⚠️ No claims available — using fallback")
        raw = [f.get("snippet", "") if isinstance(f, dict) else str(f)
               for f in state.get("verified_findings", state.get("findings", []))]
        return {"report": fallback_report(state["goal"], raw)}

    try:
        response = get_writer_llm().invoke(f"""
You are the report writer for FactCrafter, an evidence-first research agent.

Research brief:
Topic: {brief.get("topic", state["goal"])}
Research type: {brief.get("research_type", "general")}
Target depth: {brief.get("target_depth", "standard")}
Must cover: {brief.get("must_cover", [])}

Supported claims (use ONLY these — do not add facts from memory):
{claims_text}

Write a clear, well-structured research report.

Strict rules:
- Use ONLY the supported claims above
- Include source URLs next to important claims like this: [source](url)
- Do not add facts from memory or training data
- Clearly separate: fact (supported by evidence), interpretation (your reading), uncertainty
- When confidence is low or caveat exists — say so explicitly
- If claims conflict — explain the conflict, do not pick a side without evidence
- If evidence is thin — say "evidence is limited" rather than speculating
- Do not overstate conclusions

Structure your report exactly like this:

## Direct Answer
One paragraph directly answering the research goal.

## Key Findings
Bullet points of the most important supported claims with sources.

## Evidence-Based Analysis
Deeper analysis organized by theme. Cite sources inline.

## Uncertainties and Limitations
What the evidence doesn't cover. Where sources conflict. What needs more research.

## Conclusion
Brief summary. What is well-supported vs what remains uncertain.

## Sources
List all URLs cited in the report.
""")

        report = response.content
        print(f"   ✅ Report written: {len(report)} chars")
        return {"report": report}

    except Exception as e:
        print(f"   ⚠️ Writer failed ({e}) — using fallback")
        raw = [c.get("claim", "") for c in state["claims"]]
        return {"report": fallback_report(state["goal"], raw)}