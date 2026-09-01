import io
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock
from unittest.mock import patch

import untap_matcher

from untap_matcher import (
    candidate_has_brewery_overlap,
    candidate_matches_trailing_relaxed_identity,
    strip_redundant_terminal_style_for_search,
    trailing_beer_relaxations_for_search,
    trailing_relaxation_search_queries,
    get_matcher_timing_stats,
    reset_matcher_timing_stats,
    run_search_fallback_attempt,
    search_one,
)


class MatcherContractTests(unittest.TestCase):
    def test_style_suffix_relaxation_is_exact_and_search_only(self):
        self.assertEqual(
            strip_redundant_terminal_style_for_search("Élixir-IPA", "IPA"),
            "Élixir",
        )
        self.assertIsNone(
            strip_redundant_terminal_style_for_search("Foo IPA", "West Coast IPA")
        )

    def test_trailing_relaxation_is_bounded(self):
        self.assertEqual(
            trailing_beer_relaxations_for_search("Demoliri #0031 - XTRM Turbo"),
            ["Demoliri #0031 XTRM", "Demoliri #0031"],
        )

    def test_trailing_relaxation_queries_keep_brewery_identity(self):
        self.assertEqual(
            trailing_relaxation_search_queries(
                "Vue Du Bureau XTRM Turbo",
                "Messorem x Foam",
            ),
            [
                "Messorem Foam Vue Du Bureau XTRM",
                "Messorem Foam Vue Du Bureau",
            ],
        )

    def test_ambiguity_projection_preserves_canonical_type_name(self):
        candidate = {
            "name": "Variant",
            "score": 0.98,
            "type_name": "Lager - Helles",
            "url": "https://untappd.com/b/example/1",
        }
        alternative = untap_matcher._alternative_from_candidate(candidate)
        self.assertEqual(alternative["type_name"], "Lager - Helles")

    def test_relaxed_candidate_must_be_base_identity(self):
        self.assertTrue(
            candidate_matches_trailing_relaxed_identity(
                {"name": "Vue Du Bureau"},
                "Vue Du Bureau XTRM Turbo",
            )
        )
        self.assertFalse(
            candidate_matches_trailing_relaxed_identity(
                {"name": "Bureau Vue"},
                "Vue Du Bureau XTRM Turbo",
            )
        )


    def test_matcher_timing_is_opt_in_and_reports_residual(self):
        reset_matcher_timing_stats()
        fake_result = {"query": "Test Beer", "status": "failed", "reason": "test"}
        output = io.StringIO()
        with (
            patch("untap_matcher.debug_timing_enabled", return_value=True),
            patch("untap_matcher._search_one_impl", return_value=fake_result),
            patch("untap_matcher.perf_counter", side_effect=[10.0, 10.5]),
            redirect_stdout(output),
        ):
            result = search_one(None, "Test Beer")

        self.assertEqual(result, fake_result)
        stats = get_matcher_timing_stats()
        self.assertEqual(stats["count"], 1)
        self.assertAlmostEqual(stats["total_seconds"], 0.5)
        self.assertAlmostEqual(stats["residual_total_seconds"], 0.5)
        self.assertIn("matcher residual / unaccounted: 0.500s", output.getvalue())
        self.assertIn("matcher total: 0.500s", output.getvalue())

    def test_matcher_phase_timer_does_not_change_return_value(self):
        output = io.StringIO()
        with (
            patch("untap_matcher.debug_timing_enabled", return_value=True),
            patch("untap_matcher.perf_counter", side_effect=[20.0, 20.25]),
            redirect_stdout(output),
        ):
            from untap_matcher import _timed_matcher_call
            value = _timed_matcher_call("candidate phase", "Test Beer", lambda: 42)

        self.assertEqual(value, 42)
        self.assertIn("candidate phase: 0.250s | Test Beer", output.getvalue())


    def test_fallback_timing_uses_fallback_query_without_name_error(self):
        output = io.StringIO()
        with (
            patch("untap_matcher.debug_timing_enabled", return_value=True),
            patch("untap_matcher.open_search_box", return_value=None),
            patch("untap_matcher.perf_counter", side_effect=[1.0, 1.25]),
            redirect_stdout(output),
        ):
            result = run_search_fallback_attempt(None, "Fallback Beer", 0.5)

        self.assertIn("Search box not found", result["error"])
        self.assertIn(
            "search page -> search box ready: 0.250s | Fallback Beer",
            output.getvalue(),
        )

    def test_primary_matcher_times_search_page_readiness(self):
        source = Path("untap_matcher.py").read_text(encoding="utf-8")
        self.assertIn('"search page -> search box ready"', source)
        self.assertIn('lambda: open_search_box(page)', source)
        self.assertIn('"direct Algolia search operation"', source)

    def test_unrelated_brewery_is_a_contradiction(self):
        self.assertTrue(
            candidate_has_brewery_overlap(
                {"brewery": "Brasserie du Bas-Canada"},
                "Brasserie du Bas-Canada x Herman",
            )
        )
        self.assertFalse(
            candidate_has_brewery_overlap(
                {"brewery": "Braumanufaktur Vest"},
                "Brasserie du Bas-Canada x Herman",
            )
        )


if __name__ == "__main__":
    unittest.main()

class AlgoliaCandidateAuthorityTests(unittest.TestCase):
    def test_algolia_page0_candidates_preserve_native_abv_precision(self):
        from untap_matcher import _algolia_page0_candidates

        page0 = {
            "hits": [{
                "beer_name": "Sacrilegio",
                "brewery_name": "Brujos Brewing",
                "beer_abv": 6.66,
                "bid": 6781625,
                "beer_slug": "brujos-brewing-sacrilegio",
            }]
        }
        candidates = _algolia_page0_candidates(
            page0,
            "Brujos Sacrilegio",
            expected_beer="Sacrilegio",
            expected_brewery="Brujos",
            expected_abv=6.6,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["abv"], 6.66)
        self.assertEqual(candidates[0]["brewery"], "Brujos Brewing")

    def test_algolia_page0_candidates_retain_brewery_when_dom_historically_omitted_it(self):
        from untap_matcher import _algolia_page0_candidates

        page0 = {
            "hits": [{
                "beer_name": "Silent Spaces",
                "brewery_name": "Sante Adairius Rustic Ales",
                "beer_abv": 6.3,
                "bid": 4662558,
                "beer_slug": "sante-adairius-rustic-ales-silent-spaces",
            }]
        }
        candidates = _algolia_page0_candidates(
            page0,
            "Sante Adairius Rustic Ales Silent Spaces",
            expected_beer="Silent Spaces",
            expected_brewery="Sante Adairius Rustic Ales",
            expected_abv=6.3,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["brewery"], "Sante Adairius Rustic Ales")

    def test_v68_primary_candidate_discovery_does_not_scrape_dom(self):
        source = Path("untap_matcher.py").read_text(encoding="utf-8")
        self.assertNotIn("discover_search_candidates", source)
        self.assertNotIn('"DOM candidate discovery"', source)
        self.assertIn('"Algolia candidate construction"', source)

    def test_algolia_candidate_filter_keeps_v67_query_word_rule(self):
        from untap_matcher import _algolia_page0_candidates

        page0 = {
            "hits": [
                {
                    "beer_name": "Fazy (2026)",
                    "brewery_name": "Badlands Brewing Company",
                    "beer_abv": 6.5,
                    "bid": 6736235,
                    "beer_slug": "badlands-brewing-company-fazy-2026",
                },
                {
                    "beer_name": "Unrelated Beer",
                    "brewery_name": "Elsewhere",
                    "beer_abv": 6.5,
                    "bid": 1,
                    "beer_slug": "elsewhere-unrelated-beer",
                },
            ]
        }
        candidates = _algolia_page0_candidates(
            page0,
            "Badlands Fazy (2026)",
            expected_beer="Fazy (2026)",
            expected_brewery="Badlands",
            expected_abv=6.5,
        )
        self.assertEqual([item["name"] for item in candidates], ["Fazy (2026)"])



class SearchTransportSelfHealingTests(unittest.TestCase):
    def test_non_429_direct_error_invalidates_and_recovers_once_through_ui(self):
        direct_request = {"kind": "request", "url": "https://example", "algolia_requests": []}
        direct_response = {"kind": "response", "status": 500, "url": "https://example", "algolia_requests": [], "algolia_response": []}
        recovered = {
            "request_event": {"kind": "request", "url": "https://fresh", "algolia_requests": []},
            "events": [{"kind": "response", "status": 200}],
            "error": None,
            "transport": "ui-recovery",
        }
        with mock.patch.object(untap_matcher, "search_transport_template_available", return_value=True), \
             mock.patch.object(untap_matcher, "fetch_authoritative_algolia_search", return_value=(direct_request, direct_response, "HTTP 500")), \
             mock.patch.object(untap_matcher, "invalidate_search_transport_template") as invalidate, \
             mock.patch.object(untap_matcher, "_run_ui_page0_search_transport", return_value=recovered) as ui_recovery, \
             mock.patch.object(untap_matcher, "note_search_transport_recovery") as note:
            result = untap_matcher._run_page0_search_transport(object(), "Beer")
        invalidate.assert_called_once_with()
        ui_recovery.assert_called_once_with(
            mock.ANY, "Beer", include_search_urls=False, recovery=True
        )
        note.assert_called_once_with(True)
        self.assertIs(result, recovered)

    def test_http_429_never_invalidates_or_recovers_through_ui(self):
        direct_request = {"kind": "request", "url": "https://example", "algolia_requests": []}
        direct_response = {"kind": "response", "status": 429, "url": "https://example", "algolia_requests": [], "algolia_response": []}
        with mock.patch.object(untap_matcher, "search_transport_template_available", return_value=True), \
             mock.patch.object(untap_matcher, "fetch_authoritative_algolia_search", return_value=(direct_request, direct_response, "HTTP 429")), \
             mock.patch.object(untap_matcher, "invalidate_search_transport_template") as invalidate, \
             mock.patch.object(untap_matcher, "_run_ui_page0_search_transport") as ui_recovery:
            result = untap_matcher._run_page0_search_transport(object(), "Beer")
        invalidate.assert_not_called()
        ui_recovery.assert_not_called()
        self.assertEqual(result["error"], "HTTP 429")
        self.assertEqual(result["transport"], "browser-fetch")

    def test_failed_ui_recovery_is_bounded_to_one_attempt(self):
        direct_response = {"kind": "response", "status": 500, "url": "https://example", "algolia_requests": [], "algolia_response": []}
        failed = {
            "request_event": None,
            "events": [],
            "error": "Search box not found",
            "transport": "ui-recovery",
        }
        with mock.patch.object(untap_matcher, "search_transport_template_available", return_value=True), \
             mock.patch.object(untap_matcher, "fetch_authoritative_algolia_search", return_value=(None, direct_response, "HTTP 500")), \
             mock.patch.object(untap_matcher, "invalidate_search_transport_template"), \
             mock.patch.object(untap_matcher, "_run_ui_page0_search_transport", return_value=failed) as ui_recovery, \
             mock.patch.object(untap_matcher, "note_search_transport_recovery") as note:
            result = untap_matcher._run_page0_search_transport(object(), "Beer")
        self.assertEqual(ui_recovery.call_count, 1)
        note.assert_called_once_with(False)
        self.assertEqual(result["error"], "Search box not found")

if __name__ == "__main__":
    unittest.main()


class DetailAlgoliaParityTests(unittest.TestCase):
    def test_detail_algolia_comparison_matches_independent_fields(self):
        from untap_matcher import _detail_algolia_field_comparison

        comparison = _detail_algolia_field_comparison(
            {"beer": "Sacrilegio", "rating": 4.17, "ratings": 409, "abv": "6.66%"},
            {"name": "Sacrilegio", "rating_score": 4.17, "rating_count": 409, "abv": 6.66},
        )
        self.assertTrue(all(item["equal"] for item in comparison.values()))

    def test_detail_algolia_comparison_reports_rating_and_count_differences(self):
        from untap_matcher import _detail_algolia_field_comparison

        comparison = _detail_algolia_field_comparison(
            {"beer": "Beer", "rating": 4.2, "ratings": 101, "abv": "6.5%"},
            {"name": "Beer", "rating_score": 4.19, "rating_count": 100, "abv": 6.5},
        )
        self.assertEqual(comparison["rating"]["state"], "mismatch")
        self.assertEqual(comparison["ratings"]["state"], "mismatch")
        self.assertEqual(comparison["abv"]["state"], "equal")

    def test_v70_complete_algolia_candidate_builds_confirmed_result(self):
        from untap_matcher import _confirmed_info_from_algolia
        info = _confirmed_info_from_algolia({
            "name": "Sacrilegio", "rating_score": 4.17, "rating_count": 409,
            "abv": 6.66, "url": "https://untappd.com/b/x/1", "ibu": 45,
        }, "Brujos Brewing")
        self.assertEqual(info["beer"], "Sacrilegio")
        self.assertEqual(info["rating"], 4.17)
        self.assertEqual(info["ratings"], 409)
        self.assertEqual(info["abv"], "6.66%")
        self.assertEqual(info["ibu"], "45")

    def test_v70_incomplete_algolia_candidate_requires_detail_fallback(self):
        from untap_matcher import _confirmed_info_from_algolia
        candidate = {"name": "Beer", "rating_score": None, "rating_count": 10, "abv": 5.0, "url": "https://untappd.com/b/x/1"}
        self.assertIsNone(_confirmed_info_from_algolia(candidate, "Brewery"))

    def test_v70_detail_navigation_is_only_fallback_after_algolia_fast_path(self):
        source = Path("untap_matcher.py").read_text(encoding="utf-8")
        fast_pos = source.index("info = _confirmed_info_from_algolia(best, brewery)")
        fallback_pos = source.index('"detail-page operation total"', fast_pos)
        self.assertLess(fast_pos, fallback_pos)
        self.assertIn("if info is None:", source[fast_pos:fallback_pos])


class SearchTransportAuthorityWiringTests(unittest.TestCase):
    def test_v72_direct_transport_is_isolated_before_matching(self):
        source = Path("untap_matcher.py").read_text(encoding="utf-8")
        self.assertIn("shadow_compare_search_transport", source)
        self.assertIn("primary_algolia_page", source)
        self.assertIn("initial_algolia_page", source)
