# team/writer.py
# ✍️ THE WRITER AGENT (The Editor)
# Responsibility: Read all snippets in Findings. Ask LLM to summarize into a report.
# Save text to the Report section and end the process.
# This is the final node in our agent's workflow. It synthesizes all the collected information
# into a coherent report that addresses the original goal.
# A good writer can make even mediocre findings look insightful, while a bad writer can bury great research in a wall of text.
# This agent ONLY writes — it never plans or searches.
# Has its own LLM — can be tuned for quality independently.
# Intent-aware synthesis. Produces a markdown table for COMPARE goals,
# structured prose for others. Cites inline via [n] linking to source URLs.

import os
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import is_quota_or_model_error, fallback_report

# 🧠 WRITER'S OWN BRAIN
WRITER_MODEL_NAME = os.getenv("WRITER_MODEL", "gemini-2.5-flash-lite")

writer_llm = ChatGoogleGenerativeAI(
    model=WRITER_MODEL_NAME,
    max_retries=3,
    request_timeout=45,
)


def _build_sources_block(findings: list[str]) -> str:
    """Extract [SOURCE n] / URL pairs into a references block for the prompt."""
    lines = []
    for f in findings:
        src_line = next((l for l in f.splitlines() if l.startswith("[SOURCE")), None)
        url_line = next((l for l in f.splitlines() if l.startswith("URL:")), None)
        if src_line and url_line:
            n = src_line.split("]")[0].replace("[SOURCE", "").strip()
            url = url_line.replace("URL:", "").strip()
            lines.append(f"[{n}] {url}")
    return "\n".join(lines)


@traceable(
    name="writer_agent",
    tags=["writer", "writing", "llm"],
    metadata={"agent": "writer", "model": WRITER_MODEL_NAME},
)
def writer_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Synthesizes findings into a report with inline [n] citations.
    Produces a comparison table for 'compare' goals.
    """
    print(f"\n✍️  WRITER: Synthesizing {len(state['findings'])} findings...")

    findings_list = state["verified_findings"] or state["findings"]
    findings_text = "\n\n".join(findings_list)
    sources_block = _build_sources_block(findings_list)

    try:
        response = writer_llm.invoke(f"""
You are an expert research writer. Write a report that directly answers the goal.

GOAL: {state['goal']}

RESEARCH FINDINGS (each starts with [SOURCE n], includes a URL and a Snippet):
{findings_text}

INSTRUCTIONS:

1. Infer the goal's intent. If the goal asks to COMPARE, RANK, or CHOOSE BETWEEN
   options, you MUST include a markdown comparison table with the most relevant
   attributes (e.g. price, range, key spec, standout feature).
   Otherwise, use well-organized prose with bullet points.

2. CONSTRAINT FIT (HARD RULE) — if the goal specifies a hard constraint
   (price cap, size, region, category, year range, etc.), the comparison table
   / main recommendation list MUST ONLY contain items where at least one source
   in the findings confirms the constraint-relevant attribute satisfies the
   constraint. For an "under $40k" goal, that means a source must cite a price
   at or below $40k for that item — otherwise it does NOT go in the table.
   - Items with NO stated price in any source → exclude from the main table.
   - Items with a stated price ABOVE the cap → exclude entirely (do not even
     acknowledge them).
   - If you want to note items that lacked pricing data, put them under a
     separate "## Unverified candidates" paragraph after the main table,
     in prose — never as a table row. Keep this section brief (one sentence).
   - Never fabricate a number. Never write "not stated in sources" inside a
     comparison table cell — just don't include that row.

3. Cite every specific claim inline using [n] where n matches the [SOURCE n]
   tag from the findings. Example: "The Kia EV4 starts at $34,000 [2]."
   Do NOT invent sources. If a claim is not backed by a source, omit it.

4. Only use facts present in the findings. Do not add outside knowledge.
   If findings conflict, note the conflict.

5. Structure:
   - Short intro (1–2 sentences, no citations)
   - Main body (table for COMPARE, bulleted prose otherwise) with inline [n] cites
   - "Bottom line" — 1–2 sentences of direct takeaway
   - "Sources" section listing each [n] with its URL

6. Tone: concrete, analytical, no filler ("in conclusion", "robust landscape",
   "breaking the bank" are banned). Aim for 300–500 words before the Sources list.

SOURCES (for your reference — list these at the end under a "## Sources" heading):
{sources_block}
""")
        state["report"] = response.content
        print(f"   ✅ Report written: {len(state['report'])} chars")

    except Exception as e:
        if is_quota_or_model_error(e):
            print(f"   ⚠️ Writer LLM unavailable ({WRITER_MODEL_NAME}). Using fallback.")
            state["report"] = fallback_report(state["goal"], findings_list)
        else:
            raise

    return state
    """
    Writer Agent — reads all findings from shared notebook.
    Synthesizes into a structured 400-word report.
    Writes result to state['report'].
    """
    print(f"\n✍️  WRITER: Synthesizing {len(state['findings'])} findings...")

    findings_text = "\n\n".join(state["findings"])

    try:
        response = writer_llm.invoke(f"""
            You are an expert research writer.

            Goal: {state['goal']}

            Research findings:
            {findings_text}

            Write a clear, well-structured 400-word report.
            Requirements:
            - Directly address the goal
            - Use bullet points for key findings
            - End with a short conclusion
            - Be concise and factual
        """)
        state["report"] = response.content
        print(f"   ✅ Report written: {len(state['report'])} chars")

    except Exception as e:
        if is_quota_or_model_error(e):
            print(f"   ⚠️ Writer LLM unavailable ({WRITER_MODEL_NAME}). Using fallback.")
            state["report"] = fallback_report(state["goal"], state["findings"])
        else:
            raise

    return state
