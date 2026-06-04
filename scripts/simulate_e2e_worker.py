from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from web.job_store import JobStore


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def event(event_type: str, message: str, *, step: str | None = None, payload: dict | None = None) -> dict:
    return {
        "type": event_type,
        "message": message,
        "step": step,
        "payload": payload or {},
        "created_at": now(),
    }


def upsert_step(store: JobStore, job_id: str, step: str, completed_steps: list[str]) -> None:
    record = store.get(job_id)
    if record is None:
        raise RuntimeError(f"job not found: {job_id}")

    events = list(record.get("events") or [])
    events.append(event("step", f"Completed {step}", step=step))
    state = dict(record.get("state") or {})
    state["goal"] = record.get("goal", "")
    state["user_id"] = record.get("user_id", "")

    record.update(
        {
            "status": "running",
            "current_step": step,
            "completed_steps": completed_steps,
            "events": events,
            "state": state,
            "last_heartbeat_at": now(),
            "updated_at": now(),
        }
    )
    store.upsert(record)


def complete_job(store: JobStore, job_id: str, completed_steps: list[str]) -> None:
    record = store.get(job_id)
    if record is None:
        raise RuntimeError(f"job not found: {job_id}")

    report = """# Synthetic E2E Report

This deterministic report proves the browser can follow active worker progress
and render a completed job without live model or search calls.
"""
    state = dict(record.get("state") or {})
    state.update(
        {
            "goal": record.get("goal", ""),
            "user_id": record.get("user_id", ""),
            "report": report,
            "grounding_gate_passed": True,
            "evaluation": {"passes_grounding": True, "grounding_score": 100},
            "input_guardrail_passed": True,
            "output_guardrail_passed": True,
        }
    )
    events = list(record.get("events") or [])
    events.append(
        event(
            "completed",
            "Research run finished",
            payload={"status": "completed", "grounding_gate_passed": True},
        )
    )
    record.update(
        {
            "status": "completed",
            "current_step": "evaluate",
            "completed_steps": completed_steps,
            "events": events,
            "state": state,
            "error": None,
            "last_heartbeat_at": now(),
            "updated_at": now(),
        }
    )
    store.upsert(record)


def simulate(job_id: str, *, delay_seconds: float) -> None:
    store = JobStore()
    record = store.get(job_id)
    if record is None:
        raise RuntimeError(f"job not found: {job_id}")

    started = dict(record)
    started.update(
        {
            "status": "running",
            "current_step": "brief",
            "completed_steps": [],
            "events": list(record.get("events") or [])
            + [event("status", "Research pipeline started")],
            "attempt_count": int(record.get("attempt_count", 0) or 0) + 1,
            "locked_by": "e2e-simulated-worker",
            "locked_at": now(),
            "last_heartbeat_at": now(),
            "updated_at": now(),
        }
    )
    store.upsert(started)

    completed: list[str] = []
    for step in ["brief", "plan", "search", "claim_build", "write", "evaluate"]:
        time.sleep(delay_seconds)
        completed.append(step)
        upsert_step(store, job_id, step, completed)

    time.sleep(delay_seconds)
    complete_job(store, job_id, completed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate deterministic E2E worker progress.")
    parser.add_argument("job_id")
    parser.add_argument("--delay-seconds", type=float, default=0.4)
    args = parser.parse_args()

    simulate(args.job_id, delay_seconds=args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
