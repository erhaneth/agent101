# web/server.py
# FastAPI server for the FactCrafter web UI.

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from web.auth.config import auth_settings
from web.auth.database import User
from web.auth.deps import get_optional_user, require_user
from web.auth.router import router as auth_router
from web.health import readiness_report
from web.jobs import job_manager
from web.limits import enforce_active_job_limit, job_create_rate_limiter
from web.metrics import metrics_snapshot
from web.observability import install_observability
from web.runs import default_runs_dir, get_run, list_runs
from web.security import allowed_cors_origins, install_security_headers

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
UI_DIST = PROJECT_ROOT / "ui" / "dist"


class ResearchRequest(BaseModel):
    goal: str = Field(min_length=8, max_length=4000)


class ReviewDecision(BaseModel):
    approved: bool


def create_app() -> FastAPI:
    settings = auth_settings()
    app = FastAPI(
        title="FactCrafter",
        description="Evidence-first research agent web API",
        version="1.0.0",
    )

    install_observability(app)
    install_security_headers(app, is_production=bool(settings["is_production"]))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "runs_dir": default_runs_dir(),
            "auth_required": settings["auth_required"],
            "google_enabled": settings["google_enabled"],
        }

    @app.get("/api/ready")
    def ready() -> JSONResponse:
        payload = readiness_report()
        status_code = 200 if payload["ready"] else 503
        return JSONResponse(payload, status_code=status_code)

    @app.get("/api/metrics")
    def metrics() -> dict:
        return metrics_snapshot()

    @app.get("/api/runs")
    def api_list_runs(
        limit: int = 50,
        user: User = Depends(require_user),
    ) -> dict:
        return {"runs": list_runs(user.id, limit=limit)}

    @app.get("/api/runs/{run_id}")
    def api_get_run(run_id: str, user: User = Depends(require_user)) -> dict:
        payload = get_run(run_id, user.id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return payload

    @app.get("/api/jobs")
    def api_list_jobs(user: User = Depends(require_user)) -> dict:
        return {"jobs": job_manager.list_jobs(user.id)}

    @app.get("/api/jobs/{job_id}")
    def api_get_job(
        job_id: str,
        include_state: bool = False,
        user: User = Depends(require_user),
    ) -> dict:
        job = job_manager.get_job(job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job.to_dict(include_state=include_state)

    @app.post("/api/jobs")
    def api_create_job(
        body: ResearchRequest,
        user: User = Depends(require_user),
    ) -> dict:
        goal = body.goal.strip()
        if not goal:
            raise HTTPException(status_code=400, detail="Goal is required")
        enforce_active_job_limit(job_manager.list_jobs(user.id))
        job_create_rate_limiter.check_and_record(user.id)
        job = job_manager.create_job(goal, user.id)
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/review")
    def api_review_job(
        job_id: str,
        body: ReviewDecision,
        user: User = Depends(require_user),
    ) -> dict:
        job = job_manager.get_job(job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job_manager.approve_review(job_id, body.approved):
            raise HTTPException(status_code=409, detail="No pending review for this job")
        return {"ok": True, "approved": body.approved}

    @app.post("/api/jobs/{job_id}/cancel")
    def api_cancel_job(
        job_id: str,
        user: User = Depends(require_user),
    ) -> dict:
        job = job_manager.get_job(job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        canceled = job_manager.cancel_job(job_id, user.id)
        if canceled is None:
            raise HTTPException(
                status_code=409,
                detail="Only queued jobs can be canceled before execution.",
            )
        return canceled.to_dict()

    @app.get("/api/jobs/{job_id}/events")
    async def api_job_events(
        job_id: str,
        user: User = Depends(require_user),
    ) -> StreamingResponse:
        job = job_manager.get_job(job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        async def event_stream() -> AsyncGenerator[str, None]:
            seen = 0
            while True:
                current = job_manager.get_job(job_id, user.id)
                if current is None:
                    break
                while seen < len(current.events):
                    payload = current.events[seen].to_dict()
                    seen += 1
                    yield f"data: {json.dumps(payload)}\n\n"
                if current.status.value in {"completed", "failed", "blocked", "canceled"}:
                    if seen >= len(current.events):
                        yield f"data: {json.dumps({'type': 'done', 'status': current.status.value})}\n\n"
                        break
                await asyncio.sleep(0.8)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    if UI_DIST.exists():
        assets_dir = UI_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str) -> FileResponse:
            candidate = UI_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")

    return app


app = create_app()
