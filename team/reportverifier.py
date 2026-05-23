# team/reportverifier.py
# 🔐 POST-WRITER CITATION VERIFIER
# Responsibility: verify that cited final-report statements are actually
# supported by the source text behind those citations.

from __future__ import annotations

import json
import os
import re

from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable

from team.evaluator import (
    MARKDOWN_LINK_RE,
    URL_RE,
    block_needs_citation,
    extract_urls,
    markdown_blocks,
    normalize_url,
    split_report_body_and_sources,
)
from team.state import ResearchAgentState
from team.utils import content_to_text, strip_json_fences


SUPPORTED_VERDICTS = {"supported", "partial"}


def get_report_verifier_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("REPORT_VERIFIER_MODEL", os.getenv("CLAIM_VERIFIER_MODEL", os.getenv("CLAIM_MODEL", "gemini-3.1-flash-lite"))),
        max_retries=2,
        request_timeout=45,
        temperature=0.0,
    )


def source_lookup(verified_findings: list[dict]) -> dict[str, dict]:
    """Index verified findings by normalized original and final URLs."""
    lookup = {}

    for finding in verified_findings:
        for key in ("url", "final_url"):
            normalized = normalize_url(finding.get(key, ""))
            if normalized:
                lookup[normalized] = finding

    return lookup


def report_text_for_verification(block_text: str) -> str:
    """Remove citation syntax while keeping the factual sentence text."""
    text = MARKDOWN_LINK_RE.sub(lambda match: match.group(1), block_text or "")
    text = URL_RE.sub("", text)
    text = re.sub(r"[*_`>#]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def cited_report_items(report: str, max_items: int | None = None) -> list[dict]:
    """
    Extract citation-bearing report blocks from the body, excluding Sources.

    We verify blocks rather than raw URLs because the risk is semantic: a sentence
    may contain a citation while saying something the cited page does not support.
    """
    report = content_to_text(report)
    body_text, _ = split_report_body_and_sources(report)
    items = []

    for block in markdown_blocks(body_text):
        urls = extract_urls(block.get("text", ""))
        if not urls:
            continue

        verification_text = report_text_for_verification(block.get("text", ""))
        if len(verification_text) < 30:
            continue

        if not block_needs_citation(block.get("text", "")) and len(verification_text) < 90:
            continue

        items.append(
            {
                "item_index": len(items) + 1,
                "kind": block.get("kind", "paragraph"),
                "start_line": block.get("start_line", 0),
                "text": verification_text,
                "urls": urls,
            }
        )

        if max_items and len(items) >= max_items:
            break

    return items


def source_blocks_for_item(item: dict, lookup: dict[str, dict]) -> list[dict]:
    """Return verified source excerpts for one cited report item."""
    blocks = []

    for url in item.get("urls", []) or []:
        normalized = normalize_url(url)
        finding = lookup.get(normalized)

        if not finding:
            blocks.append(
                {
                    "url": normalized or url,
                    "title": "",
                    "evidence_text": "",
                    "missing": True,
                }
            )
            continue

        evidence_text = (
            finding.get("evidence_text")
            or finding.get("fetched_text")
            or finding.get("snippet", "")
        )
        blocks.append(
            {
                "url": normalized,
                "title": finding.get("title", ""),
                "evidence_text": evidence_text,
                "missing": False,
            }
        )

    return blocks


def format_verification_prompt_items(items: list[dict], verified_findings: list[dict]) -> str:
    """Format report items and cited source excerpts for the verifier prompt."""
    lookup = source_lookup(verified_findings)
    prompt_items = []

    for item in items:
        sources = []
        for source in source_blocks_for_item(item, lookup):
            if source["missing"]:
                sources.append(f"""
URL: {source["url"]}
Source text: MISSING FROM VERIFIED SOURCES
""")
            else:
                sources.append(f"""
URL: {source["url"]}
Title: {source["title"]}
Source text:
{source["evidence_text"][:1600]}
""")

        prompt_items.append(f"""
REPORT ITEM {item["item_index"]}
Report text:
{item["text"]}

Cited URLs:
{json.dumps(item.get("urls", []) or [])}

Cited source excerpts:
{"".join(sources) if sources else "No cited URLs provided."}
""")

    return "\n".join(prompt_items)


def fallback_verifications(items: list[dict], verified_findings: list[dict], reason: str) -> list[dict]:
    """
    Conservative fallback when the semantic verifier model is unavailable.

    Items with verified source text are marked partial, never fully supported,
    because URL mapping is weaker than semantic entailment.
    """
    lookup = source_lookup(verified_findings)
    verifications = []

    for item in items:
        matched_urls = [
            normalize_url(url)
            for url in item.get("urls", []) or []
            if normalize_url(url) in lookup
        ]
        missing_urls = [
            normalize_url(url) or url
            for url in item.get("urls", []) or []
            if normalize_url(url) not in lookup
        ]

        verdict = "partial" if matched_urls and not missing_urls else "unsupported"
        verifications.append(
            {
                "item_index": item.get("item_index"),
                "verdict": verdict,
                "supported_urls": matched_urls,
                "reason": reason if matched_urls else "No verified source text matched the report citation URLs.",
                "caveat": "Semantic verifier unavailable; report item retained from verified URL mapping only."
                if matched_urls
                else "Report item failed because at least one cited URL was not in verified sources.",
            }
        )

    return verifications


def order_verifications(items: list[dict], raw_verifications: list[dict]) -> list[dict]:
    """Align model output to report item order and fill missing verifier results."""
    if not isinstance(raw_verifications, list):
        raw_verifications = []

    by_index = {}
    for item in raw_verifications:
        if not isinstance(item, dict):
            continue
        index = item.get("item_index")
        if isinstance(index, int):
            by_index[index] = item

    if not by_index:
        ordered = []
        for index, item in enumerate(items):
            if index < len(raw_verifications) and isinstance(raw_verifications[index], dict):
                ordered.append(raw_verifications[index])
            else:
                ordered.append(
                    {
                        "item_index": item["item_index"],
                        "verdict": "unsupported",
                        "supported_urls": [],
                        "reason": "Verifier did not return a result for this report item.",
                        "caveat": "Report item failed because verifier result was missing.",
                    }
                )
        return ordered

    ordered = []
    for item in items:
        index = item["item_index"]
        ordered.append(
            by_index.get(
                index,
                {
                    "item_index": index,
                    "verdict": "unsupported",
                    "supported_urls": [],
                    "reason": "Verifier did not return a result for this report item.",
                    "caveat": "Report item failed because verifier result was missing.",
                },
            )
        )

    return ordered


def build_records(items: list[dict], verifications: list[dict], verified_findings: list[dict]) -> tuple[list[dict], dict]:
    """Combine extracted report items with verifier verdicts and summary metrics."""
    lookup = source_lookup(verified_findings)
    records = []

    for item, verification in zip(items, verifications):
        cited_urls = [normalize_url(url) for url in item.get("urls", []) or [] if normalize_url(url)]
        known_urls = [url for url in cited_urls if url in lookup]
        missing_urls = [url for url in cited_urls if url not in lookup]
        supported_urls = [
            normalize_url(url)
            for url in verification.get("supported_urls", []) or []
            if normalize_url(url)
        ]
        supported_urls = sorted(set(supported_urls) & set(cited_urls))
        verdict = (verification.get("verdict") or "unsupported").lower()

        if verdict in SUPPORTED_VERDICTS and not supported_urls:
            verdict = "unsupported"

        records.append(
            {
                "item_index": item.get("item_index"),
                "kind": item.get("kind"),
                "start_line": item.get("start_line"),
                "text": item.get("text", ""),
                "cited_urls": cited_urls,
                "known_source_urls": known_urls,
                "missing_source_urls": missing_urls,
                "verdict": verdict,
                "supported_urls": supported_urls,
                "reason": verification.get("reason", ""),
                "caveat": verification.get("caveat"),
            }
        )

    total = len(records)
    supported_count = sum(1 for record in records if record["verdict"] == "supported")
    partial_count = sum(1 for record in records if record["verdict"] == "partial")
    unsupported_count = sum(1 for record in records if record["verdict"] not in SUPPORTED_VERDICTS)
    missing_source_url_count = sum(len(record["missing_source_urls"]) for record in records)
    semantic_support_count = supported_count + partial_count
    support_rate = semantic_support_count / total if total else 1.0
    passes = total > 0 and unsupported_count == 0 and missing_source_url_count == 0

    if total == 0:
        reason = "No citation-bearing report items were available for semantic verification."
    elif missing_source_url_count:
        reason = "Report cites URLs that were not present in verified source findings."
    elif unsupported_count:
        reason = "Post-writer verifier found cited report text not supported by its cited sources."
    else:
        reason = "All checked final-report citations are semantically supported or partially supported by verified source text."

    summary = {
        "passes": passes,
        "skipped": total == 0,
        "reason": reason,
        "total_items": total,
        "supported_count": supported_count,
        "partial_count": partial_count,
        "unsupported_count": unsupported_count,
        "missing_source_url_count": missing_source_url_count,
        "support_rate": round(support_rate, 3),
    }

    return records, summary


@traceable(
    name="report_citation_verifier_agent",
    tags=["report", "citations", "verification", "grounding", "llm"],
    metadata={"agent": "report_verifier"},
)
def report_verifier_agent(state: ResearchAgentState) -> dict:
    """
    Post-writer verifier — checks whether final-report citations actually support
    the text they are attached to.
    """
    human_review = state.get("human_review", {}) or {}
    if human_review.get("required") and human_review.get("approved") is False:
        print("\n🔐 REPORT VERIFIER: Skipped because human review blocked writing")
        return {
            "report_verifications": [],
            "report_verification": {
                "passes": False,
                "skipped": True,
                "reason": "Skipped because human review blocked report writing.",
                "total_items": 0,
                "supported_count": 0,
                "partial_count": 0,
                "unsupported_count": 0,
                "missing_source_url_count": 0,
                "support_rate": 0.0,
            },
        }

    max_items = int(os.getenv("REPORT_VERIFIER_MAX_ITEMS", "12"))
    items = cited_report_items(state.get("report", ""), max_items=max_items)
    verified_findings = state.get("verified_findings", [])

    print(f"\n🔐 REPORT VERIFIER: Checking {len(items)} cited report items...")

    if not items:
        return {
            "report_verifications": [],
            "report_verification": {
                "passes": True,
                "skipped": True,
                "reason": "No citation-bearing report items found; grounding evaluator handles citation coverage.",
                "total_items": 0,
                "supported_count": 0,
                "partial_count": 0,
                "unsupported_count": 0,
                "missing_source_url_count": 0,
                "support_rate": 1.0,
            },
        }

    prompt_items = format_verification_prompt_items(items, verified_findings)

    try:
        response = get_report_verifier_llm().invoke(f"""
You are the post-writer citation verifier for FactCrafter.

Your job:
Decide whether each final-report text item is actually supported by the URLs it cites.

Rules:
- Use ONLY the provided cited source excerpts.
- Do NOT use outside knowledge.
- "supported" means the cited source text directly states or clearly entails the report text.
- "partial" means the cited source text supports the core idea but misses a detail, scope, number, or causal strength.
- "unsupported" means the cited source text does not support the report text, is missing, only weakly related, or contradicts it.
- If a report item cites multiple URLs, include only the URLs that actually support the item in supported_urls.
- Be conservative. If unsure, choose "partial" or "unsupported".

Report items to verify:
{prompt_items}

Return STRICT JSON only. No markdown, no backticks:
[
  {{
    "item_index": 1,
    "verdict": "supported",
    "supported_urls": ["https://..."],
    "reason": "short explanation tied to source text",
    "caveat": null
  }}
]
""")

        content = strip_json_fences(response)
        raw_verifications = json.loads(content)
    except Exception as error:
        print(f"   ⚠️ Report verifier failed ({error}) — using conservative fallback")
        raw_verifications = fallback_verifications(
            items,
            verified_findings,
            "Semantic report verifier failed; item retained only because citation URL matched verified evidence.",
        )

    ordered = order_verifications(items, raw_verifications)
    records, summary = build_records(items, ordered, verified_findings)

    print(f"   Semantic citation support rate: {summary['support_rate']}")
    print(f"   Unsupported report items: {summary['unsupported_count']}")
    print(f"   Missing cited source URLs: {summary['missing_source_url_count']}")
    print(f"   Verdict: {'PASS' if summary['passes'] else 'FAIL'}")
    print(f"   Reason: {summary['reason']}")

    for record in records:
        if record["verdict"] not in SUPPORTED_VERDICTS or record["missing_source_urls"]:
            preview = record["text"][:160]
            print(f"   - line {record['start_line']}: {preview}...")

    return {
        "report_verifications": records,
        "report_verification": summary,
    }
