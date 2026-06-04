from __future__ import annotations

import os
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic

from fastapi import HTTPException


TERMINAL_JOB_STATUSES = {"completed", "failed", "blocked", "canceled"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class LimitSettings:
    max_active_jobs_per_user: int = _env_int("MAX_ACTIVE_JOBS_PER_USER", 3)
    max_job_creates_per_window: int = _env_int("MAX_JOB_CREATES_PER_WINDOW", 10)
    job_create_window_seconds: int = _env_int("JOB_CREATE_WINDOW_SECONDS", 3600)


class JobCreateRateLimiter:
    def __init__(self, settings: LimitSettings | None = None) -> None:
        self.settings = settings or LimitSettings()
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check_and_record(self, key: str, *, now: float | None = None) -> None:
        if self.settings.max_job_creates_per_window <= 0:
            return
        current = monotonic() if now is None else now
        window_start = current - self.settings.job_create_window_seconds

        with self._lock:
            events = self._events[key]
            while events and events[0] <= window_start:
                events.popleft()
            if len(events) >= self.settings.max_job_creates_per_window:
                raise HTTPException(
                    status_code=429,
                    detail="Too many research jobs created recently. Please wait before starting another.",
                )
            events.append(current)


def active_job_count(jobs: list[dict]) -> int:
    return sum(1 for job in jobs if job.get("status") not in TERMINAL_JOB_STATUSES)


def enforce_active_job_limit(jobs: list[dict], settings: LimitSettings | None = None) -> None:
    resolved = settings or LimitSettings()
    if resolved.max_active_jobs_per_user <= 0:
        return
    if active_job_count(jobs) >= resolved.max_active_jobs_per_user:
        raise HTTPException(
            status_code=429,
            detail="You already have the maximum number of active research jobs.",
        )


job_create_rate_limiter = JobCreateRateLimiter()
