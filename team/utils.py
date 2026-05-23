# team/utils.py
# THE SAFETY NET (The Budget Checker)
# Shared utility fucntions used by all agents, like checking token usage and providing fallback logic if the LLM is unavailable.
# Kept seperate so any agent can import and use these functions without creating circular dependencies.

import json
from typing import Any, List


def is_quota_or_model_error(err: Exception) -> bool:
    """Detects if the error is a Gemini quota or model issue."""
    msg = str(err).lower()
    return (
        "resource_exhausted" in msg
        or "quota" in msg
        or "429" in msg
        or "not_found" in msg
        or ("model" in msg and "not found" in msg)
    )


def content_to_text(content: Any) -> str:
    """Normalize LangChain message content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(content_to_text(text))
                else:
                    parts.append(json.dumps(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        if text is not None:
            return content_to_text(text)
        return json.dumps(content)
    return str(content)


def response_to_text(response: Any) -> str:
    """Return text from a LangChain response or a raw response value."""
    return content_to_text(getattr(response, "content", response))


def strip_json_fences(text: Any) -> str:
    """Remove common markdown JSON fences after normalizing to text."""
    content = response_to_text(text).strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
    return content.strip()


def fallback_plan_queries(goal: str) -> list:
    """Universal fallback queries — works for any topic."""
    return [
        {"query": f"{goal} overview", "purpose": "overview", "priority": 1},
        {"query": f"{goal} official data OR official source", "purpose": "primary source", "priority": 1},
        {"query": f"{goal} latest news 2026", "purpose": "recent data", "priority": 2},
        {"query": f"{goal} statistics report analysis", "purpose": "statistics", "priority": 2},
        {"query": f"{goal} expert analysis", "purpose": "expert analysis", "priority": 2},
        {"query": f"{goal} criticism risks limitations", "purpose": "criticism", "priority": 3},
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
            preview = content_to_text(item).replace("\n", " ")
            lines.append(f"- {preview[:240]}")
    lines.extend([
        "",
        "Next step: re-run when Gemini quota resets.",
    ])
    return "\n".join(lines)
    """Emergency fallback for the Writer if LLM is down - generates a basic report from findings."""
    lines = [
        f"Goal: {goal}",
        "",
        "Gemini API call could not be completed (quota/model issue), so this report was generated from collected search snippets.",
        "",
        "Key findings:",
    ]
    if not findings:
        lines.append("- No findings were collected.")
    else:
        for item in findings[:5]:  # limit to first 5 findings for brevity
            preview = item.replace("\n", " ")
            lines.append(f"- {preview[:240]}")  # show first 240 chars of each finding
    lines.extend([
        "",
        "Next step:",
        "- Enable Gemini quota/billing (or wait for reset) and rerun to get an LLM-written synthesized report.",
    ])
    return "\n".join(lines)
