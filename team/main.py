# team/main.py
# 🚀 THE ENTRY POINT
# This is where we run the whole team. It imports the compiled graph from graph.py and executes it with the initial state.
# The main.py file is the simplest — it just runs the graph. All the complexity is hidden in the agents and the graph definition. This separation keeps our code organized and makes it clear where to look for different types of logic.
# Responsibility: Run the research team with a goal.
# This is the ONLY file you touch to change what gets researched.
# Everything else is wired automatically.


import os
from pathlib import Path
from dotenv import load_dotenv

# ✅ LOAD .env FIRST — before any team imports
load_dotenv(Path(__file__).parent.parent / ".env")

# ✅ THEN import team modules — they need env vars ready
from team.graph import research_team
def run_research(goal: str) -> str:
    """
    Run the full multi-agent research pipeline.
    
    Args:
        goal: The research question to investigate.
    
    Returns:
        The final synthesized report as a string.
    """
    print("\n" + "="*50)
    print("🚀 RESEARCH TEAM STARTING")
    print(f"📌 Goal: {goal}")
    print("="*50)

    result = research_team.invoke(
        # Initial state — notebook starts empty
        {
            "goal": goal,
            "plan": [],           # Planner fills this
            "searches_done": [],  # Searcher fills this
            "findings": [],       # Searcher fills this
            "report": ""          # Writer fills this
        },
        # Run-level metadata for LangSmith
        config={
            "tags": ["research", "production"],
            "metadata": {
                "user_id": "researher_agents_team21",  # who ran this
                "agent_version": "2.0",      # ← upgraded from 1.0!
                "environment": "development",
                "planner_model": os.getenv("PLANNER_MODEL", "gemini-2.5-flash-lite"),
                "writer_model": os.getenv("WRITER_MODEL", "gemini-2.5-flash-lite"),
            }
        }
    )

    print("\n" + "="*50)
    print("📄 FINAL REPORT")
    print("="*50)
    print(result["report"])

    return result["report"]


if __name__ == "__main__":
    run_research(
        "why building AI agents is more important than building application with Vibe Coding can we do some analysis and compare?"
    )