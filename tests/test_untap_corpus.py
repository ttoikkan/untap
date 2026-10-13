"""Payload-shaped, hand-authored corpus, replayed only at Playwright I/O."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest

import untap.matcher as matcher
import untap.transport as transport
from tests.replay_page import ReplayPage

class SearchCorpusTests(unittest.TestCase):
    def test_strict_corpus(self):
        paths = sorted((Path(__file__).parent / "testdata/search_corpus").glob("*.json"))
        self.assertGreaterEqual(len(paths), 9, "Missing replay corpus")
        self.assertTrue({"s1_conflict_links", "s7_preserve_primary", "trailing_identity"} <= {p.stem for p in paths})
        for path in paths:
            with self.subTest(case=path.stem):
                case = json.loads(path.read_text())
                transport.reset_search_transport_authority_state()
                self.addCleanup(transport.reset_search_transport_authority_state)
                page = ReplayPage(case["exchanges"])
                with redirect_stdout(io.StringIO()):
                    result = matcher._search_one_impl(page, **case["search"])
                page.assert_complete(self)
                for key, value in case["expected"].items():
                    self.assertEqual(result.get(key), value, (key, result))
                self.assertEqual([r["url"] for r in result.get("excluded_candidates") or []], case.get("excluded_urls", []))

    def test_replay_rejects_unexpected_and_unused_requests(self):
        page = ReplayPage([])
        with self.assertRaises(AssertionError):
            page.fill("unexpected")
        with self.assertRaises(AssertionError):
            page.assert_complete(self)
        with self.assertRaises(AssertionError):
            ReplayPage([{}]).assert_complete(self)


class ResponseShapeCanaryTests(unittest.TestCase):
    def test_corpus_shape_and_optional_additions(self):
        folder = Path(__file__).parent / "testdata/search_corpus"
        for path in folder.glob("*.json"):
            case = json.loads(path.read_text())
            for exchange in case["exchanges"]:
                if exchange.get("status", 200) == 200:
                    payload = exchange["payload"]
                    payload["extra"] = "allowed"
                    expected = case.get("shape_issues", []) if exchange is case["exchanges"][0] else []
                    self.assertEqual(transport.algolia_response_shape_issues(payload), expected)

    def test_missing_and_changed_types_are_diagnostic(self):
        payload = {"results": [{"hits": [{"beer_name": 42}], "nbHits": "1", "page": 0, "nbPages": 1}]}
        issues = transport.algolia_response_shape_issues(payload)
        self.assertIn("result.nbHits: missing or unexpected type", issues)
        self.assertIn("hit.beer_name: missing or unexpected type", issues)
        self.assertIn("hit.bid: missing or unexpected type", issues)
