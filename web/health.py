from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable

from team.artifact_store import configured_artifact_store
from web.auth import database as auth_db
from web.job_store import JobStore
from web.runs import default_runs_dir


Probe = Callable[[], dict]


def readiness_report() -> dict:
    checks = {
        "auth_store": _probe("auth_store", _auth_store_probe),
        "job_store": _probe("job_store", _job_store_probe),
        "artifact_storage": _probe("artifact_storage", _artifact_storage_probe),
    }
    ready = all(check["ok"] for check in checks.values())
    return {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "checks": checks,
    }


def _probe(name: str, callback: Probe) -> dict:
    try:
        return callback()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "name": name,
            "status": "error",
            "detail": str(exc),
        }


def _auth_store_probe() -> dict:
    auth_db.init_db()
    auth_db.get_user_by_id("__factcrafter_healthcheck__")
    return {"ok": True, "name": "auth_store", "status": "ok"}


def _job_store_probe() -> dict:
    JobStore().list(limit=1)
    return {"ok": True, "name": "job_store", "status": "ok"}


def _artifact_storage_probe() -> dict:
    store = configured_artifact_store()
    if store is not None:
        store.list_run_summaries(user_id="__factcrafter_healthcheck__", limit=1)
        return {
            "ok": True,
            "name": "artifact_storage",
            "status": "ok",
            "mode": "database",
        }

    runs_dir = Path(default_runs_dir())
    runs_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".factcrafter-health-",
        dir=runs_dir,
        delete=True,
    ) as probe_file:
        probe_file.write(b"ok")
        probe_file.flush()

    return {
        "ok": True,
        "name": "artifact_storage",
        "status": "ok",
        "mode": "filesystem",
        "production_warning": _production_without_artifact_database(),
    }


def _production_without_artifact_database() -> bool:
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    return environment == "production" and not os.getenv("ARTIFACT_DATABASE_URL", "").strip()
