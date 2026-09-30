"""Offline October menu regressions; no live Untappd requests."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import untap_matcher as matcher
import test_untap_v86 as fixtures
from test_untap_v86 import candidate


class MatcherV99Tests(unittest.TestCase):
    def test_ddh_scores_like_expanded_name_without_erasing_hop_qualifiers(self):
        names = ["Double Dry Hopped Fort Point", "Mosaic Dry Hopped Fort Point",
                 "Citra Double Dry Hopped Fort Point", "Mosaic Double Dry Hopped Fort Point",
                 "Galaxy Double Dry Hopped Fort Point"]
        rows = []
        for i, name in enumerate(names):
            row = candidate(name, "Trillium Brewing Company", 6.6, bid=415360 + i)
            row["score"] = matcher.score_candidate("Trillium DDH Fort Point", name, row["text"],
                expected_beer="DDH Fort Point", expected_brewery="Trillium", expected_abv=6.6)
            rows.append(row)
        self.assertAlmostEqual(rows[0]["score"], 1.0)
        self.assertGreater(rows[0]["score"] - max(r["score"] for r in rows[1:]), matcher.AMBIGUITY_SCORE_MARGIN)
        self.assertIsNone(matcher.detect_candidate_ambiguity(rows, "DDH Fort Point", 6.6))
        self.assertEqual(matcher.same_abv_family_variants(rows, "DDH Fort Point", 6.6), [])
        self.assertEqual(matcher.expand_beer_abbreviations("Oddhill DDH ddh"),
                         "Oddhill double dry hopped double dry hopped")
        with ExitStack() as stack:
            for name, value in {
                "_run_page0_search_transport": {"request_event": None, "events": []},
                "_matching_algolia_response_status": 200,
                "_matching_algolia_nb_hits": 5,
                "_matching_algolia_initial_page": {"hits": []},
                "_algolia_page0_candidates": rows,
            }.items():
                stack.enter_context(patch.object(matcher, name, return_value=value))
            result = matcher.search_one(None, "Trillium DDH Fort Point",
                expected_beer="DDH Fort Point", expected_brewery="Trillium", expected_abv=6.6)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"], rows[0]["url"])

    def test_ddh_keeps_vintage_safeguard(self):
        rows = [candidate("Double Dry Hopped Fort Point", "Trillium", 6.6),
                candidate("Double Dry Hopped Fort Point (2026)", "Trillium", 6.6, .8, 2)]
        self.assertTrue(matcher.candidate_adds_release_qualifier("DDH Fort Point", rows[1]["name"]))
        self.assertIsNotNone(matcher.detect_candidate_ambiguity(rows, "DDH Fort Point", 6.6))

    def test_messorem_recoveries_are_review_only(self):
        for beer, name, abv, bid in [
            ("A7Y7 X Bas Canada X Yakima Chief - XTRM Turbo", "A7Y7 X Bas Canada X Yakima Chief Hops", 7., 6807896),
            ("A7Y7 X Fidens - XTRM Turbo", "A7Y7 X Fidens X Freestyle Hops", 7.5, 6807894),
        ]:
            with self.subTest(beer=beer):
                row = candidate(name, "Messorem", abv, 1., bid)
                query = matcher.trailing_relaxation_search_queries(beer, "Messorem")[-1]
                def fallback(page, text, **kwargs):
                    rows = [row] if text == query else []
                    return dict(candidates=rows, weak_match=not rows, ambiguity_reason=None)
                result, _ = fixtures.MatcherV86Tests().run_search([], beer, "Messorem", abv, hits=0, fallback=fallback)
                self.assertEqual(result["status"], "ambiguous")
                self.assertEqual(result["alternatives"][0]["url"], row["url"])
                self.assertIn("manual confirmation required", result["reason"])

    def test_review_recovery_guards(self):
        beer = "A7Y7 X Fidens - XTRM Turbo"
        row = candidate("A7Y7 X Fidens X Freestyle Hops", "Messorem", 7.5)
        self.assertTrue(matcher.candidate_needs_trailing_review(row, beer, "Messorem", 7.5))
        for changes in [{"brewery": "Other Brewery"}, {"abv": None}, {"abv": 6.5},
                        {"name": "A7Y7 X Fidens 2026"}, {"name": "Unrelated IPA"}]:
            self.assertFalse(matcher.candidate_needs_trailing_review(dict(row, **changes), beer, "Messorem", 7.5))
        self.assertFalse(matcher.candidate_needs_trailing_review(row, beer, "Messorem", None))
        self.assertFalse(matcher.candidate_needs_trailing_review(row, "A7Y7 X Fidens", "Messorem", 7.5))

    def test_vintage_and_inserted_ingredient_remain_manual(self):
        for beer, brewery, abv, other, ids in [
            ("Boston Lager", "Samuel Adams", 5., "Boston Lager (1985–2022)", (4167619, 2)),
            ("Schmoojee Peach Pear Dragonfruit", "Imprint Beer Co.", 6.5,
             "Schmoojee Peach Pear Apricot Dragonfruit", (6790150, 3)),
        ]:
            rows = [candidate(beer, brewery, abv, 1., ids[0]), candidate(other, brewery, abv, .965, ids[1])]
            result, _ = fixtures.MatcherV86Tests().run_search(rows, beer, brewery, abv)
            self.assertEqual(result["status"], "ambiguous")

    def test_humble_sea_abv_conflict_remains_failed(self):
        rows = [candidate("A7Y7 X Humble Sea", "Messorem", 7.5, bid=6811010)]
        result, _ = fixtures.MatcherV86Tests().run_search(rows, "A7Y7 X Humble Sea", "Messorem", 6.5,
            fallback=lambda *a, **k: {"candidates": [], "weak_match": True})
        self.assertEqual(result["status"], "failed")
        self.assertIn("ABV conflict", result["reason"])
