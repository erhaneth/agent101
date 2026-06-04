# web/jobs.py
# In-memory research job manager with LangGraph streaming updates.

from __future__ import annotations

import os
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

from team.artifacts import write_run_artifacts  # noqa: E402
from team.graph import research_team  # noqa: E402
from team.guardrails import input_guardrail, output_guardrail  # noqa: E402
from team.main import initial_state  # noqa: E402
from team.runtime_context import web_job_context  # noqa: E402
from team.utils import content_to_text  # noqa: E402
from team.web_review import clear_review, get_pending_review  # noqa: E402
from web.alerts import send_job_alert  # noqa: E402
from web.job_store import JobStore  # noqa: E402
from web.metrics import record_job_event  # noqa: E402
from web.observability import current_request_id  # noqa: E402


DEFAULT_MAX_JOB_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
DEFAULT_STALE_JOB_SECONDS = int(os.getenv("JOB_STALE_AFTER_SECONDS", "900"))
job_logger = logging.getLogger("factcrafter.jobs")


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELED = "canceled"


PIPELINE_STEPS = [
    "brief",
    "anchors",
    "plan",
    "search",
    "source_fetch",
    "fact_check",
    "claim_build",
    "claim_verify",
    "human_review",
    "budget_check",
    "build_evidence_map",
    "write",
    "report_verify",
    "report_repair",
    "evaluate",
]

STEP_LABELS = {
    "brief": "Research brief",
    "anchors": "Topic anchors",
    "plan": "Search plan",
    "search": "Web search",
    "source_fetch": "Source fetching",
    "fact_check": "Evidence scoring",
    "claim_build": "Claim extraction",
    "claim_verify": "Claim verification",
    "human_review": "Human review",
    "budget_check": "Token budget",
    "build_evidence_map": "Evidence map",
    "write": "Report writing",
    "report_verify": "Citation verification",
    "report_repair": "Report repair",
    "evaluate": "Grounding evaluation",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobEvent:
    type: str
    message: str
    step: Optional[str] = None
    payload: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            "step": self.step,
            "payload": self.payload,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobEvent":
        return cls(
            type=str(data.get("type", "")),
            message=str(data.get("message", "")),
            step=data.get("step"),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
            created_at=str(data.get("created_at") or _utc_now()),
        )


@dataclass
class ResearchJob:
    id: str
    goal: str
    user_id: str
    status: JobStatus = JobStatus.QUEUED
    current_step: Optional[str] = None
    completed_steps: List[str] = field(default_factory=list)
    events: List[JobEvent] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    run_id: Optional[str] = None
    artifact_dir: Optional[str] = None
    error: Optional[str] = None
    attempt_count: int = 0
    cancel_requested: bool = False
    locked_by: Optional[str] = None
    locked_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self, *, include_state: bool = False) -> dict:
        status = self.status
        if get_pending_review(self.id):
            status = JobStatus.AWAITING_REVIEW
        data = {
            "id": self.id,
            "goal": self.goal,
            "status": status.value,
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "run_id": self.run_id,
            "artifact_dir": self.artifact_dir,
            "error": self.error,
            "attempt_count": self.attempt_count,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pipeline": [
                {
                    "id": step,
                    "label": STEP_LABELS.get(step, step),
                    "status": _step_status(step, self),
                }
                for step in PIPELINE_STEPS
            ],
            "summary": _job_summary(self.state) if self.state else None,
            "pending_review": get_pending_review(self.id),
            "events": [event.to_dict() for event in self.events[-80:]],
        }
        if include_state:
            data["state"] = _trim_state(self.state)
        return data

    def to_record(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "user_id": self.user_id,
            "status": self.status.value,
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "events": [event.to_dict() for event in self.events],
            "state": _trim_state(self.state),
            "run_id": self.run_id,
            "artifact_dir": self.artifact_dir,
            "error": self.error,
            "attempt_count": self.attempt_count,
            "cancel_requested": self.cancel_requested,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict) -> "ResearchJob":
        raw_status = str(record.get("status") or JobStatus.FAILED.value)
        try:
            status = JobStatus(raw_status)
        except ValueError:
            status = JobStatus.FAILED

        return cls(
            id=str(record["id"]),
            goal=str(record.get("goal", "")),
            user_id=str(record.get("user_id", "")),
            status=status,
            current_step=record.get("current_step"),
            completed_steps=list(record.get("completed_steps") or []),
            events=[
                JobEvent.from_dict(event)
                for event in record.get("events", [])
                if isinstance(event, dict)
            ],
            state=record.get("state") if isinstance(record.get("state"), dict) else {},
            run_id=record.get("run_id"),
            artifact_dir=record.get("artifact_dir"),
            error=record.get("error"),
            attempt_count=int(record.get("attempt_count", 0) or 0),
            cancel_requested=bool(record.get("cancel_requested", False)),
            locked_by=record.get("locked_by"),
            locked_at=record.get("locked_at"),
            last_heartbeat_at=record.get("last_heartbeat_at"),
            created_at=str(record.get("created_at") or _utc_now()),
            updated_at=str(record.get("updated_at") or _utc_now()),
        )


def _step_status(step: str, job: ResearchJob) -> str:
    if step in job.completed_steps:
        return "done"
    if job.current_step == step:
        if job.status == JobStatus.AWAITING_REVIEW and step == "human_review":
            return "waiting"
        return "active"
    return "pending"


def _job_summary(state: dict) -> dict:
    evaluation = state.get("evaluation", {}) or {}
    brief = state.get("brief", {}) or {}
    human_review = state.get("human_review", {}) or {}
    report_verification = state.get("report_verification", {}) or {}
    return {
        "brief_type": brief.get("research_type"),
        "brief_target_depth": brief.get("target_depth"),
        "grounding_gate_passed": state.get("grounding_gate_passed"),
        "grounding_score": evaluation.get("grounding_score"),
        "finding_count": len(state.get("findings", []) or []),
        "verified_finding_count": len(state.get("verified_findings", []) or []),
        "claim_count": len(state.get("claims", []) or []),
        "human_review_required": human_review.get("required"),
        "human_review_approved": human_review.get("approved"),
        "report_verification_passes": report_verification.get("passes"),
    }


def _trim_state(state: dict) -> dict:
    trimmed = dict(state)
    for key in ("findings", "verified_findings", "rejected_findings"):
        items = trimmed.get(key) or []
        if isinstance(items, list) and len(items) > 40:
            trimmed[key] = items[:40]
    return trimmed


def _append_event(job: ResearchJob, event: JobEvent) -> None:
    job.events.append(event)
    job.updated_at = _utc_now()


def _log_job_event(job: ResearchJob, event: str, **fields: object) -> None:
    payload = {
        "event": event,
        "job_id": job.id,
        "user_id": job.user_id,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
    }
    if job.locked_by:
        payload["worker_id"] = job.locked_by
    request_id = current_request_id()
    if request_id:
        payload["request_id"] = request_id
    payload.update({key: value for key, value in fields.items() if value is not None})
    record_job_event(event=event, status=job.status.value)
    job_logger.info(json.dumps(payload, sort_keys=True, default=str))


def _alert_terminal_job(job: ResearchJob, *, reason: str | None = None) -> None:
    if job.status not in {JobStatus.FAILED, JobStatus.BLOCKED}:
        return
    send_job_alert(
        job_id=job.id,
        user_id=job.user_id,
        status=job.status.value,
        goal=job.goal,
        reason=reason or job.error,
        run_id=job.run_id,
        attempt_count=job.attempt_count,
        current_step=job.current_step,
    )


def _cancel_event(message: str = "Research job cancellation requested") -> JobEvent:
    return JobEvent(type="canceled", message=message)


def _step_payload(step: str, state: dict) -> dict:
    if step == "plan":
        return {"plan_count": len(state.get("plan", []) or [])}
    if step == "search":
        return {"finding_count": len(state.get("findings", []) or [])}
    if step == "fact_check":
        return {
            "verified_count": len(state.get("verified_findings", []) or []),
            "rejected_count": len(state.get("rejected_findings", []) or []),
        }
    if step == "claim_build":
        return {"claim_count": len(state.get("claims", []) or [])}
    if step == "claim_verify":
        return {
            "verified_claims": len(state.get("claim_verifications", []) or []),
            "rejected_claims": len(state.get("rejected_claims", []) or []),
        }
    if step == "write":
        return {"report_chars": len(content_to_text(state.get("report", "")))}
    if step == "evaluate":
        evaluation = state.get("evaluation", {}) or {}
        return {
            "grounding_score": evaluation.get("grounding_score"),
            "passes_grounding": evaluation.get("passes_grounding"),
        }
    return {}


class JobManager:
    def __init__(
        self,
        store: JobStore | None = None,
        *,
        execution_mode: str | None = None,
        load_existing: bool = True,
    ) -> None:
        self._jobs: Dict[str, ResearchJob] = {}
        self._lock = threading.Lock()
        self._store = store or JobStore()
        self.execution_mode = (execution_mode or os.getenv("JOB_EXECUTION_MODE", "thread")).strip().lower()
        if load_existing:
            self._load_jobs()

    def _load_jobs(self) -> None:
        loaded: Dict[str, ResearchJob] = {}
        changed_jobs: list[ResearchJob] = []
        for record in self._store.load_all():
            job = ResearchJob.from_record(record)
            if job.status in {
                JobStatus.RUNNING,
                JobStatus.AWAITING_REVIEW,
            }:
                job.status = JobStatus.FAILED
                job.error = job.error or "Job was interrupted before this server process started."
                _append_event(job, JobEvent(type="error", message=job.error))
                changed_jobs.append(job)
            loaded[job.id] = job

        for job in changed_jobs:
            self._store.upsert(job.to_record())

        with self._lock:
            self._jobs = loaded

    def _persist_job(self, job: ResearchJob) -> None:
        self._store.upsert(job.to_record())

    def _remember_job(self, job: ResearchJob) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def list_jobs(self, user_id: str) -> list[dict]:
        with self._lock:
            jobs = [
                job
                for job in self._jobs.values()
                if job.user_id == user_id
            ]
            jobs = sorted(jobs, key=lambda item: item.created_at, reverse=True)
        return [job.to_dict() for job in jobs]

    def get_job(self, job_id: str, user_id: str | None = None) -> Optional[ResearchJob]:
        record = self._store.get(job_id)
        if record is not None:
            refreshed = ResearchJob.from_record(record)
            self._remember_job(refreshed)

        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if user_id is not None and job.user_id != user_id:
            return None
        return job

    def create_job(self, goal: str, user_id: str) -> ResearchJob:
        job = ResearchJob(id=str(uuid.uuid4()), goal=goal.strip(), user_id=user_id)
        self._remember_job(job)
        self._persist_job(job)
        _log_job_event(job, "job_created", execution_mode=self.execution_mode)
        if self.execution_mode == "thread":
            self.start_job_thread(job.id)
        return job

    def start_job_thread(self, job_id: str) -> None:
        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()

    def claim_next_job(
        self,
        *,
        worker_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
    ) -> Optional[ResearchJob]:
        record = self._store.claim_next_queued(worker_id=worker_id, max_attempts=max_attempts)
        if record is None:
            return None
        job = ResearchJob.from_record(record)
        self._remember_job(job)
        _log_job_event(job, "job_claimed", worker_id=job.locked_by)
        return job

    def run_claimed_job(self, job: ResearchJob, *, worker_id: str | None = None) -> None:
        if worker_id:
            job.locked_by = worker_id
        self._remember_job(job)
        self._run_job(job.id)

    def run_next_queued_job(
        self,
        *,
        worker_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
    ) -> bool:
        job = self.claim_next_job(worker_id=worker_id, max_attempts=max_attempts)
        if job is None:
            return False
        self.run_claimed_job(job, worker_id=worker_id)
        return True

    def heartbeat(self, job_id: str, *, worker_id: str | None = None) -> None:
        self._store.heartbeat(job_id, worker_id=worker_id)

    def healthcheck(self) -> dict:
        self._store.list(limit=1)
        return {
            "status": "ok",
            "execution_mode": self.execution_mode,
            "job_store": "ok",
        }

    def recover_stale_jobs(
        self,
        *,
        stale_after_seconds: int = DEFAULT_STALE_JOB_SECONDS,
        max_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
    ) -> int:
        recovered = self._store.recover_stale_running_jobs(
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
        )
        if recovered:
            self._load_jobs()
            job_logger.info(
                json.dumps(
                    {
                        "event": "stale_jobs_recovered",
                        "recovered_count": recovered,
                        "stale_after_seconds": stale_after_seconds,
                        "max_attempts": max_attempts,
                    },
                    sort_keys=True,
                )
            )
        return recovered

    def cancel_job(self, job_id: str, user_id: str) -> Optional[ResearchJob]:
        job = self.get_job(job_id, user_id)
        if job is None:
            return None
        if job.status == JobStatus.QUEUED:
            event = _cancel_event("Research job canceled before execution")
            error = "Job canceled by user before execution."
            record = self._store.cancel_queued(
                job_id,
                user_id,
                event=event.to_dict(),
                error=error,
            )
            if record is None:
                self._load_jobs()
                return None

            canceled = ResearchJob.from_record(record)
            self._remember_job(canceled)
            _log_job_event(canceled, "job_canceled")
            return canceled

        if job.status not in {JobStatus.RUNNING, JobStatus.AWAITING_REVIEW}:
            return None

        record = self._store.request_cancel(
            job_id,
            user_id,
            event=_cancel_event().to_dict(),
        )
        if record is None:
            self._load_jobs()
            return None

        requested = ResearchJob.from_record(record)
        self._remember_job(requested)
        _log_job_event(requested, "job_cancel_requested")
        return requested

    def _refresh_cancel_requested(self, job: ResearchJob) -> bool:
        record = self._store.get(job.id)
        if record is None:
            return False
        refreshed = ResearchJob.from_record(record)
        job.cancel_requested = refreshed.cancel_requested
        job.events = refreshed.events
        job.updated_at = refreshed.updated_at
        return job.cancel_requested

    def _mark_job_canceled(self, job: ResearchJob, *, message: str) -> None:
        job.status = JobStatus.CANCELED
        job.cancel_requested = True
        job.error = message
        record = self._store.mark_canceled(
            job.id,
            event=_cancel_event(message).to_dict(),
            error=message,
        )
        if record:
            canceled = ResearchJob.from_record(record)
            self._remember_job(canceled)
            _log_job_event(canceled, "job_canceled")
        else:
            _append_event(job, _cancel_event(message))
            self._persist_job(job)
            _log_job_event(job, "job_canceled")

    def approve_review(self, job_id: str, approved: bool) -> bool:
        from team.web_review import submit_web_approval

        job = self.get_job(job_id)
        if job is None:
            return False
        # review is keyed by job_id only; caller must verify ownership
        ok = submit_web_approval(job_id, approved)
        if ok and job.status == JobStatus.AWAITING_REVIEW:
            job.status = JobStatus.RUNNING
            self._persist_job(job)
        return ok

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            return

        os.environ.setdefault("HITL_REVIEW_MODE", "auto")

        self._remember_job(job)
        job.status = JobStatus.RUNNING
        job.last_heartbeat_at = _utc_now()
        _append_event(job, JobEvent(type="status", message="Research pipeline started"))
        self._persist_job(job)
        _log_job_event(job, "job_started")

        try:
            with web_job_context(job_id):
                if self._refresh_cancel_requested(job):
                    self._mark_job_canceled(job, message="Research job canceled before guardrail check.")
                    return

                is_safe, reason = input_guardrail(job.goal)
                if not is_safe:
                    state = initial_state(job.goal)
                    state["input_guardrail_passed"] = False
                    state["input_guardrail_reason"] = reason
                    state["report"] = f"Request blocked by safety guardrail: {reason}"
                    job.state = state
                    job.status = JobStatus.BLOCKED
                    self._save_artifacts(job, state)
                    _append_event(job, JobEvent(type="blocked", message=reason))
                    self._persist_job(job)
                    _log_job_event(job, "job_blocked", reason=reason)
                    _alert_terminal_job(job, reason=reason)
                    return

                state = initial_state(job.goal)
                state["user_id"] = job.user_id

                for chunk in research_team.stream(
                    state,
                    config={
                        "tags": ["research", "web-ui"],
                        "metadata": {"job_id": job_id, "interface": "web"},
                    },
                    stream_mode="updates",
                ):
                    if self._refresh_cancel_requested(job):
                        self._mark_job_canceled(job, message="Research job canceled before processing next update.")
                        return

                    for step, update in chunk.items():
                        if not isinstance(update, dict):
                            continue
                        state = {**state, **update}
                        job.state = state
                        job.last_heartbeat_at = _utc_now()

                        if step == "human_review" and get_pending_review(job_id):
                            job.status = JobStatus.AWAITING_REVIEW
                            job.current_step = step
                            _append_event(
                                job,
                                JobEvent(
                                    type="review_required",
                                    step=step,
                                    message="Waiting for human review in the web UI",
                                    payload=get_pending_review(job_id) or {},
                                ),
                            )
                            self._persist_job(job)
                            _log_job_event(job, "job_awaiting_review", step=step)
                            continue

                        if step not in job.completed_steps:
                            job.completed_steps.append(step)
                        job.current_step = step
                        _append_event(
                            job,
                            JobEvent(
                                type="step",
                                step=step,
                                message=f"Completed {STEP_LABELS.get(step, step)}",
                                payload=_step_payload(step, state),
                            ),
                        )
                        self._persist_job(job)
                        _log_job_event(job, "job_step_completed", step=step)

                report = content_to_text(state.get("report", ""))
                state["report"] = report
                state["input_guardrail_passed"] = True
                state["input_guardrail_reason"] = reason
                evaluation = state.get("evaluation", {}) or {}
                state["grounding_gate_passed"] = bool(evaluation.get("passes_grounding", False))

                if state.get("grounding_gate_passed"):
                    out_safe, out_reason = output_guardrail(report, job.goal)
                    state["output_guardrail_passed"] = out_safe
                    state["output_guardrail_reason"] = out_reason
                else:
                    state["output_guardrail_passed"] = None
                    state["output_guardrail_reason"] = "skipped"

                job.state = state
                self._save_artifacts(job, state)
                self._set_terminal_status(job, state)
                _append_event(
                    job,
                    JobEvent(
                        type="completed",
                        message="Research run finished",
                        payload={
                            "status": job.status.value,
                            "run_id": job.run_id,
                            "grounding_gate_passed": state.get("grounding_gate_passed"),
                        },
                    ),
                )
                self._persist_job(job)
                _log_job_event(
                    job,
                    "job_finished",
                    run_id=job.run_id,
                    grounding_gate_passed=state.get("grounding_gate_passed"),
                )
                _alert_terminal_job(job, reason=job.error or state.get("output_guardrail_reason"))
        except Exception as exc:  # noqa: BLE001
            job.status = JobStatus.FAILED
            job.error = str(exc)
            _append_event(job, JobEvent(type="error", message=str(exc)))
            self._persist_job(job)
            _log_job_event(job, "job_failed", error=str(exc), error_type=type(exc).__name__)
            _alert_terminal_job(job, reason=str(exc))
        finally:
            clear_review(job_id)

    def _save_artifacts(self, job: ResearchJob, state: dict) -> None:
        state["user_id"] = job.user_id
        artifact_dir = write_run_artifacts(state, user_id=job.user_id)
        job.artifact_dir = str(artifact_dir)
        job.run_id = artifact_dir.name
        self._persist_job(job)

    def _set_terminal_status(self, job: ResearchJob, state: dict) -> None:
        human_review = state.get("human_review", {}) or {}
        if not state.get("input_guardrail_passed", True):
            job.status = JobStatus.BLOCKED
        elif human_review.get("required") and human_review.get("approved") is False:
            job.status = JobStatus.BLOCKED
        elif not state.get("grounding_gate_passed", False):
            job.status = JobStatus.BLOCKED
        else:
            job.status = JobStatus.COMPLETED


job_manager = JobManager()
