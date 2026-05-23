# team/writer.py
# ✍️ THE WRITER AGENT
# Responsibility: Organize supported claims into a readable, source-backed report.
#
# Universal writer:
# - Works for any user question.
# - Does NOT use hardcoded job-market / AGI / product / health templates.
# - Derives the report structure from the goal, brief, must_cover, and claims.
# - Uses only supported claims.
# - Requires inline source URLs in every factual block.

import os
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import fallback_report, response_to_text


def get_writer_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("WRITER_MODEL", "gemini-3.1-flash-lite"),
        max_retries=3,
        request_timeout=60,
        temperature=0.0,
    )


def format_claims(claims: list) -> str:
    """
    Format supported claims for the writer prompt.

    Important:
    We call them EVIDENCE ITEMS, not CLAIM 1 / CLAIM 2, to reduce the chance
    that the model cites internal claim IDs instead of real source URLs.
    """
    if not claims:
        return "No supported claims available."

    blocks = []

    for i, claim in enumerate(claims, start=1):
        urls = claim.get("support_urls", []) or []
        urls_text = "\n  ".join(urls) if urls else "No source URLs provided"
        caveat = claim.get("caveat", "")
        confidence = claim.get("confidence", "medium")
        verification_verdict = claim.get("verification_verdict", "not_provided")
        verification_reason = claim.get("verification_reason", "")

        blocks.append(f"""
EVIDENCE ITEM {i}
Supported statement:
{claim.get("claim", "")}

Confidence:
{confidence}

Verification verdict:
{verification_verdict}

Verification reason:
{verification_reason or "No verifier reason provided."}

Source URLs:
  {urls_text}

{"Caveat: " + caveat if caveat else ""}
""")

    return "\n".join(blocks)


@traceable(
    name="writer_agent",
    tags=["writer", "writing", "llm"],
    metadata={"agent": "writer"},
)
def writer_agent(state: ResearchAgentState) -> dict:
    """
    Writer Agent — creates a source-backed report from supported claims only.

    It must adapt to any question type:
    - scientific
    - technical
    - market
    - product comparison
    - local/regional
    - policy/legal
    - historical
    - general explainer
    - company/person profile

    It must not leak irrelevant templates from previous tasks.
    """
    print(f"\n✍️  WRITER: Synthesizing {len(state.get('claims', []))} supported claims...")

    brief = state.get("brief", {})
    claims = state.get("claims", [])
    human_review = state.get("human_review", {}) or {}
    claims_text = format_claims(claims)

    if human_review.get("required") and human_review.get("approved") is False:
        reasons = human_review.get("reasons", []) or []
        decision = human_review.get("decision", "human review was not approved")
        reasons_text = "\n".join(f"- {reason}" for reason in reasons) or "- human review required"
        print("   ⛔ Human review was not approved — blocking report writing")
        return {
            "report": (
                "## Report Blocked: Human Review Required\n\n"
                "This high-stakes report was not written because human review is required before synthesis.\n\n"
                f"Decision: {decision}\n\n"
                "Reasons:\n"
                f"{reasons_text}\n\n"
                "Run the research in an interactive terminal for review, or change HITL_REVIEW_MODE only if this is appropriate for your workflow."
            )
        }

    if not claims:
        print("   ⚠️ No claims available — using fallback")
        raw = [
            f.get("snippet", "") if isinstance(f, dict) else str(f)
            for f in state.get("verified_findings", state.get("findings", []))
        ]
        return {"report": fallback_report(state["goal"], raw)}

    try:
        response = get_writer_llm().invoke(f"""
You are the report writer for FactCrafter, an evidence-first research agent.

Your job:
Write a clear, useful, source-backed answer to the user's exact question.

User goal:
{state["goal"]}

Research brief:
Topic: {brief.get("topic", state["goal"])}
Research type: {brief.get("research_type", "general_explainer")}
Target depth: {brief.get("target_depth", "standard")}
Must cover: {brief.get("must_cover", [])}
Avoid: {brief.get("avoid", [])}

Supported evidence:
{claims_text}

Core rules:
- Use ONLY the supported evidence items above.
- Do NOT add facts from memory or training data.
- Do NOT invent examples, statistics, mechanisms, risks, or recommendations.
- Do NOT cite internal labels such as EVIDENCE ITEM 1, CLAIM 1, [CLAIM 1], or similar.
- Cite actual source URLs inline using markdown format: [source](https://...).
- The Sources section is not enough. Important factual claims must have inline citations in the body.
- The Direct Answer must include inline citations if it makes factual claims.
- The Conclusion must include inline citations if it summarizes factual claims.
- Every factual paragraph or bullet must include at least one inline source URL.
- If a claim has a caveat, include the caveat naturally.
- If evidence is limited, say evidence is limited.
- If confidence is low or verification verdict is partial, use cautious language such as "available evidence suggests" or "one source indicates".
- Do NOT turn partial claims into broad conclusions, best-practice claims, market consensus, or "clearly outperforms" statements.
- Do NOT use article titles, nav headings, or adjacent page links as proof unless the source excerpt directly supports the factual sentence.
- If sources conflict or are weak, say so.
- Do not overstate evidence.
- Do not make predictions unless the supported evidence explicitly supports them.
- Do not use domain-specific templates unless the user's question actually asks for that domain.

Universal structure rules:
- Build the report structure from the user's question, the research type, and must_cover.
- Use section headings that fit the actual question.
- Do not force every answer into job-market, AGI, health, product, or software-comparison wording.
- Do not include irrelevant phrases such as "Role name", "Demand direction", "Why AGI won't replace it", or "job-seeker" unless the user explicitly asked about jobs, AGI, career planning, or employment.
- Do not write "No specific job categories were mentioned" unless the user actually asked about job categories.
- If the question asks for ways to do something, organize by recommended actions/interventions.
- If the question asks for a comparison, organize by comparison dimensions.
- If the question asks for causes, organize by causes and evidence.
- If the question asks for a timeline, organize chronologically.
- If the question asks for a policy/legal answer, organize by rule, obligation, risk, and uncertainty.
- If the question asks for technical differences, organize by architecture, developer experience, flexibility, orchestration, operations, and tradeoffs.
- If none of those fit, organize by the main evidence themes.

Required output sections:

## Direct Answer
Answer the user's exact question directly in 1-2 paragraphs.
Include inline citations for factual claims.

## Key Findings
Bullet points with the most important supported findings.
Every bullet must include at least one inline source URL.

## Evidence-Based Analysis
Use headings and structure that fit this specific question.
Cover the must_cover items when the evidence supports them.
Each factual paragraph, bullet, or subsection must include inline source URLs.

## Uncertainties and Limitations
Explain what the evidence does not prove, where the evidence is weak, and what remains unclear.
Use inline citations when referencing specific evidence limits.

## Conclusion
Summarize what is well-supported and what the reader should take away.
Include inline citations if summarizing factual claims.

## Sources
List every URL cited in the report.

Final quality checks before answering:
- Does this answer the user's actual question?
- Are all sections relevant to the user's question?
- Did you avoid irrelevant templates from other domains?
- Did every factual block include inline source URLs?
- Did you avoid [CLAIM n] / EVIDENCE ITEM citations?
- Did you use only supported evidence?
""")

        report = response_to_text(response)
        print(f"   ✅ Report written: {len(report)} chars")
        return {"report": report}

    except Exception as e:
        print(f"   ⚠️ Writer failed ({e}) — using fallback")
        raw = [c.get("claim", "") for c in claims]
        return {"report": fallback_report(state["goal"], raw)}
