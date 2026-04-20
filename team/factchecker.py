# team/factchecker.py
# 🕵️ THE FACT-CHECKER
# Single batched LLM call verifies all findings at once.
# A finding passes if it is topically relevant AND contains a concrete claim.

import os
import re
from datetime import datetime
from langsmith import traceable
from langchain_google_genai import ChatGoogleGenerativeAI

from team.state import ResearchAgentState


def get_checker_llm():
    """Lazy load — after .env is loaded."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("CHECKER_MODEL", "gemini-2.5-flash-lite"),
        max_retries=2,
        request_timeout=30,
        temperature=0.0,
    )


_VERDICT_RE = re.compile(r"^\s*(\d+)\s*[:.)\-]\s*(ACCEPT|REJECT)\b(.*)$", re.IGNORECASE | re.MULTILINE)


@traceable(
    name="fact_checker_agent",
    tags=["fact-checker", "verification", "llm"],
    metadata={"agent": "fact_checker"},
)
def fact_checker_agent(state: ResearchAgentState) -> ResearchAgentState:
    """
    Batches all findings into ONE LLM call and parses per-finding verdicts.
    Passes = topically relevant AND contains a concrete claim (name/number/date).
    """
    findings = state["findings"]
    print(f"\n✅ FACT-CHECKER: Verifying {len(findings)} findings (batched)...")

    if not findings:
        state["verified_findings"] = []
        return state

    current_year = datetime.now().year

    numbered = "\n\n".join(
        f"FINDING {i+1}:\n{f[:1000]}" for i, f in enumerate(findings)
    )

    prompt = f"""
You are a strict research quality checker.

Today's date is {datetime.now().strftime('%Y-%m-%d')}. For temporal relevance,
treat the previous two model years and the current/upcoming year as valid
"current" information (e.g. 2024, 2025, and 2026 cars are all "current" now).
Do NOT reject a finding just because the year in the snippet isn't the current year.

Research goal: "{state['goal']}"

For EACH finding below, decide ACCEPT or REJECT. ACCEPT only if ALL are true:
  (a) Relevance — it is directly relevant to the research goal.
  (b) Concreteness — it contains at least one specific claim: name, number,
      date, price, spec, quote, or verifiable fact.
  (c) Constraint fit — if the goal specifies a constraint (price cap, size,
      category, region, etc.), the finding must plausibly satisfy it OR be
      about an item that is a candidate for that constraint.
      If a finding mentions an item that clearly VIOLATES the constraint
      (e.g. a $56k car for an "under $40k" goal), REJECT it.
      If price is just unstated, do NOT reject on constraint alone — rely on (b).

REJECT reasons include: off-topic, dictionary definition, generic marketing
fluff, no concrete claim, meta-content ("this page compares X"), or item
clearly outside the goal's constraint.

Findings:

{numbered}

Output format — EXACTLY one line per finding, in order, nothing else:
1: ACCEPT
2: REJECT — brief reason
3: ACCEPT
...
"""

    try:
        response = get_checker_llm().invoke(prompt)
        raw = response.content
    except Exception as e:
        print(f"   ⚠️ Batch check failed ({e}) — keeping all findings")
        state["verified_findings"] = list(findings)
        return state

    verdicts: dict[int, tuple[str, str]] = {}
    for m in _VERDICT_RE.finditer(raw):
        idx = int(m.group(1))
        decision = m.group(2).upper()
        reason = m.group(3).strip(" —-:").strip()
        verdicts[idx] = (decision, reason)

    verified = []
    blocked = 0
    for i, finding in enumerate(findings, start=1):
        decision, reason = verdicts.get(i, ("ACCEPT", "no verdict parsed — keeping"))
        if decision == "ACCEPT":
            verified.append(finding)
            print(f"   ✅ Finding {i}: ACCEPTED")
        else:
            blocked += 1
            print(f"   ❌ Finding {i}: REJECTED — {reason[:80]}")

    state["verified_findings"] = verified
    print(f"\n   📊 FACT-CHECK COMPLETE:")
    print(f"   ✅ Verified: {len(verified)}")
    print(f"   ❌ Blocked:  {blocked}")
    return state
