import os
import contextlib
import io
import sys
import tempfile
import unittest
from unittest import mock

import untap
import untap_report


class HtmlReportTests(unittest.TestCase):
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
                        "url": "https://untappd.com/b/brewery-c-wrong/4",
                    },
                    {
                        "name": "Right Variant",
                        "score": 1.0,
                        "rating": 4.2,
                        "ratings": 40,
                        "abv": 10.0,
                        "brewery": "Brewery C",
                        "url": "https://untappd.com/b/brewery-c-right/3",
                    },
                ],
            },
        ]

    def test_confirmed_beers_are_sorted_by_rating_descending(self):
        html = untap_report.render_html_report(self._results())
        self.assertLess(html.index("High Rated"), html.index("Low Rated"))

    def test_confirmed_beer_names_link_to_canonical_untappd_pages(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn('href="https://untappd.com/b/brewery-a-high-rated/1"', html)
        self.assertIn(">High Rated</a>", html)

    def test_needs_review_candidates_are_sorted_by_match_score_and_linked(self):
        html = untap_report.render_html_report(self._results())
        review_start = html.index("Needs review")
        review_html = html[review_start:]
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

    def test_report_is_self_contained_and_mobile_ready(self):
        html = untap_report.render_html_report(self._results())
        self.assertIn('name="viewport"', html)
        self.assertIn("<style>", html)
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("stylesheet", html.lower())

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
            self.assertIn("3 beers · 2 confirmed · 1 need review", html)
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
