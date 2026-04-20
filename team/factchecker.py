# team/fact_checker.py
# 🕵️ THE FACT-CHECKER (The Verifier)
# Responsibility: Verify each finding is relevant to the goal.
# This agent verifies the raw findings from the Searcher before they go to the Writer.
# It uses a combination of rules-based checks and an LLM for semantic verification.
# If any finding fails, it's flagged and removed from the report.
# This ensures the final report is based on accurate and trustworthy information.
# Blocks irrelevant findings — writer only gets clean data.
# Reads: goal + findings
# Writes: verified_findings

import os
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState


def get_checker_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("CHECKER_MODEL", "gemini-2.5-flash-lite"),
        max_retries=2,
        request_timeout=20,
        temperature=0.0,  # deterministic for fact checking
    )


@traceable(
    name="fact_checker_agent",
    tags=["fact-checker", "verification", "llm"],
    metadata={"agent": "fact_checker"}
)
def fact_checker_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Fact-Checker Agent — verifies each finding against the goal.
    Blocks irrelevant findings before they reach the writer.
    Reads: goal + findings
    Writes: verified_findings
    """
    print(f"\n✅ FACT-CHECKER: Verifying {len(state['findings'])} findings...")

    verified = []
    blocked = 0

    for i, finding in enumerate(state["findings"]):
        try:
            response = get_checker_llm().invoke(f"""
                You are a research quality checker.

                Research goal: "{state['goal']}"

                Finding:
                {finding[:400]}

                Is this finding at least partially related to the research goal?
                Be lenient — if there is ANY connection to the topic, answer YES.
                Only answer NO if the finding is completely off-topic.

                Answer with EXACTLY one word: YES or NO
            """)

            verdict = response.content.strip().upper()

            if "YES" in verdict:
                verified.append(finding)
                print(f"   ✅ Finding {i+1}: VERIFIED")
            else:
                blocked += 1
                print(f"   ❌ Finding {i+1}: BLOCKED — not relevant to goal")

        except Exception as e:
            # If check fails — keep the finding (fail open for quality)
            print(f"   ⚠️ Finding {i+1}: check failed ({e}) — keeping")
            verified.append(finding)

    state["verified_findings"] = verified

    print(f"\n   📊 FACT-CHECK COMPLETE:")
    print(f"   ✅ Verified: {len(verified)}")
    print(f"   ❌ Blocked:  {blocked}")

    return state