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
     evidence_text: str
     search_cache_status: str
     fetched_text: str
     fetch_status: str # ok, weak, failed, skipped
     fetch_error: str
     cache_status: str
     http_status: int
     content_type: str
     final_url: str
     source_metadata: dict
     source_quality_score: int
     source_quality_category: str
     source_quality_reasons: List[str]
     source_quality_hard_reject: bool
     source_type: str # news, research_paper, blog_post, product_page, etc.
        
class VerifiedFinding(TypedDict):
    """Created by fact_checker_agent. Scored and judged evidence."""
    title: str
    url: str
    snippet: str
    evidence_text: str
    search_cache_status: str
    fetched_text: str
    fetch_status: str
    fetch_error: str
    cache_status: str
    http_status: int
    content_type: str
    final_url: str
    source_metadata: dict
    source_quality_score: int
    source_quality_category: str
    source_quality_reasons: List[str]
    source_quality_hard_reject: bool
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
    caveat: Optional[str]

class ClaimVerification(TypedDict):
    """Created by claim_verifier_agent. Checks claim/source entailment."""
    claim: str
    support_urls: List[str]
    verdict: str # supported | partial | unsupported
    reason: str
    caveat: Optional[str]

class HumanReviewResult(TypedDict):
    """Created by human_review_agent. Records high-stakes review gate decision."""
    required: bool
    approved: bool
    mode: str
    reasons: List[str]
    decision: str
    reviewer: str

class ReportCitationVerification(TypedDict):
    """Created by report_verifier_agent. Checks final report text against cited sources."""
    item_index: int
    kind: str
    start_line: int
    text: str
    cited_urls: List[str]
    known_source_urls: List[str]
    missing_source_urls: List[str]
    verdict: str # supported | partial | unsupported
    supported_urls: List[str]
    reason: str
    caveat: Optional[str]

class ReportVerificationSummary(TypedDict):
    """Created by report_verifier_agent. Summarizes post-writer citation support."""
    passes: bool
    skipped: bool
    reason: str
    total_items: int
    supported_count: int
    partial_count: int
    unsupported_count: int
    missing_source_url_count: int
    support_rate: float

class ReportRepairRecord(TypedDict):
    """Created by report_repair_agent. Records final-report repair attempts."""
    attempt: int
    method: str
    failed_item_count: int
    failed_item_indexes: List[int]
    
class EvaluationResult(TypedDict):
    """Created by evaluator_agent. Measures final report quality."""
    metric: str
    passes_grounding: bool
    grounding_score: float
    threshold: float
    reason: str
    total_claims: int
    claims_with_sources: int
    grounded_claim_count: int
    ungrounded_claim_count: int
    claim_citation_rate: float
    support_url_citation_rate: float

# ── MAIN STATE ──

class ResearchAgentState(TypedDict):
     # ── INPUT ──
    goal: str                               # set by user

    # ── BRIEF ──
    brief: ResearchBrief                    # written by brief_agent

    # ── PLANNING ──
    anchors: List[dict]                     # written by anchor_agent
    plan: List[SearchQuery]                 # written by planner_agent
    searches_done: List[str]               # written by searcher_agent (idempotency)

    # ── EVIDENCE ──
    findings: List[SourceFinding]          # written by searcher_agent
    verified_findings: List[VerifiedFinding]  # written by fact_checker_agent
    rejected_findings: List[VerifiedFinding]  # written by fact_checker_agent (audit)

    # ── CLAIMS ──
    claims: List[SupportedClaim]           # written by claim_builder_agent
    claim_verifications: List[ClaimVerification]  # written by claim_verifier_agent
    rejected_claims: List[ClaimVerification]      # written by claim_verifier_agent
    human_review: HumanReviewResult        # written by human_review_agent

    # ── OUTPUT ──
    report: str                            # written by writer_agent
    report_verifications: List[ReportCitationVerification]  # written by report_verifier_agent
    report_verification: ReportVerificationSummary          # written by report_verifier_agent
    report_repair_attempts: int                           # written by report_repair_agent
    report_repair_history: List[ReportRepairRecord]        # written by report_repair_agent
    
       # ── EVALUATION ──
    evaluation : EvaluationResult                    # written by evaluator_agent
