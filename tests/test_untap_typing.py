from pathlib import Path
from typing import get_args, get_type_hints
import inspect
import unittest

import untap.batch as untap_batch
import untap.matcher as untap_matcher
import untap.parser as untap_parser
from untap.types import AlternativeRecord, CsvRow, MatchResult, MatchStatus, NormalizedMenuRecord


ROOT = Path(__file__).resolve().parent.parent


class StaticContractTests(unittest.TestCase):
    def test_normalized_typed_dict_matches_runtime_record_contract(self):
        self.assertEqual(
            tuple(NormalizedMenuRecord.__annotations__),
            untap_parser.NORMALIZED_RECORD_FIELDS,
        )

    def test_csv_typed_dict_matches_runtime_csv_contract(self):
        self.assertEqual(
            tuple(CsvRow.__annotations__),
            untap_batch.CSV_FIELDS,
        )

    def test_ambiguity_candidate_contract_includes_canonical_type_name(self):
        self.assertIn("type_name", AlternativeRecord.__annotations__)

    def test_match_status_type_matches_runtime_status_vocabulary(self):
        self.assertEqual(
            frozenset(get_args(MatchStatus)),
            untap_matcher.MATCH_RESULT_STATUSES,
        )

    def test_boundary_entry_points_expose_typed_records(self):
        parser_hints = get_type_hints(untap_parser.validate_and_parse_menu_lines)
        matcher_hints = get_type_hints(untap_matcher.search_one)
        batch_hints = get_type_hints(untap_batch.run_batch)

        self.assertIn("NormalizedMenuRecord", str(parser_hints["return"]))
        self.assertIs(matcher_hints["return"], MatchResult)
        self.assertIn("NormalizedMenuRecord", str(batch_hints["items"]))
        self.assertIn("MatchResult", str(batch_hints["return"]))

    def test_type_contract_module_has_no_runtime_layer_dependencies(self):
        import ast
        tree = ast.parse((ROOT / 'untap/types.py').read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertTrue(imports.isdisjoint({'untap.parser', 'untap.matcher', 'untap.batch', 'untap.transport', 'playwright'}))

    def test_static_checker_is_pinned_for_local_use(self):
        requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        active = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(active, ["mypy==1.14.1"])

    def test_v74_transport_contract_types_are_present(self):
        from untap.types import AlgoliaRequestRecord, AlgoliaTransportEvent, SearchTransportResult
        self.assertIn('indexName', AlgoliaRequestRecord.__annotations__)
        self.assertIn('algolia_requests', AlgoliaTransportEvent.__annotations__)
        self.assertIn('request_event', SearchTransportResult.__annotations__)

    def test_type_hardening_does_not_change_search_one_parameter_order(self):
        self.assertEqual(
            tuple(inspect.signature(untap_matcher.search_one).parameters),
            (
                "page", "query", "min_score", "debug", "expected_beer",
                "expected_brewery", "expected_abv", "expected_style",
            ),
        )


if __name__ == "__main__":
    unittest.main()
