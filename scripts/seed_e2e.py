from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from team.artifact_store import ArtifactStore
from web.job_store import JobStore


USER_ID = os.getenv("AUTH_DEV_USER_ID", "dev-local")
RUN_ID = "20260603T120000Z-production-readiness-fixture"
REVIEW_JOB_ID = "11111111-1111-4111-8111-111111111111"
GOAL = "Production readiness checklist for FactCrafter"


def put_json(store: ArtifactStore, filename: str, payload: object) -> None:
    store.put_text(
        user_id=USER_ID,
        run_id=RUN_ID,
        filename=filename,
        content=json.dumps(payload, indent=2),
        content_type="application/json",
    )


def put_text(store: ArtifactStore, filename: str, content: str, content_type: str) -> None:
    store.put_text(
        user_id=USER_ID,
        run_id=RUN_ID,
        filename=filename,
        content=content,
        content_type=content_type,
    )


def main() -> None:
    store = ArtifactStore()
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "artifact_version": "1",
        "run_id": RUN_ID,
        "artifact_dir": f"artifact-store://{USER_ID}/{RUN_ID}",
        "user_id": USER_ID,
        "goal": GOAL,
        "brief_type": "technical",
        "grounding_gate_passed": True,
        "grounding_score": 96,
        "verified_finding_count": 2,
        "claim_count": 2,
    }
    verified_findings = [
        {
            "title": "FastAPI deployment checklist",
            "url": "https://example.com/fastapi-deploy",
            "reason": "Covers readiness probes, worker split, and shared storage.",
        },
        {
            "title": "Browser E2E guidance",
            "url": "https://example.com/browser-e2e",
            "reason": "Explains why UI/API integration checks catch production regressions.",
        },
    ]
    claims = [
        {
            "claim": "Production readiness requires shared durable storage for jobs and artifacts.",
            "confidence": "high",
            "support_urls": ["https://example.com/fastapi-deploy"],
        },
        {
            "claim": "Browser E2E tests should cover the critical user journey, not just static rendering.",
            "confidence": "high",
            "support_urls": ["https://example.com/browser-e2e"],
        },
    ]
    report = """# Production Readiness Checklist

FactCrafter should run the web process separately from workers, share durable job
storage, and verify the browser workflow before each release.

## Key Findings

- Shared job storage keeps queued work visible across web and worker processes.
- Browser E2E coverage protects the user-facing report creation and library paths.
"""

    put_json(store, "summary.json", summary)
    put_json(store, "verified_findings.json", verified_findings)
    put_json(store, "claims.json", claims)
    put_json(store, "evaluation.json", {"grounding_score": 96, "passes_grounding": True})
    put_text(store, "report.md", report, "text/markdown")
    put_text(store, "summary.md", "# FactCrafter Run Summary\n", "text/markdown")

    pending_review = {
        "job_id": REVIEW_JOB_ID,
        "goal": "Human review approval E2E fixture",
        "reasons": ["mode=required"],
        "claims": [
            {
                "claim": "Human review approval should unblock the web workflow.",
                "confidence": "high",
                "support_urls": ["https://example.com/human-review"],
            }
        ],
    }
    JobStore().upsert(
        {
            "id": REVIEW_JOB_ID,
            "goal": pending_review["goal"],
            "user_id": USER_ID,
            "status": "awaiting_review",
            "current_step": "human_review",
            "completed_steps": ["brief", "anchors", "plan", "search", "claim_build"],
            "events": [
                {
                    "type": "review_required",
                    "message": "Waiting for human review in the web UI",
                    "step": "human_review",
                    "payload": pending_review,
                    "created_at": now,
                }
            ],
            "state": {"_pending_review": pending_review},
            "run_id": None,
            "artifact_dir": None,
            "error": None,
            "attempt_count": 1,
            "cancel_requested": False,
            "locked_by": "e2e-fixture-worker",
            "locked_at": now,
            "last_heartbeat_at": now,
            "created_at": now,
            "updated_at": now,
        }
    )


if __name__ == "__main__":
    main()
