#!/usr/bin/env python3
"""Run FactCrafter behavior evals and save per-run artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from team.evaluator import extract_urls
from team.main import run_research_state
from team.utils import content_to_text


DEFAULT_CASES_PATH = ROOT / "evals" / "questions.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "evals" / "runs"


def load_cases(path: Path) -> list[dict]:
    """Load JSONL eval cases."""
    cases = []

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                cases.append(json.loads(stripped))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {error}") from error

    return cases


def select_cases(cases: list[dict], case_id: str | None, tag: str | None, limit: int | None) -> list[dict]:
    """Filter eval cases from CLI args."""
    selected = cases

    if case_id:
        selected = [case for case in selected if case.get("id") == case_id]

    if tag:
        selected = [case for case in selected if tag in case.get("tags", [])]

    if limit is not None:
        selected = selected[:limit]

    return selected


def hostname(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def domain_is_disallowed(url: str, disallowed_domains: list[str]) -> bool:
    host = hostname(url)
    return any(host == domain or host.endswith(f".{domain}") for domain in disallowed_domains)


def add_check(checks: list[dict], name: str, passed: bool, detail: str, *, required: bool = True) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "required": required,
            "detail": detail,
        }
    )


def score_case(case: dict, state: dict) -> dict:
    """Score one completed agent state against case expectations."""
    expected = case.get("expected", {})
    evaluation = state.get("evaluation", {}) or {}
    report = content_to_text(state.get("report", ""))
    report_urls = extract_urls(report)
    checks = []

    add_check(
        checks,
        "input_guardrail_passed",
        state.get("input_guardrail_passed", False),
        state.get("input_guardrail_reason", ""),
    )

    if expected.get("require_passes_grounding", True):
        add_check(
            checks,
            "passes_grounding",
            evaluation.get("passes_grounding", False),
            evaluation.get("reason", ""),
        )

    min_grounding_score = expected.get("min_grounding_score")
    if min_grounding_score is not None:
        actual = float(evaluation.get("grounding_score", 0) or 0)
        add_check(
            checks,
            "min_grounding_score",
            actual >= min_grounding_score,
            f"actual={actual}, expected>={min_grounding_score}",
        )

    if expected.get("require_citation_integrity", True):
        add_check(
            checks,
            "citation_integrity",
            evaluation.get("citation_integrity_passes", False),
            f"mismatches={evaluation.get('citation_mismatch_count', 0)}",
        )

    if expected.get("require_claim_verification", True):
        verification_count = len(state.get("claim_verifications", []) or [])
        claim_count = len(state.get("claims", []) or [])
        add_check(
            checks,
            "claim_verification_ran",
            verification_count > 0 and claim_count > 0,
            f"verifications={verification_count}, retained_claims={claim_count}",
        )

    if expected.get("require_report_verification", False):
        report_verification = state.get("report_verification", {}) or {}
        add_check(
            checks,
            "report_verification_passed",
            report_verification.get("passes", False) and not report_verification.get("skipped", False),
            report_verification.get("reason", ""),
        )

    min_verified_findings = expected.get("min_verified_findings")
    if min_verified_findings is not None:
        actual = len(state.get("verified_findings", []) or [])
        add_check(
            checks,
            "min_verified_findings",
            actual >= min_verified_findings,
            f"actual={actual}, expected>={min_verified_findings}",
        )

    min_claims = expected.get("min_claims")
    if min_claims is not None:
        actual = len(state.get("claims", []) or [])
        add_check(
            checks,
            "min_claims",
            actual >= min_claims,
            f"actual={actual}, expected>={min_claims}",
        )

    required_sections = expected.get("required_report_sections", [])
    for section in required_sections:
        add_check(
            checks,
            f"section:{section}",
            section in report,
            "present" if section in report else "missing",
        )

    disallowed_domains = expected.get("disallowed_domains", [])
    if disallowed_domains:
        bad_urls = [url for url in report_urls if domain_is_disallowed(url, disallowed_domains)]
        add_check(
            checks,
            "no_disallowed_domains",
            not bad_urls,
            f"bad_urls={bad_urls[:5]}",
        )

    required_checks = [check for check in checks if check["required"]]
    passed_required = [check for check in required_checks if check["passed"]]
    pass_rate = len(passed_required) / len(required_checks) if required_checks else 1.0
    passed = len(passed_required) == len(required_checks)

    return {
        "id": case.get("id"),
        "goal": case.get("goal"),
        "passed": passed,
        "pass_rate": round(pass_rate, 3),
        "checks_passed": len(passed_required),
        "checks_total": len(required_checks),
        "grounding_score": evaluation.get("grounding_score", 0),
        "verified_findings": len(state.get("verified_findings", []) or []),
        "retained_claims": len(state.get("claims", []) or []),
        "rejected_claims": len(state.get("rejected_claims", []) or []),
        "report_verification_passes": (state.get("report_verification", {}) or {}).get("passes"),
        "report_verification_support_rate": (state.get("report_verification", {}) or {}).get("support_rate"),
        "report_verification_unsupported_count": (state.get("report_verification", {}) or {}).get("unsupported_count"),
        "report_repair_attempts": state.get("report_repair_attempts", 0),
        "source_fetch_ok": sum(
            1
            for finding in state.get("findings", []) or []
            if finding.get("fetch_status") == "ok"
        ),
        "source_fetch_weak": sum(
            1
            for finding in state.get("findings", []) or []
            if finding.get("fetch_status") == "weak"
        ),
        "source_fetch_failed": sum(
            1
            for finding in state.get("findings", []) or []
            if finding.get("fetch_status") == "failed"
        ),
        "search_cache_hits": sum(
            1
            for finding in state.get("findings", []) or []
            if finding.get("search_cache_status") == "hit"
        ),
        "source_cache_hits": sum(
            1
            for finding in state.get("findings", []) or []
            if finding.get("cache_status") == "hit"
        ),
        "average_source_quality": round(
            sum(
                finding.get("source_quality_score", 0)
                for finding in state.get("verified_findings", []) or []
            )
            / len(state.get("verified_findings", []) or [1]),
            2,
        ),
        "report_url_count": len(report_urls),
        "checks": checks,
    }


def json_safe(value):
    """Make run artifacts JSON serializable."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(data), indent=2, ensure_ascii=False), encoding="utf-8")


def write_case_artifacts(case_dir: Path, case: dict, state: dict, score: dict) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "case.json", case)
    write_json(case_dir / "state.json", state)
    write_json(case_dir / "evaluation.json", state.get("evaluation", {}))
    write_json(case_dir / "report_verification.json", state.get("report_verification", {}))
    write_json(case_dir / "report_verifications.json", state.get("report_verifications", []))
    write_json(case_dir / "report_repair_history.json", state.get("report_repair_history", []))
    write_json(case_dir / "score.json", score)
    (case_dir / "report.md").write_text(content_to_text(state.get("report", "")), encoding="utf-8")


def write_summary_markdown(path: Path, summary: dict) -> None:
    lines = [
        "# FactCrafter Eval Summary",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Cases: `{summary['passed_cases']}/{summary['total_cases']}` passed",
        f"- Average pass rate: `{summary['average_pass_rate']}`",
        "",
        "| Case | Passed | Pass Rate | Grounding | Fetched | Cache Hits | Avg Quality | Verified | Claims | Rejected Claims |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for result in summary["results"]:
        lines.append(
            "| {id} | {passed} | {pass_rate} | {grounding_score} | {source_fetch_ok} | {search_cache_hits}/{source_cache_hits} | {average_source_quality} | {verified_findings} | {retained_claims} | {rejected_claims} |".format(
                **result
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cases(cases: list[dict], output_root: Path, *, run_output_check: bool, fail_fast: bool) -> dict:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    results = []

    for index, case in enumerate(cases, start=1):
        case_id = case.get("id", f"case_{index}")
        print(f"\n🧪 EVAL {index}/{len(cases)}: {case_id}")

        try:
            state = run_research_state(case["goal"], run_output_check=run_output_check, save_artifacts=False)
            score = score_case(case, state)
        except Exception as error:
            state = {
                "goal": case.get("goal"),
                "report": "",
                "evaluation": {},
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
            score = {
                "id": case_id,
                "goal": case.get("goal"),
                "passed": False,
                "pass_rate": 0.0,
                "checks_passed": 0,
                "checks_total": 1,
                "grounding_score": 0,
                "verified_findings": 0,
                "retained_claims": 0,
                "rejected_claims": 0,
                "report_url_count": 0,
                "checks": [
                    {
                        "name": "run_completed",
                        "passed": False,
                        "required": True,
                        "detail": str(error),
                    }
                ],
            }

        write_case_artifacts(run_dir / case_id, case, state, score)
        results.append(score)

        print(
            "   {status} pass_rate={pass_rate} grounding={grounding} verified={verified} claims={claims}".format(
                status="✅ PASS" if score["passed"] else "❌ FAIL",
                pass_rate=score["pass_rate"],
                grounding=score["grounding_score"],
                verified=score["verified_findings"],
                claims=score["retained_claims"],
            )
        )

        if fail_fast and not score["passed"]:
            break

    passed_cases = sum(1 for result in results if result["passed"])
    average_pass_rate = (
        sum(result["pass_rate"] for result in results) / len(results)
        if results
        else 0.0
    )
    summary = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "total_cases": len(results),
        "passed_cases": passed_cases,
        "failed_cases": len(results) - passed_cases,
        "average_pass_rate": round(average_pass_rate, 3),
        "results": results,
    }

    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FactCrafter behavior evals.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="Path to JSONL eval cases.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for run artifacts.")
    parser.add_argument("--case-id", help="Run only one case id.")
    parser.add_argument("--tag", help="Run only cases with this tag.")
    parser.add_argument("--limit", type=int, help="Limit number of selected cases.")
    parser.add_argument("--dry-run", action="store_true", help="List selected cases without running the agent.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing case.")
    parser.add_argument("--skip-output-guardrail", action="store_true", help="Skip final output guardrail during evals.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = select_cases(load_cases(args.cases), args.case_id, args.tag, args.limit)

    if not cases:
        print("No eval cases selected.")
        return 1

    if args.dry_run:
        for case in cases:
            print(f"{case.get('id')}: {case.get('goal')}")
        return 0

    summary = run_cases(
        cases,
        args.output_dir,
        run_output_check=not args.skip_output_guardrail,
        fail_fast=args.fail_fast,
    )

    print("\n" + "=" * 50)
    print("📊 EVAL SUMMARY")
    print("=" * 50)
    print(f"Run artifacts: {summary['run_dir']}")
    print(f"Passed: {summary['passed_cases']}/{summary['total_cases']}")
    print(f"Average pass rate: {summary['average_pass_rate']}")
    return 0 if summary["failed_cases"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
