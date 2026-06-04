from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any


alert_logger = logging.getLogger("factcrafter.alerts")


def alert_webhook_url() -> str:
    return os.getenv("ALERT_WEBHOOK_URL", "").strip()


def alerts_enabled() -> bool:
    return bool(alert_webhook_url())


def send_job_alert(
    *,
    job_id: str,
    user_id: str,
    status: str,
    goal: str,
    reason: str | None = None,
    run_id: str | None = None,
    attempt_count: int = 0,
    current_step: str | None = None,
) -> bool:
    url = alert_webhook_url()
    if not url:
        return False

    payload = {
        "event": "factcrafter_job_alert",
        "job_id": job_id,
        "user_id": user_id,
        "status": status,
        "goal": goal,
        "reason": reason or "",
        "run_id": run_id,
        "attempt_count": attempt_count,
        "current_step": current_step,
    }
    try:
        _post_json(url, payload)
    except Exception as exc:  # noqa: BLE001
        alert_logger.warning(
            json.dumps(
                {
                    "event": "job_alert_delivery_failed",
                    "job_id": job_id,
                    "status": status,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return False

    alert_logger.info(
        json.dumps(
            {
                "event": "job_alert_sent",
                "job_id": job_id,
                "status": status,
            },
            sort_keys=True,
        )
    )
    return True


def _post_json(url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        if response.status >= 400:
            raise RuntimeError(f"alert webhook returned HTTP {response.status}")
