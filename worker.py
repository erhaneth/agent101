from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import uuid

from web.jobs import JobManager


def install_shutdown_handlers(stop_event: threading.Event) -> None:
    def request_stop(signum: int, _frame: object) -> None:
        print(f"Worker received signal {signum}; stopping after current job.", flush=True)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


def run_worker_loop(
    manager: JobManager,
    *,
    once: bool,
    poll_seconds: float,
    stale_after_seconds: int,
    max_attempts: int,
    worker_id: str,
    stop_event: threading.Event | None = None,
) -> int:
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        manager.recover_stale_jobs(
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
        )
        ran_job = manager.run_next_queued_job(
            worker_id=worker_id,
            max_attempts=max_attempts,
        )
        if once:
            return 0
        if not ran_job:
            stop_event.wait(max(poll_seconds, 0.1))
    return 0


def run_worker_healthcheck(manager: JobManager) -> int:
    try:
        payload = manager.healthcheck()
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "status": "error",
                    "job_store": "error",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run queued FactCrafter research jobs.")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Verify worker job-store connectivity and exit without claiming work.",
    )
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="Seconds to wait between queue polls when no job is available.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=int(os.getenv("JOB_STALE_AFTER_SECONDS", "900")),
        help="Recover running jobs whose heartbeat is older than this many seconds.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("JOB_MAX_ATTEMPTS", "3")),
        help="Fail a job after this many worker attempts.",
    )
    parser.add_argument(
        "--worker-id",
        default=os.getenv("FACTCRAFTER_WORKER_ID") or f"worker-{uuid.uuid4()}",
        help="Stable worker id used for job leases and heartbeats.",
    )
    args = parser.parse_args()

    manager = JobManager(execution_mode="external")
    if args.healthcheck:
        return run_worker_healthcheck(manager)

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event)

    return run_worker_loop(
        manager,
        once=args.once,
        poll_seconds=args.poll_seconds,
        stale_after_seconds=args.stale_after_seconds,
        max_attempts=args.max_attempts,
        worker_id=args.worker_id,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    raise SystemExit(main())
