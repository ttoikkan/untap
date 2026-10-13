"""Scenario guard: brewery conflicts that surface only from the beer-only fallback.

Menu: Badlands / Fazy / 6.5%.  Only the final (beer-name-only) fallback returns
candidates, so every outcome here is decided after _recover_search_discovery().
Characterizes how the fallback-loop filter and decide_candidates() interact.
"""
from contextlib import ExitStack, redirect_stdout
import io
import unittest
from unittest.mock import patch

import untap.matcher as matcher
def candidate(name, brewery, score, url):
    return {"name": name, "brewery": brewery, "abv": 6.5, "score": score, "url": url,
            "text": f"{brewery} {name} 6.5% ABV", "rating_score": 4.2, "rating_count": 50,
            "type_name": "IPA", "bid": 1, "ibu": None}


def wrong(score):
    return candidate("Fazy", "Elsewhere Brewing", score, "https://untappd.com/b/elsewhere-fazy/9")


def right(score):
    return candidate("Fazy", "Badlands Brewing Company", score, "https://untappd.com/b/badlands-fazy/10")


def run_beer_only_fallback(rows, brewery="Badlands", primary_rows=None, debug=False, transcript=None):
    """Zero-hit primary search; the beer-only fallback returns `rows`."""
    primary_rows = primary_rows or []
    rows = sorted(rows, key=lambda row: -row["score"])
    callbacks = {
        "_run_page0_search_transport": lambda *a, **k: dict(request_event=None, events=[], error=None),
        "evaluate_and_expand_candidates": lambda *a, **k: dict(
            candidates=primary_rows, ambiguity_reason=None, release_qualifier_trigger=False,
            needs_expansion=False, expanded_candidates=[], expansion_diagnostics=None,
            abv_sorted_diagnostics=None, rate_limited=False),
        "run_search_fallback_attempt": lambda *a, **k: dict(
            candidates=rows, weak_match=rows[0]["score"] < matcher.DEFAULT_MIN_SCORE,
            ambiguity_reason=matcher.detect_candidate_ambiguity(rows, expected_beer="Fazy", expected_abv=6.5),
            initial_algolia_page=None, expanded_candidates=[], expansion_diagnostics=None,
            rate_limited=False),
        "build_search_fallback_queries": lambda *a, **k: ["Fazy"],   # beer-only query is last
    }
    constants = {"_matching_algolia_response_status": 200, "_matching_algolia_nb_hits": len(primary_rows),
                 "_matching_algolia_initial_page": None, "_algolia_page0_candidates": primary_rows}
    with ExitStack() as stack, redirect_stdout(transcript if transcript is not None else io.StringIO()):
        for name, callback in callbacks.items():
            stack.enter_context(patch.object(matcher, name, side_effect=callback))
        for name, value in constants.items():
            stack.enter_context(patch.object(matcher, name, return_value=value))
        return matcher._search_one_impl(object(), "Badlands Fazy", expected_beer="Fazy",
                                        expected_brewery=brewery, expected_abv=6.5, debug=debug)


class BeerOnlyFallbackBreweryTests(unittest.TestCase):
    def test_only_conflicting_brewery_is_reported_with_inspection_evidence(self):
        """S1 - the case that fails on v110: result says 'No matching beer found' and drops the link."""
        result = run_beer_only_fallback([wrong(.90)])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["reason"].startswith("Brewery conflict"), result["reason"])
        links = result.get("excluded_candidates") or []
        self.assertEqual([item["url"] for item in links], ["https://untappd.com/b/elsewhere-fazy/9"])
        self.assertIn("Badlands", links[0]["exclusion_reason"])
        self.assertFalse(result.get("alternatives"))          # never selectable

    def test_matching_brewery_wins_over_a_higher_scored_conflicting_one(self):
        for wrong_score, right_score in ((.95, .80), (.90, .30)):        # S2, S3
            with self.subTest(wrong=wrong_score, right=right_score):
                result = run_beer_only_fallback([wrong(wrong_score), right(right_score)])
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["url"], "https://untappd.com/b/badlands-fazy/10")

    def test_conflicting_same_name_candidate_does_not_create_ambiguity(self):
        result = run_beer_only_fallback([wrong(.80), right(.79)])         # S4
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"], "https://untappd.com/b/badlands-fazy/10")

    def test_menu_without_brewery_is_not_filtered(self):
        result = run_beer_only_fallback([wrong(.90)], brewery=None)       # S5
        self.assertEqual(result["status"], "ok")

    def test_conflicting_fallback_does_not_replace_weak_correct_primary(self):
        result = run_beer_only_fallback([wrong(.90)], primary_rows=[right(.20)])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['url'], 'https://untappd.com/b/badlands-fazy/10')
        self.assertEqual(result['score'], .20)
        self.assertIsNone(result.get('search_fallback'))

    def test_brewery_filter_debug_diagnostic_is_preserved(self):
        output = io.StringIO()
        result = run_beer_only_fallback([wrong(.9)], debug=True, transcript=output)
        self.assertIn('brewery contradiction filter: 1 unrelated candidate(s) rejected', output.getvalue())
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result.get('excluded_candidates'))

    def test_matching_brewery_alone_is_accepted(self):
        result = run_beer_only_fallback([right(.80)])                     # S6
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result.get("excluded_candidates"))


if __name__ == "__main__":
    unittest.main()
