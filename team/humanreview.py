# team/humanreview.py
# 🧑‍⚖️ HUMAN-IN-THE-LOOP REVIEW
# Responsibility: pause before writing high-stakes reports when an interactive
# reviewer is available, and always record the review decision in state/artifacts.

from __future__ import annotations

import os
import re
import sys

from langsmith import traceable

from team.state import ResearchAgentState


HIGH_STAKES_RESEARCH_TYPES = {
    "policy_legal",
}

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
    r"\btax\b",
    r"\binvest(?:ment|ing)?\b",
    r"\bfinancial\b",
    r"\binsurance\b",
    r"\bcredit\b",
    r"\bmortgage\b",
    r"\bsafety\b",
    r"\beligibility\b",
]


def hitl_mode() -> str:
    """Return human review mode: auto, always, off, or required."""
    return os.getenv("HITL_REVIEW_MODE", "auto").strip().lower()


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def is_high_stakes(goal: str, brief: dict | None = None) -> tuple[bool, list[str]]:
    """Detect whether a topic should cross a human-review boundary."""
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

    for pattern in HIGH_STAKES_PATTERNS:
        if re.search(pattern, text):
            reasons.append(f"keyword:{pattern.strip('\\\\b')}")

    return bool(reasons), reasons


def review_required_for_state(state: dict) -> tuple[bool, list[str]]:
    mode = hitl_mode()
    if mode == "off":
        return False, ["mode=off"]
    if mode in {"always", "required"}:
        return True, [f"mode={mode}"]
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

    - Low-stakes topics pass without review.
    - High-stakes topics pause in interactive CLI mode.
    - Noninteractive runs do not hang; they block writing and record why.
    """
    required, reasons = review_required_for_state(state)
    mode = hitl_mode()

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
