# team/claimverifier.py
# 🔎 THE CLAIM VERIFIER AGENT
# Responsibility: Check whether each claim is actually supported by its cited source text.
#
# This is stricter than checking whether a claim has a URL. The verifier uses the
# verified source excerpts as evidence and labels each claim as supported, partial,
# or unsupported before the writer sees it.

import json
import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable

from team.evaluator import normalize_url
from team.state import ResearchAgentState
from team.utils import strip_json_fences


SUPPORTED_VERDICTS = {"supported", "partial"}


def get_verifier_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("CLAIM_VERIFIER_MODEL", os.getenv("CLAIM_MODEL", "gemini-3.1-flash-lite")),
        max_retries=2,
        request_timeout=40,
        temperature=0.0,
    )


def source_lookup(verified_findings: list[dict]) -> dict[str, dict]:
    """Index verified findings by normalized URL."""
    lookup = {}

    for finding in verified_findings:
        normalized = normalize_url(finding.get("url", ""))
        if not normalized:
            continue
        lookup[normalized] = finding

    return lookup


def source_blocks_for_claim(claim: dict, lookup: dict[str, dict]) -> list[dict]:
    """Return source excerpts matching the claim's support URLs."""
    blocks = []

    for url in claim.get("support_urls", []) or []:
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

        blocks.append(
            {
                "url": normalized,
                "title": finding.get("title", ""),
                "evidence_text": finding.get("evidence_text") or finding.get("snippet", ""),
                "missing": False,
            }
        )

    return blocks


def format_verification_prompt_items(claims: list[dict], verified_findings: list[dict]) -> str:
    """Format claims and their cited source excerpts for the verifier prompt."""
    lookup = source_lookup(verified_findings)
    items = []

    for index, claim in enumerate(claims, start=1):
        source_blocks = source_blocks_for_claim(claim, lookup)
        sources_text = []

        for source in source_blocks:
            if source["missing"]:
                sources_text.append(f"""
URL: {source["url"]}
Source text: MISSING FROM VERIFIED SOURCES
""")
            else:
                sources_text.append(f"""
URL: {source["url"]}
Title: {source["title"]}
Source text:
{source["evidence_text"][:1400]}
""")

        items.append(f"""
CLAIM {index}
Claim text:
{claim.get("claim", "")}

Claim support URLs:
{json.dumps(claim.get("support_urls", []) or [])}

Source excerpts:
{"".join(sources_text) if sources_text else "No source URLs provided."}
""")

    return "\n".join(items)


def fallback_verifications(claims: list[dict], verified_findings: list[dict], reason: str) -> list[dict]:
    """
    Conservative non-LLM fallback.

    If the verifier model is unavailable, keep only claims whose support URLs still
    map to verified source text, and mark them partial so the writer sees the caveat.
    """
    lookup = source_lookup(verified_findings)
    verifications = []

    for claim in claims:
        matched_urls = [
            normalize_url(url)
            for url in claim.get("support_urls", []) or []
            if normalize_url(url) in lookup
        ]
        verdict = "partial" if matched_urls else "unsupported"
        verifications.append(
            {
                "claim": claim.get("claim", ""),
                "support_urls": matched_urls,
                "verdict": verdict,
                "reason": reason if matched_urls else "No verified source text matched the claim support URLs.",
                "caveat": "Semantic verifier unavailable; retained from verified source mapping only."
                if matched_urls
                else "Claim removed because no verified source text was available.",
            }
        )

    return verifications


def apply_verifications(claims: list[dict], verifications: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep supported/partial claims and reject unsupported claims."""
    verified_claims = []
    rejected_claims = []

    for claim, verification in zip(claims, verifications):
        verdict = (verification.get("verdict") or "unsupported").lower()
        supported_urls = verification.get("supported_urls") or verification.get("support_urls") or []
        normalized_supported_urls = [
            normalize_url(url)
            for url in supported_urls
            if normalize_url(url)
        ]

        record = {
            "claim": claim.get("claim", ""),
            "support_urls": normalized_supported_urls,
            "verdict": verdict,
            "reason": verification.get("reason", ""),
            "caveat": verification.get("caveat"),
        }

        if verdict in SUPPORTED_VERDICTS and normalized_supported_urls:
            updated_claim = dict(claim)
            updated_claim["support_urls"] = normalized_supported_urls
            updated_claim["verification_verdict"] = verdict
            updated_claim["verification_reason"] = record["reason"]

            if verdict == "partial":
                updated_claim["confidence"] = "low"
                caveats = [
                    item
                    for item in (claim.get("caveat"), verification.get("caveat") or verification.get("reason"))
                    if item
                ]
                updated_claim["caveat"] = " ".join(caveats)

            verified_claims.append(updated_claim)
        else:
            rejected_claims.append(record)

    return verified_claims, rejected_claims


@traceable(
    name="claim_verifier_agent",
    tags=["claims", "verification", "grounding", "llm"],
    metadata={"agent": "claim_verifier"},
)
def claim_verifier_agent(state: ResearchAgentState) -> dict:
    """
    Claim Verifier — checks whether claim text is supported by cited source excerpts.
    Writes filtered claims back to state['claims'] and rejected claims to audit state.
    """
    claims = state.get("claims", [])
    verified_findings = state.get("verified_findings", [])

    print(f"\n🔎 CLAIM VERIFIER: Checking support for {len(claims)} claims...")

    if not claims:
        return {"claims": [], "claim_verifications": [], "rejected_claims": []}

    prompt_items = format_verification_prompt_items(claims, verified_findings)

    try:
        response = get_verifier_llm().invoke(f"""
You are the semantic claim verifier for FactCrafter.

Your job:
Decide whether each claim is actually supported by its cited source excerpts.

Rules:
- Use ONLY the source excerpts provided for each claim.
- Do NOT use outside knowledge.
- "supported" means the source text directly states or clearly entails the whole claim.
- "partial" means the source text supports the core idea but misses a detail, scope, number, or causal strength.
- "unsupported" means the source text does not support the claim, only weakly relates to it, is missing, or contradicts it.
- Return supported_urls using only the URLs that actually support the claim.
- Be conservative. If unsure, choose "partial" or "unsupported".

Claims to verify:
{prompt_items}

Return STRICT JSON only. No markdown, no backticks:
[
  {{
    "claim_index": 1,
    "verdict": "supported",
    "supported_urls": ["https://..."],
    "reason": "short explanation tied to source text",
    "caveat": null
  }}
]
""")

        content = strip_json_fences(response)
        raw_verifications = json.loads(content)
    except Exception as e:
        print(f"   ⚠️ Claim verifier failed ({e}) — using conservative fallback")
        raw_verifications = fallback_verifications(
            claims,
            verified_findings,
            "Semantic verifier failed; claim retained only because source URL matched verified evidence.",
        )

    verifications_by_index = {}
    for item in raw_verifications:
        index = item.get("claim_index")
        if isinstance(index, int):
            verifications_by_index[index] = item

    ordered_verifications = []
    if verifications_by_index:
        for index, claim in enumerate(claims, start=1):
            ordered_verifications.append(
                verifications_by_index.get(
                    index,
                    {
                        "claim": claim.get("claim", ""),
                        "support_urls": [],
                        "verdict": "unsupported",
                        "reason": "Verifier did not return a result for this claim.",
                        "caveat": "Claim removed because verifier result was missing.",
                    },
                )
            )
    else:
        ordered_verifications = raw_verifications

    verified_claims, rejected_claims = apply_verifications(claims, ordered_verifications)

    print(f"   ✅ Supported/partial claims kept: {len(verified_claims)}")
    print(f"   ❌ Unsupported claims rejected: {len(rejected_claims)}")

    for claim in verified_claims[:3]:
        verdict = claim.get("verification_verdict", "?")
        text = claim.get("claim", "")[:70]
        print(f"   [{verdict}] {text}...")

    return {
        "claims": verified_claims,
        "claim_verifications": ordered_verifications,
        "rejected_claims": rejected_claims,
    }
