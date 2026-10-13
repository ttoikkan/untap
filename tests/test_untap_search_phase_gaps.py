"""Guards for two search-phase behaviors the nine frozen scenarios do not assert."""
from contextlib import ExitStack, redirect_stdout
import io
import unittest
from unittest.mock import patch

import untap_matcher as matcher


def row(name, score, bid):
    return {"name": name, "brewery": "Brewery", "abv": 5.0, "score": score, "bid": bid,
            "url": f"https://untappd.com/b/x/{bid}", "text": f"Brewery {name} 5% ABV"}


class FallbackPagePairingTests(unittest.TestCase):
    def test_winning_fallback_supplies_the_page_used_for_metadata_recovery(self):
        """The final result must pair the winning fallback's candidates with ITS Algolia page."""
        seen = {}
        queries = ["Recovery One", "Recovery Two", "Recovery Three"]
        scores = {"Recovery One": .2, "Recovery Two": .8, "Recovery Three": .9}

        def fallback(page, query, **kwargs):
            return dict(candidates=[row("Beer", scores[query], 2)], weak_match=scores[query] < .425,
                        ambiguity_reason=None, initial_algolia_page={"source": query},
                        expanded_candidates=[])

        def resolve(*args, **kwargs):
            seen["fallback_query"], seen["page"] = args[13], args[15]
            return {"status": "ok"}

        callbacks = {"_run_page0_search_transport": lambda *a, **k: dict(request_event=None, events=[], error=None),
                     "evaluate_and_expand_candidates": lambda *a, **k: dict(
                         candidates=[row("Beer", .1, 1)], ambiguity_reason=None, release_qualifier_trigger=False,
                         needs_expansion=False, expanded_candidates=[], expansion_diagnostics=None,
                         rate_limited=False),
                     "build_search_fallback_queries": lambda *a, **k: queries,
                     "run_search_fallback_attempt": fallback,
                     "_resolve_discovered_candidates": resolve}
        constants = {"_matching_algolia_response_status": 200, "_matching_algolia_nb_hits": 2,
                     "_matching_algolia_initial_page": {"source": "primary"},
                     "_algolia_page0_candidates": [row("Beer", .1, 1)]}
        with ExitStack() as stack, redirect_stdout(io.StringIO()):
            for name, callback in callbacks.items():
                stack.enter_context(patch.object(matcher, name, side_effect=callback))
            for name, value in constants.items():
                stack.enter_context(patch.object(matcher, name, return_value=value))
            matcher._search_one_impl(object(), "Brewery Beer", expected_beer="Beer",
                                     expected_brewery="Brewery", expected_abv=5.0)
        self.assertEqual(seen["fallback_query"], "Recovery Two")        # first non-weak attempt wins
        self.assertEqual(seen["page"], {"source": "Recovery Two"})      # not the primary page


class ZeroHitExpansionGateTests(unittest.TestCase):
    def test_zero_hit_primary_never_requests_expansion_pages(self):
        request = {"url": "https://example.algolia.net/1/indexes/*/queries",
                   "algolia_requests": [{"indexName": "beer", "query": "Brewery Beer", "params": {"query": "Brewery Beer"}}]}
        with patch.object(matcher, "_fetch_algolia_page",
                          side_effect=AssertionError("expansion requested for a zero-hit search")) as fetch, \
             redirect_stdout(io.StringIO()):
            result = matcher.evaluate_and_expand_candidates(
                object(), "Brewery Beer", [], request, matcher.DEFAULT_MIN_SCORE,
                expected_beer="Beer", expected_brewery="Brewery", expected_abv=5.0,
                initial_nb_hits=0, initial_algolia_page=None)
        fetch.assert_not_called()
        self.assertFalse(result["needs_expansion"])


if __name__ == "__main__":
    unittest.main()
