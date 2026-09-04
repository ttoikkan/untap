"""Offline regressions for v89 production hints and HD label previews."""
import unittest

import untap_matcher
import untap_report


THUMB = "https://assets.untappd.com/site/beer_logos/beer-1_sm.jpeg"
HD = "https://assets.untappd.com/site/beer_logos_hd/beer-1.jpeg"


class ProductionMetadataTests(unittest.TestCase):
    def test_algolia_metadata_reaches_confirmed_and_alternative_records(self):
        candidate = untap_matcher._algolia_hit_to_candidate({
            "beer_name": "Beer", "brewery_name": "Brewery", "beer_abv": 6.5,
            "beer_slug": "beer", "bid": 1, "beer_label": THUMB,
            "beer_label_hd": HD, "in_production": 0,
            "rating_score": 4.0, "rating_count": 10,
        })
        candidate["score"] = 1.0
        self.assertEqual(candidate["image_hd_url"], HD)
        self.assertEqual(candidate["in_production"], 0)
        alternative = untap_matcher._alternative_from_candidate(candidate)
        self.assertEqual(alternative["image_hd_url"], HD)
        self.assertEqual(alternative["in_production"], 0)
        confirmed = untap_matcher._confirmed_info_from_algolia(candidate, "Brewery")
        self.assertEqual(confirmed["image_hd_url"], HD)
        self.assertEqual(confirmed["in_production"], 0)

    def test_only_explicit_false_values_show_production_warning(self):
        for value in (False, 0, 0.0, "0", "false", " FALSE "):
            with self.subTest(value=value):
                self.assertIn("Listed as out of production", untap_report._production_warning(value))
        for value in (None, "", True, 1, 1.0, "1", "true", "unknown", [], {}):
            with self.subTest(value=value):
                self.assertEqual(untap_report._production_warning(value), "")

    def test_warning_is_visible_only_for_ambiguous_candidates(self):
        confirmed = {"status": "ok", "beer": "Old Beer", "brewery": "Brewery",
                     "rating": 4, "ratings": 10, "abv": 6, "in_production": False}
        ambiguous = {"status": "ambiguous", "query": "Maybe", "reason": "Close",
                     "alternatives": [{"name": "Old Candidate", "score": .9,
                                       "in_production": 0}]}
        html = untap_report.render_html_report([confirmed, ambiguous])
        self.assertEqual(html.count("Listed as out of production on Untappd"), 1)
        confirmed_html = untap_report.render_html_report([confirmed])
        self.assertNotIn("Listed as out of production", confirmed_html)


class HdPreviewTests(unittest.TestCase):
    def test_valid_hd_image_turns_thumbnail_into_accessible_button(self):
        result = {"status": "ok", "beer": "Beer", "brewery": "Brewery",
                  "rating": 4, "ratings": 10, "abv": 6, "image_url": THUMB,
                  "image_hd_url": HD}
        html = untap_report.render_html_report([result])
        self.assertIn(f'data-label-preview="{HD}"', html)
        self.assertIn('aria-label="View larger Beer label"', html)
        self.assertIn('<dialog class="label-dialog"', html)
        self.assertIn("dialog.showModal()", html)
        self.assertIn("if (opener) opener.focus()", html)

    def test_missing_or_untrusted_hd_url_leaves_plain_thumbnail(self):
        for hd in (None, "http://assets.untappd.com/hd.jpeg",
                   "https://assets.untappd.com.evil.test/hd.jpeg"):
            with self.subTest(hd=hd):
                result = {"status": "ok", "beer": "Beer", "brewery": "Brewery",
                          "rating": 4, "ratings": 10, "abv": 6,
                          "image_url": THUMB, "image_hd_url": hd}
                html = untap_report.render_html_report([result])
                self.assertIn(f'src="{THUMB}"', html)
                self.assertNotIn('data-label-preview=', html)

    def test_hd_url_and_name_are_attribute_escaped(self):
        result = {"status": "ok", "beer": 'A &quot; Beer', "brewery": "Brewery",
                  "rating": 4, "ratings": 10, "abv": 6, "image_url": THUMB,
                  "image_hd_url": HD + "?x=1&y=2"}
        html = untap_report.render_html_report([result])
        self.assertIn("?x=1&amp;y=2", html)
        self.assertNotIn("?x=1&y=2", html)


if __name__ == "__main__":
    unittest.main()
