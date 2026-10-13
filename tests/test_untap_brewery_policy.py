"""Policy reasons and compatibility are shared by recovery and eligibility."""
import unittest
from untap.brewery_policy import brewery_verdict
import untap.matcher as matcher
class BreweryPolicyTests(unittest.TestCase):
    def test_verdicts_preserve_brewery_evidence_rules(self):
        for candidate, expected, kind in [
            ("Badlands Brewing Company", "Badlands", "compatible"),
            ("Elsewhere Brewing", "Badlands", "conflicting"),
            ("Unknown", "Badlands", "unknown"), (None, "Badlands", "unknown"),
            ("Elsewhere", None, "unknown"), ("Brewing Company", "Badlands", "unknown"),
            ("To Øl", "To Øl", "compatible"), ("To Else", "To Øl", "conflicting"),
            ("Brasserie du Bas-Canada", "BBC", "conflicting")]:
            with self.subTest(candidate=candidate, expected=expected):
                verdict = brewery_verdict(candidate, expected)
                self.assertEqual(verdict.kind, kind)
                self.assertEqual(matcher.candidate_has_brewery_overlap({"brewery": candidate}, expected), kind != "conflicting")
                if kind == "conflicting":
                    self.assertEqual(verdict.reason, f"Brewery does not match menu brewery {expected}")
