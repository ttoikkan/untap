"""Offline regression fixtures for v86 search, acceptance and report contracts."""
import copy
import io
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import untap_matcher as matcher
import untap_publish as publish
import untap_report as report


def candidate(name, brewery, abv, score=1.0, bid=1):
    return dict(name=name, brewery=brewery, abv=abv, score=score,
                url=f"https://untappd.com/b/fixture/{bid}", bid=bid,
                text=f"{name}\n{brewery}\n{abv}% ABV", type_name="IPA - Sour",
                rating_score=4.0, rating_count=100)


class MatcherV86Tests(unittest.TestCase):
    def test_full_twelve_candidate_pb_j_fixture(self):
        names = ["PB&J Mixtape", "PB&J Mixtape: Peach", "PB&J Mixtape: Cherry",
                 "PB&J Mixtape: Raspberry", "PB&J Mixtape: Blueberry",
                 "PB&J Mixtape: Strawberry", "PB&J Mixtape: Blackberry",
                 "PB&J Mixtape: Marshmallow", "PB&J Mixtape: Orange Marmalade",
                 "PB&J Mixtape Fluff: Strawberry", "BA PB&J Mixtape", "Pb&j Mixtape: Grape"]
        scores = [1., .9375, .9294, .9081, .9081, .9018, .9018, .8958, .8704, .8704, .5590, .53125]
        abvs = [6.5] * 10 + [8.5, 5.0]
        rows = [candidate(name, "Xül Beer Company", abvs[i], scores[i], i + 1)
                for i, name in enumerate(names)]
        before = copy.deepcopy(rows)
        result, _ = self.run_search(rows, "PB&J Mixtape", "Xül", 6.5)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"], rows[0]["url"])
        self.assertEqual(result["score"], 1.)
        self.assertEqual(rows, before)

    def test_abv_filter_boundary_unknowns_order_and_debug(self):
        abvs = [6.5, 7.49, 5.51, 7.5, 5.5, None, float("nan")]
        rows = [candidate(f"Beer {i}", "Brewery", abv, .9, i) for i, abv in enumerate(abvs)]
        output = io.StringIO()
        with redirect_stdout(output):
            kept = matcher._exclude_abv_conflicts(rows, 6.5, debug=True)
        self.assertEqual([row["bid"] for row in kept], [0, 1, 2, 5, 6])
        self.assertIn("Excluded: Beer 3 — 7.5% conflicts with menu 6.5%", output.getvalue())
        self.assertIn("Excluded: Beer 4 — 5.5% conflicts with menu 6.5%", output.getvalue())
        self.assertEqual(matcher._exclude_abv_conflicts(rows, None), rows)

    def test_all_conflicting_candidates_report_explicit_conflict_without_links(self):
        rows = [candidate("Some Beer", "Brewery", 8.5), candidate("Some Beer Peach", "Brewery", 5.0, .8, 2)]
        # Simulate completed recovery: all retrieved candidates still conflict.
        result, _ = self.run_search(rows, "Some Beer", "Brewery", 6.5,
                                    fallback=lambda *a, **k: {"candidates": [], "weak_match": True})
        self.assertEqual(result["status"], "failed")
        self.assertIn("ABV conflict: all retrieved candidates", result["reason"])
        for field in ["url", "match", "alternatives", "same_abv_variants"]:
            self.assertNotIn(field, result)
        self.assertNotIn("https://untappd.com/b/fixture", report.render_html_report([result]))

    def test_conflicts_are_absent_from_ambiguous_result_and_report(self):
        rows = [candidate("Each A Little Token", "Sante Adairius Rustic Ales", 5.2),
                candidate("Each A Little Token (Batch 2)", "Sante Adairius Rustic Ales", 5.2, .94, 2),
                candidate("Each A Little Token Conflicting", "Sante Adairius Rustic Ales", 8.0, .8, 3)]
        result, _ = self.run_search(rows, "Each A Little Token", "Sante Adairius Rustic Ales", 5.2)
        self.assertEqual(result["status"], "ambiguous")
        self.assertNotIn("Conflicting", str(result))
        self.assertNotIn("Conflicting", report.render_html_report([result]))

    def test_stale_ambiguity_is_recomputed_after_exclusion(self):
        rows = [candidate("Some Beer", "Brewery", 6.5), candidate("Other Beer", "Brewery", 8.5, .99, 2)]
        result, _ = self.run_search(rows, "Some Beer", "Brewery", 6.5)
        self.assertEqual(result["status"], "ok")
        incomplete, _ = self.run_search(rows, "Some Beer", "Brewery", 6.5, diagnostics={"capped": True})
        self.assertEqual(incomplete["status"], "ambiguous")
        self.assertIn("Search incomplete", incomplete["reason"])

    def test_xul_short_menu_brewery_matches_terminal_beer_company(self):
        suffixes = ["", ": Peach", ": Cherry", ": Raspberry", ": Blueberry",
                    ": Strawberry", ": Blackberry", ": Marshmallow",
                    ": Orange Marmalade", " Fluff: Strawberry"]
        rows = [candidate("PB&J Mixtape" + suffix, "Xül Beer Company", 6.5,
                          1.0 if i == 0 else .9, i + 1)
                for i, suffix in enumerate(suffixes)]
        before = copy.deepcopy(rows)
        result, calls = self.run_search(rows, "PB&J Mixtape", "Xül", 6.5)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"], rows[0]["url"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(rows, before)
        self.assertFalse(calls)

    def test_company_suffix_is_narrow_and_does_not_change_shared_normalization(self):
        for name in ["Xül Beer Company", "Xül Beer Co."]:
            self.assertEqual(matcher._exact_base_brewery_words(name), {"xul"})
        self.assertEqual(matcher._meaningful_brewery_words("Xül Beer Company"), {"xul", "beer"})
        for name in ["Xül Beer", "Xül Beer Company North", "Xül Other Beer Company"]:
            self.assertNotEqual(matcher._exact_base_brewery_words(name), {"xul"})
        self.assertEqual(matcher._exact_base_brewery_words("Beer Tree Brewing"), {"beer", "tree"})

    def test_debug_exposes_candidates_beyond_ten_and_blocking_qualifier(self):
        rows = [candidate("PB&J Mixtape", "Xül Beer Company", 6.5)]
        rows += [candidate("PB&J Mixtape: Peach", "Xül Beer Company", 6.5, .9, i)
                 for i in range(2, 12)]
        rows.append(candidate("PB&J Mixtape: Unknown Edition", "Xül Beer Company", 6.5, .8, 12))
        before = copy.deepcopy(rows)
        output = io.StringIO()
        with redirect_stdout(output):
            result = matcher.exact_base_candidate(rows, "PB&J Mixtape", "Xül", 6.5, debug=True)
        self.assertIsNone(result)
        self.assertIn("12 candidates", output.getvalue())
        self.assertIn("unrecognized qualifier 'unknown edition'", output.getvalue())
        self.assertEqual(rows, before)
        with redirect_stdout(io.StringIO()) as quiet:
            self.assertIsNone(matcher.exact_base_candidate(rows, "PB&J Mixtape", "Xül", 6.5))
        self.assertEqual(quiet.getvalue(), "")

    def run_search(self, candidates, beer, brewery, abv, *, hits=2,
                   diagnostics=None, fallback=None):
        evaluation = dict(candidates=candidates, ambiguity_reason="Multiple candidates",
                          release_qualifier_trigger=False, needs_expansion=False,
                          expanded_candidates=[], expansion_diagnostics=diagnostics)
        if not candidates:
            evaluation["ambiguity_reason"] = None
        with ExitStack() as stack:
            for name, value in {
                "_run_page0_search_transport": {"request_event": None, "events": []},
                "_matching_algolia_response_status": 200,
                "_matching_algolia_nb_hits": hits,
                "_matching_algolia_initial_page": {"hits": []},
                "_algolia_page0_candidates": candidates,
                "evaluate_and_expand_candidates": evaluation,
            }.items():
                stack.enter_context(patch.object(matcher, name, return_value=value))
            retry = stack.enter_context(patch.object(
                matcher, "run_search_fallback_attempt", side_effect=fallback
            ))
            result = matcher.search_one(None, brewery + " " + beer,
                                        expected_beer=beer, expected_brewery=brewery,
                                        expected_abv=abv, expected_style="Sour DIPA")
            return result, retry.call_args_list

    def test_exact_base_acceptance_preserves_score(self):
        for beer, brewery, abv, suffix in [
            ("PB&J Mixtape", "Xül Beer Company", 6.5, ": Peach"),
            ("Tomorrow, Today", "Sante Adairius Rustic Ales", 7.4,
             " (Double Dry Hopped W Centennial)"),
        ]:
            with self.subTest(beer=beer):
                rows = [candidate(beer, brewery, abv),
                        candidate(beer + suffix, brewery, abv, .836, 2)]
                before = copy.deepcopy(rows)
                result, calls = self.run_search(rows, beer, brewery, abv)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["url"], rows[0]["url"])
                self.assertEqual(result["score"], 1.0)
                self.assertEqual(rows, before)
                self.assertFalse(calls)

    def test_batch_and_unknown_qualifiers_remain_ambiguous(self):
        for suffix in [" (Batch 2)", " (2025)", " Reserve", " Special Edition",
                       " (Batch Two)", " N.E. India Pale Ale"]:
            with self.subTest(suffix=suffix):
                rows = [candidate("Each A Little Token", "Sante Adairius Rustic Ales", 5.2),
                        candidate("Each A Little Token" + suffix,
                                  "Sante Adairius Rustic Ales", 5.2, .946, 2)]
                result, _ = self.run_search(rows, "Each A Little Token",
                                            "Sante Adairius Rustic Ales", 5.2)
                self.assertEqual(result["status"], "ambiguous")

    def test_exact_preference_fails_closed(self):
        base = candidate("PB&J Mixtape", "Xül Beer Company", 6.5)
        variant = candidate("PB&J Mixtape: Peach", "Xül Beer Company", 6.5, .938, 2)
        for changes in [{"name": "PB&J Mixtape"}, {"brewery": "Other Brewery"},
                        {"abv": 7.5}, {"abv": None}, {"name": "Unrelated Peach"}]:
            with self.subTest(changes=changes):
                self.assertIsNone(matcher.exact_base_candidate(
                    [base, dict(variant, **changes)], "PB&J Mixtape", "Xül", 6.5))
        self.assertIsNone(matcher.exact_base_candidate([variant, base], "PB&J Mixtape", "Xül", 6.5))
        self.assertIsNone(matcher.exact_base_candidate([base, variant], "PB&J Mixtape", None, 6.5))
        self.assertIsNone(matcher.exact_base_candidate([base, variant], "PB&J Mixtape", "Xül", None))

    def test_incomplete_expansion_keeps_ambiguity(self):
        rows = [candidate("PB&J Mixtape", "Xül Beer Company", 6.5),
                candidate("PB&J Mixtape: Peach", "Xül Beer Company", 6.5, .938, 2)]
        for diagnostics in [{"capped": True}, {"errors": ["failed page"]},
                            {"ambiguity_early_stopped": True}]:
            result, _ = self.run_search(rows, "PB&J Mixtape", "Xül", 6.5,
                                        diagnostics=diagnostics)
            self.assertEqual(result["status"], "ambiguous")

    def test_m43_is_unchanged(self):
        rows = [candidate("M-43 Tropical", "Old Nation Brewing Co.", 6.8, .835),
                candidate("M-43 N.E. India Pale Ale", "Old Nation Brewing Co.", 6.8, .780, 2)]
        result, _ = self.run_search(rows, "M-43", "Old Nation", 6.8)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["score"], .835)

    def test_leading_on_recovery_uses_original_identity(self):
        beer = "On the Manner of Addressing Clouds"
        row = candidate("The Manner Of Addressing Clouds", "Hudson Valley Brewery", 8.0)
        def fallback(page, query, **kwargs):
            self.assertEqual(kwargs["expected_beer"], beer)
            return dict(candidates=[row], weak_match=False, ambiguity_reason=None)
        result, calls = self.run_search([], beer, "Hudson Valley", 8.0, hits=0, fallback=fallback)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[1], "Hudson Valley the Manner of Addressing Clouds")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["query"], "Hudson Valley " + beer)
        self.assertAlmostEqual(result["score"], .985576923076923)

    def test_leading_retry_requires_zero_hits(self):
        for enabled in [False, True]:
            queries = matcher.build_search_fallback_queries(
                "Hudson Valley On the Manner of Addressing Clouds",
                expected_beer="On the Manner of Addressing Clouds",
                expected_brewery="Hudson Valley", enable_trailing_relaxation=enabled)
            self.assertEqual("Hudson Valley the Manner of Addressing Clouds" in queries, enabled)
        for beer in ["On IPA", "In the Manner of Addressing Clouds", "Only the Manner of Addressing Clouds"]:
            self.assertIsNone(matcher.leading_word_recovery(beer, "Hudson Valley"))

    def test_leading_retry_rejects_wrong_identity_and_abv(self):
        beer = "On the Manner of Addressing Clouds"
        for changes in [{"abv": 9.0}, {"brewery": "Other Brewery"},
                        {"name": "The Manner Of Addressing Clouds Peach"}, {"abv": None}]:
            row = dict(candidate("The Manner Of Addressing Clouds", "Hudson Valley Brewery", 8.0), **changes)
            def fallback(page, query, **kwargs):
                rows = [row] if query == "Hudson Valley the Manner of Addressing Clouds" else []
                return dict(candidates=rows, weak_match=not rows, ambiguity_reason=None)
            result, _ = self.run_search([], beer, "Hudson Valley", 8.0, hits=0, fallback=fallback)
            self.assertEqual(result["status"], "failed")

    def test_recovery_rate_limit_stops_retries(self):
        result, calls = self.run_search([], "On the Manner of Addressing Clouds", "Hudson Valley", 8.0,
                                        hits=0, fallback=lambda *args, **kwargs: {"rate_limited": True})
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(len(calls), 1)


class ReportV86Tests(unittest.TestCase):
    def test_split_counts_round_trip_and_archive(self):
        results = [{"status": "ok", "beer": "Beer", "rating": 4.0},
                   {"status": "ambiguous"}, {"status": "failed"},
                   {"status": "low_confidence"}, {"status": "rate_limited"}]
        html = report.render_html_report(results)
        expected = "1 confirmed · 1 ambiguous · 1 failed · 2 unresolved"
        self.assertIn(expected, html)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(html, encoding="utf-8")
            metadata = publish.read_report_metadata(path)
        self.assertEqual(metadata.review_count, 4)
        self.assertEqual(metadata.ambiguous_count, 1)
        self.assertEqual(metadata.failed_count, 1)
        self.assertIn(expected, publish.render_archive_index([publish.ArchiveReport(metadata, "report.html")]))

    def test_invalid_optional_metadata_fails_closed(self):
        html = report.render_html_report([{"status": "failed"}])
        for bad in [html.replace('name="untap-failed-count"', 'name="ignored"'),
                    html.replace('name="untap-failed-count" content="1"', 'name="untap-failed-count" content="2"'),
                    html.replace('name="untap-failed-count" content="1"', 'name="untap-failed-count" content="-1"')]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "report.html"
                path.write_text(bad, encoding="utf-8")
                with self.assertRaises(publish.PublishError):
                    publish.read_report_metadata(path)

    def test_legacy_metadata_is_unresolved_not_ambiguous(self):
        metadata = publish.ReportMetadata("Old", "2026-09-01", 19, 15, 4)
        html = publish.render_archive_index([publish.ArchiveReport(metadata, "old.html")])
        self.assertIn("15 confirmed · 4 unresolved", html)


if __name__ == "__main__":
    unittest.main()
