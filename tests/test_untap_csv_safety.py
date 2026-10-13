"""CSV output must not be interpretable as spreadsheet formulas."""
import csv
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from untap_run_output import save_csv


class CsvFormulaSafetyTests(unittest.TestCase):
    def test_formula_prefixes_are_neutralised_but_normal_values_unchanged(self):
        hostile = {"query": "q", "status": "ok", "beer": '=HYPERLINK("http://evil.example","x")',
                   "brewery": "+cmd|' /C calc'!A0", "reason": "-2+3", "url": "https://untappd.com/b/x/1",
                   "rating": 4.2, "ratings": 10, "abv": "6.5%", "original_menu_text": "@SUM(1)\tBeer\t5%\tIPA"}
        normal = {"query": "q2", "status": "ok", "beer": "Fazy (2026)", "brewery": "Badlands", "abv": "6.5%",
                  "rating": 4.3, "ratings": 109, "url": "https://untappd.com/b/y/2"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'results.csv'
            with mock.patch("builtins.print"):
                save_csv([hostile, normal], str(path))
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        for field in ("beer", "brewery", "reason", "original_menu_text"):
            self.assertTrue(rows[0][field].startswith("'"), (field, rows[0][field]))
        self.assertEqual(rows[0]["url"], "https://untappd.com/b/x/1")
        self.assertEqual((rows[1]["beer"], rows[1]["brewery"], rows[1]["abv"]), ("Fazy (2026)", "Badlands", "6.5%"))

    def test_every_formula_prefix_is_protected_in_regular_and_derived_cells(self):
        for prefix in ('=', '+', '-', '@', '\t', '\r'):
            with self.subTest(prefix=repr(prefix)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'results.csv'
                result = dict(query=prefix + 'Query', status='ok', beer=prefix + 'Beer',
                              brewery=prefix + 'Brewery',
                              alternatives=[dict(name=prefix + 'Candidate', score=.5, abv=5.)])
                with mock.patch('builtins.print'):
                    save_csv([result], str(path))
                with path.open(encoding='utf-8', newline='') as handle:
                    row = next(csv.DictReader(handle))
                for field in ('query', 'beer', 'brewery', 'alternatives'):
                    self.assertTrue(row[field].startswith("'" + prefix), field)

    def test_numeric_cells_and_existing_apostrophes_are_unchanged(self):
        result = dict(query="'Already text", status='ok', beer='Ordinary Beer',
                      rating=-2.5, ratings=0, abv=0.)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'results.csv'
            with mock.patch('builtins.print'):
                save_csv([result], str(path))
            with path.open(encoding='utf-8', newline='') as handle:
                row = next(csv.DictReader(handle))
        self.assertEqual(row['query'], "'Already text")
        self.assertEqual(row['rating'], '-2.5')
        self.assertEqual(row['ratings'], '0')
        self.assertEqual(row['abv'], '0.0')


if __name__ == "__main__":
    unittest.main()
