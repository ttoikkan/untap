import builtins
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap.run as untap
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
            "Brujos\tLament\n"
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
            "Badlands\tPop Pop (2026)\t6,5\n"
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
                with self.assertRaises(SystemExit) as exc:
                    untap.main()
                self.assertEqual(exc.exception.code, 0)
            text = output.getvalue()
            self.assertIn("usage:", text)
            self.assertIn("--debug-timing", text)
            self.assertIn("--smoke-test", text)
            self.assertIn("--report-title TITLE", text)
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


    def test_report_title_without_html_is_browser_free(self):
        output = io.StringIO()
        with self._forbid_playwright_import(), mock.patch.object(
            sys, "argv", ["untap.py", "--report-title", "Bottle Share"]
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc:
                untap.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("--report-title requires --menu or --file batch input", output.getvalue())

    def test_empty_report_title_is_browser_free(self):
        output = io.StringIO()
        with self._forbid_playwright_import(), mock.patch.object(
            sys, "argv", ["untap.py", "--html", "--report-title", "   "]
        ), contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as exc:
                untap.main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("--report-title requires a non-empty title", output.getvalue())

    def test_legacy_menu_is_rejected_before_browser(self):
        path = str(Path(__file__).with_name("testdata") / "menu2.txt")
        with self._forbid_playwright_import(), mock.patch.object(sys, "argv", ["untap.py", "--menu", path]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                untap.main()

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
