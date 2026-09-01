import contextlib
import io
import json
import sys
import unittest
from unittest import mock
from urllib.parse import urlencode

import untap_untappd
from untap_untappd import (
    _build_algolia_replay_body,
    _matching_algolia_initial_page,
    _matching_algolia_nb_hits,
    _matching_algolia_response_status,
    _parse_algolia_request_body,
    _summarize_algolia_response,
)


class UntappdTransportContractTests(unittest.TestCase):
    def test_transport_import_is_playwright_lazy(self):
        self.assertNotIn("playwright.sync_api", sys.modules)

    def test_extract_beer_info_parses_detail_text(self):
        class FakeLocator:
            def __init__(self, text):
                self._text = text
                self.first = self
            def inner_text(self):
                return self._text

        class FakePage:
            def goto(self, *args, **kwargs):
                pass
            def wait_for_timeout(self, *args, **kwargs):
                pass
            def locator(self, selector):
                if selector == "body":
                    return FakeLocator("(4.37) 220 Ratings 6.0% ABV 45 IBU")
                if selector == "h1":
                    return FakeLocator("Bahama Bliss")
                raise AssertionError(selector)

        info = untap_untappd.extract_beer_info(
            FakePage(),
            "https://untappd.com/b/example/1",
            brewery_from_search="Transcend Beer Crafters",
        )
        self.assertEqual(info["beer"], "Bahama Bliss")
        self.assertEqual(info["brewery"], "Transcend Beer Crafters")
        self.assertEqual(info["rating"], 4.37)
        self.assertEqual(info["ratings"], 220)
        self.assertEqual(info["abv"], "6.0%")
        self.assertEqual(info["ibu"], "45")


    def test_transport_has_no_fixed_playwright_sleeps(self):
        from pathlib import Path

        source = Path(__file__).with_name("untap_untappd.py").read_text()
        self.assertNotIn("page.wait_for_timeout(", source)

    def test_submit_search_waits_for_exact_algolia_response(self):
        class FakeRequest:
            method = "POST"
            post_data = json.dumps({
                "requests": [{
                    "indexName": "beer",
                    "params": urlencode({
                        "query": "Brujos Populus w/ Citra",
                        "page": "0",
                        "hitsPerPage": "5",
                    }),
                }]
            })

        class FakeResponse:
            url = "https://example.algolia.net/1/indexes/*/queries"
            request = FakeRequest()

        class ExpectContext:
            def __init__(self, predicate):
                self.predicate = predicate
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                if exc_type is None:
                    if not self.predicate(FakeResponse()):
                        raise AssertionError("response predicate did not match")
                return False

        class FakePage:
            def __init__(self):
                self.timeout = None
            def expect_response(self, predicate, timeout):
                self.timeout = timeout
                return ExpectContext(predicate)

        class FakeSearchBox:
            def __init__(self):
                self.filled = None
                self.pressed = None
            def fill(self, value):
                self.filled = value
            def press(self, key):
                self.pressed = key

        page = FakePage()
        box = FakeSearchBox()
        untap_untappd.submit_search(page, box, "Brujos Populus w/ Citra")
        self.assertEqual(box.filled, "Brujos Populus w/ Citra")
        self.assertEqual(box.pressed, "Enter")
        self.assertEqual(page.timeout, untap_untappd.SEARCH_RESPONSE_TIMEOUT_MS)


    def test_submit_search_arms_response_listener_before_fill(self):
        state = {"listening": False}

        class ExpectContext:
            def __enter__(self):
                state["listening"] = True
                return self
            def __exit__(self, exc_type, exc, tb):
                state["listening"] = False
                return False

        class FakePage:
            def expect_response(self, predicate, timeout):
                return ExpectContext()

        class FakeSearchBox:
            def fill(self, value):
                if not state["listening"]:
                    raise AssertionError("response listener was not armed before fill")
                self.value = value
            def press(self, key):
                if not state["listening"]:
                    raise AssertionError("response listener was not armed before Enter")
                self.key = key

        box = FakeSearchBox()
        untap_untappd.submit_search(FakePage(), box, "Badlands Fazy (2026)")
        self.assertEqual(box.value, "Badlands Fazy (2026)")
        self.assertEqual(box.key, "Enter")

    def test_submit_search_timing_is_opt_in_and_measures_exact_response_wait(self):
        class FakeRequest:
            method = "POST"
            post_data = json.dumps({
                "requests": [{
                    "indexName": "beer",
                    "params": urlencode({
                        "query": "Badlands Fazy (2026)",
                        "page": "0",
                    }),
                }]
            })

        class FakeResponse:
            url = "https://example.algolia.net/1/indexes/*/queries"
            request = FakeRequest()

        class ExpectContext:
            def __init__(self, predicate):
                self.predicate = predicate
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                if exc_type is None and not self.predicate(FakeResponse()):
                    raise AssertionError("response predicate did not match")
                return False

        class FakePage:
            def expect_response(self, predicate, timeout):
                return ExpectContext(predicate)

        class FakeSearchBox:
            def fill(self, value):
                self.value = value
            def press(self, key):
                self.key = key

        output = io.StringIO()
        untap_untappd.configure_search_timing(True)
        try:
            with mock.patch.object(
                untap_untappd, "perf_counter", side_effect=[10.0, 10.375]
            ), contextlib.redirect_stdout(output):
                untap_untappd.submit_search(
                    FakePage(), FakeSearchBox(), "Badlands Fazy (2026)"
                )
                untap_untappd.print_search_timing_summary()

            stats = untap_untappd.get_search_timing_stats()
            self.assertEqual(stats["count"], 1)
            self.assertAlmostEqual(stats["total_seconds"], 0.375)
            self.assertAlmostEqual(stats["min_seconds"], 0.375)
            self.assertAlmostEqual(stats["max_seconds"], 0.375)
            text = output.getvalue()
            self.assertIn("[timing] search -> Algolia response: 0.375s", text)
            self.assertIn("Timed search submissions: 1", text)
            self.assertIn("Average submit-to-response time: 0.375s", text)
        finally:
            untap_untappd.configure_search_timing(False)

    def test_search_timing_disabled_by_default(self):
        untap_untappd.configure_search_timing(False)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            untap_untappd.print_search_timing_summary()
        self.assertEqual(output.getvalue(), "")

    def test_algolia_request_body_round_trip_preserves_query_and_page(self):
        body = json.dumps({
            "requests": [{
                "indexName": "beer",
                "params": urlencode({
                    "query": "Badlands Pop Pop (2026)",
                    "page": "0",
                    "hitsPerPage": "5",
                }),
            }]
        })
        parsed = _parse_algolia_request_body(body)
        self.assertEqual(parsed[0]["indexName"], "beer")
        self.assertEqual(parsed[0]["query"], "Badlands Pop Pop (2026)")
        self.assertEqual(parsed[0]["page"], "0")

        replay = _build_algolia_replay_body(parsed, page_number=3)
        reparsed = _parse_algolia_request_body(json.dumps(replay))
        self.assertEqual(reparsed[0]["query"], "Badlands Pop Pop (2026)")
        self.assertEqual(reparsed[0]["page"], "3")

    def test_algolia_response_summary_keeps_raw_page_for_reuse(self):
        payload = {
            "results": [{
                "index": "beer",
                "nbHits": 1,
                "page": 0,
                "nbPages": 1,
                "hitsPerPage": 5,
                "hits": [{
                    "beer_name": "Silent Spaces",
                    "brewery_name": "Sante Adairius Rustic Ales",
                    "beer_abv": 6.3,
                    "type_name": "Farmhouse Ale - Saison",
                    "bid": 123,
                }],
            }]
        }
        summary = _summarize_algolia_response(payload)[0]
        self.assertEqual(summary["nbHits"], 1)
        self.assertEqual(summary["rawHits"][0]["beer_name"], "Silent Spaces")
        self.assertEqual(
            summary["rawHits"][0]["brewery_name"],
            "Sante Adairius Rustic Ales",
        )


    def test_matcher_has_no_direct_playwright_page_operations(self):
        from pathlib import Path

        source = Path(__file__).with_name("untap_matcher.py").read_text()
        forbidden = (
            "page.goto(",
            "page.on(",
            "page.remove_listener(",
            "page.evaluate(",
            "page.locator(",
            "page.wait_for_timeout(",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_matching_network_helpers_select_exact_query(self):
        query = "Messorem Demoliri #0031 - XTRM Turbo"
        events = [{
            "kind": "response",
            "url": "https://example.algolia.net/1/indexes/*/queries",
            "status": 200,
            "algolia_requests": [{
                "indexName": "beer",
                "query": query,
                "page": "0",
                "hitsPerPage": "5",
            }],
            "algolia_response": [{
                "index": "beer",
                "nbHits": 0,
                "page": 0,
                "nbPages": 0,
                "hitsPerPage": 5,
                "hitsReturned": 0,
                "rawHits": [],
            }],
        }]
        self.assertEqual(_matching_algolia_response_status(events, query), 200)
        self.assertEqual(_matching_algolia_nb_hits(events, query), 0)
        page = _matching_algolia_initial_page(events, query)
        self.assertEqual(page["page"], 0)
        self.assertEqual(page["nbHits"], 0)

    def test_detail_timing_separates_navigation_and_extraction(self):
        class FakeLocator:
            def __init__(self, text):
                self._text = text
                self.first = self
            def wait_for(self, **kwargs):
                return None
            def inner_text(self):
                return self._text

        class FakePage:
            def goto(self, *args, **kwargs):
                return None
            def locator(self, selector):
                if selector == "h1":
                    return FakeLocator("Bahama Bliss")
                if selector == "body":
                    return FakeLocator("(4.37) 220 Ratings 6.0% ABV 45 IBU")
                raise AssertionError(selector)

        output = io.StringIO()
        untap_untappd.configure_search_timing(True)
        try:
            with mock.patch.object(
                untap_untappd, "perf_counter",
                side_effect=[10.0, 10.500, 20.0, 20.025],
            ), contextlib.redirect_stdout(output):
                info = untap_untappd.extract_beer_info(
                    FakePage(),
                    "https://untappd.com/b/example/1",
                    brewery_from_search="Transcend Beer Crafters",
                )
                untap_untappd.print_search_timing_summary()

            stats = untap_untappd.get_detail_timing_stats()
            self.assertEqual(stats["count"], 1)
            self.assertAlmostEqual(stats["navigation_total_seconds"], 0.500)
            self.assertAlmostEqual(stats["extraction_total_seconds"], 0.025)
            self.assertEqual(info["beer"], "Bahama Bliss")
            text = output.getvalue()
            self.assertIn("[timing] detail navigation -> usable content: 0.500s", text)
            self.assertIn("[timing] detail extraction: 0.025s | Bahama Bliss", text)
            self.assertIn("Timed detail pages: 1", text)
            self.assertIn("Average navigation-to-content time: 0.500s", text)
            self.assertIn("Average detail-extraction time: 0.025s", text)
        finally:
            untap_untappd.configure_search_timing(False)

    def test_detail_timing_disabled_by_default(self):
        untap_untappd.configure_search_timing(False)
        class FakeLocator:
            def __init__(self, text):
                self._text = text
                self.first = self
            def wait_for(self, **kwargs):
                return None
            def inner_text(self):
                return self._text
        class FakePage:
            def goto(self, *args, **kwargs):
                return None
            def locator(self, selector):
                return FakeLocator(
                    "Beer" if selector == "h1" else "(4.00) 1 Ratings 5.0% ABV"
                )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            untap_untappd.extract_beer_info(FakePage(), "https://untappd.com/b/x/1")
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(untap_untappd.get_detail_timing_stats()["count"], 0)


if __name__ == "__main__":
    unittest.main()

class SearchTransportShadowTests(unittest.TestCase):
    def tearDown(self):
        untap_untappd.configure_search_transport_shadow(0)

    def _request_event(self):
        return {
            "url": "https://example.algolia.net/1/indexes/*/queries",
            "algolia_requests": [{
                "indexName": "beer",
                "query": "Badlands Fazy (2026)",
                "page": "0",
                "hitsPerPage": "5",
                "filters": None,
                "params": {
                    "query": "Badlands Fazy (2026)",
                    "page": "0",
                    "hitsPerPage": "5",
                },
            }],
        }

    def _page0(self):
        hit = {
            "beer_name": "Fazy (2026)",
            "brewery_name": "Badlands Brewing Company",
            "beer_abv": 6.5,
            "rating_score": 4.30,
            "rating_count": 109,
            "type_name": "IPA - New England / Hazy",
            "bid": 6736235,
            "beer_slug": "badlands-brewing-company-fazy-2026",
        }
        return {
            "index": "beer",
            "nbHits": 1,
            "page": 0,
            "nbPages": 1,
            "hitsPerPage": 5,
            "hitsReturned": 1,
            "rawHits": [hit],
            "hits": [hit],
        }

    def test_exact_shadow_replay_preserves_page_zero_params(self):
        body = untap_untappd._build_algolia_exact_replay_body(
            self._request_event()["algolia_requests"]
        )
        parsed = untap_untappd._parse_algolia_request_body(json.dumps(body))
        self.assertEqual(parsed[0]["query"], "Badlands Fazy (2026)")
        self.assertEqual(parsed[0]["page"], "0")
        self.assertEqual(parsed[0]["hitsPerPage"], "5")

    def test_shadow_is_bounded_and_never_changes_matcher_input(self):
        payload = {
            "results": [{
                "index": "beer",
                "nbHits": 1,
                "page": 0,
                "nbPages": 1,
                "hitsPerPage": 5,
                "hits": self._page0()["hits"],
            }]
        }
        untap_untappd.configure_search_transport_shadow(1)
        with mock.patch.object(
            untap_untappd,
            "_fetch_algolia_exact_request",
            return_value=(200, payload, None),
        ) as fetch:
            untap_untappd.shadow_compare_search_transport(
                object(), self._request_event(), "Badlands Fazy (2026)", self._page0()
            )
            untap_untappd.shadow_compare_search_transport(
                object(), self._request_event(), "Badlands Fazy (2026)", self._page0()
            )
        stats = untap_untappd.get_search_transport_shadow_stats()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(stats["attempted"], 1)
        self.assertEqual(stats["exact"], 1)
        self.assertEqual(stats["mismatch"], 0)

    def test_shadow_disabled_issues_no_request(self):
        untap_untappd.configure_search_transport_shadow(0)
        with mock.patch.object(untap_untappd, "_fetch_algolia_exact_request") as fetch:
            untap_untappd.shadow_compare_search_transport(
                object(), self._request_event(), "Badlands Fazy (2026)", self._page0()
            )
        fetch.assert_not_called()


class SearchTransportAuthorityTests(unittest.TestCase):
    def setUp(self):
        untap_untappd.reset_search_transport_authority_state()
        untap_untappd.configure_search_timing(False)

    def _template_event(self):
        return {
            "kind": "request",
            "method": "POST",
            "url": "https://example.algolia.net/1/indexes/*/queries",
            "algolia_requests": [{
                "indexName": "beer",
                "query": "Bootstrap Beer",
                "page": "0",
                "hitsPerPage": "5",
                "filters": None,
                "params": {
                    "query": "Bootstrap Beer",
                    "page": "0",
                    "hitsPerPage": "5",
                },
            }],
        }

    def test_template_rewrites_only_query_and_page_for_serial_search(self):
        self.assertTrue(
            untap_untappd.remember_search_transport_template(self._template_event())
        )
        event = untap_untappd._query_request_event_from_template("Fallback Beer")
        req = event["algolia_requests"][0]
        self.assertEqual(req["query"], "Fallback Beer")
        self.assertEqual(req["page"], "0")
        self.assertEqual(req["hitsPerPage"], "5")
        self.assertEqual(req["indexName"], "beer")

    def test_authoritative_fetch_builds_matchable_response_event(self):
        untap_untappd.remember_search_transport_template(self._template_event())

        class FakePage:
            def evaluate(self, script, args):
                return {
                    "status": 200,
                    "ok": True,
                    "payload": {
                        "results": [{
                            "index": "beer",
                            "nbHits": 1,
                            "page": 0,
                            "nbPages": 1,
                            "hitsPerPage": 5,
                            "hits": [{
                                "bid": 1,
                                "beer_slug": "fallback-beer",
                                "beer_name": "Fallback Beer",
                                "brewery_name": "Example Brewery",
                                "beer_abv": 6.5,
                                "rating_score": 4.2,
                                "rating_count": 10,
                                "type_name": "IPA",
                            }],
                        }]
                    },
                    "text": None,
                }

        request_event, response_event, error = (
            untap_untappd.fetch_authoritative_algolia_search(
                FakePage(), "Fallback Beer"
            )
        )
        self.assertIsNone(error)
        self.assertEqual(response_event["status"], 200)
        events = [request_event, response_event]
        page0 = untap_untappd._matching_algolia_initial_page(
            events, "Fallback Beer"
        )
        self.assertEqual(page0["hits"][0]["beer_name"], "Fallback Beer")


    def test_template_can_be_invalidated_and_recaptured_as_recovery(self):
        self.assertTrue(
            untap_untappd.remember_search_transport_template(self._template_event())
        )
        self.assertTrue(untap_untappd.invalidate_search_transport_template())
        self.assertFalse(untap_untappd.search_transport_template_available())
        self.assertTrue(
            untap_untappd.remember_search_transport_template(
                self._template_event(), recovery=True
            )
        )
        stats = untap_untappd._SEARCH_TRANSPORT_AUTHORITY_STATS
        self.assertEqual(stats["template_invalidations"], 1)
        self.assertEqual(stats["ui_recovery_searches"], 1)

    def test_recovery_stats_distinguish_success_and_failure(self):
        untap_untappd.note_search_transport_recovery(True)
        untap_untappd.note_search_transport_recovery(False)
        stats = untap_untappd._SEARCH_TRANSPORT_AUTHORITY_STATS
        self.assertEqual(stats["successful_recoveries"], 1)
        self.assertEqual(stats["failed_recoveries"], 1)

    def test_authoritative_fetch_surfaces_429_without_ui_retry(self):
        untap_untappd.remember_search_transport_template(self._template_event())

        class FakePage:
            def evaluate(self, script, args):
                return {"status": 429, "ok": False, "payload": None, "text": "rate limited"}

        request_event, response_event, error = (
            untap_untappd.fetch_authoritative_algolia_search(
                FakePage(), "Fallback Beer"
            )
        )
        self.assertIsNotNone(request_event)
        self.assertEqual(response_event["status"], 429)
        self.assertEqual(error, "HTTP 429")
        stats = untap_untappd._SEARCH_TRANSPORT_AUTHORITY_STATS
        self.assertEqual(stats["direct_rate_limited"], 1)
