from pathlib import Path
from typing import get_args, get_type_hints
import inspect
import unittest

import untap_batch
import untap_matcher
import untap_parser
from untap_types import CsvRow, MatchResult, MatchStatus, NormalizedMenuRecord


ROOT = Path(__file__).resolve().parent


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
        source = (ROOT / "untap_types.py").read_text(encoding="utf-8")
        for forbidden in (
            "untap_parser", "untap_matcher", "untap_batch", "untap_untappd",
            "playwright",
        ):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)

    def test_static_checker_is_pinned_for_local_use(self):
        requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        active = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(active, ["mypy==1.14.1"])

    def test_v74_transport_contract_types_are_present(self):
        type_source = (ROOT / "untap_types.py").read_text(encoding="utf-8")
        self.assertIn("class AlgoliaRequestRecord", type_source)
        self.assertIn("class AlgoliaTransportEvent", type_source)
        self.assertIn("class SearchTransportResult", type_source)

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
