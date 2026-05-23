import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from team.artifacts import write_run_artifacts
from team.cache import clear_cache, get_cached_json, set_cached_json
from team.guardrails import input_guardrail
from team.claimverifier import apply_verifications, source_blocks_for_claim, source_lookup
from team.evaluator import apply_report_verification, evaluate_grounding, markdown_url_label_mismatches
from team.humanreview import human_review_agent, is_high_stakes
from team.reportverifier import build_records, cited_report_items
from team.sourcequality import rank_source, source_quality_passes
from team.sourcefetcher import clean_text, fetch_and_parse_source, is_probably_bad_page, parse_html
from team.searcher import (
    classify_source_type,
    search_days_for_brief,
    searcher_agent,
    should_skip_source,
)
from team.factchecker import source_passes_static_checks
from team.main import run_research
from team.utils import response_to_text, strip_json_fences
from team.writer import writer_agent
from evals.run_eval import score_case


class FailingSearchClient:
    def search(self, **kwargs):
        raise RuntimeError("search unavailable")


class CountingSearchClient:
    def __init__(self):
        self.calls = 0

    def search(self, **kwargs):
        self.calls += 1
        return {
            "results": [
                {
                    "title": "Cached result",
                    "url": "https://example.com/cached",
                    "content": "This source has enough content to pass the snippet length check for caching. It includes a second sentence so the searcher accepts it as usable evidence.",
                    "raw_content": "Cached raw source content about evidence quality.",
                }
            ]
        }


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeHTTPResponse:
    encoding = "utf-8"
    apparent_encoding = "utf-8"


class HardeningTests(unittest.TestCase):
    def test_search_failure_is_marked_done(self):
        state = {
            "goal": "test goal",
            "brief": {"freshness_required": True, "research_type": "current_events"},
            "plan": [{"query": "one query", "purpose": "overview", "priority": 1}],
            "searches_done": [],
            "findings": [],
        }

        with patch("team.searcher.get_search_client", return_value=FailingSearchClient()):
            result = searcher_agent(state)

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["searches_done"], ["one query"])

    def test_social_sources_are_classified_and_skipped(self):
        url = "https://www.facebook.com/example/posts/123"

        self.assertEqual(classify_source_type(url, "EV tax credit post"), "social")
        should_skip, reason = should_skip_source(url, "EV tax credit post", "x" * 120)

        self.assertTrue(should_skip)
        self.assertIn("social", reason)

    def test_factchecker_static_checks_reject_social_sources(self):
        source_ok, reason = source_passes_static_checks(
            "https://www.facebook.com/example/posts/123",
            "social",
        )

        self.assertFalse(source_ok)
        self.assertIn("social", reason)

    def test_academic_brief_rejects_secondary_academic_profiles(self):
        source_ok, reason = source_passes_static_checks(
            "https://www.researchgate.net/publication/123",
            "web",
            {"research_type": "scientific_academic"},
        )

        self.assertFalse(source_ok)
        self.assertIn("secondary academic", reason)

    def test_academic_brief_rejects_academic_adjacent_commentary(self):
        source_ok, reason = source_passes_static_checks(
            "https://blogs.lse.ac.uk/impactofsocialsciences/example",
            "web",
            {"research_type": "scientific_academic"},
        )

        self.assertFalse(source_ok)
        self.assertIn("not strong enough", reason)

    def test_search_freshness_uses_brief(self):
        self.assertEqual(
            search_days_for_brief({"freshness_required": True, "research_type": "product_comparison"}),
            365,
        )
        self.assertIsNone(
            search_days_for_brief({"freshness_required": False, "research_type": "historical_background"})
        )
        self.assertEqual(
            search_days_for_brief({"freshness_required": True, "research_type": "general_explainer"}),
            30,
        )

    def test_guardrail_allows_rules_only_when_llm_fails(self):
        with patch("team.guardrails.invoke_guard_llm", side_effect=RuntimeError("model unavailable")):
            is_safe, reason = input_guardrail("Compare electric cars under $40k right now.")

        self.assertTrue(is_safe)
        self.assertEqual(reason, "passed rules-only guardrail")

    def test_structured_llm_content_is_normalized_to_text(self):
        response = FakeResponse([{"type": "text", "text": "```json\n{\"ok\": true}\n```"}])

        self.assertEqual(response_to_text(response), "```json\n{\"ok\": true}\n```")
        self.assertEqual(strip_json_fences(response), "{\"ok\": true}")

    def test_evaluator_accepts_structured_report_content(self):
        report = [
            {
                "type": "text",
                "text": "## Direct Answer\nCitation quality matters. [source](https://example.com/a)\n\n## Sources\nhttps://example.com/a",
            }
        ]
        claims = [{"claim": "Citation quality matters.", "support_urls": ["https://example.com/a"]}]

        result = evaluate_grounding(report, claims)

        self.assertIn("grounding_score", result)
        self.assertEqual(result["report_url_count"], 1)

    def test_evaluator_rejects_mismatched_markdown_url_citations(self):
        report = (
            "## Direct Answer\n"
            "Citation quality matters "
            "[https://example.com/a](https://example.com/b).\n\n"
            "## Sources\n"
            "https://example.com/a"
        )
        claims = [{"claim": "Citation quality matters.", "support_urls": ["https://example.com/a"]}]

        result = evaluate_grounding(report, claims)

        self.assertFalse(result["passes_grounding"])
        self.assertFalse(result["citation_integrity_passes"])
        self.assertEqual(result["citation_mismatch_count"], 1)
        self.assertEqual(len(markdown_url_label_mismatches(report)), 1)

    def test_claim_verifier_maps_claims_to_verified_source_text(self):
        findings = [
            {
                "url": "https://example.com/study",
                "title": "Study",
                "snippet": "short",
                "evidence_text": "The study found source credibility increases perceived accuracy.",
            }
        ]
        claim = {"claim": "Source credibility increases perceived accuracy.", "support_urls": ["https://example.com/study/"]}

        blocks = source_blocks_for_claim(claim, source_lookup(findings))

        self.assertFalse(blocks[0]["missing"])
        self.assertIn("perceived accuracy", blocks[0]["evidence_text"])

    def test_claim_verifier_filters_unsupported_claims(self):
        claims = [
            {"claim": "Supported claim", "support_urls": ["https://example.com/a"], "confidence": "high"},
            {"claim": "Partial claim", "support_urls": ["https://example.com/b"], "confidence": "medium", "caveat": None},
            {"claim": "Unsupported claim", "support_urls": ["https://example.com/c"], "confidence": "high"},
        ]
        verifications = [
            {"verdict": "supported", "supported_urls": ["https://example.com/a"], "reason": "directly supported"},
            {"verdict": "partial", "supported_urls": ["https://example.com/b"], "reason": "scope is narrower"},
            {"verdict": "unsupported", "supported_urls": [], "reason": "not in source"},
        ]

        verified_claims, rejected_claims = apply_verifications(claims, verifications)

        self.assertEqual(len(verified_claims), 2)
        self.assertEqual(len(rejected_claims), 1)
        self.assertEqual(verified_claims[1]["confidence"], "low")
        self.assertIn("scope is narrower", verified_claims[1]["caveat"])

    def test_eval_harness_scores_agent_state(self):
        case = {
            "id": "sample",
            "goal": "test",
            "expected": {
                "require_passes_grounding": True,
                "require_citation_integrity": True,
                "require_claim_verification": True,
                "require_report_verification": True,
                "min_grounding_score": 80,
                "min_verified_findings": 1,
                "min_claims": 1,
                "required_report_sections": ["## Direct Answer", "## Sources"],
                "disallowed_domains": ["facebook.com"],
            },
        }
        state = {
            "input_guardrail_passed": True,
            "input_guardrail_reason": "passed",
            "verified_findings": [{"url": "https://example.com/a"}],
            "claims": [{"claim": "A", "support_urls": ["https://example.com/a"]}],
            "claim_verifications": [{"verdict": "supported"}],
            "report": "## Direct Answer\nA [source](https://example.com/a).\n\n## Sources\nhttps://example.com/a",
            "report_verification": {
                "passes": True,
                "skipped": False,
                "reason": "ok",
                "total_items": 1,
                "support_rate": 1.0,
            },
            "evaluation": {
                "passes_grounding": True,
                "grounding_score": 95,
                "citation_integrity_passes": True,
                "citation_mismatch_count": 0,
                "reason": "ok",
            },
        }

        result = score_case(case, state)

        self.assertTrue(result["passed"])
        self.assertEqual(result["checks_passed"], result["checks_total"])

    def test_source_fetcher_parses_html_text(self):
        html = b"""
        <html>
          <head><title>Research page</title><script>ignore()</script></head>
          <body><h1>Finding</h1><p>Source credibility improves trust decisions.</p></body>
        </html>
        """

        text, metadata = parse_html(html, FakeHTTPResponse())

        self.assertIn("Source credibility improves trust decisions", text)
        self.assertNotIn("ignore", text)
        self.assertEqual(metadata["parsed_title"], "Research page")

    def test_source_fetcher_detects_bad_pages(self):
        self.assertTrue(is_probably_bad_page("Sign in"))
        self.assertEqual(clean_text("a   b\n\n\n c"), "a b\n\nc")

    def test_source_fetcher_handles_fetch_failures_without_raising(self):
        result = fetch_and_parse_source("http://127.0.0.1:1/not-running", timeout_seconds=1)

        self.assertEqual(result["fetch_status"], "failed")
        self.assertIn("fetch_error", result)

    def test_source_quality_ranks_official_sources_high(self):
        rank = rank_source(
            {
                "url": "https://www.irs.gov/credits-deductions/clean-vehicle-credit",
                "source_type": "official",
                "fetch_status": "ok",
                "evidence_text": "x" * 2000,
            },
            {"research_type": "policy_legal"},
        )

        self.assertEqual(rank["source_quality_score"], 5)
        self.assertEqual(rank["source_quality_category"], "official_primary")
        self.assertFalse(rank["source_quality_hard_reject"])

    def test_source_quality_rejects_social_sources(self):
        rank = rank_source(
            {
                "url": "https://www.reddit.com/r/example/comments/1",
                "source_type": "social",
                "fetch_status": "ok",
                "evidence_text": "x" * 2000,
            },
            {"research_type": "general_explainer"},
        )

        passed, reason = source_quality_passes(rank, {"research_type": "general_explainer"})

        self.assertFalse(passed)
        self.assertIn("hard reject", reason)

    def test_source_quality_scientific_requires_strong_evidence(self):
        rank = rank_source(
            {
                "url": "https://example.com/opinion",
                "source_type": "web",
                "fetch_status": "ok",
                "evidence_text": "x" * 2000,
            },
            {"research_type": "scientific_academic"},
        )

        passed, reason = source_quality_passes(rank, {"research_type": "scientific_academic"})

        self.assertFalse(passed)
        self.assertLess(rank["source_quality_score"], 3)
        self.assertIn("scientific-academic", reason)

    def test_run_artifacts_write_audit_files(self):
        state = {
            "goal": "test goal",
            "brief": {"research_type": "general_explainer"},
            "plan": [{"query": "test", "purpose": "overview", "priority": 1}],
            "findings": [],
            "verified_findings": [],
            "rejected_findings": [],
            "claims": [],
            "claim_verifications": [],
            "rejected_claims": [],
            "report_verification": {"passes": True, "support_rate": 1.0},
            "report_verifications": [],
            "evaluation": {"grounding_score": 91, "passes_grounding": True},
            "report": "## Direct Answer\nTest.\n\n## Sources\n",
            "input_guardrail_passed": True,
            "output_guardrail_passed": True,
            "grounding_gate_passed": True,
        }

        with TemporaryDirectory() as tmpdir:
            artifact_dir = write_run_artifacts(state, root=tmpdir, run_id="test-run")

            self.assertTrue((artifact_dir / "summary.json").exists())
            self.assertTrue((artifact_dir / "report.md").exists())
            self.assertTrue((artifact_dir / "state.json").exists())
            self.assertTrue((artifact_dir / "claim_verifications.json").exists())
            self.assertTrue((artifact_dir / "report_verification.json").exists())

    def test_report_verifier_extracts_cited_report_items(self):
        report = (
            "## Direct Answer\n"
            "Research evidence indicates citation quality increases perceived accuracy and trust "
            "in user decisions [source](https://example.com/study).\n\n"
            "## Sources\n"
            "https://example.com/study"
        )

        items = cited_report_items(report)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["urls"], ["https://example.com/study"])
        self.assertIn("citation quality", items[0]["text"])

    def test_report_verifier_flags_missing_cited_sources(self):
        items = [
            {
                "item_index": 1,
                "kind": "paragraph",
                "start_line": 2,
                "text": "Research evidence indicates citation quality increases trust.",
                "urls": ["https://example.com/missing"],
            }
        ]
        verifications = [
            {
                "item_index": 1,
                "verdict": "supported",
                "supported_urls": ["https://example.com/missing"],
                "reason": "model believed it was supported",
            }
        ]

        records, summary = build_records(items, verifications, verified_findings=[])

        self.assertFalse(summary["passes"])
        self.assertEqual(summary["missing_source_url_count"], 1)
        self.assertEqual(records[0]["missing_source_urls"], ["https://example.com/missing"])

    def test_report_verifier_passes_supported_citations(self):
        items = [
            {
                "item_index": 1,
                "kind": "paragraph",
                "start_line": 2,
                "text": "Research evidence indicates citation quality increases trust.",
                "urls": ["https://example.com/study"],
            }
        ]
        verifications = [
            {
                "item_index": 1,
                "verdict": "supported",
                "supported_urls": ["https://example.com/study"],
                "reason": "source text supports the report item",
            }
        ]
        verified_findings = [
            {
                "url": "https://example.com/study",
                "evidence_text": "Research evidence indicates citation quality increases trust.",
            }
        ]

        records, summary = build_records(items, verifications, verified_findings=verified_findings)

        self.assertTrue(summary["passes"])
        self.assertEqual(summary["support_rate"], 1.0)
        self.assertEqual(records[0]["verdict"], "supported")

    def test_evaluator_fails_when_report_verifier_fails(self):
        evaluation = evaluate_grounding(
            "## Direct Answer\nA [source](https://example.com/a).\n\n## Sources\nhttps://example.com/a",
            [{"claim": "A", "support_urls": ["https://example.com/a"]}],
        )

        updated = apply_report_verification(
            evaluation,
            {
                "passes": False,
                "skipped": False,
                "reason": "unsupported final-report citation",
                "total_items": 1,
                "unsupported_count": 1,
                "missing_source_url_count": 0,
                "support_rate": 0.0,
            },
        )

        self.assertFalse(updated["passes_grounding"])
        self.assertFalse(updated["semantic_citation_passes"])
        self.assertLessEqual(updated["grounding_score"], 69.0)

    def test_file_cache_round_trip_and_clear(self):
        with TemporaryDirectory() as tmpdir:
            payload = {"query": "test"}
            self.assertIsNone(get_cached_json("unit", payload, root=tmpdir))

            set_cached_json("unit", payload, {"ok": True}, root=tmpdir)
            self.assertEqual(get_cached_json("unit", payload, root=tmpdir), {"ok": True})
            self.assertEqual(clear_cache("unit", root=tmpdir), 1)
            self.assertIsNone(get_cached_json("unit", payload, root=tmpdir))

    def test_searcher_uses_cached_search_results(self):
        state = {
            "goal": "test goal",
            "brief": {"freshness_required": False, "research_type": "general_explainer"},
            "plan": [{"query": "cache query", "purpose": "overview", "priority": 1}],
            "searches_done": [],
            "findings": [],
        }
        client = CountingSearchClient()

        with TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"FACTCRAFTER_CACHE_DIR": tmpdir}):
                with patch("team.searcher.get_search_client", return_value=client):
                    first = searcher_agent(state)
                    second = searcher_agent({**state, "searches_done": [], "findings": []})

        self.assertEqual(client.calls, 1)
        self.assertEqual(first["findings"][0]["search_cache_status"], "miss")
        self.assertEqual(second["findings"][0]["search_cache_status"], "hit")

    def test_human_review_detects_high_stakes_topics(self):
        high_stakes, reasons = is_high_stakes(
            "What changed in U.S. EV tax credit eligibility?",
            {"research_type": "policy_legal", "must_cover": []},
        )

        self.assertTrue(high_stakes)
        self.assertTrue(any("policy_legal" in reason for reason in reasons))

    def test_human_review_auto_mode_blocks_high_stakes_without_interactive_reviewer(self):
        state = {
            "goal": "What changed in U.S. EV tax credit eligibility?",
            "brief": {"research_type": "policy_legal", "must_cover": []},
            "claims": [
                {
                    "claim": "Buyers should verify eligibility before purchase.",
                    "support_urls": ["https://example.com"],
                    "confidence": "high",
                }
            ],
            "rejected_claims": [],
        }

        with patch.dict("os.environ", {"HITL_REVIEW_MODE": "auto"}):
            with patch("team.humanreview.is_interactive", return_value=False):
                result = human_review_agent(state)

        self.assertFalse(result["human_review"]["approved"])
        self.assertEqual(result["human_review"]["mode"], "auto")
        self.assertEqual(result["claims"], [])

    def test_human_review_required_mode_blocks_without_interactive_reviewer(self):
        state = {
            "goal": "What changed in U.S. EV tax credit eligibility?",
            "brief": {"research_type": "policy_legal", "must_cover": []},
            "claims": [
                {
                    "claim": "Buyers should verify eligibility before purchase.",
                    "support_urls": ["https://example.com"],
                    "confidence": "high",
                }
            ],
            "rejected_claims": [],
        }

        with patch.dict("os.environ", {"HITL_REVIEW_MODE": "required"}):
            with patch("team.humanreview.is_interactive", return_value=False):
                result = human_review_agent(state)

        self.assertFalse(result["human_review"]["approved"])
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["rejected_claims"][0]["verdict"], "blocked_for_human_review")

    def test_human_review_rejection_clears_claims(self):
        state = {
            "goal": "What changed in U.S. EV tax credit eligibility?",
            "brief": {"research_type": "policy_legal", "must_cover": []},
            "claims": [
                {
                    "claim": "Buyers should verify eligibility before purchase.",
                    "support_urls": ["https://example.com"],
                    "confidence": "high",
                }
            ],
            "rejected_claims": [],
        }

        with patch.dict("os.environ", {"HITL_REVIEW_MODE": "auto"}):
            with patch("team.humanreview.is_interactive", return_value=True):
                with patch("builtins.input", return_value="n"):
                    result = human_review_agent(state)

        self.assertFalse(result["human_review"]["approved"])
        self.assertEqual(result["human_review"]["reviewer"], "human_cli")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["rejected_claims"][0]["reason"], "Interactive human reviewer rejected the claims before writing.")

    def test_writer_does_not_fallback_when_human_review_blocks(self):
        result = writer_agent(
            {
                "goal": "What changed in U.S. EV tax credit eligibility?",
                "brief": {"research_type": "policy_legal"},
                "claims": [],
                "verified_findings": [{"snippet": "Do not turn this raw evidence into a report."}],
                "human_review": {
                    "required": True,
                    "approved": False,
                    "decision": "blocked: no interactive reviewer available",
                    "reasons": ["research_type=policy_legal"],
                },
            }
        )

        self.assertIn("Report Blocked", result["report"])
        self.assertNotIn("Do not turn this raw evidence", result["report"])

    def test_run_research_returns_human_review_block_before_grounding_failure(self):
        blocked_report = "## Report Blocked: Human Review Required\n\nReview needed."
        graph_result = {
            "report": blocked_report,
            "human_review": {
                "required": True,
                "approved": False,
                "decision": "blocked: no interactive reviewer available",
            },
            "evaluation": {"passes_grounding": False, "grounding_score": 0},
        }

        with patch("team.main.input_guardrail", return_value=(True, "passed")):
            with patch("team.main.research_team.invoke", return_value=graph_result):
                with patch("team.main.should_save_artifacts", return_value=False):
                    report = run_research("What changed in U.S. EV tax credit eligibility?")

        self.assertEqual(report, blocked_report)


if __name__ == "__main__":
    unittest.main()
