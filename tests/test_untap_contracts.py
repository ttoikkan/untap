import ast
import csv
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap.run as untap
import untap.batch as untap_batch
import untap.matcher as untap_matcher
import untap.parser as untap_parser
import untap.transport as untap_untappd
class ArchitectureContractTests(unittest.TestCase):
    def test_normalized_menu_record_contract_is_explicit_and_exact(self):
        self.assertEqual(
            untap_parser.NORMALIZED_RECORD_FIELDS,
            ("brewery", "beer", "style", "menu_abv", "query", "original"),
        )
        item = untap_parser.parse_menu_lines(["Badlands\tFazy (2026)\t6.5%\tIPA"])[0]
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
            frozenset({"ok", "ambiguous", "low_confidence", "failed", "rate_limited", "not_attempted"}),
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
        with mock.patch.object(untap_batch, "_reset_run_algolia_debug_stats"),\
             mock.patch.object(untap_batch, "search_one", return_value=response) as search,\
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
        roots = Path(__file__).parent.parent
        imports = {}
        for path in (roots / "untap").rglob("*.py"):
            filename = str(path.relative_to(roots))
            tree = ast.parse((roots / filename).read_text(encoding="utf-8"))
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
            imports[filename] = modules

        self.assertTrue(imports["untap/parser.py"].isdisjoint(
            {"untap.matcher", "untap.transport", "untap.batch", "playwright"}
        ))
        self.assertNotIn("untap.matcher", imports["untap/transport.py"])
        self.assertNotIn("untap.batch", imports["untap/transport.py"])
        self.assertNotIn("untap.batch", imports["untap/matcher.py"])
        self.assertNotIn("untap.parser", imports["untap/batch.py"])
        self.assertIn("untap.matcher", imports["untap/batch.py"])
        self.assertIn("untap.transport", imports["untap/batch.py"])
        self.assertTrue(imports["untap/smoke.py"].isdisjoint(
            {"untap.parser", "untap.batch", "playwright"}
        ))
        self.assertIn("untap.matcher", imports["untap/smoke.py"])
        self.assertIn("untap.transport", imports["untap/smoke.py"])
        self.assertIn("untap.types", imports["untap/smoke.py"])
        self.assertTrue(imports["untap/report.py"].isdisjoint(
            {"untap.parser", "untap.matcher", "untap.batch", "untap.transport", "untap.smoke", "playwright"}
        ))
        self.assertIn("untap.types", imports["untap/report.py"])
        self.assertTrue(imports["untap/publish.py"].isdisjoint(
            {
                "untap.types", "untap.parser", "untap.matcher", "untap.batch",
                "untap.transport", "untap.smoke", "untap.report", "playwright",
            }
        ))
        self.assertNotIn("untap.publish", imports["untap/run.py"])
        self.assertNotIn("untap.publish", imports["untap/report.py"])

        graph = {name[:-3].replace("/", "."): set(modules) for name, modules in imports.items()}
        def reachable(module):
            seen = set()
            pending = list(graph.get(module, ()))
            while pending:
                dependency = pending.pop()
                if dependency in seen:
                    continue
                seen.add(dependency)
                pending.extend(graph.get(dependency, ()))
            return seen
        for module in ('untap.run', 'untap.registry', 'untap.report'):
            self.assertNotIn('untap.publish', reachable(module), module)
        for module in ('untap.types', 'untap.identity', 'untap.refresh_config'):
            self.assertFalse({name for name in reachable(module) if name.startswith('untap.')}, module)
        for module in ('untap.report', 'untap.snapshot', 'untap.publish', 'untap.run_output', 'untap.review_policy', 'untap.report_model'):
            self.assertTrue(reachable(module).isdisjoint({'untap.batch', 'untap.matcher', 'untap.transport', 'playwright'}), module)
        for module in graph:
            if module not in {'untap.cli', 'untap.__main__'}:
                self.assertNotIn('untap.cli', reachable(module), module)
        self.assertEqual({name for name in reachable("untap.brewery_policy") if name.startswith("untap.")}, {"untap.parser", "untap.types"})
        expected = {'untap.cli', 'untap.inspect', 'untap.local_review', 'untap.manual_candidates', 'untap.refresh', 'untap.refresh_config', 'untap.registry', 'untap.snapshot', 'untap.identity'}
        self.assertTrue(expected.issubset(graph))
        self.assertNotIn("untap.batch", reachable("untap.refresh"))
        self.assertEqual({name for name in reachable("untap.review_policy") if name.startswith("untap.")}, {"untap.types"})
        for filename in ("untap/refresh.py", "untap/local_review.py"):
            tree = ast.parse((roots / filename).read_text())
            renderer_imports = {alias.name for node in ast.walk(tree)
                                if isinstance(node, ast.ImportFrom) and node.module == "untap.report"
                                for alias in node.names}
            self.assertEqual(renderer_imports, {"render_html_report"})

    def test_importing_architecture_modules_remains_playwright_lazy(self):
        # The transport imports Playwright only inside untappd_browser_page().
        self.assertNotIn("playwright.sync_api", sys.modules)

    def test_cli_uses_owned_boundary_entry_points(self):
        self.assertIs(untap.run_batch, untap_batch.run_batch)
        self.assertIs(untap.search_one, untap_matcher.search_one)
        self.assertEqual(untap.write_run_outputs.__module__, 'untap.run_output')


if __name__ == "__main__":
    unittest.main()
