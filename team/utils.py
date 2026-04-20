# team/utils.py
# Shared helpers — quota/error detection + emergency fallbacks.

from typing import List


def is_quota_or_model_error(err: Exception) -> bool:
    """Detects Gemini quota or model-availability issues."""
    msg = str(err).lower()
    return (
        "resource_exhausted" in msg
        or "quota" in msg
        or "429" in msg
        or "not_found" in msg
        or ("model" in msg and "not found" in msg)
    )


def fallback_plan_queries(goal: str) -> List[str]:
    """Emergency planner when Gemini is unavailable."""
    return [
        goal,
        f"recent research {goal}",
        f"industry applications {goal}",
    ]


def fallback_report(goal: str, findings: List[str]) -> str:
    """Emergency writer when Gemini is unavailable."""
    lines = [
        f"Goal: {goal}",
        "",
        "⚠️ Gemini unavailable — report generated from raw search snippets.",
        "",
        "Key findings:",
    ]
    if not findings:
        lines.append("- No findings collected.")
    else:
        for item in findings[:5]:
            preview = item.replace("\n", " ")
            lines.append(f"- {preview[:240]}")
    lines.extend(["", "Next step: re-run when Gemini quota resets."])
    return "\n".join(lines)
