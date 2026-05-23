# team/evaluator.py
# 📏 THE EVALUATOR AGENT
# Responsibility: Measure whether the final report is truly grounded in citations.
#
# v3 upgrade:
# - URLs dumped in "## Sources" do NOT count as grounding.
# - Claim-support URLs must appear inline in the report body.
# - Factual paragraphs / markdown blocks must have local citations.
# - This catches reports where Key Findings are cited, but Direct Answer,
#   Conclusion, or role-analysis blocks make unsupported factual claims.
#
# Reads: report + claims
# Writes: evaluation

import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from langsmith import traceable

from team.state import ResearchAgentState
from team.utils import content_to_text


URL_RE = re.compile(r"https?://[^\s\]\)\}<\"']+", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", re.IGNORECASE)

SOURCES_HEADING_RE = re.compile(
    r"(?im)^\s{0,3}#{1,6}\s*(sources|references|bibliography|works cited)\s*$"
)

HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+.+$")
TOP_LEVEL_LIST_RE = re.compile(r"^\s{0,3}([-*+]|\d+\.)\s+")
CLAIM_REFERENCE_RE = re.compile(r"\[CLAIM\s+\d+\]", re.IGNORECASE)

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}

FACTUAL_SIGNALS = {
    "will",
    "expected",
    "projected",
    "projection",
    "forecast",
    "forecasted",
    "anticipated",
    "demand",
    "growing",
    "growth",
    "stable",
    "decline",
    "increasing",
    "decreasing",
    "include",
    "includes",
    "identified",
    "indicates",
    "suggests",
    "evidence",
    "research",
    "study",
    "report",
    "market",
    "job",
    "jobs",
    "roles",
    "career",
    "careers",
    "automation",
    "automate",
    "risk",
    "productivity",
    "ai",
    "agi",
    "2025",
    "2026",
    "2027",
    "%",
}

LOW_VALUE_BLOCK_PREFIXES = (
    "what someone reading this should do now:",
    "**what someone reading this should do now:**",
)


def normalize_url(url: str) -> str:
    """
    Normalize URLs so the same source is counted consistently.

    Handles:
    - trailing punctuation after markdown links
    - fragments like #section
    - common tracking params like utm_source
    - www. prefix
    - trailing slash
    """
    if not url or not isinstance(url, str):
        return ""

    url = url.strip().rstrip(".,;:!?)]}\"'")

    if not url.startswith(("http://", "https://")):
        return ""

    parsed = urlparse(url)

    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()

    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path.rstrip("/")

    clean_query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()

        if key_lower.startswith("utm_"):
            continue

        if key_lower in TRACKING_PARAMS:
            continue

        clean_query_pairs.append((key, value))

    query = urlencode(sorted(clean_query_pairs))

    return urlunparse((scheme, netloc, path, "", query, ""))


def extract_urls(text: str) -> list[str]:
    """Extract and normalize all URLs from text."""
    if not text:
        return []

    urls = set()

    for match in URL_RE.finditer(text):
        normalized = normalize_url(match.group(0))
        if normalized:
            urls.add(normalized)

    return sorted(urls)


def markdown_url_label_mismatches(text: str) -> list[dict]:
    """
    Find markdown links where the visible label is a URL but points elsewhere.

    Example:
    [https://source-a.example](https://source-b.example)
    This is dangerous because it looks cited to a reader and to URL counters,
    but the actual clickable citation goes to a different source.
    """
    mismatches = []

    for match in MARKDOWN_LINK_RE.finditer(text or ""):
        label = match.group(1).strip()
        href = match.group(2).strip()
        label_urls = extract_urls(label)

        if not label_urls:
            continue

        normalized_href = normalize_url(href)
        for label_url in label_urls:
            if label_url != normalized_href:
                mismatches.append(
                    {
                        "label_url": label_url,
                        "href_url": normalized_href,
                        "text_preview": match.group(0)[:220],
                    }
                )

    return mismatches


def split_report_body_and_sources(report: str) -> tuple[str, str]:
    """
    Split report into:
    - body: everything before the Sources/References section
    - sources: the Sources/References section and everything after it
    """
    report = content_to_text(report)

    if not report:
        return "", ""

    match = SOURCES_HEADING_RE.search(report)

    if not match:
        return report, ""

    return report[: match.start()], report[match.start() :]


def claim_support_urls(claim: dict) -> list[str]:
    """Return normalized support URLs for one claim."""
    urls = claim.get("support_urls", []) or []

    normalized_urls = []
    for url in urls:
        normalized = normalize_url(url)
        if normalized:
            normalized_urls.append(normalized)

    return sorted(set(normalized_urls))


def strip_urls(text: str) -> str:
    """Remove URLs for cleaner block classification."""
    return URL_RE.sub("", text or "")


def markdown_blocks(body_text: str) -> list[dict]:
    """
    Split markdown body into citation-checkable blocks.

    Rules:
    - Headings are ignored.
    - Normal paragraphs become blocks.
    - Top-level bullets become blocks, including their indented sub-bullets.
      This works well for your Evidence-Based Analysis role blocks.
    """
    blocks = []
    current_lines = []
    current_kind = None
    current_start_line = 1

    def flush():
        nonlocal current_lines, current_kind, current_start_line

        raw = "\n".join(current_lines).strip()
        if raw:
            blocks.append(
                {
                    "kind": current_kind or "paragraph",
                    "text": raw,
                    "start_line": current_start_line,
                    "urls": extract_urls(raw),
                }
            )

        current_lines = []
        current_kind = None

    lines = body_text.splitlines()

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()

        if not stripped:
            flush()
            continue

        if HEADING_RE.match(line):
            flush()
            continue

        is_top_level_list = bool(TOP_LEVEL_LIST_RE.match(line))

        if is_top_level_list:
            flush()
            current_kind = "list_item"
            current_start_line = line_no
            current_lines = [line]
            continue

        if current_lines:
            current_lines.append(line)
        else:
            current_kind = "paragraph"
            current_start_line = line_no
            current_lines = [line]

    flush()

    return blocks


def block_needs_citation(block_text: str) -> bool:
    """
    Heuristic: determine whether a block makes factual claims and should be cited.

    This intentionally catches:
    - Direct Answer paragraphs
    - Key Finding bullets
    - Evidence-Based Analysis role blocks
    - Uncertainty paragraphs
    - Conclusion paragraphs with factual synthesis

    It tries not to over-penalize pure advice-only lines.
    """
    if not block_text:
        return False

    text_without_urls = strip_urls(block_text).strip()
    lower = text_without_urls.lower()

    if not lower:
        return False

    # Very short labels usually do not need citations.
    if len(lower) < 70:
        return False

    # Pure action/advice lines can be uncited.
    if lower.startswith(LOW_VALUE_BLOCK_PREFIXES):
        return False

    # Blocks with dates, percentages, named roles, market claims, automation claims,
    # or predictive language should be cited.
    tokens = set(re.findall(r"[a-zA-Z0-9%]+", lower))
    signal_count = len(tokens & FACTUAL_SIGNALS)

    if signal_count >= 2:
        return True

    # Longer analytical paragraphs usually need local evidence.
    if len(lower) >= 180 and signal_count >= 1:
        return True

    return False


def evaluate_block_citation_proximity(body_text: str) -> dict:
    """
    Evaluate whether factual markdown blocks have local citations.

    A block passes if it contains at least one URL inside that same block.
    This is stricter than checking whether URLs appear somewhere in the body.
    """
    blocks = markdown_blocks(body_text)

    factual_blocks = []
    cited_blocks = []
    uncited_blocks = []

    for index, block in enumerate(blocks, start=1):
        needs_citation = block_needs_citation(block["text"])

        if not needs_citation:
            continue

        record = {
            "block_index": index,
            "kind": block["kind"],
            "start_line": block["start_line"],
            "text_preview": strip_urls(block["text"])[:280],
            "urls": block["urls"],
        }

        factual_blocks.append(record)

        if block["urls"]:
            cited_blocks.append(record)
        else:
            uncited_blocks.append(record)

    factual_block_count = len(factual_blocks)
    cited_block_count = len(cited_blocks)

    block_citation_rate = (
        cited_block_count / factual_block_count
        if factual_block_count
        else 1.0
    )

    return {
        "factual_block_count": factual_block_count,
        "cited_factual_block_count": cited_block_count,
        "uncited_factual_block_count": len(uncited_blocks),
        "block_citation_rate": round(block_citation_rate, 3),
        "factual_blocks": factual_blocks,
        "cited_factual_blocks": cited_blocks,
        "uncited_factual_blocks": uncited_blocks,
    }


def evaluate_grounding(report: str, claims: list[dict], threshold: float = 0.70) -> dict:
    """
    Evaluate whether the final report is grounded.

    Primary metrics:
    1. claim_inline_citation_rate
       Each supported claim must have at least one support URL somewhere in the body.

    2. block_citation_rate
       Each factual paragraph/list block must contain a local citation.

    Secondary metrics:
    - support_url_inline_citation_rate
    - support_url_anywhere_citation_rate

    Important:
    URLs in the Sources section are tracked, but they do NOT make a claim grounded.
    """
    report = content_to_text(report)
    body_text, sources_text = split_report_body_and_sources(report)

    body_urls = set(extract_urls(body_text))
    sources_section_urls = set(extract_urls(sources_text))
    report_urls = set(extract_urls(report))
    citation_mismatches = markdown_url_label_mismatches(report)

    claim_references = CLAIM_REFERENCE_RE.findall(body_text or "")

    total_claims = len(claims)
    claims_with_sources = 0

    all_support_urls = set()
    grounded_claims = []
    ungrounded_claims = []

    for index, claim in enumerate(claims, start=1):
        support_urls = claim_support_urls(claim)

        if not support_urls:
            continue

        claims_with_sources += 1
        all_support_urls.update(support_urls)

        inline_cited_urls = sorted(set(support_urls) & body_urls)
        anywhere_cited_urls = sorted(set(support_urls) & report_urls)
        sources_only_cited_urls = sorted((set(support_urls) & sources_section_urls) - body_urls)

        claim_record = {
            "claim_index": index,
            "claim": claim.get("claim", "")[:300],
            "support_urls": support_urls,
            "inline_cited_urls": inline_cited_urls,
            "anywhere_cited_urls": anywhere_cited_urls,
            "sources_only_cited_urls": sources_only_cited_urls,
            "confidence": claim.get("confidence", "unknown"),
        }

        if inline_cited_urls:
            grounded_claims.append(claim_record)
        else:
            ungrounded_claims.append(claim_record)

    inline_cited_support_urls = sorted(all_support_urls & body_urls)
    anywhere_cited_support_urls = sorted(all_support_urls & report_urls)
    sources_only_support_urls = sorted((all_support_urls & sources_section_urls) - body_urls)
    missing_support_urls = sorted(all_support_urls - report_urls)
    unsupported_report_urls = sorted(report_urls - all_support_urls)

    claim_inline_citation_rate = (
        len(grounded_claims) / claims_with_sources
        if claims_with_sources
        else 0.0
    )

    support_url_inline_citation_rate = (
        len(inline_cited_support_urls) / len(all_support_urls)
        if all_support_urls
        else 0.0
    )

    support_url_anywhere_citation_rate = (
        len(anywhere_cited_support_urls) / len(all_support_urls)
        if all_support_urls
        else 0.0
    )

    block_eval = evaluate_block_citation_proximity(body_text)
    block_citation_rate = block_eval["block_citation_rate"]

    # v3 score:
    # - 55% claim URL coverage in body
    # - 35% local citation coverage for factual blocks
    # - 10% support URL coverage in body
    #
    # This means a report cannot get 100 just by citing all URLs somewhere.
    grounding_score = round(
        (
            0.55 * claim_inline_citation_rate
            + 0.35 * block_citation_rate
            + 0.10 * support_url_inline_citation_rate
        )
        * 100,
        1,
    )

    # The gate is intentionally stricter than the score:
    # both claim coverage and local block citation must pass.
    passes_grounding = (
        claims_with_sources > 0
        and len(body_urls) > 0
        and not citation_mismatches
        and claim_inline_citation_rate >= threshold
        and block_citation_rate >= threshold
    )

    if not claims:
        reason = "No claims were available to evaluate."
    elif claims_with_sources == 0:
        reason = "Claims exist, but none contain support URLs."
    elif len(body_urls) == 0 and len(sources_section_urls) > 0:
        reason = "Report cites URLs only in the Sources section, not inline in the body."
    elif len(body_urls) == 0:
        reason = "Report contains no inline citations."
    elif citation_mismatches:
        reason = "Report contains markdown citations whose visible URL points to a different linked URL."
    elif claim_references and not passes_grounding:
        reason = "Report uses claim references like [CLAIM 1] without enough inline source URLs."
    elif claim_inline_citation_rate < threshold:
        reason = "Too many supported claims were not cited inline in the report body."
    elif block_citation_rate < threshold:
        reason = "Too many factual paragraphs or role blocks lack local citations."
    elif passes_grounding:
        reason = "Report cites enough claim-supporting URLs inline and factual blocks are locally cited."
    else:
        reason = "Report failed grounding evaluation."

    return {
        "metric": "grounding",
        "passes_grounding": passes_grounding,
        "grounding_score": grounding_score,
        "threshold": threshold,
        "reason": reason,

        "total_claims": total_claims,
        "claims_with_sources": claims_with_sources,
        "grounded_claim_count": len(grounded_claims),
        "ungrounded_claim_count": len(ungrounded_claims),

        # Primary claim metric.
        "claim_citation_rate": round(claim_inline_citation_rate, 3),
        "claim_inline_citation_rate": round(claim_inline_citation_rate, 3),

        # Primary local-proximity metric.
        "block_citation_rate": block_citation_rate,
        "factual_block_count": block_eval["factual_block_count"],
        "cited_factual_block_count": block_eval["cited_factual_block_count"],
        "uncited_factual_block_count": block_eval["uncited_factual_block_count"],

        # Secondary URL metrics.
        "support_url_citation_rate": round(support_url_inline_citation_rate, 3),
        "support_url_inline_citation_rate": round(support_url_inline_citation_rate, 3),
        "support_url_anywhere_citation_rate": round(support_url_anywhere_citation_rate, 3),

        "body_url_count": len(body_urls),
        "sources_section_url_count": len(sources_section_urls),
        "report_url_count": len(report_urls),
        "support_url_count": len(all_support_urls),
        "inline_cited_support_url_count": len(inline_cited_support_urls),
        "anywhere_cited_support_url_count": len(anywhere_cited_support_urls),
        "sources_only_support_url_count": len(sources_only_support_urls),

        "uses_claim_references": bool(claim_references),
        "claim_reference_count": len(claim_references),
        "citation_integrity_passes": not citation_mismatches,
        "citation_mismatch_count": len(citation_mismatches),
        "citation_mismatches": citation_mismatches,

        "body_urls": sorted(body_urls),
        "sources_section_urls": sorted(sources_section_urls),
        "report_urls": sorted(report_urls),

        "inline_cited_support_urls": inline_cited_support_urls,
        "anywhere_cited_support_urls": anywhere_cited_support_urls,
        "sources_only_support_urls": sources_only_support_urls,
        "missing_support_urls": missing_support_urls,
        "unsupported_report_urls": unsupported_report_urls,

        "grounded_claims": grounded_claims,
        "ungrounded_claims": ungrounded_claims,

        "uncited_factual_blocks": block_eval["uncited_factual_blocks"],
        "cited_factual_blocks": block_eval["cited_factual_blocks"],
    }


def apply_report_verification(evaluation: dict, report_verification: dict | None) -> dict:
    """
    Merge post-writer semantic citation verification into grounding results.

    The base evaluator checks citation presence/proximity. The report verifier
    checks whether cited source text actually supports the final report wording.
    """
    report_verification = report_verification or {}
    skipped = bool(report_verification.get("skipped", False))
    semantic_passes = True if skipped else bool(report_verification.get("passes", True))

    updated = dict(evaluation)
    updated.update(
        {
            "semantic_citation_passes": semantic_passes,
            "semantic_citation_skipped": skipped,
            "semantic_citation_support_rate": report_verification.get("support_rate"),
            "semantic_citation_checked_count": report_verification.get("total_items", 0),
            "semantic_citation_unsupported_count": report_verification.get("unsupported_count", 0),
            "semantic_citation_missing_source_url_count": report_verification.get("missing_source_url_count", 0),
            "semantic_citation_reason": report_verification.get("reason", ""),
        }
    )

    if not semantic_passes:
        updated["passes_grounding"] = False
        updated["grounding_score"] = min(float(updated.get("grounding_score", 0) or 0), 69.0)
        updated["reason"] = (
            "Post-writer citation verifier found final-report text that was not supported "
            f"by its cited sources: {report_verification.get('reason', 'semantic citation verification failed')}"
        )

    return updated


@traceable(
    name="grounding_evaluator",
    tags=["evaluation", "grounding", "citations"],
    metadata={"agent": "evaluator"},
)
def evaluator_agent(state: ResearchAgentState) -> dict:
    """
    Evaluator Agent — checks whether the final report cites the Claim Builder's URLs inline
    and whether factual report blocks have local citations.
    """
    print("\n📏 EVALUATOR: Checking citation grounding...")

    threshold = float(os.getenv("GROUNDING_THRESHOLD", "0.70"))

    evaluation = evaluate_grounding(
        report=state.get("report", ""),
        claims=state.get("claims", []),
        threshold=threshold,
    )
    evaluation = apply_report_verification(evaluation, state.get("report_verification", {}))

    print(f"   Grounding score: {evaluation['grounding_score']}/100")
    print(f"   Claim inline citation rate: {evaluation['claim_inline_citation_rate']}")
    print(f"   Block citation rate: {evaluation['block_citation_rate']}")
    print(f"   Factual blocks: {evaluation['factual_block_count']}")
    print(f"   Uncited factual blocks: {evaluation['uncited_factual_block_count']}")
    print(f"   Support URL inline citation rate: {evaluation['support_url_inline_citation_rate']}")
    print(f"   Support URL anywhere citation rate: {evaluation['support_url_anywhere_citation_rate']}")
    print(f"   Body URLs: {evaluation['body_url_count']}")
    print(f"   Sources-only support URLs: {evaluation['sources_only_support_url_count']}")
    print(f"   Citation integrity: {'PASS' if evaluation['citation_integrity_passes'] else 'FAIL'}")
    print(f"   Semantic citations: {'PASS' if evaluation['semantic_citation_passes'] else 'FAIL'}")
    print(f"   Semantic citation support rate: {evaluation['semantic_citation_support_rate']}")
    print(f"   Uses [CLAIM n] references: {evaluation['uses_claim_references']}")
    print(f"   Verdict: {'PASS' if evaluation['passes_grounding'] else 'FAIL'}")
    print(f"   Reason: {evaluation['reason']}")

    if evaluation["citation_mismatch_count"]:
        print("   Citation mismatch previews:")
        for mismatch in evaluation["citation_mismatches"][:3]:
            print(f"   - visible {mismatch['label_url']} -> linked {mismatch['href_url']}")

    if evaluation["uncited_factual_block_count"]:
        print("   Uncited factual block previews:")
        for block in evaluation["uncited_factual_blocks"][:3]:
            preview = block["text_preview"].replace("\n", " ")
            print(f"   - line {block['start_line']}: {preview[:180]}...")

    return {"evaluation": evaluation}
