import os
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap
import untap_report


class HtmlReportTests(unittest.TestCase):
    def test_review_groups_use_results_list_spacing_only(self):
        source = Path("untap_report.py").read_text(encoding="utf-8")
        self.assertIn(".review-group {{ padding: 16px; }}", source)
        self.assertNotIn(".review-group {{ padding: 16px; margin-bottom", source)

    def _results(self):
        return [
            {
                "query": "Low Rated",
                "status": "ok",
                "beer": "Low Rated",
                "brewery": "Brewery B",
                "rating": 3.9,
                "ratings": 120,
                "abv": 5.2,
                "type_name": "Pilsner",
                "url": "https://untappd.com/b/brewery-b-low-rated/2",
            },
            {
                "query": "High Rated",
                "status": "ok",
                "beer": "High Rated",
                "brewery": "Brewery A",
                "rating": 4.5,
                "ratings": 99,
                "abv": 8.0,
                "type_name": "IPA - Imperial / Double",
                "url": "https://untappd.com/b/brewery-a-high-rated/1",
            },
            {
                "query": "Ambiguous Beer",
                "status": "ambiguous",
                "reason": "top candidates are too close",
                "alternatives": [
                    {
                        "name": "Wrong Variant",
                        "score": 0.91,
                        "rating": 4.7,
                        "ratings": 10,
                        "abv": 10.0,
                        "brewery": "Brewery C",
                        "type_name": "Stout - Imperial / Double",
                        "url": "https://untappd.com/b/brewery-c-wrong/4",
                    },
                    {
                        "name": "Right Variant",
                        "score": 1.0,
                        "rating": 4.2,
                        "ratings": 40,
                        "abv": 10.0,
                        "brewery": "Brewery C",
                        "type_name": "Stout - Imperial / Double",
                        "url": "https://untappd.com/b/brewery-c-right/3",
                    },
                ],
            },
        ]

    def test_confirmed_beers_are_sorted_by_rating_descending(self):
        html = untap_report.render_html_report(self._results())
        self.assertLess(html.index("High Rated"), html.index("Low Rated"))

    def test_ambiguous_result_is_sorted_by_top_match_rating_not_highest_candidate_rating(self):
        html = untap_report.render_html_report(self._results())
        high = html.index(">High Rated</a>")
        ambiguous = html.index("Ambiguous Beer")
        low = html.index(">Low Rated</a>")
        self.assertLess(high, ambiguous)
        self.assertLess(ambiguous, low)
        self.assertNotIn('id="review-heading"', html)
        self.assertIn('id="results-heading">Results</h2>', html)

    def test_confirmed_beer_names_link_to_canonical_untappd_pages(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn('href="https://untappd.com/b/brewery-a-high-rated/1"', html)
        self.assertIn(">High Rated</a>", html)

    def test_ambiguous_candidates_are_sorted_by_match_score_and_linked(self):
        html = untap_report.render_html_report(self._results())
        review_html = html[html.index("Ambiguous Beer"):]
        self.assertLess(review_html.index("Right Variant"), review_html.index("Wrong Variant"))
        self.assertIn('href="https://untappd.com/b/brewery-c-right/3"', review_html)
        self.assertIn("Match 1.000", review_html)


    def test_custom_report_title_is_visible_and_machine_readable(self):
        html = untap_report.render_html_report(
            self._results(),
            title='September Bottle Share & Friends',
            report_date='2026-09-01',
        )
        self.assertIn('<title>September Bottle Share &amp; Friends</title>', html)
        self.assertIn('<h1>September Bottle Share &amp; Friends</h1>', html)
        self.assertIn(
            'name="untap-report-title" content="September Bottle Share &amp; Friends"',
            html,
        )
        self.assertIn('name="untap-report-date" content="2026-09-01"', html)

    def test_report_metadata_exposes_archive_summary_counts(self):
        html = untap_report.render_html_report(self._results(), report_date='2026-09-01')
        self.assertIn('name="untap-total-beers" content="3"', html)
        self.assertIn('name="untap-confirmed-count" content="2"', html)
        self.assertIn('name="untap-review-count" content="1"', html)

    def test_missing_ambiguity_reason_uses_clear_fallback(self):
        ambiguous = dict(self._results()[2])
        ambiguous.pop("reason")
        html = untap_report.render_html_report([ambiguous])
        self.assertIn("Match is ambiguous", html)
        self.assertNotIn("Review required", html)

    def test_report_is_self_contained_and_mobile_ready(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn('name="viewport"', html)
        self.assertIn("<style>", html)
        self.assertIn("<script>", html)
        self.assertNotIn("stylesheet", html.lower())
        self.assertNotIn("src=", html.lower())

    def test_style_group_uses_untappd_leading_style_component(self):
        self.assertEqual(untap_report._style_group("IPA - New England / Hazy"), "IPA")
        self.assertEqual(untap_report._style_group("Lager - Helles"), "Lager")
        self.assertEqual(untap_report._style_group("Historical Beer - Gruit / Ancient Herbed Ale"), "Historical Beer")
        self.assertEqual(untap_report._style_group("Barleywine"), "Barleywine")
        self.assertIsNone(untap_report._style_group(None))

    def test_style_filters_are_data_derived_present_only_and_alphabetical(self):
        results = [
            {"status": "ok", "beer": "Sour One", "rating": 4.0, "type_name": "Sour - Fruited"},
            {"status": "ok", "beer": "IPA One", "rating": 4.0, "type_name": "IPA - New England / Hazy"},
            {"status": "ok", "beer": "Lager One", "rating": 4.0, "type_name": "Lager - Helles"},
            {"status": "ok", "beer": "IPA Two", "rating": 4.0, "type_name": "IPA - Imperial / Double"},
            {"status": "ok", "beer": "Stout One", "rating": 4.0, "type_name": "Stout - Imperial / Double"},
        ]
        html = untap_report.render_html_report(results)
        filter_start = html.index('<fieldset class="style-filters">')
        filter_end = html.index('</fieldset>', filter_start)
        filters = html[filter_start:filter_end]
        self.assertLess(filters.index("checked><span>IPA</span></label>"), filters.index("checked><span>Lager</span></label>"))
        self.assertLess(filters.index("checked><span>Lager</span></label>"), filters.index("checked><span>Sour</span></label>"))
        self.assertLess(filters.index("checked><span>Sour</span></label>"), filters.index("checked><span>Stout</span></label>"))
        self.assertEqual(filters.count('data-style-filter'), 4)
        self.assertEqual(filters.count(' checked'), 4)
        self.assertNotIn("Pilsner", filters)

    def test_style_filter_groups_are_not_predefined(self):
        results = [
            {
                "status": "ok",
                "beer": "Ancient One",
                "rating": 4.0,
                "type_name": "Historical Beer - Gruit / Ancient Herbed Ale",
            },
            {"status": "ok", "beer": "Wine Beer", "rating": 4.0, "type_name": "Grape Ale - Italian"},
        ]
        html = untap_report.render_html_report(results)
        self.assertIn("checked><span>Grape Ale</span></label>", html)
        self.assertIn("checked><span>Historical Beer</span></label>", html)
        self.assertNotIn("checked><span>Other</span></label>", html)

    def test_style_filters_render_as_accessible_selectable_chips(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn('<div class="style-chips">', html)
        self.assertIn('class="style-chip"', html)
        self.assertIn('type="checkbox"', html)
        self.assertIn('checked><span>IPA</span></label>', html)
        self.assertIn('.style-chip input:checked + span', html)
        self.assertIn('.style-chip:hover span', html)
        self.assertIn('.style-chip input:focus-visible + span', html)
        self.assertIn('@media (prefers-reduced-motion: reduce)', html)
        self.assertNotIn('class="style-option"', html)

    def test_beer_cards_carry_normalized_style_group_keys(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn('data-style-group="ipa"', html)
        self.assertIn('data-style-group="pilsner"', html)
        self.assertIn('data-style-group="stout"', html)

    def test_review_candidate_displays_detailed_untappd_style(self):
        html = untap_report.render_html_report(self._results())
        review_html = html[html.index("Ambiguous Beer"):]
        self.assertIn("Stout - Imperial / Double", review_html)

    def test_inline_javascript_filters_cards_without_external_dependency(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn("filter.addEventListener('change', applyStyleFilters)", html)
        self.assertIn("card.hidden = !enabled.has(card.dataset.styleGroup)", html)
        self.assertIn("applyStyleFilters();", html)
        self.assertNotIn("<script src=", html.lower())

    def test_report_without_styles_omits_filter_controls_but_remains_valid(self):
        results = [{"status": "ok", "beer": "Unknown Style", "rating": 4.0}]
        html = untap_report.render_html_report(results)
        self.assertNotIn('class="style-filters"', html)
        self.assertIn("Unknown Style", html)

    def test_non_untappd_url_is_not_emitted_as_link(self):
        results = [{
            "query": "Unsafe",
            "status": "ok",
            "beer": "Unsafe",
            "brewery": "Brewery",
            "rating": 4.0,
            "ratings": 1,
            "abv": 5.0,
            "url": "https://example.com/not-untappd",
        }]
        html = untap_report.render_html_report(results)
        self.assertNotIn("example.com", html)
        self.assertIn("Unsafe", html)

    def test_save_html_report_writes_single_file(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
        path = handle.name
        handle.close()
        try:
            untap_report.save_html_report(self._results(), path)
            with open(path, "r", encoding="utf-8") as saved:
                html = saved.read()
            self.assertIn("Untap Results", html)
            self.assertIn("3 beers · 2 confirmed · 1 ambiguous", html)
        finally:
            os.unlink(path)

    def test_cli_html_flag_writes_report_after_batch(self):
        menu = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False)
        try:
            menu.write("Badlands\tPop Pop (2026)\t6.5%\tIPA\n")
            menu.close()
            fake_result = [{
                "query": "Badlands Pop Pop (2026)",
                "status": "ok",
                "beer": "Pop Pop (2026)",
                "brewery": "Badlands Brewing Company",
                "rating": 4.25,
                "ratings": 14,
                "abv": 6.5,
                "url": "https://untappd.com/b/badlands-brewing-company-pop-pop-2026/6794932",
            }]

            class FakeBrowserContext:
                def __enter__(self):
                    return object()
                def __exit__(self, exc_type, exc, tb):
                    return False

            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["untap.py", "--menu", menu.name, "--html"]), \
                 mock.patch.object(untap, "untappd_browser_page", return_value=FakeBrowserContext()), \
                 mock.patch.object(untap, "run_batch", return_value=fake_result), \
                 mock.patch.object(untap, "print_batch_results"), \
                 mock.patch.object(untap, "save_csv"), \
                 mock.patch.object(untap, "save_html_report") as save_report, \
                 contextlib.redirect_stdout(output):
                untap.main()

            save_report.assert_called_once_with(
                fake_result, untap.DEFAULT_HTML_REPORT, title=untap.DEFAULT_REPORT_TITLE
            )
        finally:
            if not menu.closed:
                menu.close()
            os.unlink(menu.name)


    def test_cli_report_title_is_forwarded_to_html_renderer(self):
        menu = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False)
        try:
            menu.write("Badlands\tPop Pop (2026)\t6.5%\tIPA\n")
            menu.close()
            fake_result = [{
                "query": "Badlands Pop Pop (2026)",
                "status": "ok",
                "beer": "Pop Pop (2026)",
                "brewery": "Badlands Brewing Company",
                "rating": 4.25,
                "ratings": 14,
                "abv": 6.5,
                "url": "https://untappd.com/b/badlands-brewing-company-pop-pop-2026/6794932",
            }]

            class FakeBrowserContext:
                def __enter__(self):
                    return object()
                def __exit__(self, exc_type, exc, tb):
                    return False

            with mock.patch.object(
                sys,
                "argv",
                [
                    "untap.py", "--menu", menu.name, "--html",
                    "--report-title", "September Bottle Share",
                ],
            ), mock.patch.object(
                untap, "untappd_browser_page", return_value=FakeBrowserContext()
            ), mock.patch.object(
                untap, "run_batch", return_value=fake_result
            ), mock.patch.object(untap, "print_batch_results"), mock.patch.object(
                untap, "save_csv"
            ), mock.patch.object(untap, "save_html_report") as save_report:
                untap.main()

            save_report.assert_called_once_with(
                fake_result, untap.DEFAULT_HTML_REPORT, title="September Bottle Share"
            )
        finally:
            if not menu.closed:
                menu.close()
            os.unlink(menu.name)


if __name__ == "__main__":
    unittest.main()
