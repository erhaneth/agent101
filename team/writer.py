# team/writer.py
# ✍️ THE WRITER AGENT (The Editor)
# Responsibility: Read all snippets in Findings. Ask LLM to summarize into a report.
# Save text to the Report section and end the process.
# This is the final node in our agent's workflow. It synthesizes all the collected information
# into a coherent report that addresses the original goal. 
# A good writer can make even mediocre findings look insightful, while a bad writer can bury great research in a wall of text.
# This agent ONLY writes — it never plans or searches.
# Has its own LLM — can be tuned for quality independently.


import os
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState
from team.utils import is_quota_or_model_error, fallback_report

# 🧠 WRITER'S OWN BRAIN
WRITER_MODEL_NAME = os.getenv("WRITER_MODEL", "gemini-2.5-flash-lite")

writer_llm = ChatGoogleGenerativeAI(
    model=WRITER_MODEL_NAME,
    max_retries=3,
    request_timeout=30,
)

@traceable(
    name="writer_agent",
    tags=["writer", "writing", "llm"],
    metadata={"agent": "writer", "model": WRITER_MODEL_NAME}
)
def writer_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Writer Agent — reads all findings from shared notebook.
    Synthesizes into a structured 400-word report.
    Writes result to state['report'].
    """
    print(f"\n✍️  WRITER: Synthesizing {len(state['findings'])} findings...")

    findings_text = "\n\n".join(state["findings"])

    try:
        response = writer_llm.invoke(f"""
            You are an expert research writer.

            Goal: {state['goal']}

            Research findings:
            {findings_text}

            Write a clear, well-structured 400-word report.
            Requirements:
            - Directly address the goal
            - Use bullet points for key findings
            - End with a short conclusion
            - Be concise and factual
        """)
        state["report"] = response.content
        print(f"   ✅ Report written: {len(state['report'])} chars")

    except Exception as e:
        if is_quota_or_model_error(e):
            print(f"   ⚠️ Writer LLM unavailable ({WRITER_MODEL_NAME}). Using fallback.")
            state["report"] = fallback_report(state["goal"], state["findings"])
        else:
            raise

    return state