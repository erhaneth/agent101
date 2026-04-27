# teaam/state.py
# SHARED NOTEBOOK (The State)
# This is the single source of thuth for the entire team. Every agent reads from and writes to this shared notebook.
# It starts with the initial goal and empty sections for the plan, findings, and report.
# Without this shared state, the agents would be isolated and unable to collaborate effectively and agents cant communicate or hand off work to each other.

from typing import TypedDict, List, Optional
# ── STRUCTURED TYPES ──

class ResearchBrief(TypedDict):
    """Created by brief_agent. Classified the reserach intent."""
    user_goal: str
    topic: str
    reserach_type: str # market_analysis, current_events, technical_research etc.
    freshness_required: bool # true prices, news, laws, products, people
    target_depth: str # brief | standard | deep
    must_cover: List[str] # topics that must appear in the report 
    avoid: List[str] # topics that should be avoided in the report
    
class SearchQuery(TypedDict): 
    """Created by planner_agent. One targeted search query."""
    query: str
    purpose: str # overview, primary_sources, recent_data, expert_analysis, etc.
    priority: int # 1 = highest priority, 2 = medium priority, 3 = low priority

class SourceFinding(TypedDict):
     """Created by searcher_agent. One structured search result."""
     query: str
     purpose: str
     title: str
     url: str
     snippet: str
     source_type: str # news, research_paper, blog_post, product_page, etc.
        
class VerifiedFinding(TypedDict):
    """Created by fact_checker_agent. Scored and judged evidence."""
    title: str
    url: str
    snippet: str
    relevance_score: int 
    credibility_score: int
    freshness_score: int
    usefulness_score: int
    verdict: str # "keep" or "discard"
    reason: str # brief explanation for the verdict

class SupportedClaim(TypedDict):
    """Created by claim_builder_agent. Evidence-backed claim."""
    claim: str
    support_urls: List[str]
    confidence: str # high, medium, low

# ── MAIN STATE ──

class ResearchAgentState(TypedDict):
     # ── INPUT ──
    goal: str                               # set by user

    # ── BRIEF ──
    brief: ResearchBrief                    # written by brief_agent

    # ── PLANNING ──
    plan: List[SearchQuery]                 # written by planner_agent
    searches_done: List[str]               # written by searcher_agent (idempotency)

    # ── EVIDENCE ──
    findings: List[SourceFinding]          # written by searcher_agent
    verified_findings: List[VerifiedFinding]  # written by fact_checker_agent
    rejected_findings: List[VerifiedFinding]  # written by fact_checker_agent (audit)

    # ── CLAIMS ──
    claims: List[SupportedClaim]           # written by claim_builder_agent

    # ── OUTPUT ──
    report: str                            # written by writer_agent