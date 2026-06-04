# team/web_review.py
# Web UI human-in-the-loop approval bridge.

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ReviewRequest:
    job_id: str
    goal: str
    claims: list
    reasons: list
    event: threading.Event = field(default_factory=threading.Event)
    approved: Optional[bool] = None
    decision: str = ""


_lock = threading.Lock()
_requests: Dict[str, ReviewRequest] = {}


def _job_store():
    from web.job_store import JobStore

    return JobStore()


def _review_payload(request: ReviewRequest) -> dict:
    return {
        "job_id": request.job_id,
        "goal": request.goal,
        "reasons": request.reasons,
        "claims": request.claims,
    }


def _load_persisted_state(job_id: str) -> tuple[dict, dict] | tuple[None, None]:
    record = _job_store().get(job_id)
    if record is None:
        return None, None
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    return record, dict(state)


def _persist_pending_review(request: ReviewRequest) -> None:
    store = _job_store()
    record = store.get(request.job_id)
    if record is None:
        return
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    state = dict(state)
    state["_pending_review"] = _review_payload(request)
    state.pop("_web_review_decision", None)
    events = list(record.get("events") or [])
    events.append(
        {
            "type": "review_required",
            "message": "Waiting for human review in the web UI",
            "step": "human_review",
            "payload": state["_pending_review"],
        }
    )
    record["state"] = state
    record["status"] = "awaiting_review"
    record["current_step"] = "human_review"
    record["events"] = events
    store.upsert(record)


def _persist_review_decision(job_id: str, approved: bool, decision: str) -> bool:
    store = _job_store()
    record = store.get(job_id)
    if record is None:
        return False
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    state = dict(state)
    if not state.get("_pending_review"):
        return False
    state["_web_review_decision"] = {
        "approved": approved,
        "decision": decision,
    }
    record["state"] = state
    record["status"] = "running"
    store.upsert(record)
    return True


def _persisted_review_decision(job_id: str) -> tuple[bool, str] | None:
    _record, state = _load_persisted_state(job_id)
    if state is None:
        return None
    decision = state.get("_web_review_decision")
    if not isinstance(decision, dict):
        return None
    approved = bool(decision.get("approved"))
    text = str(decision.get("decision") or ("approved via web" if approved else "rejected via web"))
    return approved, text


def register_review(
    job_id: str,
    *,
    goal: str,
    claims: list,
    reasons: list,
) -> ReviewRequest:
    with _lock:
        request = ReviewRequest(job_id=job_id, goal=goal, claims=claims, reasons=reasons)
        _requests[job_id] = request
    _persist_pending_review(request)
    return request


def wait_for_web_approval(job_id: str, timeout: float | None = None) -> tuple[bool, str]:
    with _lock:
        request = _requests.get(job_id)
    if request is None:
        return False, "missing web review session"

    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        if request.event.wait(timeout=0.5):
            break
        persisted = _persisted_review_decision(job_id)
        if persisted is not None:
            return persisted
        if deadline is not None and time.monotonic() >= deadline:
            return False, "timed out waiting for web reviewer"

    approved = bool(request.approved)
    return approved, request.decision or ("approved via web" if approved else "rejected via web")


def submit_web_approval(job_id: str, approved: bool, *, decision: str = "") -> bool:
    with _lock:
        request = _requests.get(job_id)
        final_decision = decision or (
            "approved via web reviewer" if approved else "rejected via web reviewer"
        )
        if request is None:
            return _persist_review_decision(job_id, approved, final_decision)
        request.approved = approved
        request.decision = final_decision
        request.event.set()
    _persist_review_decision(job_id, approved, final_decision)
    return True


def get_pending_review(job_id: str) -> Optional[dict]:
    with _lock:
        request = _requests.get(job_id)
    if request is None or request.approved is not None:
        _record, state = _load_persisted_state(job_id)
        if state is None or state.get("_web_review_decision"):
            return None
        pending = state.get("_pending_review")
        return pending if isinstance(pending, dict) else None
    return _review_payload(request)


def clear_review(job_id: str) -> None:
    with _lock:
        _requests.pop(job_id, None)
    store = _job_store()
    record = store.get(job_id)
    if record is None:
        return
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    state = dict(state)
    state.pop("_pending_review", None)
    state.pop("_web_review_decision", None)
    record["state"] = state
    store.upsert(record)
