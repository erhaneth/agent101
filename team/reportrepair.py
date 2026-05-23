# team/reportrepair.py
# 🛠️ REPORT REPAIR AGENT
# Responsibility: revise a draft report after post-writer citation verification
# finds unsupported final-report wording.

from __future__ import annotations

import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable

from team.evaluator import split_report_body_and_sources
from team.reportverifier import SUPPORTED_VERDICTS
from team.state import ResearchAgentState
from team.utils import content_to_text, response_to_text
from team.writer import format_claims


def get_report_repair_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("REPORT_REPAIR_MODEL", os.getenv("WRITER_MODEL", "gemini-3.1-flash-lite")),
        max_retries=2,
        request_timeout=50,
        temperature=0.0,
    )


def failed_report_items(report_verifications: list[dict]) -> list[dict]:
    """Return report verification records that need repair."""
    failed = []

    for record in report_verifications or []:
        verdict = (record.get("verdict") or "unsupported").lower()
        if verdict not in SUPPORTED_VERDICTS or record.get("missing_source_urls"):
            failed.append(record)

    return failed


def format_failed_items(items: list[dict]) -> str:
    blocks = []

    for item in items:
        cited_urls = "\n  ".join(item.get("cited_urls", []) or [])
        missing_urls = "\n  ".join(item.get("missing_source_urls", []) or [])
        blocks.append(f"""
FAILED REPORT ITEM {item.get("item_index")}
Line: {item.get("start_line")}
Verdict: {item.get("verdict")}
Text:
{item.get("text", "")}

Cited URLs:
  {cited_urls or "none"}

Missing source URLs:
  {missing_urls or "none"}

Verifier reason:
{item.get("reason", "")}

Caveat:
{item.get("caveat", "")}
""")

    return "\n".join(blocks)


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def remove_failed_report_items(report: str, failed_items: list[dict]) -> str:
    """
    Deterministic fallback: remove unsupported blocks by line number.

    The line numbers come from markdown body parsing before the Sources section.
    This is deliberately conservative: if we cannot confidently rewrite a failed
    claim, we remove it rather than return unsupported wording.
    """
    report = content_to_text(report)
    body_text, sources_text = split_report_body_and_sources(report)
    body_lines = body_text.splitlines()
    failed_starts = {
        safe_int(item.get("start_line", 0))
        for item in failed_items
        if safe_int(item.get("start_line", 0)) > 0
    }

    remove_indexes = set()

    for start_line in failed_starts:
        index = start_line - 1
        if index < 0 or index >= len(body_lines):
            continue

        line = body_lines[index]
        stripped = line.strip()

        if stripped.startswith(("*", "-", "+")) or stripped[:2].endswith("."):
            end = index + 1
            while end < len(body_lines):
                next_line = body_lines[end]
                next_stripped = next_line.strip()
                if not next_stripped:
                    break
                if next_line[:1] not in {" ", "\t"} and (
                    next_stripped.startswith(("*", "-", "+")) or next_stripped[:2].endswith(".")
                ):
                    break
                if next_stripped.startswith("#"):
                    break
                end += 1
        else:
            end = index + 1
            while end < len(body_lines):
                next_stripped = body_lines[end].strip()
                if not next_stripped or next_stripped.startswith("#"):
                    break
                if next_stripped.startswith(("*", "-", "+")) or next_stripped[:2].endswith("."):
                    break
                end += 1

        remove_indexes.update(range(index, end))

    repaired_body = "\n".join(
        line
        for index, line in enumerate(body_lines)
        if index not in remove_indexes
    ).strip()

    if sources_text:
        return repaired_body + "\n\n" + sources_text.strip()
    return repaired_body


@traceable(
    name="report_repair_agent",
    tags=["report", "repair", "citations", "grounding"],
    metadata={"agent": "report_repair"},
)
def report_repair_agent(state: ResearchAgentState) -> dict:
    """
    Repair report text after semantic citation verification fails.

    The repair step gets one chance by default. It should remove or soften only
    unsupported final-report wording, not add new evidence.
    """
    failed_items = failed_report_items(state.get("report_verifications", []))
    attempts = int(state.get("report_repair_attempts", 0) or 0)
    history = list(state.get("report_repair_history", []) or [])

    print(f"\n🛠️ REPORT REPAIR: Attempt {attempts + 1}, failed items: {len(failed_items)}")

    if not failed_items:
        print("   No failed report items to repair.")
        return {
            "report_repair_attempts": attempts,
            "report_repair_history": history,
        }

    report = content_to_text(state.get("report", ""))
    failed_text = format_failed_items(failed_items)
    claims_text = format_claims(state.get("claims", []))

    try:
        response = get_report_repair_llm().invoke(f"""
You are the report repair agent for FactCrafter.

The post-writer citation verifier found final-report wording that was not supported by its cited source text.

Your job:
Rewrite the complete report so it passes semantic citation verification.

Rules:
- Use ONLY the supported evidence items below.
- Do NOT add new facts, examples, statistics, recommendations, or URLs.
- Remove failed report items if the evidence does not support them.
- If a failed item is partly supported, soften it with cautious language and include the caveat.
- Never turn partial evidence into broad phrases like "best practices", "clearly outperforms", or "the 2026 landscape favors" unless directly supported.
- Keep required report sections when possible.
- Keep inline source URLs on factual paragraphs and bullets.
- Return markdown report only. No explanation before or after.

User goal:
{state.get("goal", "")}

Supported evidence items:
{claims_text}

Failed final-report items:
{failed_text}

Current report:
{report}
""")
        repaired_report = response_to_text(response).strip()
        if not repaired_report:
            raise ValueError("empty repair response")
        method = "llm"
    except Exception as error:
        print(f"   ⚠️ Report repair failed ({error}) — removing failed blocks")
        repaired_report = remove_failed_report_items(report, failed_items)
        method = "fallback_remove_failed_blocks"

    history.append(
        {
            "attempt": attempts + 1,
            "method": method,
            "failed_item_count": len(failed_items),
            "failed_item_indexes": [item.get("item_index") for item in failed_items],
        }
    )

    print(f"   ✅ Repaired report length: {len(repaired_report)} chars ({method})")

    return {
        "report": repaired_report,
        "report_repair_attempts": attempts + 1,
        "report_repair_history": history,
    }
