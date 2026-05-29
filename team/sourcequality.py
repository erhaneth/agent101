# team/sourcequality.py
# 🧭 SOURCE QUALITY RANKING
# Responsibility: deterministic source credibility signals before LLM judging.
#
# The LLM can judge topic relevance and usefulness, but source credibility should
# not be entirely model-vibes-based. This module assigns transparent source ranks
# and reasons that are passed into the evidence judge and stored in artifacts.

from __future__ import annotations

from urllib.parse import urlparse


PRIMARY_OFFICIAL_HOST_HINTS = (
    ".gov",
    ".mil",
    "who.int",
    "oecd.org",
    "worldbank.org",
    "imf.org",
    "un.org",
    "europa.eu",
    "federalregister.gov",
    "irs.gov",
    "energy.gov",
    "epa.gov",
    "cdc.gov",
    "nih.gov",
    "nist.gov",
    "bls.gov",
)

ACADEMIC_HOST_HINTS = (
    ".edu",
    ".ac.",
    "arxiv.org",
    "doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "nature.com",
    "science.org",
    "springer.com",
    "link.springer.com",
    "onlinelibrary.wiley.com",
    "tandfonline.com",
    "sagepub.com",
    "frontiersin.org",
    "plos.org",
    "mdpi.com",
    "sciencedirect.com",
    "jstor.org",
    "acm.org",
    "ieee.org",
)

# Reputable organizations whose primary research reports should be treated more leniently
# in scientific_academic mode (even if hosted on .com or blog-like paths).
REPUTABLE_RESEARCH_ORGS = (
    "4dayweek.com",
    "autonomy.work",
    "jrc.ec.europa.eu",
    "publications.jrc.ec.europa.eu",
    "gov.uk",
    "whitehouse.gov",
    "oecd.org",
    "worldbank.org",
    "imf.org",
    "who.int",
    "un.org",
)

MAJOR_NEWS_HOST_HINTS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "bloomberg.com",
    "ft.com",
    "nytimes.com",
    "washingtonpost.com",
    "wsj.com",
    "theguardian.com",
)

LOW_QUALITY_HOST_HINTS = (
    "medium.com",
    "substack.com",
    "quora.com",
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
)

ACADEMIC_PROFILE_HOST_HINTS = (
    "researchgate.net",
    "academia.edu",
)

WEAK_PATH_HINTS = (
    "/blog",
    "/topics/",
    "/editor-resources/",
    "/publish/article/",
    "/the-reader/",
)


def normalized_host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def host_matches(host: str, hints: tuple[str, ...]) -> bool:
    for hint in hints:
        if hint.startswith("."):
            if hint in host:
                return True
        elif host == hint or host.endswith(f".{hint}"):
            return True
    return False


def evidence_length_score(text: str) -> int:
    length = len(text or "")
    if length >= 4000:
        return 2
    if length >= 1000:
        return 1
    if length < 300:
        return -1
    return 0


def rank_source(finding: dict, brief: dict | None = None) -> dict:
    """
    Rank a source from 0-5 using transparent deterministic signals.

    0 = reject-level source
    1 = weak
    2 = low/secondary
    3 = acceptable
    4 = strong
    5 = primary/high-authority
    """
    brief = brief or {}
    url = finding.get("url", "")
    host = normalized_host(url)
    path = urlparse(url).path.lower()
    source_type = finding.get("source_type", "web")
    fetch_status = finding.get("fetch_status", "not_fetched")
    evidence_text = finding.get("evidence_text") or finding.get("snippet", "")
    research_type = brief.get("research_type", "")

    score = 2
    category = "general_web"
    reasons = []
    hard_reject = False

    if host_matches(host, LOW_QUALITY_HOST_HINTS) or source_type == "social":
        score = 0
        category = "blocked_social_or_forum"
        hard_reject = True
        reasons.append("social/forum or low-quality user-generated domain")
    elif host_matches(host, PRIMARY_OFFICIAL_HOST_HINTS) or source_type == "official":
        score = 5
        category = "official_primary"
        reasons.append("official or institutional primary source")
    elif host_matches(host, ACADEMIC_HOST_HINTS) or source_type == "academic":
        score = 4
        category = "academic"
        reasons.append("academic, paper, DOI, journal, or university source")
    elif host_matches(host, MAJOR_NEWS_HOST_HINTS) or source_type == "news":
        score = 3
        category = "major_news"
        reasons.append("established news source")
    elif source_type == "technical":
        score = 4
        category = "technical_primary"
        reasons.append("technical documentation or developer source")
    elif source_type == "blog":
        score = 1
        category = "blog_or_commentary"
        reasons.append("blog/commentary source")

    if host_matches(host, ACADEMIC_PROFILE_HOST_HINTS):
        score = min(score, 2)
        category = "academic_profile"
        reasons.append("academic profile/aggregator rather than primary publication")

    if any(part in path for part in WEAK_PATH_HINTS):
        score = min(score, 2)
        reasons.append("weak path pattern such as blog/topic/editorial page")

    if path.endswith(".pdf"):
        score = min(5, score + 1)
        reasons.append("direct PDF/document source")

    if fetch_status == "ok":
        score = min(5, score + 1)
        reasons.append("full source text fetched successfully")
    elif fetch_status in {"weak", "failed"}:
        score = max(0, score - 1)
        reasons.append(f"source fetch {fetch_status}; relying on fallback text")

    length_adjustment = evidence_length_score(evidence_text)
    if length_adjustment:
        score = max(0, min(5, score + length_adjustment))
        reasons.append(f"evidence text length adjustment {length_adjustment:+d}")

    if research_type == "scientific_academic" and category not in {
        "academic",
        "official_primary",
        "technical_primary",
    }:
        # Give a boost for known reputable research organizations
        if any(org in host for org in REPUTABLE_RESEARCH_ORGS):
            score = max(score, 3)
            reasons.append("reputable research organization — boosted for scientific_academic use")
        else:
            score = min(score, 2)
            reasons.append("scientific-academic brief requires academic, official, or technical primary evidence")

    if research_type == "policy_legal" and category == "official_primary":
        score = 5
        reasons.append("policy/legal question prioritizes official sources")

    if score <= 1:
        hard_reject = True

    return {
        "source_quality_score": score,
        "source_quality_category": category,
        "source_quality_reasons": reasons or ["no strong deterministic quality signal"],
        "source_quality_hard_reject": hard_reject,
    }


def source_quality_passes(rank: dict, brief: dict | None = None) -> tuple[bool, str]:
    brief = brief or {}
    score = rank.get("source_quality_score", 0)

    if rank.get("source_quality_hard_reject"):
        return False, "source quality rank is hard reject"

    if brief.get("research_type") == "scientific_academic" and score < 3:
        return False, "source quality rank is too low for scientific-academic evidence"

    if score < 2:
        return False, "source quality rank is too low"

    return True, ""
