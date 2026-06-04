# web/runs.py
# Load persisted FactCrafter run artifacts from disk.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from team.artifact_store import configured_artifact_store
from team.artifacts import DEFAULT_RUNS_DIR, user_runs_dir


ARTIFACT_FILES = {
    "summary": "summary.json",
    "brief": "brief.json",
    "plan": "plan.json",
    "findings": "findings.json",
    "verified_findings": "verified_findings.json",
    "rejected_findings": "rejected_findings.json",
    "claims": "claims.json",
    "claim_verifications": "claim_verifications.json",
    "rejected_claims": "rejected_claims.json",
    "human_review": "human_review.json",
    "evaluation": "evaluation.json",
    "report_verification": "report_verification.json",
    "report_verifications": "report_verifications.json",
    "evidence_map": "evidence_map.json",
    "guardrails": "guardrails.json",
}


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _runs_base(user_id: str | None) -> Path:
    return user_runs_dir(user_id)


def list_runs(user_id: str | None, *, limit: int = 50) -> list[dict]:
    store = configured_artifact_store()
    if store is not None:
        entries = []
        for summary in store.list_run_summaries(user_id=user_id, limit=limit):
            run_id = summary.get("run_id", "")
            entries.append(
                {
                    "run_id": run_id,
                    "goal": summary.get("goal", ""),
                    "created_at": run_id.split("-", 1)[0] if "-" in run_id else run_id,
                    "brief_type": summary.get("brief_type"),
                    "grounding_gate_passed": summary.get("grounding_gate_passed"),
                    "grounding_score": summary.get("grounding_score"),
                    "verified_finding_count": summary.get("verified_finding_count"),
                    "claim_count": summary.get("claim_count"),
                }
            )
        return entries

    runs_dir = _runs_base(user_id)
    if not runs_dir.exists():
        return []

    entries = []
    for child in runs_dir.iterdir():
        if not child.is_dir():
            continue
        summary_path = child / "summary.json"
        if not summary_path.exists():
            continue
        summary = _read_json(summary_path) or {}
        if user_id and summary.get("user_id") and summary.get("user_id") != user_id:
            continue
        entries.append(
            {
                "run_id": child.name,
                "goal": summary.get("goal", ""),
                "created_at": child.name.split("-", 1)[0] if "-" in child.name else child.name,
                "brief_type": summary.get("brief_type"),
                "grounding_gate_passed": summary.get("grounding_gate_passed"),
                "grounding_score": summary.get("grounding_score"),
                "verified_finding_count": summary.get("verified_finding_count"),
                "claim_count": summary.get("claim_count"),
            }
        )

    entries.sort(key=lambda item: item["run_id"], reverse=True)
    return entries[:limit]


def get_run(run_id: str, user_id: str | None) -> Optional[dict]:
    store = configured_artifact_store()
    if store is not None:
        summary = store.get_json(user_id=user_id, run_id=run_id, filename="summary.json") or {}
        if not summary:
            return None
        if user_id and summary.get("user_id") and summary.get("user_id") != user_id:
            return None

        payload: dict[str, Any] = {
            "run_id": run_id,
            "artifact_dir": summary.get("artifact_dir", f"artifact-store://{user_id or 'anonymous'}/{run_id}"),
            "report_md": store.get_text(user_id=user_id, run_id=run_id, filename="report.md"),
            "summary_md": store.get_text(user_id=user_id, run_id=run_id, filename="summary.md"),
        }

        for key, filename in ARTIFACT_FILES.items():
            payload[key] = store.get_json(user_id=user_id, run_id=run_id, filename=filename)

        return payload

    runs_dir = _runs_base(user_id)
    run_dir = runs_dir / run_id
    if not run_dir.exists():
        return None

    summary = _read_json(run_dir / "summary.json") or {}
    if user_id and summary.get("user_id") and summary.get("user_id") != user_id:
        return None

    payload: dict[str, Any] = {
        "run_id": run_id,
        "artifact_dir": str(run_dir),
        "report_md": _read_text(run_dir / "report.md"),
        "summary_md": _read_text(run_dir / "summary.md"),
    }

    for key, filename in ARTIFACT_FILES.items():
        payload[key] = _read_json(run_dir / filename)

    return payload


def default_runs_dir() -> str:
    return str(DEFAULT_RUNS_DIR)
