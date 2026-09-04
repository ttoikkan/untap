"""Offline regressions for complete production-status presentation."""
import unittest

import untap_report


class ProductionStatusTests(unittest.TestCase):
    def test_explicit_true_forms_show_in_production(self):
        for value in (True, 1, 1.0, "1", "true", " TRUE "):
            with self.subTest(value=value):
                html = untap_report._production_status(value)
                self.assertIn("Listed as in production on Untappd", html)

    def test_unknown_status_reserves_an_unannounced_row(self):
        html = untap_report._production_status(None)
        self.assertIn('class="production-status production-status-empty"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertNotIn("Listed as", html)

    def test_all_confirmed_and_candidate_cards_have_equal_height_status_rows(self):
        results = [
            {"status": "ok", "beer": "Current", "brewery": "Brewery",
             "rating": 4, "ratings": 1, "abv": 5, "in_production": True},
            {"status": "ok", "beer": "Unknown", "brewery": "Brewery",
             "rating": 3, "ratings": 1, "abv": 5},
            {"status": "ambiguous", "query": "Maybe", "reason": "Close",
             "alternatives": [
                 {"name": "Retired", "score": .9, "in_production": False},
                 {"name": "Current Candidate", "score": .8, "in_production": 1},
             ]},
        ]
        html = untap_report.render_html_report(results)
        self.assertEqual(html.count('<p class="production-status">'), 3)
        self.assertEqual(html.count("production-status-empty"), 1)
        self.assertIn("Listed as in production on Untappd", html)
        self.assertIn("Listed as out of production on Untappd", html)


if __name__ == "__main__":
    unittest.main()
