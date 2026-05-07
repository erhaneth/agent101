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
from team.guardrails import input_guardrail, output_guardrail

def run_research(goal: str) -> str:
    print("\n" + "="*50)
    print("🚀 RESEARCH TEAM STARTING")
    print(f"📌 Goal: {goal}")
    print("="*50)

    # 🛡️ INPUT GUARDRAIL — check before running
    is_safe, reason = input_guardrail(goal)
    if not is_safe:
        return f"❌ Request blocked by safety guardrail: {reason}"

    result = research_team.invoke(
        {
            "goal": goal,
            "brief": {},
            "plan": [],
            "searches_done": [],
            "findings": [],
            "verified_findings": [],
            "rejected_findings": [],
            "claims": [],
            "report": "",
            "evaluation": {},
        },
        config={
            "tags": ["research", "production"],
            "metadata": {"user_id": "husseyin", "agent_version": "2.1", "environment": "development"}
        }
    )
    evaluation = result.get("evaluation", {})

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
    is_safe, reason = output_guardrail(result["report"], goal)
    if not is_safe:
        return f"⚠️ Report failed quality check: {reason}"

    return result["report"]


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
