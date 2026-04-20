# teaam/state.py
# SHARED NOTEBOOK (The State)
# This is the single source of thuth for the entire team. Every agent reads from and writes to this shared notebook.
# It starts with the initial goal and empty sections for the plan, findings, and report.
# Without this shared state, the agents would be isolated and unable to collaborate effectively and agents cant communicate or hand off work to each other.

from typing import TypedDict, List

class ResearchAgentState(TypedDict):
    goal: str       # what we're trying to achieve
    plan: List[str] # queries created by the Planner
    searches_done: List[str] # Idempotency checklist to avoid repeating searches
    findings: List[str] # Raw data from the Searcher
    verified_findings: List[str] # Verified facts after fact-checking
    report: str    # The final polished report from the Writer

