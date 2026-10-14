"""Corpus tooling: sanitizer allowlist follows runtime consumers; recording replays strictly."""
import ast
import contextlib
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlencode

import untap
import untap.matcher as matcher
import untap.transport as transport
from tests import corpus_tools as tools
from tests.replay_page import ReplayPage, URL

CASES = Path(__file__).parent / "testdata" / "search_corpus"


def load(name):
    return json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))


class ServerPage(ReplayPage):
    """Answers any recorded request like a live server, and emits browser events for fetches too."""

    def __init__(self, pool, ui_extra=None):
        super().__init__([])
        self.pool, self.ui_extra = pool, ui_extra or {}

    def _answer(self, mode, body):
        requests = (json.loads(body) if isinstance(body, str) else body)["requests"]
        actual = {"mode": mode, "requests": tools.request_entries({"requests": requests})}
        for exchange in self.pool:
            if exchange["request"] == actual:
                return exchange
        raise AssertionError(f"server has no answer for {actual}")

    def _emit(self, exchange, body):
        text = body if isinstance(body, str) else json.dumps(body)
        request = SimpleNamespace(url=URL, method="POST", resource_type="xhr", post_data=text, headers={})
        response = SimpleNamespace(url=URL, status=exchange.get("status", 200), request=request,
                                   json=lambda: exchange["payload"])
        for callback in list(self.listeners["request"]):
            callback(request)
        for callback in list(self.listeners["response"]):
            callback(response)

    def evaluate(self, script, args):
        exchange = self._answer("fetch", args["body"])
        self._emit(exchange, args["body"])
        status = exchange.get("status", 200)
        return {"status": status, "ok": status == 200, "payload": exchange["payload"], "text": ""}

    def fill(self, query):
        params = {"query": query, "page": "0", "hitsPerPage": "5", **self.ui_extra}
        body = json.dumps({"requests": [{"indexName": "beer", "params": urlencode(params)}]})
        self._emit(self._answer("ui", body), body)


def with_ui_extra(case, extra):
    pool = copy.deepcopy(case["exchanges"])
    for exchange in pool:
        for request in exchange["request"]["requests"]:
            request["params"].update(extra)
    return pool


def record(pool, search, ui_extra=None):
    transport.reset_search_transport_authority_state()
    recorder = tools.RecordingPage(ServerPage(pool, ui_extra))
    with contextlib.redirect_stdout(io.StringIO()):
        result = matcher._search_one_impl(recorder, **search)
    recorder.close()
    transport.reset_search_transport_authority_state()
    return result, recorder


def consumed_hit_fields():
    fields = set()
    for path in sorted(Path(untap.__file__).parent.glob("*.py")):
        for func in [n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)]:
            names = {a.arg for a in func.args.args if a.arg == "hit"}
            names |= {"hit" for n in ast.walk(func) if isinstance(n, ast.For) and getattr(n.target, "id", None) == "hit"}
            for node in ast.walk(func):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                        and getattr(node.func.value, "id", None) in names and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    fields.add(node.args[0].value)
                if (isinstance(node, ast.Subscript) and getattr(node.value, "id", None) in names
                        and isinstance(node.slice, ast.Constant)):
                    fields.add(node.slice.value)
    return fields


class AllowlistTests(unittest.TestCase):
    def test_allowlist_covers_every_hit_field_read_by_runtime_code(self):
        consumed = consumed_hit_fields()
        self.assertTrue({"alias_alt", "beer_ibu", "in_production"} <= consumed)   # sanity: optional readers found
        self.assertEqual(sorted(consumed - set(tools.ALLOWED_HIT_FIELDS)), [])

    def test_allowlist_has_no_unconsumed_fields(self):
        self.assertEqual(sorted(set(tools.ALLOWED_HIT_FIELDS) - consumed_hit_fields()), [])

    def test_shape_canary_fields_are_all_preserved(self):
        self.assertTrue((set(transport._ALGOLIA_REQUIRED_HIT_FIELDS) | set(transport._ALGOLIA_CONFIRMATION_HIT_FIELDS)) <= set(tools.ALLOWED_HIT_FIELDS))
        self.assertTrue(set(transport._ALGOLIA_REQUIRED_RESULT_FIELDS) - {"hits"} <= set(tools.RESULT_FIELDS))


class SanitizeTests(unittest.TestCase):
    def hit(self, **extra):
        base = {"beer_name": "Fazy (2026)", "brewery_name": "Badlands Brewing Company", "beer_abv": 6.66, "bid": 6736235,
                "beer_slug": "badlands-brewing-company-fazy-2026", "type_name": "IPA - American", "in_production": False,
                "alias_alt": ["Fazy"], "beer_ibu": 45, "rating_score": 4.3123, "rating_count": 109}
        base.update(extra)
        return base

    def payload(self, hits, **result):
        return {"results": [{"index": "beer", "page": 0, "nbPages": 3, "nbHits": 14, "hitsPerPage": 5, "hits": hits, **result}]}

    def test_identity_and_original_paging_are_unchanged_even_when_counts_exceed_the_saved_page(self):
        clean, _ = tools.sanitize_payload(self.payload([self.hit()]))
        result = clean["results"][0]
        self.assertEqual((result["nbHits"], result["nbPages"], result["page"], result["hitsPerPage"]), (14, 3, 0, 5))
        self.assertEqual(len(result["hits"]), 1)             # nbHits is original, not len(hits)
        kept = result["hits"][0]
        for key in ("beer_name", "brewery_name", "beer_abv", "bid", "beer_slug", "type_name", "in_production",
                    "alias_alt", "beer_ibu"):
            self.assertEqual(kept[key], self.hit()[key], key)
        self.assertIs(kept["in_production"], False)

    def test_unconsumed_fields_are_dropped_and_reported(self):
        clean, report = tools.sanitize_payload(self.payload(
            [self.hit(auth_rating=5, brewery_id=9, _highlightResult={"x": 1})], processingTimeMS=3, params="query=x"))
        self.assertEqual(sorted(clean["results"][0]["hits"][0]), sorted(self.hit()))
        self.assertNotIn("processingTimeMS", clean["results"][0])
        self.assertEqual(report["dropped_fields"], ["_highlightResult", "auth_rating", "brewery_id", "params", "processingTimeMS"])

    def test_rating_distinctions_survive_masking(self):
        hits = [self.hit(bid=1, rating_score=0, rating_count=0), self.hit(bid=2, rating_score=3.1, rating_count=2),
                self.hit(bid=3, rating_score=None, rating_count=None), self.hit(bid=4, rating_score=4.9, rating_count=40000)]
        out = tools.sanitize_payload(self.payload(hits))[0]["results"][0]["hits"]
        self.assertEqual([(h["rating_score"], h["rating_count"]) for h in out],
                         [(0, 0), (4.0, 100), (None, None), (4.0, 100)])
        self.assertTrue(all(isinstance(h["rating_count"], (int, type(None))) for h in out))

    def test_unexpected_value_types_stay_visible_to_the_shape_canary(self):
        clean, _ = tools.sanitize_payload(self.payload([self.hit(rating_count="many")]))
        self.assertIn("hit.rating_count: missing or unexpected type", transport.algolia_response_shape_issues(clean))

    def test_only_untappd_asset_labels_are_kept(self):
        good, bad = "https://assets.untappd.com/site/beer_logos/a.jpeg", "https://evil.example/x.png"
        out = tools.sanitize_payload(self.payload([self.hit(beer_label=good, beer_label_hd=bad)]))
        hit = out[0]["results"][0]["hits"][0]
        self.assertEqual((hit["beer_label"], hit["beer_label_hd"]), (good, None))
        self.assertEqual(out[1]["labels_removed"], 1)

    def test_sanitizing_twice_changes_nothing(self):
        once, _ = tools.sanitize_payload(self.payload([self.hit()]))
        self.assertEqual(tools.sanitize_payload(once)[0], once)

    def test_every_shipped_case_is_already_sanitized(self):
        for path in sorted(CASES.glob("*.json")):
            with self.subTest(case=path.stem):
                for exchange in json.loads(path.read_text(encoding="utf-8"))["exchanges"]:
                    if exchange.get("status", 200) == 200:
                        payload = exchange["payload"]
                        self.assertEqual(tools.sanitize_payload(payload, keep_ratings=True)[0], payload)


class RecordingTests(unittest.TestCase):
    def test_full_flow_records_every_exchange_once_and_replays_strictly(self):
        case = load("conditional_expansion")                 # primary page plus expansion page(s)
        result, recorder = record(case["exchanges"], case["search"])
        draft = tools.build_draft(recorder.exchanges, case["search"], captured_on="2026-10-13")
        self.assertEqual([e["request"] for e in draft["exchanges"]], [e["request"] for e in case["exchanges"]])
        self.assertGreater(len(draft["exchanges"]), 1)       # expansion pages were captured too
        first = draft["exchanges"][0]["payload"]["results"][0]
        self.assertEqual((first["nbHits"], first["nbPages"]),
                         tuple(case["exchanges"][0]["payload"]["results"][0][k] for k in ("nbHits", "nbPages")))
        expected = {key: result.get(key) for key in case["expected"]}
        final = tools.finalize(draft, expected)
        self.assertEqual(tools.replay_case(final)[2], [])
        self.assertIn("2026-10-13", final["provenance"])

    def test_captured_ui_parameters_are_replayed_and_a_wrong_query_is_detected(self):
        base = load("fallback_metadata")                     # UI search plus two direct fetches
        extra = {"facets": "[\"type_name\"]", "attributesToRetrieve": "beer_name,bid"}
        result, recorder = record(with_ui_extra(base, extra), base["search"], ui_extra=extra)
        draft = tools.build_draft(recorder.exchanges, base["search"])
        for exchange in draft["exchanges"]:
            self.assertEqual({k: exchange["request"]["requests"][0]["params"][k] for k in extra}, extra)
        final = tools.finalize(draft, {key: result.get(key) for key in base["expected"]})
        self.assertEqual(tools.replay_case(final)[2], [])
        wrong = copy.deepcopy(final)
        wrong["search"]["query"] = "Badlands Fazy Typo"
        self.assertTrue(tools.replay_case(wrong)[2])

    def test_rate_limited_recordings_are_refused(self):
        exchanges = [{"request": {"mode": "ui", "requests": []}, "status": 429, "payload": None}]
        with self.assertRaisesRegex(tools.CaptureRefused, "429"):
            tools.build_draft(exchanges, {})

    def test_other_non_200_and_empty_recordings_are_refused(self):
        with self.assertRaises(tools.CaptureRefused):
            tools.build_draft([{"request": {}, "status": 500, "payload": None}], {})
        with self.assertRaises(tools.CaptureRefused):
            tools.build_draft([], {})

    def test_shape_issues_after_the_first_exchange_are_refused(self):
        case = load("fallback_metadata")
        broken = copy.deepcopy(case["exchanges"])
        del broken[-1]["payload"]["results"][0]["hits"][0]["bid"]
        with self.assertRaisesRegex(tools.CaptureRefused, "exchange 3"):
            tools.build_draft(broken, case["search"])

    def test_expected_values_are_never_inferred(self):
        case = load("fallback_metadata")
        draft = tools.build_draft(copy.deepcopy(case["exchanges"]), case["search"])
        self.assertIsNone(draft["expected"])
        with self.assertRaisesRegex(tools.CaptureRefused, "explicitly"):
            tools.finalize(draft, {})

    def test_a_wrong_expectation_fails_strict_replay(self):
        case = load("fallback_metadata")
        draft = tools.build_draft(copy.deepcopy(case["exchanges"]), case["search"])
        with self.assertRaisesRegex(tools.CaptureRefused, "expected status"):
            tools.finalize(draft, {"status": "failed"})

    def test_incomplete_recordings_fail_strict_replay(self):
        case = load("conditional_expansion")
        draft = tools.build_draft(copy.deepcopy(case["exchanges"][:1]), case["search"])   # expansion page missing
        with self.assertRaisesRegex(tools.CaptureRefused, "strict replay failed"):
            tools.finalize(draft, {"status": case["expected"]["status"]})

    def test_draft_files_are_never_picked_up_as_cases(self):
        self.assertFalse(list(CASES.glob("*.draft")) and list(CASES.glob("*.json.draft"))[0].match("*.json"))
        self.assertEqual([p.name for p in Path(CASES).glob("*.json") if p.name.endswith(".draft")], [])


class CaptureSafeguardTests(unittest.TestCase):
    def draft(self):
        case = load("fallback_metadata")
        return tools.build_draft(copy.deepcopy(case["exchanges"]), case["search"])

    def test_promotion_revalidates_every_status_in_an_edited_draft(self):
        for status in (429, 500):
            for number in (0, 2):
                with self.subTest(status=status, exchange=number):
                    draft = self.draft()
                    draft["exchanges"][number]["status"] = status
                    with self.assertRaises(tools.CaptureRefused):
                        tools.finalize(draft, {"status": "rate_limited" if status == 429 else "ok"})

    def test_first_response_shape_is_refused_even_with_a_synthetic_annotation(self):
        draft = self.draft()
        del draft["exchanges"][0]["payload"]["results"][0]["nbPages"]
        draft["shape_issues"] = ["result.nbPages: missing or unexpected type"]
        for validate in (lambda: tools.build_draft(draft["exchanges"], draft["search"]),
                         lambda: tools.finalize(draft, {"status": "ok"})):
            with self.assertRaisesRegex(tools.CaptureRefused, "exchange 1.*shape"):
                validate()

    def test_edited_drafts_cannot_promote_unconsumed_fields(self):
        draft = self.draft()
        draft["exchanges"][-1]["payload"]["unconsumed"] = "must not land"
        with self.assertRaisesRegex(tools.CaptureRefused, "unsanitized"):
            tools.finalize(draft, {"status": "ok"})

    def test_malformed_ui_json_retains_status_and_prevents_more_traffic(self):
        for status in (429, 500, 200):
            with self.subTest(status=status):
                live = mock.Mock()
                recorder = tools.RecordingPage(live)
                response = SimpleNamespace(url=URL, status=status,
                    request=SimpleNamespace(method="POST", post_data=json.dumps({"requests": [{"indexName": "beer", "params": "query=Beer"}]})),
                    json=mock.Mock(side_effect=ValueError("not JSON")))
                recorder._on_response(response)
                self.assertEqual(len(recorder.exchanges), 1)
                self.assertEqual(recorder.exchanges[0]["status"], status)
                self.assertIsNone(recorder.exchanges[0]["payload"])
                with self.assertRaises(tools.CaptureRefused):
                    tools.build_draft(recorder.exchanges, {})
                with self.assertRaises(tools.CaptureRefused):
                    recorder.evaluate("script", {"url": URL, "body": {"requests": []}})
                with self.assertRaises(tools.CaptureRefused):
                    recorder.goto("https://untappd.com/search")
                live.evaluate.assert_not_called()
                live.goto.assert_not_called()
                recorder.close()

    def test_malformed_ui_request_cannot_disappear(self):
        recorder = tools.RecordingPage(mock.Mock())
        response = SimpleNamespace(url=URL, status=200,
            request=SimpleNamespace(method="POST", post_data="invalid JSON"),
            json=lambda: load("fallback_metadata")["exchanges"][0]["payload"])
        recorder._on_response(response)
        self.assertEqual(len(recorder.exchanges), 1)
        with self.assertRaisesRegex(tools.CaptureRefused, "request"):
            tools.build_draft(recorder.exchanges, {})
        recorder.close()

    def test_failed_direct_fetch_is_recorded_and_cannot_be_retried(self):
        live = mock.Mock()
        live.evaluate.side_effect = RuntimeError("fetch failed")
        recorder = tools.RecordingPage(live)
        args = {"url": URL, "body": {"requests": [{"indexName": "beer", "params": "query=Beer"}]}}
        with self.assertRaises(RuntimeError):
            recorder.evaluate("script", args)
        self.assertEqual(len(recorder.exchanges), 1)
        self.assertIsNone(recorder.exchanges[0]["status"])
        with self.assertRaises(tools.CaptureRefused):
            recorder.evaluate("script", args)
        self.assertEqual(live.evaluate.call_count, 1)
        recorder.close()

    def test_failed_flow_removes_listener_and_saves_no_draft(self):
        live = ServerPage([])
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(tools, "CORPUS", Path(folder)), \
             mock.patch.object(transport, "untappd_browser_page", return_value=contextlib.nullcontext(live)), \
             mock.patch.object(matcher, "search_one", side_effect=RuntimeError("flow failed")), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(tools.main(["record", "failed", "--brewery", "Badlands", "--beer", "Fazy", "--abv", "6.5"]), 2)
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertFalse(any(live.listeners.values()))
        self.assertFalse(transport.search_transport_template_available())

    def test_expectations_require_known_fields_and_an_explicit_status(self):
        for expected in ({}, {"url": "example"}, {"status": "ok", "typo": None},
                         {"status": "unknown"}, {"status": []}):
            with self.subTest(expected=expected), self.assertRaises(tools.CaptureRefused):
                tools.finalize(self.draft(), expected)
        for item in ("status", "=ok"):
            with self.assertRaises(tools.CaptureRefused):
                tools._parse_expect([item])

    def test_negative_rating_values_are_not_masked_into_positive_values(self):
        payload = SanitizeTests().payload([SanitizeTests().hit(rating_count=-1, rating_score=-1)])
        hit = tools.sanitize_payload(payload)[0]["results"][0]["hits"][0]
        self.assertEqual((hit["rating_count"], hit["rating_score"]), (-1, -1))

    def test_complete_ui_batches_record_and_replay_with_queryless_requests(self):
        base = load("fallback_metadata")
        pool = copy.deepcopy(base["exchanges"])
        for exchange in pool:
            exchange["request"]["requests"].append({"index": "beer_aux", "params": {"page": "0", "hitsPerPage": "5"}})
            result = copy.deepcopy(exchange["payload"]["results"][0])
            result.update(index="beer_aux", hits=[], nbHits=0, nbPages=0)
            exchange["payload"]["results"].append(result)

        class BatchServerPage(ServerPage):
            def fill(self, query):
                entries = pool[0]["request"]["requests"]
                requests = []
                for entry in entries:
                    params = dict(entry["params"])
                    if "query" in params:
                        params["query"] = query
                    requests.append({"indexName": entry["index"], "params": urlencode(params)})
                body = {"requests": requests}
                self._emit(self._answer("ui", body), body)

        transport.reset_search_transport_authority_state()
        self.addCleanup(transport.reset_search_transport_authority_state)
        live = BatchServerPage(pool)
        recorder = tools.RecordingPage(live)
        with contextlib.redirect_stdout(io.StringIO()):
            matcher._search_one_impl(recorder, **base["search"])
        recorder.close()
        draft = tools.build_draft(recorder.exchanges, base["search"])
        self.assertEqual([e["request"] for e in draft["exchanges"]], [e["request"] for e in pool])
        self.assertEqual(len(draft["exchanges"][0]["request"]["requests"]), 2)
        final = tools.finalize(draft, base["expected"])
        wrong = copy.deepcopy(final)
        wrong["search"]["query"] += " Typo"
        with self.assertRaisesRegex(tools.CaptureRefused, "strict replay"):
            tools.finalize(wrong, base["expected"])


class CommandLineTests(unittest.TestCase):
    def test_record_then_finalize_round_trip_and_refusals(self):
        base = load("fallback_metadata")

        @contextlib.contextmanager
        def fake_browser():
            yield ServerPage(copy.deepcopy(base["exchanges"]))

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(tools, "CORPUS", Path(folder)), \
                mock.patch.object(transport, "untappd_browser_page", fake_browser), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tools.main(["record", "demo", "--brewery", "Badlands", "--beer", "Fazy", "--abv", "6.5"]), 0)
            draft = Path(folder) / "demo.json.draft"
            self.assertTrue(draft.exists())
            self.assertIsNone(json.loads(draft.read_text(encoding="utf-8"))["expected"])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(tools.main(["finalize", "demo"]), 2)               # no --expect: refused
            self.assertFalse((Path(folder) / "demo.json").exists())
            self.assertEqual(tools.main(["finalize", "demo", "--expect", "status=ok",
                                         "--expect", "url=https://untappd.com/b/badlands-fazy/10"]), 0)
            self.assertTrue((Path(folder) / "demo.json").exists())
            self.assertFalse(draft.exists())


if __name__ == "__main__":
    unittest.main()


class LiveCaptureReplayTests(unittest.TestCase):
    def test_navigation_bootstrap_precedes_typed_search(self):
        case = load("live_badlands_fazy")
        result, page, problems = tools.replay_case(case)
        self.assertEqual(problems, [])
        self.assertEqual(result["url"], case["expected"]["url"])
        self.assertNotIn("query", page.requests[0]["requests"][0]["params"])
        self.assertEqual(page.requests[1]["requests"][0]["params"]["query"], case["search"]["query"])
        self.assertFalse(page.exchanges)
        self.assertFalse(any(page.listeners.values()))

    def test_wrong_typed_query_still_fails_after_bootstrap(self):
        case = load("live_badlands_fazy")
        case["search"]["query"] = "Wrong search"
        _, _, problems = tools.replay_case(case)
        self.assertTrue(problems)

    def test_exact_match_skips_expansion_despite_multiple_pages(self):
        case = load("live_guinness_draught")
        self.assertGreater(case["exchanges"][1]["payload"]["results"][0]["nbPages"], 1)
        _, page, problems = tools.replay_case(case)
        self.assertEqual(problems, [])
        self.assertEqual([r["mode"] for r in page.requests], ["ui", "ui"])


class FinalizePromotionTests(unittest.TestCase):
    def draft(self):
        case = load("fallback_metadata")
        return tools.build_draft(copy.deepcopy(case["exchanges"]), case["search"])

    def test_synthetic_shape_issue_annotations_are_refused_for_live_drafts(self):
        draft = self.draft()
        draft["shape_issues"] = ["hit.bid: missing or unexpected type"]
        with self.assertRaisesRegex(tools.CaptureRefused, "unsupported fields"):
            tools.finalize(draft, {"status": "ok"})

    def test_unknown_draft_fields_are_never_promoted(self):
        draft = self.draft()
        draft["note"] = "hand edited"
        with self.assertRaisesRegex(tools.CaptureRefused, "unsupported fields"):
            tools.finalize(draft, {"status": "ok"})

    def test_search_and_provenance_must_be_present(self):
        draft = self.draft()
        del draft["provenance"]
        with self.assertRaisesRegex(tools.CaptureRefused, "provenance"):
            tools.finalize(draft, {"status": "ok"})
