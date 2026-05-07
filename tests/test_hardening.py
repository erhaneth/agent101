import unittest
from unittest.mock import patch

from team.guardrails import input_guardrail
from team.searcher import (
    classify_source_type,
    search_days_for_brief,
    searcher_agent,
    should_skip_source,
)
from team.factchecker import source_passes_static_checks


class FailingSearchClient:
    def search(self, **kwargs):
        raise RuntimeError("search unavailable")


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
        with patch("team.guardrails.get_guard_llm", side_effect=RuntimeError("model unavailable")):
            is_safe, reason = input_guardrail("Compare electric cars under $40k right now.")

        self.assertTrue(is_safe)
        self.assertEqual(reason, "passed rules-only guardrail")


if __name__ == "__main__":
    unittest.main()
