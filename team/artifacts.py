# team/artifacts.py
# 🗂️ RUN ARTIFACTS
# Responsibility: Persist each research run as an inspectable audit trail.
#
# This is separate from eval artifacts. Evals save benchmark-specific scoring
# outputs under evals/runs/. Normal research runs save their pipeline state under
# runs/ so you can inspect exactly what the agent did.

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from team.utils import content_to_text


ARTIFACT_VERSION = "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"


def json_safe(value: Any) -> Any:
    """Make arbitrary state values JSON serializable."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(data), indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(text: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_length].strip("-") or "research-run")


def make_run_id(goal: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{slugify(goal)}"


def run_artifact_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(os.getenv("RUN_ARTIFACT_DIR", DEFAULT_RUNS_DIR))


def should_save_artifacts(value: bool | None = None) -> bool:
    if value is not None:
        return value
    env_value = os.getenv("SAVE_RUN_ARTIFACTS", "true").strip().lower()
    return env_value not in {"0", "false", "no", "off"}


def summarize_state(state: dict, run_id: str, artifact_dir: Path) -> dict:
    evaluation = state.get("evaluation", {}) or {}
    findings = state.get("findings", []) or []
    verified = state.get("verified_findings", []) or []
    claims = state.get("claims", []) or []
    rejected_claims = state.get("rejected_claims", []) or []
    report_verification = state.get("report_verification", {}) or {}

    brief = state.get("brief", {}) or {}
    return {
        "artifact_version": ARTIFACT_VERSION,
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "goal": state.get("goal", ""),
        "brief_type": brief.get("research_type"),
        "brief_target_depth": brief.get("target_depth"),
        "brief_hype_sensitivity": brief.get("hype_sensitivity"),
        "input_guardrail_passed": state.get("input_guardrail_passed"),
        "output_guardrail_passed": state.get("output_guardrail_passed"),
        "grounding_gate_passed": state.get("grounding_gate_passed"),
        "grounding_score": evaluation.get("grounding_score"),
        "citation_integrity_passes": evaluation.get("citation_integrity_passes"),
        "finding_count": len(findings),
        "verified_finding_count": len(verified),
        "rejected_finding_count": len(state.get("rejected_findings", []) or []),
        "claim_count": len(claims),
        "claim_verification_count": len(state.get("claim_verifications", []) or []),
        "rejected_claim_count": len(rejected_claims),
        "human_review_required": (state.get("human_review", {}) or {}).get("required"),
        "human_review_approved": (state.get("human_review", {}) or {}).get("approved"),
        "human_review_decision": (state.get("human_review", {}) or {}).get("decision"),
        "report_verification_passes": report_verification.get("passes"),
        "report_verification_support_rate": report_verification.get("support_rate"),
        "report_verification_unsupported_count": report_verification.get("unsupported_count"),
        "report_verification_missing_source_url_count": report_verification.get("missing_source_url_count"),
        "report_repair_attempts": state.get("report_repair_attempts", 0),
        "source_fetch_ok_count": sum(1 for finding in findings if finding.get("fetch_status") == "ok"),
        "source_fetch_weak_count": sum(1 for finding in findings if finding.get("fetch_status") == "weak"),
        "source_fetch_failed_count": sum(1 for finding in findings if finding.get("fetch_status") == "failed"),
        "search_cache_hit_count": sum(1 for finding in findings if finding.get("search_cache_status") == "hit"),
        "source_cache_hit_count": sum(1 for finding in findings if finding.get("cache_status") == "hit"),
    }

    # Add key evidence map stats if available (for source intelligence)
    em = state.get("evidence_map") or {}
    if em:
        summary["evidence_map_total_verified"] = em.get("total_verified")
        summary["evidence_map_high_quality_count"] = em.get("high_quality_count")
        summary["evidence_map_academic_official_count"] = em.get("academic_or_official_count")
        summary["evidence_map_average_credibility"] = (em.get("credibility_stats") or {}).get("average_credibility")
        summary["evidence_map_key_gaps"] = em.get("key_gaps", [])


def write_summary_markdown(path: Path, summary: dict) -> None:
    lines = [
        "# FactCrafter Run Summary",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Goal: {summary['goal']}",
        f"- Research type: `{summary.get('brief_type')}`",
        f"- Grounding passed: `{summary.get('grounding_gate_passed')}`",
        f"- Grounding score: `{summary.get('grounding_score')}`",
        f"- Citation integrity: `{summary.get('citation_integrity_passes')}`",
        "",
        "## Counts",
        "",
        f"- Findings: `{summary['finding_count']}`",
        f"- Verified findings: `{summary['verified_finding_count']}`",
        f"- Rejected findings: `{summary['rejected_finding_count']}`",
        f"- Claims retained: `{summary['claim_count']}`",
        f"- Claim verifications: `{summary['claim_verification_count']}`",
        f"- Rejected claims: `{summary['rejected_claim_count']}`",
        f"- Human review required/approved: `{summary.get('human_review_required')}/{summary.get('human_review_approved')}`",
        f"- Human review decision: `{summary.get('human_review_decision')}`",
        f"- Report citation verification: `{summary.get('report_verification_passes')}`",
        f"- Report citation support rate: `{summary.get('report_verification_support_rate')}`",
        f"- Unsupported/missing final citations: `{summary.get('report_verification_unsupported_count')}/{summary.get('report_verification_missing_source_url_count')}`",
        f"- Report repair attempts: `{summary.get('report_repair_attempts')}`",
        f"- Sources fetched OK/weak/failed: `{summary['source_fetch_ok_count']}/{summary['source_fetch_weak_count']}/{summary['source_fetch_failed_count']}`",
        f"- Search/source cache hits: `{summary['search_cache_hit_count']}/{summary['source_cache_hit_count']}`",
    ]

    if summary.get("evidence_map_total_verified"):
        lines.append("")
        lines.append("## Evidence Quality")
        lines.append(f"- Verified findings: `{summary.get('evidence_map_total_verified')}`")
        lines.append(f"- High-quality sources (4-5): `{summary.get('evidence_map_high_quality_count', 0)}`")
        lines.append(f"- Academic/official primary sources: `{summary.get('evidence_map_academic_official_count', 0)}`")
        lines.append(f"- Average credibility: `{summary.get('evidence_map_average_credibility', 'N/A')}`")
        if summary.get("evidence_map_key_gaps"):
            lines.append("- Key gaps noted in evidence map")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_artifacts(
    state: dict,
    *,
    root: str | Path | None = None,
    run_id: str | None = None,
) -> Path:
    """Persist one complete research run and return its artifact directory."""
    run_id = run_id or make_run_id(state.get("goal", "research-run"))
    artifact_dir = run_artifact_root(root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report = content_to_text(state.get("report", ""))
    summary = summarize_state(state, run_id, artifact_dir)

    write_json(
        artifact_dir / "input.json",
        {
            "artifact_version": ARTIFACT_VERSION,
            "run_id": run_id,
            "goal": state.get("goal", ""),
        },
    )
    write_json(
        artifact_dir / "guardrails.json",
        {
            "input_guardrail_passed": state.get("input_guardrail_passed"),
            "input_guardrail_reason": state.get("input_guardrail_reason"),
            "output_guardrail_passed": state.get("output_guardrail_passed"),
            "output_guardrail_reason": state.get("output_guardrail_reason"),
        },
    )
    write_json(artifact_dir / "brief.json", state.get("brief", {}))
    write_json(artifact_dir / "plan.json", state.get("plan", []))
    write_json(artifact_dir / "findings.json", state.get("findings", []))
    write_json(artifact_dir / "verified_findings.json", state.get("verified_findings", []))
    write_json(artifact_dir / "rejected_findings.json", state.get("rejected_findings", []))
    write_json(artifact_dir / "claims.json", state.get("claims", []))
    write_json(artifact_dir / "claim_verifications.json", state.get("claim_verifications", []))
    write_json(artifact_dir / "rejected_claims.json", state.get("rejected_claims", []))

    # Save full evidence map for source intelligence
    if state.get("evidence_map"):
        write_json(artifact_dir / "evidence_map.json", state.get("evidence_map"))
    write_json(artifact_dir / "human_review.json", state.get("human_review", {}))
    write_json(artifact_dir / "report_verification.json", state.get("report_verification", {}))
    write_json(artifact_dir / "report_verifications.json", state.get("report_verifications", []))
    write_json(artifact_dir / "report_repair_history.json", state.get("report_repair_history", []))
    write_json(artifact_dir / "evaluation.json", state.get("evaluation", {}))
    write_json(artifact_dir / "summary.json", summary)
    write_json(artifact_dir / "state.json", state)
    write_summary_markdown(artifact_dir / "summary.md", summary)
    (artifact_dir / "report.md").write_text(report, encoding="utf-8")

    return artifact_dir
