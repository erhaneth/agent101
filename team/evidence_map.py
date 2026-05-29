# team/evidence_map.py
# 📊 EVIDENCE MAP
# Builds a structured summary of the quality and characteristics of the evidence base.
# This is used by the writer to create a high-quality "Evidence Quality Map" section.

from typing import List, Dict, Any
from collections import Counter


def build_evidence_map(verified_findings: List[dict]) -> dict:
    """
    Create a rich, structured evidence quality summary.
    """
    if not verified_findings:
        return {
            "total_verified": 0,
            "summary": "No verified evidence available.",
            "quality_breakdown": {},
            "source_type_breakdown": {},
            "credibility_stats": {},
            "key_gaps": ["No high-quality sources were verified."],
            "strengths": [],
        }

    total = len(verified_findings)

    # Source quality scores
    quality_scores = [f.get("source_quality_score", 0) for f in verified_findings]
    avg_quality = round(sum(quality_scores) / total, 2) if total > 0 else 0

    quality_breakdown = dict(Counter(quality_scores))

    # Credibility / usefulness / relevance from fact checker
    cred_scores = [f.get("credibility_score", 0) for f in verified_findings if "credibility_score" in f]
    usefulness_scores = [f.get("usefulness_score", 0) for f in verified_findings if "usefulness_score" in f]

    avg_cred = round(sum(cred_scores) / len(cred_scores), 2) if cred_scores else 0
    avg_useful = round(sum(usefulness_scores) / len(usefulness_scores), 2) if usefulness_scores else 0

    # Source categories
    categories = [f.get("source_quality_category", "unknown") for f in verified_findings]
    category_breakdown = dict(Counter(categories))

    # High value sources
    high_quality = [f for f in verified_findings if f.get("source_quality_score", 0) >= 4]
    academic_or_official = [
        f for f in verified_findings
        if f.get("source_quality_category") in ("academic", "official_primary", "technical_primary")
    ]

    # Identify potential gaps — more proactive even on strong evidence bases
    key_gaps = []
    if len(high_quality) < 3:
        key_gaps.append("Limited number of high-quality (score 4-5) primary sources.")
    if avg_cred < 4.0:
        key_gaps.append("Average source credibility is moderate.")
    if not academic_or_official:
        key_gaps.append("No strong academic or official primary sources were included.")

    # New analytical gap signals (even on strong bases)
    if len(category_breakdown) <= 2:
        key_gaps.append("Low source type diversity — evidence concentrated in very few categories.")
    if avg_useful < 3.8:
        key_gaps.append("Average usefulness score is moderate — many sources may not be highly actionable.")
    if len(high_quality) / total < 0.6 and total >= 8:
        key_gaps.append("Significant portion of verified findings come from medium or lower quality sources.")

    strengths = []
    if len(academic_or_official) >= 2:
        strengths.append("Multiple high-credibility academic or official sources.")
    if avg_quality >= 3.8:
        strengths.append("Strong overall source quality.")
    if any(f.get("source_quality_score", 0) == 5 for f in verified_findings):
        strengths.append("At least one primary/official high-authority source.")
    if len(category_breakdown) >= 4:
        strengths.append("Good source type diversity across the evidence base.")

    summary = (
        f"{total} verified findings. "
        f"Average source quality: {avg_quality}/5. "
        f"Average credibility: {avg_cred}/5. "
        f"High-quality sources (4-5): {len(high_quality)}."
    )

    return {
        "total_verified": total,
        "summary": summary,
        "quality_breakdown": quality_breakdown,
        "source_type_breakdown": category_breakdown,
        "credibility_stats": {
            "average_credibility": avg_cred,
            "average_usefulness": avg_useful,
        },
        "high_quality_count": len(high_quality),
        "academic_or_official_count": len(academic_or_official),
        "source_diversity": len(category_breakdown),
        "high_quality_ratio": round(len(high_quality) / total, 2) if total > 0 else 0,
        "key_gaps": key_gaps,
        "strengths": strengths,
    }


def format_evidence_map_for_writer(evidence_map: dict) -> str:
    """Create a highly structured, report-ready Evidence Quality Map block."""
    if not evidence_map or evidence_map.get("total_verified", 0) == 0:
        return "No verified evidence available."

    lines = [
        "EVIDENCE QUALITY MAP — Use this structured data to build a clear section (prefer tables or tight bullets over prose):",
        "",
        f"Total verified findings: {evidence_map['total_verified']}",
        f"Summary: {evidence_map.get('summary', '')}",
        "",
        "Quality Score Distribution:",
    ]

    for score in sorted(evidence_map.get("quality_breakdown", {}).keys(), reverse=True):
        count = evidence_map["quality_breakdown"][score]
        lines.append(f"  - Score {score}/5: {count} sources")

    lines.append("")
    lines.append("Source Type Breakdown:")
    for cat, count in evidence_map.get("source_type_breakdown", {}).items():
        lines.append(f"  - {cat}: {count} sources")

    lines.append("")
    lines.append("Key Aggregates:")
    lines.append(f"  - High-quality sources (4-5): {evidence_map.get('high_quality_count', 0)}")
    lines.append(f"  - Academic/official primary sources: {evidence_map.get('academic_or_official_count', 0)}")
    lines.append(f"  - Source type diversity: {evidence_map.get('source_diversity', 'N/A')} categories")
    lines.append(f"  - High-quality ratio: {evidence_map.get('high_quality_ratio', 'N/A')}")

    if evidence_map.get("credibility_stats"):
        stats = evidence_map["credibility_stats"]
        lines.append("")
        lines.append("Credibility & Usefulness:")
        lines.append(f"  - Average credibility: {stats.get('average_credibility', 'N/A')}/5")
        lines.append(f"  - Average usefulness: {stats.get('average_usefulness', 'N/A')}/5")

    if evidence_map.get("key_gaps"):
        lines.append("")
        lines.append("Evidence Gaps (be direct about these):")
        for gap in evidence_map["key_gaps"]:
            lines.append(f"  - {gap}")

    if evidence_map.get("strengths"):
        lines.append("")
        lines.append("Evidence Strengths:")
        for s in evidence_map["strengths"]:
            lines.append(f"  - {s}")

    return "\n".join(lines)
