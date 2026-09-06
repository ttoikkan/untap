"""Small offline fixtures derived from the September Konttori run."""
import copy
import io
import unittest
from contextlib import redirect_stdout

import untap_matcher as matcher
import untap_report as report
import test_untap_v86 as fixtures


class KonttoriTests(unittest.TestCase):
    def test_dragons_milk_preserves_cap_warning_beside_family_reason(self):
        rows = [fixtures.candidate("Dragon's Milk", "New Holland Brewing", 11),
                fixtures.candidate("Dragon's Milk (2014)", "New Holland Brewing", 11, .95, 2)]
        result, _ = fixtures.MatcherV86Tests().run_search(
            rows, "Dragon's Milk", "New Holland", 11,
            diagnostics={"capped": True, "nbHits": 186})
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["reason"], "Multiple 11% variants found")
        self.assertIn("page limit", result["search_warning"])
        html = report.render_html_report([result])
        self.assertIn("Multiple 11% variants found", html)
        self.assertIn("Search incomplete", html)

    def test_complete_family_has_no_incomplete_warning(self):
        rows = [fixtures.candidate("Dragon's Milk", "New Holland Brewing", 11),
                fixtures.candidate("Dragon's Milk (2014)", "New Holland Brewing", 11, .95, 2)]
        result, _ = fixtures.MatcherV86Tests().run_search(rows, "Dragon's Milk", "New Holland", 11)
        self.assertIsNone(result["search_warning"])
        self.assertNotIn("Search incomplete", report.render_html_report([result]))

    def test_just_fruit_full_name_still_triggers_shared_prefix_rule(self):
        name = "Just Fruit (Pineapple, Orange, Mango)"
        rows = [fixtures.candidate(name, "Frequentem", 5.5),
                fixtures.candidate("Just Fruit (Pineapple, Cara Cara Orange, Mango)",
                                   "Frequentem", 5.5, .959, 2)]
        self.assertGreater(1 - .959, matcher.AMBIGUITY_SCORE_MARGIN)
        self.assertTrue(matcher.detect_candidate_ambiguity(rows, name, 5.5).startswith("Multiple candidates"))
        self.assertIsNone(matcher.exact_base_candidate(rows, name, "Frequentem", 5.5))

    def test_messorem_relaxation_retains_numbered_identity(self):
        for name, number in [("DESTRUCTIO", "0011"), ("TEMPORALIS", "0061")]:
            text = f"{name} #{number} - XTRM TURBO"
            queries = matcher.trailing_relaxation_search_queries(text, "MESSOREM")
            self.assertEqual(len(queries), 2)
            self.assertTrue(queries[-1].endswith(number))
            self.assertTrue(matcher.candidate_matches_trailing_relaxed_identity(
                {"name": f"{name} {number}"}, text))
            self.assertFalse(matcher.candidate_matches_trailing_relaxed_identity(
                {"name": f"{name} 9999"}, text))

    def test_style_diagnostic_observes_conflict_without_mutation(self):
        rows = [{"name": "Dragon's Milk", "type_name": "Stout - Imperial / Double"},
                {"name": "Dragon's Milk Emerald IPA", "type_name": "IPA - American"},
                {"name": "Unknown style", "type_name": None}]
        before = copy.deepcopy(rows)
        output = io.StringIO()
        with redirect_stdout(output):
            matcher.print_style_shadow(rows, "BARREL AGED IMPERIAL STOUT")
        self.assertEqual(rows, before)
        self.assertIn("Emerald IPA", output.getvalue())
        self.assertNotIn("Unknown style", output.getvalue())
        self.assertIn("diagnostic only", output.getvalue())

    def test_warning_is_escaped(self):
        html = report.render_html_report([{"query": "Beer", "status": "ambiguous",
                                          "search_warning": "<script>bad</script>"}])
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)

