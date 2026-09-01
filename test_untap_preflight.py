import builtins
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap


class MenuPreflightBoundaryTests(unittest.TestCase):
    def _forbid_playwright_import(self):
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "playwright" or name.startswith("playwright."):
                raise AssertionError("Playwright was imported during local menu preflight")
            return real_import(name, *args, **kwargs)

        return mock.patch("builtins.__import__", side_effect=guarded_import)

    def _temp_menu(self, text):
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        )
        try:
            handle.write(text)
            return handle.name
        finally:
            handle.close()

    def test_invalid_menu_aborts_before_playwright_import(self):
        filename = self._temp_menu(
            "Badlands\tPop Pop (2026)\t6.5%\tIPA\n"
            "Brujos\tLament\t5.3%\n"
        )
        output = io.StringIO()
        try:
            with self._forbid_playwright_import(), mock.patch.object(
                sys, "argv", ["untap.py", "--menu", filename]
            ), contextlib.redirect_stdout(output):
                with self.assertRaises(SystemExit) as exc:
                    untap.main()
            self.assertEqual(exc.exception.code, 1)
            self.assertIn("Menu validation failed.", output.getvalue())
            self.assertIn("No Untappd queries were made.", output.getvalue())
        finally:
            os.unlink(filename)

    def test_validate_menu_with_debug_timing_is_browser_free(self):
        filename = self._temp_menu(
            "Badlands\tPop Pop (2026)\t6.5%\tIPA\n"
        )
        output = io.StringIO()
        try:
            with self._forbid_playwright_import(), mock.patch.object(
                sys,
                "argv",
                ["untap.py", "--debug-timing", "--validate-menu", filename],
            ), contextlib.redirect_stdout(output):
                untap.main()
            self.assertIn("Menu validation succeeded.", output.getvalue())
            self.assertIn("No Untappd queries were made.", output.getvalue())
            self.assertNotIn("Search timing summary", output.getvalue())
        finally:
            os.unlink(filename)


    def test_help_is_browser_free(self):
        for flag in ("--help", "-h"):
            output = io.StringIO()
            with self.subTest(flag=flag), self._forbid_playwright_import(), mock.patch.object(
                sys, "argv", ["untap.py", flag]
            ), contextlib.redirect_stdout(output):
                untap.main()
            text = output.getvalue()
            self.assertIn("Usage:", text)
            self.assertIn("--debug-timing", text)
            self.assertIn("--smoke-test", text)
            self.assertNotIn("Searching Untappd", text)

    def test_invalid_smoke_test_combination_is_browser_free(self):
        output = io.StringIO()
        with self._forbid_playwright_import(), mock.patch.object(
            sys, "argv", ["untap.py", "--smoke-test", "Brujos Lament"]
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc:
                untap.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("standalone live integration check", output.getvalue())


    def test_invalid_html_without_batch_input_is_browser_free(self):
        output = io.StringIO()
        with self._forbid_playwright_import(), mock.patch.object(
            sys, "argv", ["untap.py", "--html"]
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc:
                untap.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("--html requires --menu or --file", output.getvalue())

    def test_v76_historical_structured_fixtures_validate_browser_free(self):
        fixture_dir = Path(__file__).with_name("testdata")
        expected = {
            "menu2.txt": ("Brewery-heading blocks", "Normalized records: 4"),
            "menu3.txt": ("Beer/style + ABV/IBU/brewery pairs", "Normalized records: 2"),
            "menu4.txt": ("Tap-list blocks", "Normalized records: 3"),
        }

        for filename, (format_name, record_count) in expected.items():
            output = io.StringIO()
            path = str(fixture_dir / filename)
            with self.subTest(filename=filename), self._forbid_playwright_import(), mock.patch.object(
                sys, "argv", ["untap.py", "--validate-menu", path]
            ), contextlib.redirect_stdout(output):
                untap.main()
            text = output.getvalue()
            self.assertIn("Menu validation succeeded.", text)
            self.assertIn(format_name, text)
            self.assertIn(record_count, text)
            self.assertIn("No Untappd queries were made.", text)

    def test_validate_menu_is_browser_free(self):
        filename = self._temp_menu(
            "Badlands\tPop Pop (2026)\t6.5%\tIPA\n"
        )
        output = io.StringIO()
        try:
            with self._forbid_playwright_import(), mock.patch.object(
                sys, "argv", ["untap.py", "--validate-menu", filename]
            ), contextlib.redirect_stdout(output):
                untap.main()
            self.assertIn("Menu validation succeeded.", output.getvalue())
            self.assertIn("No Untappd queries were made.", output.getvalue())
        finally:
            os.unlink(filename)


if __name__ == "__main__":
    unittest.main()
