# team/main.py
# 🚀 THE ENTRY POINT
# This is where we run the whole team. It imports the compiled graph from graph.py and executes it with the initial state.
# The main.py file is the simplest — it just runs the graph. All the complexity is hidden in the agents and the graph definition. This separation keeps our code organized and makes it clear where to look for different types of logic.
# Responsibility: Run the research team with a goal.
# This is the ONLY file you touch to change what gets researched.
# Everything else is wired automatically.


from pathlib import Path
from dotenv import load_dotenv



# ✅ LOAD .env FIRST — before any team imports
load_dotenv(Path(__file__).parent.parent / ".env")
from team.graph import research_team
# ✅ THEN import team modules — they need env vars ready
from team.artifacts import should_save_artifacts, write_run_artifacts
from team.guardrails import input_guardrail, output_guardrail
from team.utils import content_to_text


def initial_state(goal: str) -> dict:
    """Create the starting LangGraph state for one research run."""
    return {
        "goal": goal,
        "brief": {},
        "plan": [],
        "searches_done": [],
        "findings": [],
        "verified_findings": [],
        "rejected_findings": [],
        "claims": [],
        "claim_verifications": [],
        "rejected_claims": [],
        "human_review": {},
        "report": "",
        "report_verifications": [],
        "report_verification": {},
        "report_repair_attempts": 0,
        "report_repair_history": [],
        "evaluation": {},
    }


def run_research_state(
    goal: str,
    *,
    run_output_check: bool = True,
    save_artifacts: bool | None = None,
) -> dict:
    """
    Run the research team and return the full state.

    The CLI uses run_research() below, while evals use this function so they can
    inspect intermediate artifacts such as findings, claims, and evaluation.
    """
    print("\n" + "="*50)
    print("🚀 RESEARCH TEAM STARTING")
    print(f"📌 Goal: {goal}")
    print("="*50)

    # 🛡️ INPUT GUARDRAIL — check before running
    is_safe, reason = input_guardrail(goal)
    if not is_safe:
        state = initial_state(goal)
        state["input_guardrail_passed"] = False
        state["input_guardrail_reason"] = reason
        state["report"] = f"❌ Request blocked by safety guardrail: {reason}"
        if should_save_artifacts(save_artifacts):
            artifact_dir = write_run_artifacts(state)
            state["artifact_dir"] = str(artifact_dir)
            print(f"🗂️  Run artifacts saved: {artifact_dir}")
        return state

    result = research_team.invoke(
        initial_state(goal),
        config={
            "tags": ["research", "production"],
            "metadata": {"user_id": "husseyin", "agent_version": "2.1", "environment": "development"}
        }
    )
    report = content_to_text(result.get("report", ""))
    result["report"] = report
    result["input_guardrail_passed"] = True
    result["input_guardrail_reason"] = reason
    evaluation = result.get("evaluation", {})
    result["grounding_gate_passed"] = bool(evaluation.get("passes_grounding", False))

    if run_output_check and result["grounding_gate_passed"]:
        is_safe, output_reason = output_guardrail(report, goal)
        result["output_guardrail_passed"] = is_safe
        result["output_guardrail_reason"] = output_reason
    else:
        result["output_guardrail_passed"] = None
        result["output_guardrail_reason"] = "skipped"

    if should_save_artifacts(save_artifacts):
        artifact_dir = write_run_artifacts(result)
        result["artifact_dir"] = str(artifact_dir)
        print(f"🗂️  Run artifacts saved: {artifact_dir}")

    return result


def run_research(goal: str) -> str:
    result = run_research_state(goal)
    report = content_to_text(result.get("report", ""))

    if not result.get("input_guardrail_passed", False):
        return report

    evaluation = result.get("evaluation", {})
    human_review = result.get("human_review", {}) or {}

    if human_review.get("required") and human_review.get("approved") is False:
        return report

    if not evaluation.get("passes_grounding", False):
        return (
            "⚠️ Report failed grounding evaluation.\n\n"
            f"Score: {evaluation.get('grounding_score', 0)}/100\n"
            f"Reason: {evaluation.get('reason', 'Unknown')}\n"
            f"Claim citation rate: {evaluation.get('claim_citation_rate', 0)}\n"
            f"Support URL citation rate: {evaluation.get('support_url_citation_rate', 0)}\n\n"
            "The report was not returned because FactCrafter requires cited, grounded output."
        )

    # 🛡️ OUTPUT GUARDRAIL — check before returning
    if result.get("output_guardrail_passed") is False:
        return f"⚠️ Report failed quality check: {result.get('output_guardrail_reason')}"

    return report


if __name__ == "__main__":
    user_goal = input("Enter your research question: ").strip()
    if not user_goal:
        user_goal = "Compare electric cars under $40k right now."
        print(f"No input provided. Using default goal: {user_goal}")

    report = run_research(user_goal)
    print("\n" + "="*50)
    print("📄 FINAL REPORT")
    print("="*50)
    print(report)
