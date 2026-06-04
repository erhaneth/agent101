from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class MetricsRegistry:
    api_requests_total: int = 0
    api_errors_total: int = 0
    api_latency_sum_ms: float = 0.0
    api_latency_max_ms: float = 0.0
    api_status_counts: Counter[str] = field(default_factory=Counter)
    job_events_total: Counter[str] = field(default_factory=Counter)
    job_terminal_total: Counter[str] = field(default_factory=Counter)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_api_request(self, *, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self.api_requests_total += 1
            self.api_latency_sum_ms += duration_ms
            self.api_latency_max_ms = max(self.api_latency_max_ms, duration_ms)
            status_bucket = f"{status_code // 100}xx" if status_code else "unknown"
            self.api_status_counts[status_bucket] += 1
            if status_code >= 500:
                self.api_errors_total += 1

    def record_job_event(self, *, event: str, status: str) -> None:
        with self._lock:
            self.job_events_total[event] += 1
            if event in {"job_finished", "job_failed", "job_blocked", "job_canceled"}:
                self.job_terminal_total[status] += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg = (
                self.api_latency_sum_ms / self.api_requests_total
                if self.api_requests_total
                else 0.0
            )
            return {
                "api": {
                    "requests_total": self.api_requests_total,
                    "errors_total": self.api_errors_total,
                    "latency_avg_ms": round(avg, 2),
                    "latency_max_ms": round(self.api_latency_max_ms, 2),
                    "status_counts": dict(self.api_status_counts),
                },
                "jobs": {
                    "events_total": dict(self.job_events_total),
                    "terminal_total": dict(self.job_terminal_total),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self.api_requests_total = 0
            self.api_errors_total = 0
            self.api_latency_sum_ms = 0.0
            self.api_latency_max_ms = 0.0
            self.api_status_counts.clear()
            self.job_events_total.clear()
            self.job_terminal_total.clear()


metrics_registry = MetricsRegistry()


def record_api_request(*, status_code: int, duration_ms: float) -> None:
    metrics_registry.record_api_request(status_code=status_code, duration_ms=duration_ms)


def record_job_event(*, event: str, status: str) -> None:
    metrics_registry.record_job_event(event=event, status=status)


def metrics_snapshot() -> dict:
    return metrics_registry.snapshot()


def reset_metrics() -> None:
    metrics_registry.reset()
