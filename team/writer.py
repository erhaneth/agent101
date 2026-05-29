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
from team.evidence_map import format_evidence_map_for_writer


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

    # Build rich evidence context for the writer
    evidence_map = state.get("evidence_map") or {}
    evidence_map_text = format_evidence_map_for_writer(evidence_map)

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

**Use the research brief signals heavily:**
- `target_depth`: "deep" means the user wants substantial analysis and structure — deliver it.
- `hype_sensitivity`: "high" means you must critically dissect marketing claims vs real evidence (this is one of the most important signals for this system).

User goal:
{state["goal"]}

Research brief:
Topic: {brief.get("topic", state["goal"])}
Research type: {brief.get("research_type", "general_explainer")}
Target depth: {brief.get("target_depth", "standard")}
Hype sensitivity: {brief.get("hype_sensitivity", "medium")}
Must cover: {brief.get("must_cover", [])}
Avoid: {brief.get("avoid", [])}

Supported evidence:
{claims_text}

Evidence Quality Summary (use this to ground your analysis of source strength):
{evidence_map_text}

Core rules:
- Use ONLY the supported evidence items above.
- Do NOT add facts from memory or training data.
- Do NOT invent examples, statistics, mechanisms, risks, or recommendations.
- Do NOT cite internal labels such as EVIDENCE ITEM 1, CLAIM 1, [CLAIM 1], or similar.
- Cite actual source URLs inline using markdown format: [source](https://...).
- The Sources section is not enough. Important factual claims must have inline citations in the body.
- The Direct Answer must include inline citations if it makes factual claims.
- The Conclusion must include inline citations if it summarizes factual claims.
- Every factual paragraph or bullet must include at least one inline source URL, **except** inside the Evidence Quality Map section (see the detailed special rule at the end of these instructions). The Evidence Quality Map may present its aggregate statistics using tables and bullets without per-row citations.
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

Report structure rules:

**MANDATORY SECTION REQUIREMENTS FOR scientific_academic / technical_research / policy_legal (non-negotiable):**
When research_type is scientific_academic, technical_research, or policy_legal, you MUST produce a rich, analytical report with these exact sections in this order (do not omit any):
1. Direct Answer (with inline citations)
2. Evidence Quality Map (using the exact data and numbers from the EVIDENCE QUALITY MAP block below — table + quantitative bullets required)
3. Key Findings or Evidence Analysis (synthesis of the verified claims)
4. Key Tensions & Conflicting Evidence (or Evaluation and Methodology)
5. Synthesis & Implications (or The Debate / Uncertainties)
6. Sources

The Evidence Quality Map is the single most important new section for these research types. It must appear as a full dedicated section immediately after the Direct Answer. It must contain a markdown table of the quality/credibility/source-type stats plus bullets for strengths and gaps. Use the precise numbers from the provided EVIDENCE QUALITY MAP data. Failure to include this section means the report is incomplete for scientific research use.

**CITATION HYGIENE RULE — STRICT FOR scientific_academic / technical_research / policy_legal:**
Every factual statement, analytical claim, comparison, or implication in the following sections MUST be immediately followed by a proper inline citation using a full support URL from the verified claims:
- Evidence Quality Map (except the aggregate stats table/bullets, which are exempt)
- Hype vs Evidence Analysis
- Key Tensions & Conflicting Evidence
- Synthesis & Implications
- Any Evidence-Based Analysis or Key Findings bullets

Citation formatting must be clean and professional:
- Never use placeholder text like `[source]`, `[source](url)`, or bare "source" links.
- Preferred: bare full URL (https://...) right after the sentence.
- Also acceptable: proper markdown `[short descriptive text](https://full-url)`.
- If you cannot directly support a sentence with one of the provided verified claim URLs, remove or rephrase the sentence.
This rule is non-negotiable for these research types to maintain 100/100 grounding on rich analytical output.

**CRITICAL DEPTH INSTRUCTIONS (for target_depth == "deep" or hype_sensitivity == "high" or research_type in {"scientific_academic", "technical_research", "policy_legal"}):**
This is a high-value research request. You must produce a substantially deeper, more analytical, and evidence-rich report.

Key requirements:
- Use 7–10 well-structured sections.
- The **Evidence Quality Map** must be a prominent, dedicated section (not just a passing mention).
- You are required to directly reference the specific numbers and insights from the "EVIDENCE QUALITY MAP" block provided above (quality score distribution, high-quality source counts, average credibility, key gaps, and strengths).
- Do genuine synthesis and critical analysis — do not just list claims.
- For hype_sensitivity == "high": The Hype vs Evidence Analysis section must be one of the longest, most detailed, and most critical sections in the entire report. Systematically dismantle specific overstated claims using the Evidence Quality Map data. This is a core deliverable for these queries.

You are allowed (and encouraged) to write longer, more thoughtful analysis when the brief signals deep/high-hype or when the research_type is scientific_academic, technical_research, or policy_legal. For these research types, treat the request as requiring full analytical depth even if target_depth is "standard". Quality analysis and transparent evidence assessment are more important than brevity.

REQUIRED sections (always include):
## Direct Answer
  - Always present. 1-3 paragraphs answering the user's exact question with appropriate depth.
  - Include inline citations for any factual claims.
## Sources
  - Always present. List every URL cited in the report.

HIGHLY RECOMMENDED / REQUIRED for deep, high-hype, scientific_academic, technical_research, or policy_legal questions:

## Evidence Quality Map (ABSOLUTELY MANDATORY — the single most important section for scientific_academic, technical_research, and policy_legal reports; do not omit under any circumstances)
  - This section is **mandatory** — you must include it as a dedicated section. Do not skip or merge it away even if the number of verified claims is small.
  - You have **explicit permission** to present the aggregate data from the EVIDENCE QUALITY MAP block using tables and structured bullets **without** adding an inline citation to every row or bullet.
  - Strongly recommended structure (use this format):
    - One short opening paragraph using framing language (e.g. "Analysis of the verified findings shows...").
    - A small markdown table for the key aggregate metrics.
    - Clear bullet sections for Quality Score Distribution, Source Type Breakdown, and Key Insights (Strengths, Gaps, Diversity).
  - Be quantitative. Directly reference the exact numbers from the provided map.
  - Use analytical framing language for the entire section.
  - This section exists to give the reader an honest, transparent view of how strong (or limited) the underlying evidence actually is. Include it even when evidence is thin.

## Hype vs Evidence Analysis (MANDATORY when hype_sensitivity == "high"; strongly encouraged for scientific_academic when relevant)
  - This must be one of the strongest, longest, and most critical sections in the entire report.
  - Every analytical sentence must carry an immediate inline citation from the verified claims (see CITATION HYGIENE RULE above).
  - Systematically identify specific marketing claims / vendor narratives / popular statistics, then directly contrast them with what the verified evidence (and Evidence Quality Map) actually supports.
  - Explicitly call out overstated numbers, weak sources behind popular claims, and where marketing diverges from rigorous data.
  - Use the Evidence Quality Map data to explain why certain claims are weakly supported (e.g. "The widely cited 8x–12x efficiency gains come primarily from vendor case studies and low-quality sources, while broad independent field studies show only a 26% aggregate gain").
  - Be direct, specific, and evidence-based. Avoid hedging. Structure with clear sub-bullets for individual myths vs reality where helpful.
  - Every sentence must end with a clean inline citation (bare URL or proper markdown link) — no [source] placeholders allowed anywhere in this section.
  - Example strong tone: "Marketing frequently claims '10x developer productivity.' However, the highest-quality multi-company study available shows only a 26.08% increase in completed tasks, with experienced developers sometimes experiencing a 19% slowdown due to review overhead."

## Key Tensions & Conflicting Evidence
  - Every statement must carry an immediate inline citation from the verified claims (see CITATION HYGIENE RULE above).
  - Explicitly surface disagreements, scope differences (e.g. benchmark vs real projects), and areas where evidence is thin or contradictory.

OPTIONAL sections (include ONLY when the evidence justifies them):
## Key Findings
  - Include when there are clear, high-value takeaways worth enumerating.
## Evidence-Based Analysis
  - Deeper analysis of mechanisms, tradeoffs, or patterns in the evidence.
## Uncertainties and Limitations
  - Include ONLY if you can name concrete, specific limits backed by the evidence.
  - Avoid generic disclaimers.
## Synthesis & Implications
  - Every implication or recommendation must be directly tied to specific verified findings with inline citations (see CITATION HYGIENE RULE above).
  - For deep reports: What does this evidence suggest for decision makers or practitioners?
## Conclusion
  - Only if it adds real value beyond the Direct Answer.

Filler ban:
- If you find yourself writing one of these phrases as a section's main content,
  delete that section instead:
    * "depends on the specific use case"
    * "there is no universal winner"
    * "no single best approach"
    * "varies based on deployment"
    * "the right approach depends on"
- These phrases are signals that you don't actually have the evidence to fill that
  section. Cutting them produces a stronger report.

Final quality checks before answering:
- Does this answer the user's actual question?
- Are all sections relevant to the user's question?
- Did you avoid irrelevant templates from other domains?
- Did you use only supported evidence?

Special rule for the Evidence Quality Map section (IMPORTANT):
- This is the **only** section where the normal citation rules are relaxed.
- You have explicit permission to present the aggregate statistics from the EVIDENCE QUALITY MAP data (quality distribution, credibility averages, high-quality counts, source diversity, strengths, and gaps) using markdown tables and structured bullet points **without** adding an inline source URL to every row or bullet.
- You must use clear analytical framing language for the entire section, such as:
  - "Analysis of the verified findings shows..."
  - "The body of evidence indicates..."
  - "A notable characteristic of the evidence base is..."
- Only reference the exact numbers provided in the EVIDENCE QUALITY MAP block — do not invent or extrapolate new numbers.
- This exception exists because the Evidence Quality Map is a meta-analysis of the overall evidence base we gathered, not new factual claims drawn from individual sources.
- Every other section in the report (Direct Answer, Hype vs Evidence Analysis, Key Tensions, etc.) must still follow the standard rule of including inline source URLs for factual statements.
""")

        report = response_to_text(response)
        print(f"   ✅ Report written: {len(report)} chars")
        return {"report": report}

    except Exception as e:
        print(f"   ⚠️ Writer failed ({e}) — using fallback")
        raw = [c.get("claim", "") for c in claims]
        return {"report": fallback_report(state["goal"], raw)}
