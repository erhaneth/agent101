# app.py
# 🌐 FactCrafter API wrapper

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from team.main import run_research


app = FastAPI(
    title="FactCrafter API",
    version="0.1.0-beta",
    description="Evidence-first research agent API.",
)


class ResearchRequest(BaseModel):
    goal: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The research question or goal.",
    )


class ResearchResponse(BaseModel):
    status: str
    report: str
    warning: str = (
        "FactCrafter is in beta. Review outputs before using them for important decisions."
    )


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "FactCrafter",
        "version": "0.1.0-beta",
    }


@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest):
    try:
        report = run_research(request.goal.strip())

        if report.startswith("⚠️ Report failed grounding evaluation"):
            status = "blocked_grounding"
        elif report.startswith("⚠️ Report failed quality check"):
            status = "blocked_quality"
        elif report.startswith("❌ Request blocked by safety guardrail"):
            status = "blocked_safety"
        elif report.startswith("⚠️") or report.startswith("❌"):
            status = "blocked"
        else:
            status = "ok"

        return ResearchResponse(
            status=status,
            report=report,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"FactCrafter run failed: {exc}",
        )