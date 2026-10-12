"""Behavioral regressions for the eight v106 review findings."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import untap
import untap_batch as batch
import untap_continue as continuation
import untap_inspect as inspect
import untap_local_review as review
import untap_matcher as matcher
import untap_untappd as transport
from untap_snapshot import build_snapshot, save_snapshot
from untap_report import selection_report_id

QUERY = "Badlands Green Fields"
URL = "https://untappd.com/b/green-fields/123"


def hit(**changes):
    record = dict(beer_name="Green Fields", brewery_name="Badlands", beer_abv=5.,
                  beer_slug="green-fields", bid=123, rating_score=4., rating_count=100,
                  type_name="IPA")
    record.update(changes)
    return record


def capture(record, pages=1):
    request = {"kind": "request", "method": "POST",
               "url": "https://example.algolia.net/1/indexes/*/queries",
               "algolia_requests": [{"query": QUERY, "indexName": "beer", "page": "0",
                   "hitsPerPage": "5", "params": {"query": QUERY, "page": "0", "hitsPerPage": "5"}}]}
    payload = {"results": [{"index": "beer", "page": 0, "nbHits": pages * 5,
                           "nbPages": pages, "hitsPerPage": 5, "hits": [record]}]}
    response = {"kind": "response", "status": 200, "url": request["url"],
                "algolia_requests": request["algolia_requests"],
                "algolia_response": transport._summarize_algolia_response(payload)}
    return {"request_event": request, "events": [request, response], "error": None}, payload


def search(page=object()):
    return matcher.search_one(page, QUERY, expected_beer="Green Fields",
                              expected_brewery="Badlands", expected_abv=5.)


class DetailPage:
    def __init__(self, status=200, heading="Green Fields", url=URL, body="No ratings yet · 5% ABV"):
        self.status, self.heading, self.url, self.body = status, heading, url, body

    def goto(self, *args, **kwargs):
        return SimpleNamespace(status=self.status)

    def locator(self, selector):
        text = self.heading if selector == "h1" else self.body
        locator = Mock()
        locator.first = locator
        locator.inner_text.return_value = text
        return locator


class ConfirmationTests(unittest.TestCase):
    def test_primary_search_rejects_explicit_brewery_conflict(self):
        captured, _ = capture(hit(brewery_name="Unrelated Brewing"))
        with patch.object(matcher, "_run_page0_search_transport", return_value=captured):
            result = search()
        self.assertEqual(result["status"], "failed")
        self.assertIn("Brewery conflict", result["reason"])

    def test_unknown_brewery_and_collaboration_do_not_become_conflicts(self):
        for brewery in (None, "Unknown", "Badlands x Other Brewery"):
            self.assertTrue(matcher.candidate_has_brewery_overlap(
                {"name": "Green Fields", "text": "", "brewery": brewery}, "Badlands"))

    def test_single_strong_candidate_stays_reviewable_after_expansion_error(self):
        captured, _ = capture(hit(beer_name="Green Fields 2025"), pages=2)
        with patch.object(matcher, "_run_page0_search_transport", return_value=captured), \
             patch.object(matcher, "_fetch_algolia_page", return_value=(None, "HTTP 500")):
            result = search()
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("expansion error", result["search_warning"])
        self.assertEqual(result["alternatives"][0]["name"], "Green Fields 2025")

    def test_single_strong_candidate_stays_reviewable_after_page_cap(self):
        captured, _ = capture(hit(beer_name="Green Fields 2025"), pages=2)
        expand = matcher.expand_algolia_candidates
        def limited_expand(*args, **kwargs):
            return expand(*args, max_pages=1, **kwargs)
        with patch.object(matcher, "_run_page0_search_transport", return_value=captured), \
             patch.object(matcher, "expand_algolia_candidates", side_effect=limited_expand):
            result = search()
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("page limit", result["search_warning"])

    def test_detail_errors_do_not_confirm(self):
        captured, _ = capture(hit(rating_score=None))
        for page, status in ((DetailPage(status=403, heading="Access denied"), "failed"),
                             (DetailPage(status=404), "failed"),
                             (DetailPage(status=429), "rate_limited"),
                             (DetailPage(heading="Access denied"), "failed"),
                             (DetailPage(url="https://untappd.com/login"), "failed"),
                             (DetailPage(url="https://untappd.com/b/other/456"), "failed"),
                             (DetailPage(heading=""), "failed")):
            with self.subTest(page=page.__dict__), patch.object(matcher, "_run_page0_search_transport", return_value=captured):
                result = search(page)
            self.assertEqual(result["status"], status)
            self.assertNotIn("beer", result)

    def test_valid_unrated_detail_page_remains_confirmable(self):
        captured, _ = capture(hit(rating_score=None))
        with patch.object(matcher, "_run_page0_search_transport", return_value=captured):
            result = search(DetailPage())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["beer"], "Green Fields")
        self.assertIsNone(result["rating"])

    def test_detail_429_stops_remaining_batch_rows(self):
        captured, _ = capture(hit(rating_score=None))
        inputs = [dict(query=QUERY, original=QUERY, brewery="Badlands", beer="Green Fields", menu_abv=5., style="IPA")] * 3
        with patch.object(matcher, "_run_page0_search_transport", return_value=captured) as requests, contextlib.redirect_stdout(io.StringIO()):
            results = batch.run_batch(DetailPage(status=429), inputs)
        self.assertEqual([r["status"] for r in results], ["rate_limited", "not_attempted", "not_attempted"])
        self.assertEqual(requests.call_count, 1)


class ResponsePairingTests(unittest.TestCase):
    def requests(self):
        return {"algolia_requests": [{"query": "Other", "indexName": "beer"},
                                     {"query": QUERY, "indexName": "beer"}]}

    def test_nb_hits_uses_the_matching_response_index(self):
        event = dict(self.requests(), kind="response", algolia_response=[{"nbHits": 0}, {"nbHits": 12}])
        self.assertEqual(transport._matching_algolia_nb_hits([event], QUERY), 12)

    def test_expansion_uses_the_matching_response_index(self):
        payload = {"results": [{"page": 0, "hits": [hit(beer_name="Other")]},
                    {"page": 0, "index": "beer", "nbHits": 1, "nbPages": 1, "hits": [hit()]}]}
        with patch.object(matcher, "_fetch_algolia_page", return_value=(payload, None)):
            candidates, diagnostics = matcher.expand_algolia_candidates(object(), self.requests(), QUERY)
        self.assertEqual([c["name"] for c in candidates], ["Green Fields"])
        self.assertFalse(diagnostics["errors"])

    def test_expansion_rejects_wrong_page_or_index(self):
        for changes in ({"page": 1}, {"index": "other"}):
            result = dict(page=0, index="beer", hits=[hit()], nbPages=1, nbHits=1)
            result.update(changes)
            with patch.object(matcher, "_fetch_algolia_page", return_value=({"results": [{}, result]}, None)):
                candidates, diagnostics = matcher.expand_algolia_candidates(object(), self.requests(), QUERY)
            self.assertEqual(candidates, [])
            self.assertTrue(diagnostics["errors"])

    def test_sorted_replay_pairs_against_its_single_query_request(self):
        payload = {"results": [{"page": 0, "index": "beer_order_by_abv_desc",
                               "nbHits": 1, "nbPages": 1, "hits": [hit(beer_abv=8.)]}]}
        strategy = dict(index="beer_order_by_abv_desc", direction="descending")
        with patch.object(matcher, "_fetch_algolia_sorted_page", return_value=(payload, None)):
            candidates, diagnostics = matcher.scan_abv_sorted_ambiguity(
                object(), self.requests(), QUERY, "Badlands", 8., .425, strategy)
        self.assertEqual(len(candidates), 1)
        self.assertFalse(diagnostics["errors"])


class RecoveryTests(unittest.TestCase):
    def journal(self, root, tail):
        results = [batch.unattempted_result(query, "pending") for query in ("First", "Second")]
        save_snapshot(build_snapshot(results, "Menu"), root / "results.input.json")
        completed = dict(query="First", status="failed", reason="Search completed")
        (root / "results.partial.jsonl").write_bytes(json.dumps(completed).encode() + b"\n" + tail)
        return completed

    def test_torn_utf8_tail_keeps_completed_results(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            completed = self.journal(root, b'{"query":"Bier \xc3')
            snapshot = continuation.load_continuation(root)
        self.assertEqual(snapshot["items"][0]["result"], completed)
        self.assertEqual(snapshot["items"][1]["result"]["status"], "not_attempted")

    def test_invalid_complete_utf8_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.journal(root, b'{"query":"Bier \xc3\n')
            with self.assertRaisesRegex(ValueError, "line 2"):
                continuation.load_continuation(root)

    def test_torn_final_snapshot_can_fall_back_to_journal(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            completed = self.journal(root, b"")
            (root / "results.json").write_bytes(b'{"title":"Bier \xc3')
            self.assertEqual(continuation.load_continuation(root)["items"][0]["result"], completed)


class ServiceAndDiagnosticTests(unittest.TestCase):
    def tearDown(self):
        transport.configure_search_transport_shadow(0)
        transport.reset_search_transport_authority_state()
        transport.configure_search_timing(False)

    def test_missing_browser_returns_json_and_keeps_review_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_snapshot(build_snapshot([dict(query="Example", status="failed")], "Menu"), root / "results.json")
            session = review.ReviewSession(root)
            before = copy.deepcopy(session.snapshot)
            payload = {"format": "untap-manual-review-trial-v1", "selections": [],
                       "report_id": selection_report_id([i["result"] for i in before["items"]], "Menu", before["report"]["date"]),
                       "pending_candidates": [{"item_id": before["items"][0]["id"], "url": URL}]}
            body = json.dumps(dict(action="fetch", payload=payload)).encode()
            with patch.object(review, "HTTPServer") as server_factory:
                review.make_server(session)
            handler_type = server_factory.call_args.args[1]
            handler = object.__new__(handler_type)
            handler.server = SimpleNamespace(server_port=12345)
            handler.path = f"/{session.token}/action"
            handler.headers = {"Host": "127.0.0.1:12345", "Origin": "http://127.0.0.1:12345",
                               "X-Untap-Token": session.token, "Content-Length": str(len(body)), "Content-Type": "application/json"}
            handler.rfile = io.BytesIO(body)
            handler.reply = Mock()
            with patch.object(transport, "untappd_browser_page", side_effect=transport.BrowserUnavailableError("Run untap-install-browser")):
                handler.do_POST()
            self.assertEqual(handler.reply.call_args.args[0], 400)
            self.assertIn("untap-install-browser", json.loads(handler.reply.call_args.args[1])["error"])
            self.assertEqual(session.snapshot, before)
            handler.path = f"/{session.token}/"
            handler.do_GET()
            self.assertEqual(handler.reply.call_args.args[0], 200)

    def test_missing_browser_still_has_clean_cli_diagnostic(self):
        with patch.object(untap, "untappd_browser_page", side_effect=transport.BrowserUnavailableError("Run untap-install-browser")), \
             contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as exited:
            untap.main([QUERY])
        self.assertEqual(exited.exception.code, 2)
        self.assertIn("untap-install-browser", error.getvalue())

    def test_inspection_missing_browser_has_clean_cli_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(inspect, "_reserve_output_directory", return_value=Path(tmp)), \
             patch.object(inspect, "untappd_browser_page", side_effect=transport.BrowserUnavailableError("Run untap-install-browser")), \
             contextlib.redirect_stderr(io.StringIO()) as error:
            code = inspect.main(["--query", QUERY])
        self.assertEqual(code, 2)
        self.assertIn("untap-install-browser", error.getvalue())

    def test_fetch_timeout_is_reported_as_transport_error(self):
        captured, _ = capture(hit())
        page = Mock()
        page.evaluate.side_effect = TimeoutError("Browser request timed out after 10000 ms")
        payload, error = transport._fetch_algolia_page(page, captured["request_event"], 1)
        self.assertIsNone(payload)
        self.assertIn("timed out", error)
        self.assertGreater(page.evaluate.call_args.args[1]["timeoutMs"], 0)

    def shadow_search(self, replay_result, limit=1):
        captured, _ = capture(hit())
        req, resp = captured["events"]
        events = dict(network_events=[req, resp], response_events=[resp], request_events=[req])
        with patch.object(untap, "untappd_browser_page", return_value=contextlib.nullcontext(object())), \
             patch.object(matcher, "open_search_box", return_value=object()), \
             patch.object(matcher, "start_search_network_capture", return_value=events), \
             patch.object(matcher, "submit_search"), patch.object(matcher, "stop_search_network_capture"), \
             patch.object(transport, "_fetch_algolia_exact_request", return_value=replay_result) as replay, \
             contextlib.redirect_stdout(io.StringIO()):
            untap.main(["--shadow-search-transport", str(limit), QUERY])
        return replay.call_count

    def test_cli_flag_performs_a_bounded_shadow_replay(self):
        _, payload = capture(hit())
        self.assertEqual(self.shadow_search((200, payload, None)), 1)
        self.assertEqual(transport.get_search_transport_shadow_stats()["exact"], 1)

    def test_shadow_429_stops_without_detail_or_expansion_traffic(self):
        with patch.object(matcher, "extract_beer_info") as detail, patch.object(matcher, "_fetch_algolia_page") as expansion, \
             patch.object(untap, "print_single_result") as printed:
            self.assertEqual(self.shadow_search((429, None, "HTTP 429")), 1)
        self.assertEqual(printed.call_args.args[0]["status"], "rate_limited")
        detail.assert_not_called()
        expansion.assert_not_called()

    def test_shadow_error_does_not_replace_successful_ui_result(self):
        with patch.object(untap, "print_single_result") as printed:
            self.assertEqual(self.shadow_search((500, None, "HTTP 500")), 1)
        self.assertEqual(printed.call_args.args[0]["status"], "ok")
