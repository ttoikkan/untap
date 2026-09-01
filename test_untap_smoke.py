import contextlib
import io
import sys
import unittest
from unittest import mock

import untap
import untap_smoke


class LiveSmokeContractTests(unittest.TestCase):
    @staticmethod
    def _ok(beer, brewery):
        return {
            "query": beer,
            "status": "ok",
            "beer": beer,
            "brewery": brewery,
            "rating": 4.0,
            "ratings": 100,
            "abv": "5%",
            "url": "https://untappd.com/b/example/1",
        }

    def test_healthy_smoke_requires_bootstrap_direct_and_algolia_confirmation(self):
        results = [
            self._ok("Pivo Hull", "Brasserie du Bas-Canada"),
            self._ok("Lament", "Brujos Brewing"),
        ]
        output = io.StringIO()
        with mock.patch.object(untap_smoke, "search_one", side_effect=results), \
             mock.patch.object(untap_smoke, "search_transport_template_available", return_value=True), \
             mock.patch.object(untap_smoke, "get_search_transport_authority_stats", return_value={"direct_searches": 1, "direct_rate_limited": 0}), \
             mock.patch.object(untap_smoke, "get_algolia_confirmation_stats", return_value={"confirmed_from_algolia": 2, "detail_page_fallbacks": 0}), \
             contextlib.redirect_stdout(output):
            code = untap_smoke.run_live_smoke_test(object())
        self.assertEqual(code, untap_smoke.SMOKE_EXIT_HEALTHY)
        text = output.getvalue()
        self.assertIn("UI bootstrap", text)
        self.assertIn("Direct transport", text)
        self.assertIn("Result: HEALTHY", text)
        self.assertIn("GitHub automation", text)
        self.assertIn("NOT USED", text)

    def test_smoke_rate_limit_is_distinct_exit(self):
        output = io.StringIO()
        with mock.patch.object(untap_smoke, "search_one", return_value={"status": "rate_limited"}), \
             contextlib.redirect_stdout(output):
            code = untap_smoke.run_live_smoke_test(object())
        self.assertEqual(code, untap_smoke.SMOKE_EXIT_RATE_LIMITED)
        self.assertIn("HTTP 429", output.getvalue())

    def test_smoke_rejects_detail_page_fallback_as_contract_degradation(self):
        results = [
            self._ok("Pivo Hull", "Brasserie du Bas-Canada"),
            self._ok("Lament", "Brujos Brewing"),
        ]
        with mock.patch.object(untap_smoke, "search_one", side_effect=results), \
             mock.patch.object(untap_smoke, "search_transport_template_available", return_value=True), \
             mock.patch.object(untap_smoke, "get_search_transport_authority_stats", return_value={"direct_searches": 1, "direct_rate_limited": 0}), \
             mock.patch.object(untap_smoke, "get_algolia_confirmation_stats", return_value={"confirmed_from_algolia": 1, "detail_page_fallbacks": 1}), \
             contextlib.redirect_stdout(io.StringIO()):
            code = untap_smoke.run_live_smoke_test(object())
        self.assertEqual(code, untap_smoke.SMOKE_EXIT_RESPONSE_CONTRACT)

    def test_smoke_identity_failure_is_distinct(self):
        results = [
            self._ok("Pivo Hull", "Brasserie du Bas-Canada"),
            self._ok("Different Beer", "Brujos Brewing"),
        ]
        with mock.patch.object(untap_smoke, "search_one", side_effect=results), \
             mock.patch.object(untap_smoke, "search_transport_template_available", return_value=True), \
             mock.patch.object(untap_smoke, "get_search_transport_authority_stats", return_value={"direct_searches": 1, "direct_rate_limited": 0}), \
             mock.patch.object(untap_smoke, "get_algolia_confirmation_stats", return_value={"confirmed_from_algolia": 2, "detail_page_fallbacks": 0}), \
             contextlib.redirect_stdout(io.StringIO()):
            code = untap_smoke.run_live_smoke_test(object())
        self.assertEqual(code, untap_smoke.SMOKE_EXIT_IDENTITY)

    def test_cli_smoke_is_standalone_and_propagates_exit_code(self):
        class FakeContext:
            def __enter__(self):
                return object()
            def __exit__(self, exc_type, exc, tb):
                return False

        with mock.patch.object(sys, "argv", ["untap.py", "--smoke-test"]), \
             mock.patch.object(untap, "untappd_browser_page", return_value=FakeContext()), \
             mock.patch.object(untap_smoke, "run_live_smoke_test", return_value=0):
            untap.main()

        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["untap.py", "--smoke-test", "Brujos Lament"]), \
             contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc:
                untap.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("standalone live integration check", output.getvalue())


if __name__ == "__main__":
    unittest.main()
