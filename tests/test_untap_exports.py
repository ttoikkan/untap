"""Intentional re-exports must be declared, so tooling and readers can tell them from dead imports."""
import ast
import importlib
from pathlib import Path
import unittest

import untap

PACKAGE = Path(untap.__file__).parent
DECLARING = ("report", "batch", "run")


def unused_imports(path):
    """Lightweight check of top-level imports; not a scope-aware general linter."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported[alias.asname or alias.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return {name: line for name, line in imported.items() if name not in used and name != "annotations"}


def declared_exports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in node.targets):
            return [elt.value for elt in node.value.elts]
    return []


class ExportDeclarationTests(unittest.TestCase):
    def test_declared_names_exist_and_are_unique(self):
        for name in DECLARING:
            with self.subTest(module=name):
                module = importlib.import_module(f"untap.{name}")
                names = module.__all__
                self.assertEqual(len(names), len(set(names)))
                for export in names:
                    self.assertTrue(hasattr(module, export), export)

    def test_every_unused_top_level_import_is_a_declared_export(self):
        """A new top-level import that nothing uses must be declared (or removed), never left ambiguous."""
        for path in sorted(PACKAGE.rglob("*.py")):
            with self.subTest(module=path.name):
                undeclared = {n: l for n, l in unused_imports(path).items() if n not in declared_exports(path)}
                self.assertEqual(undeclared, {}, f"{path.name}: undeclared unused imports")

    def test_compatibility_names_remain_declared_even_when_used_internally(self):
        required = {
            "report": {"DEFAULT_REPORT_TITLE", "selection_report_id", "_format_abv", "_format_rating",
                       "_result_sort_rating", "_review_candidates", "_sorted_report_results"},
            "batch": {"CSV_FIELDS", "save_csv"}, "run": {"save_csv"}}
        for name, exports in required.items():
            self.assertTrue(exports <= set(importlib.import_module(f"untap.{name}").__all__), name)

    def test_report_compatibility_aliases_still_point_at_the_policy_implementations(self):
        import untap.report as report
        import untap.report_model as model
        import untap.review_policy as policy
        self.assertIs(report._format_rating, model.format_rating)
        self.assertIs(report._format_abv, model.format_abv)
        self.assertIs(report._review_candidates, policy.review_candidates)
        self.assertIs(report._sorted_report_results, policy.sorted_review_results)
        self.assertIs(report._result_sort_rating, policy.result_sort_rating)

    def test_batch_and_run_save_csv_come_from_the_output_module(self):
        import untap.batch as batch
        import untap.run as run
        import untap.run_output as output
        self.assertIs(batch.save_csv, output.save_csv)
        self.assertIs(run.save_csv, output.save_csv)
        self.assertIs(batch.CSV_FIELDS, output.CSV_FIELDS)


if __name__ == "__main__":
    unittest.main()
