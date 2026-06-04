# team/humanreview.py
# 🧑‍⚖️ HUMAN-IN-THE-LOOP REVIEW
# Responsibility: pause before writing high-stakes reports when an interactive
# reviewer is available, and always record the review decision in state/artifacts.
#
# Philosophy (first-principles): This is a RESEARCH tool. User intent for
# legitimate inquiry wins. Broad topic keywords ("health", "drug", "financial")
# in scientific_academic or technical_research briefs are NORMAL and expected.
# HITL only triggers for:
#   - research_type == "policy_legal"
#   - explicit requests for *personal actionable advice* ("should I take...", "treat my symptoms")
#   - explicit user mode=always/required
# mode=off is absolute and bypasses everything.

from __future__ import annotations

import os
import re
import sys

from langsmith import traceable

from team.runtime_context import current_web_job_id, is_web_context
from team.state import ResearchAgentState


HIGH_STAKES_RESEARCH_TYPES = {
    "policy_legal",
}

# Legacy patterns kept for non-research research_types only.
# For scientific_academic / technical_research we ignore these entirely
# unless the query shows clear intent to seek personalized advice.
HIGH_STAKES_PATTERNS = [
    r"\bmedical\b",
    r"\bhealth\b",
    r"\bdiagnos(?:e|is|tic)\b",
    r"\btreatment\b",
    r"\bmedicine\b",
    r"\bdrug\b",
    r"\blegal\b",
    r"\blaw\b",
    r"\blawsuit\b",
    r"\binsurance\b",
    r"\bcredit\b",
    r"\bmortgage\b",
    r"\bsafety\b",
    r"\beligibility\b",
]

# Personal advice intent patterns — these are the narrow cases where
# a research synthesis could be misused as "doctor/lawyer/financial advisor says".
PERSONAL_ADVICE_PATTERNS = [
    r"\bshould\s+i\b",
    r"\bwhat\s+should\s+i\b",
    r"\bcan\s+i\b.*\b(take|use|stop|start)\b",
    r"\bmy\s+(symptoms|condition|diagnosis|doctor)\b",
    r"\btreat\s+my\b",
    r"\bprescribe\s+(for\s+me|me)\b",
    r"\bis\s+it\s+safe\s+for\s+me\b",
    r"\bwill\s+(this|it)\s+(work|cure|fix)\s+(me|my)\b",
]


def hitl_mode() -> str:
    """Return human review mode: auto, always, off, or required."""
    return os.getenv("HITL_REVIEW_MODE", "auto").strip().lower()


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def is_web_mode() -> bool:
    return is_web_context()


def web_job_id() -> str:
    return current_web_job_id()


def contains_personal_advice_intent(text: str) -> bool:
    """True only if the query asks for personalized, actionable advice on health/legal/financial matters."""
    t = text.lower()
    return any(re.search(p, t) for p in PERSONAL_ADVICE_PATTERNS)


def is_high_stakes(goal: str, brief: dict | None = None) -> tuple[bool, list[str]]:
    """
    Detect whether a topic should cross a human-review boundary.

    First-principles rules for a research tool:
    - scientific_academic and technical_research: only trigger on explicit
      personal advice intent (e.g. "should I take this drug for my symptoms").
      Population/policy evidence questions containing "health outcomes" etc.
      are legitimate research and must NOT trigger.
    - policy_legal: always high-stakes (direct governance impact).
    - Other/unknown: apply legacy keyword list (kept for backward compatibility).
    """
    brief = brief or {}
    reasons = []
    research_type = brief.get("research_type")

    if research_type in HIGH_STAKES_RESEARCH_TYPES:
        reasons.append(f"research_type={research_type}")

    text = " ".join(
        str(part)
        for part in [
            goal,
            brief.get("topic", ""),
            " ".join(brief.get("must_cover", []) or []),
        ]
    ).lower()

    if research_type in {"scientific_academic", "technical_research"}:
        # Research synthesis on populations, policies, or technical topics.
        # Broad topic words are expected. Only block personal advice requests.
        if contains_personal_advice_intent(text):
            reasons.append("personal_advice_intent")
        return bool(reasons), reasons

    # Legacy path for other research types (or missing research_type during early brief)
    for pattern in HIGH_STAKES_PATTERNS:
        if re.search(pattern, text):
            reasons.append(f"keyword:{pattern.strip('\\\\b')}")

    return bool(reasons), reasons


def review_required_for_state(state: dict) -> tuple[bool, list[str]]:
    mode = hitl_mode()

    # HITL_REVIEW_MODE=off is absolute. User intent wins for legitimate research.
    # No keyword, research_type, or other heuristic may override this.
    if mode == "off":
        return False, ["mode=off"]

    if mode in {"always", "required"}:
        return True, [f"mode={mode}"]

    # Only in "auto" mode do we apply the narrow high-stakes heuristics.
    return is_high_stakes(state.get("goal", ""), state.get("brief", {}))


def summarize_claims_for_review(claims: list[dict]) -> str:
    lines = []
    for index, claim in enumerate(claims, start=1):
        urls = ", ".join((claim.get("support_urls") or [])[:2])
        caveat = claim.get("caveat")
        lines.append(f"{index}. {claim.get('claim', '')}")
        lines.append(f"   confidence: {claim.get('confidence', 'unknown')}")
        lines.append(f"   urls: {urls or 'none'}")
        if caveat:
            lines.append(f"   caveat: {caveat}")
    return "\n".join(lines)


def interactive_review(state: dict) -> tuple[bool, str]:
    """Ask a terminal user to approve claims before writing."""
    print("\n🧑‍⚖️ HUMAN REVIEW REQUIRED")
    print("Review the verified claims before the writer turns them into a report.")
    print("")
    print(summarize_claims_for_review(state.get("claims", [])))
    print("")
    response = input("Approve these claims for report writing? [y/N]: ").strip().lower()

    if response in {"y", "yes"}:
        return True, "approved by interactive reviewer"
    return False, "rejected by interactive reviewer"


def blocked_review_update(
    state: dict,
    mode: str,
    reasons: list[str],
    *,
    decision: str = "blocked: no interactive reviewer available",
    reviewer: str = "none",
    rejection_reason: str = "Human review was required and no interactive reviewer was available.",
    caveat: str = "Run in an interactive terminal or set HITL_REVIEW_MODE=off only for an intentional non-HITL workflow.",
) -> dict:
    """Return a state update that blocks writing until a human review is available."""
    return {
        "human_review": {
            "required": True,
            "approved": False,
            "mode": mode,
            "reasons": reasons,
            "decision": decision,
            "reviewer": reviewer,
        },
        "claims": [],
        "rejected_claims": state.get("rejected_claims", [])
        + [
            {
                "claim": claim.get("claim", ""),
                "support_urls": claim.get("support_urls", []),
                "verdict": "blocked_for_human_review",
                "reason": rejection_reason,
                "caveat": caveat,
            }
            for claim in state.get("claims", [])
        ],
    }


@traceable(
    name="human_review_agent",
    tags=["human-review", "hitl", "safety"],
    metadata={"agent": "human_review"},
)
def human_review_agent(state: ResearchAgentState) -> dict:
    """
    Human review gate.

    - mode=off: absolute bypass. Never blocks legitimate research.
    - Low-stakes / scientific research: pass without review.
    - High-stakes (policy_legal or personal advice intent): pause if interactive.
    - Noninteractive high-stakes: block writing and record why (unless mode=off).
    """
    required, reasons = review_required_for_state(state)
    mode = hitl_mode()

    if mode == "off":
        print("\n🧑‍⚖️ HUMAN REVIEW: OFF (HITL_REVIEW_MODE=off — absolute user override, all heuristics bypassed)")
        return {
            "human_review": {
                "required": False,
                "approved": True,
                "mode": "off",
                "reasons": reasons + ["user_override"],
                "decision": "not_required (user disabled review)",
                "reviewer": "system",
            }
        }

    if not required:
        print("\n🧑‍⚖️ HUMAN REVIEW: Not required")
        return {
            "human_review": {
                "required": False,
                "approved": True,
                "mode": mode,
                "reasons": reasons,
                "decision": "not_required",
                "reviewer": "system",
            }
        }

    print(f"\n🧑‍⚖️ HUMAN REVIEW: Required ({', '.join(reasons)})")

    if is_web_mode() and web_job_id():
        from team.web_review import register_review, wait_for_web_approval

        register_review(
            web_job_id(),
            goal=state.get("goal", ""),
            claims=state.get("claims", []) or [],
            reasons=reasons,
        )
        approved, decision = wait_for_web_approval(web_job_id())
        if not approved:
            return blocked_review_update(
                state,
                mode,
                reasons,
                decision=decision,
                reviewer="human_web",
                rejection_reason="Web reviewer rejected the claims before writing.",
                caveat="Revise the evidence or claims, then rerun review.",
            )
        return {
            "human_review": {
                "required": True,
                "approved": True,
                "mode": mode,
                "reasons": reasons,
                "decision": decision,
                "reviewer": "human_web",
            }
        }

    if is_interactive():
        approved, decision = interactive_review(state)
        if not approved:
            return blocked_review_update(
                state,
                mode,
                reasons,
                decision=decision,
                reviewer="human_cli",
                rejection_reason="Interactive human reviewer rejected the claims before writing.",
                caveat="Revise the evidence or claims, then rerun review.",
            )
        return {
            "human_review": {
                "required": True,
                "approved": approved,
                "mode": mode,
                "reasons": reasons,
                "decision": decision,
                "reviewer": "human_cli",
            }
        }

    print("   ❌ Review required, but no interactive reviewer is available.")
    return blocked_review_update(state, mode, reasons)
