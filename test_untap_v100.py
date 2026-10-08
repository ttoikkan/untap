"""Guarded explicit series-number acceptance."""
import copy
import unittest

import untap_matcher as matcher
import test_untap_v86 as fixtures


class NumberedNameTests(unittest.TestCase):
    def rows(self):
        return [fixtures.candidate(f"Banishing {n}", "Third Moon Brewing Company", 7.,
                    1. if n == 3 else .972, 6801235 if n == 3 else n)
                for n in (3, 2, 1, 4, 5)]

    def test_banishing_three_confirmed_without_score_changes(self):
        rows = self.rows()
        before = copy.deepcopy(rows)
        result, _ = fixtures.MatcherV86Tests().run_search(rows, "Banishing 3", "Third Moon", 7.)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"], rows[0]["url"])
        self.assertEqual(result["score"], 1.)
        self.assertEqual(rows, before)

    def test_unnumbered_and_incomplete_searches_remain_ambiguous(self):
        for beer, diagnostics in [("Banishing", None), ("Banishing 3", {"capped": True}),
                                  ("Banishing 3", {"errors": ["offline"]})]:
            result, _ = fixtures.MatcherV86Tests().run_search(self.rows(), beer, "Third Moon", 7., diagnostics=diagnostics)
            self.assertEqual(result["status"], "ambiguous")

    def test_rule_rejects_insufficient_or_contradictory_evidence(self):
        for changes in [{"name": "Banishing 3"}, {"name": "Banishing 3 Peach"},
                        {"name": "Other 2"}, {"name": "Banishing 2026"},
                        {"abv": None}, {"abv": 7.2}, {"abv": float("nan")},
                        {"brewery": "Other Brewery"}]:
            rows = self.rows()
            rows[1].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(matcher.exact_numbered_candidate(rows, "Banishing 3", "Third Moon", 7.))
        for beer, brewery, abv in [("Banishing", "Third Moon", 7.), ("Banishing 6", "Third Moon", 7.),
                                   ("Banishing 3", "", 7.), ("Banishing 3", "Third Moon", None)]:
            self.assertIsNone(matcher.exact_numbered_candidate(self.rows(), beer, brewery, abv))
        rows = self.rows()
        rows[0]["score"] = .1
        self.assertIsNone(matcher.exact_numbered_candidate(rows, "Banishing 3", "Third Moon", 7.))

    def test_years_are_not_series_numbers(self):
        rows = [fixtures.candidate(f"Beer {year}", "Brewery", 7.) for year in (2026, 2025)]
        self.assertIsNone(matcher.exact_numbered_candidate(rows, "Beer 2026", "Brewery", 7.))
