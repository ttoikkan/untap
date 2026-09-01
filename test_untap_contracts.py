import ast
import csv
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap
import untap_batch
import untap_matcher
import untap_parser
import untap_untappd


class ArchitectureContractTests(unittest.TestCase):
    def test_normalized_menu_record_contract_is_explicit_and_exact(self):
        self.assertEqual(
            untap_parser.NORMALIZED_RECORD_FIELDS,
            ("brewery", "beer", "style", "menu_abv", "query", "original"),
        )
        item = untap_parser.structured_menu_item(
            "Badlands\tFazy (2026)\t6.5%\tIPA",
            "Fazy (2026)",
            brewery="Badlands",
            style="IPA",
            menu_abv=6.5,
        )
        self.assertEqual(set(item), set(untap_parser.NORMALIZED_RECORD_FIELDS))
        self.assertIs(untap_parser.validate_normalized_menu([item])[0], item)

    def test_csv_schema_is_an_explicit_stable_contract(self):
        expected = (
            "original_menu_text", "input_brewery", "input_beer", "input_abv",
            "input_style", "query", "status", "beer", "brewery", "rating",
            "ratings", "abv", "ibu", "type_name", "score", "reason",
            "alternatives", "url",
        )
        self.assertEqual(untap_batch.CSV_FIELDS, expected)

        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        path = handle.name
        handle.close()
        try:
            with mock.patch("builtins.print"):
                untap_batch.save_csv([], path)
            with open(path, "r", encoding="utf-8", newline="") as f:
                self.assertEqual(tuple(next(csv.reader(f))), expected)
        finally:
            os.unlink(path)

    def test_matcher_entry_point_signature_is_stable(self):
        parameters = tuple(inspect.signature(untap_matcher.search_one).parameters)
        self.assertEqual(
            parameters,
            (
                "page", "query", "min_score", "debug", "expected_beer",
                "expected_brewery", "expected_abv", "expected_style",
            ),
        )
        self.assertEqual(
            untap_matcher.MATCH_RESULT_STATUSES,
            frozenset({"ok", "ambiguous", "low_confidence", "failed", "rate_limited"}),
        )

    def test_batch_forwards_normalized_identity_to_matcher(self):
        item = {
            "brewery": "Badlands",
            "beer": "Fazy (2026)",
            "style": "IPA",
            "menu_abv": 6.5,
            "query": "Badlands Fazy (2026)",
            "original": "Badlands\tFazy (2026)\t6.5%\tIPA",
        }
        response = {
            "query": item["query"],
            "status": "ok",
            "beer": "Fazy (2026)",
            "brewery": "Badlands Brewing Company",
            "rating": 4.3,
        }
        with mock.patch.object(untap_batch, "_reset_run_algolia_debug_stats"), \
             mock.patch.object(untap_batch, "search_one", return_value=response) as search, \
             mock.patch("builtins.print"):
            results = untap_batch.run_batch(object(), [item], min_score=0.5, debug=True)

        search.assert_called_once_with(
            mock.ANY,
            item["query"],
            min_score=0.5,
            debug=True,
            expected_beer="Fazy (2026)",
            expected_brewery="Badlands",
            expected_abv=6.5,
            expected_style="IPA",
        )
        self.assertEqual(results[0]["input_beer"], "Fazy (2026)")
        self.assertEqual(results[0]["input_abv"], "6.5")

    def test_dependency_graph_remains_one_way(self):
        roots = Path(__file__).parent
        imports = {}
        for filename in (
            "untap_parser.py", "untap_untappd.py", "untap_matcher.py",
            "untap_batch.py", "untap_smoke.py", "untap_report.py", "untap_publish.py", "untap.py",
        ):
            tree = ast.parse((roots / filename).read_text(encoding="utf-8"))
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
            imports[filename] = modules

        self.assertTrue(imports["untap_parser.py"].isdisjoint(
            {"untap_matcher", "untap_untappd", "untap_batch", "playwright"}
        ))
        self.assertNotIn("untap_matcher", imports["untap_untappd.py"])
        self.assertNotIn("untap_batch", imports["untap_untappd.py"])
        self.assertNotIn("untap_batch", imports["untap_matcher.py"])
        self.assertNotIn("untap_parser", imports["untap_batch.py"])
        self.assertIn("untap_matcher", imports["untap_batch.py"])
        self.assertIn("untap_untappd", imports["untap_batch.py"])
        self.assertTrue(imports["untap_smoke.py"].isdisjoint(
            {"untap_parser", "untap_batch", "playwright"}
        ))
        self.assertIn("untap_matcher", imports["untap_smoke.py"])
        self.assertIn("untap_untappd", imports["untap_smoke.py"])
        self.assertIn("untap_types", imports["untap_smoke.py"])
        self.assertTrue(imports["untap_report.py"].isdisjoint(
            {"untap_parser", "untap_matcher", "untap_batch", "untap_untappd", "untap_smoke", "playwright"}
        ))
        self.assertIn("untap_types", imports["untap_report.py"])
        self.assertTrue(imports["untap_publish.py"].isdisjoint(
            {
                "untap_types", "untap_parser", "untap_matcher", "untap_batch",
                "untap_untappd", "untap_smoke", "untap_report", "playwright",
            }
        ))
        self.assertNotIn("untap_publish", imports["untap.py"])
        self.assertNotIn("untap_publish", imports["untap_report.py"])

    def test_importing_architecture_modules_remains_playwright_lazy(self):
        # The transport imports Playwright only inside untappd_browser_page().
        self.assertNotIn("playwright.sync_api", sys.modules)

    def test_cli_contains_no_extraction_era_noop_wrapper_or_inline_history(self):
        source = Path(untap.__file__).read_text(encoding="utf-8")
        self.assertNotIn("finally:\n            # Browser/page lifecycle", source)
        self.assertNotIn("v59 changelog (relative to v58)", source)
        self.assertNotIn("def run_batch(", source)
        self.assertNotIn("def save_csv(", source)


if __name__ == "__main__":
    unittest.main()
