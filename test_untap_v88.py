"""Offline regressions for v88 report images and diagnostics."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import untap
import untap_matcher
import untap_report


class ReportImageTests(unittest.TestCase):
    def test_algolia_label_reaches_confirmed_and_alternative_records(self):
        label = "https://assets.untappd.com/site/beer_logos/beer-1.png"
        candidate = untap_matcher._algolia_hit_to_candidate({
            "beer_name": "Beer", "brewery_name": "Brewery", "beer_abv": 6.5,
            "beer_slug": "beer", "bid": 1, "beer_label": label,
        })
        candidate["score"] = 1.0
        self.assertEqual(candidate["image_url"], label)
        self.assertEqual(
            untap_matcher._alternative_from_candidate(candidate)["image_url"], label
        )

    def test_report_renders_lazy_untappd_images_without_embedding_data(self):
        label = "https://assets.untappd.com/site/beer_logos/beer-1.png"
        results = [{
            "status": "ok", "beer": "Beer", "brewery": "Brewery",
            "rating": 4.1, "ratings": 10, "abv": 6.5,
            "url": "https://untappd.com/b/beer/1", "image_url": label,
        }]
        html = untap_report.render_html_report(results)
        self.assertIn(f'src="{label}"', html)
        self.assertIn('alt="Beer label"', html)
        self.assertIn('loading="lazy"', html)
        self.assertIn('referrerpolicy="no-referrer"', html)
        self.assertNotIn("data:image", html)

    def test_report_rejects_non_untappd_or_non_https_image_urls(self):
        base = {"status": "ok", "beer": "Beer", "brewery": "Brewery",
                "rating": 4.1, "ratings": 10, "abv": 6.5}
        for url in ("http://assets.untappd.com/a.png", "https://example.com/a.png",
                    "https://assets.untappd.com.evil.test/a.png"):
            with self.subTest(url=url):
                html = untap_report.render_html_report([{**base, "image_url": url}])
                self.assertNotIn(url, html)

    def test_status_controls_and_candidate_thumbnail_are_rendered(self):
        label = "https://assets.untappd.com/site/beer_logos/candidate.png"
        result = {"status": "ambiguous", "query": "Maybe", "reason": "Close",
                  "alternatives": [{"name": "Candidate", "score": .9,
                                    "image_url": label}]}
        html = untap_report.render_html_report([result])
        self.assertIn('data-status-filter value="all" checked', html)
        self.assertIn('data-status-filter value="ambiguous"', html)
        self.assertIn('data-status="ambiguous"', html)
        self.assertIn(f'src="{label}"', html)
        self.assertIn("!statusVisible(group)", html)


class DebugTranscriptTests(unittest.TestCase):
    def test_batch_debug_log_contains_diagnostics_summary_and_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_directory = Path(tmp)
            page = object()
            with contextlib.redirect_stdout(io.StringIO()), \
                 mock.patch.object(untap, "run_batch", return_value=[]) as batch:
                untap._run_and_save_batch(
                    page, [], run_directory, min_score=.425, debug=True,
                    html_requested=False, report_title=None,
                )
            log = (run_directory / "debug.txt").read_text()
            self.assertIn("0 beers · 0 confirmed · 0 ambiguous · 0 failed", log)
            self.assertIn(f"Run outputs: {run_directory}", log)
            self.assertTrue((run_directory / "results.csv").exists())
            batch.assert_called_once_with(page, [], min_score=.425, debug=True)

    def test_enabled_transcript_tees_and_flushes_before_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            terminal = io.StringIO()
            try:
                with contextlib.redirect_stdout(terminal):
                    with untap.debug_transcript(Path(tmp), True):
                        print("diagnostic line")
                        raise RuntimeError("stop")
            except RuntimeError:
                pass
            self.assertIn("diagnostic line", terminal.getvalue())
            self.assertEqual((Path(tmp) / "debug.txt").read_text(), "diagnostic line\n")

    def test_disabled_transcript_creates_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                with untap.debug_transcript(Path(tmp), False):
                    print("ordinary output")
            self.assertFalse((Path(tmp) / "debug.txt").exists())

    def test_terminal_summary_separates_ambiguous_and_failed(self):
        results = [{"status": "ok", "rating": 4, "ratings": 1, "abv": "5%",
                    "beer": "Beer", "brewery": "Brewery"},
                   {"status": "ambiguous", "query": "Maybe", "reason": "Close",
                    "alternatives": []},
                   {"status": "failed", "query": "Missing", "reason": "None"}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            untap.print_batch_results(results)
        self.assertIn("3 beers · 1 confirmed · 1 ambiguous · 1 failed", output.getvalue())
        self.assertNotIn("failed or uncertain", output.getvalue())


if __name__ == "__main__":
    unittest.main()
