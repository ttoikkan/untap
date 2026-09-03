"""Offline output-lifecycle regression checks."""
import contextlib
from datetime import datetime
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import untap


class RunDirectoryTests(unittest.TestCase):
    def test_same_second_runs_preserve_existing_output_and_sanitize_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                with mock.patch.object(untap, "datetime") as clock:
                    clock.now.return_value = datetime(2026, 9, 4, 9, 15, 30)
                    first = untap.create_run_directory("menu.txt", "../Nailo -- / Arrivals")
                    (first / "results.csv").write_text("earlier", encoding="utf-8")
                    second = untap.create_run_directory("menu.txt", "../Nailo -- / Arrivals")
                    fallback = untap.create_run_directory("/menus/Pien.txt", None)
                self.assertEqual(first.name, "2026-09-04_091530_nailo-arrivals")
                self.assertEqual(second.name, first.name + "-1")
                self.assertTrue(fallback.name.endswith("_pien"))
                self.assertEqual(first.parent, Path(tmp).resolve() / "results")
                self.assertEqual((first / "results.csv").read_text(), "earlier")
            finally:
                os.chdir(previous)

    def test_removed_options_fail_before_browser_or_output(self):
        for flag in ("--csv", "--csv=old.csv", "--resume", "--resume-from"):
            with self.subTest(flag=flag), mock.patch.object(sys, "argv", ["untap.py", flag]), \
                 mock.patch.object(untap, "untappd_browser_page") as browser, \
                 mock.patch.object(untap, "create_run_directory") as directory, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as error:
                    untap.main()
                self.assertEqual(error.exception.code, 1)
                self.assertIn("not supported in v87", output.getvalue())
                browser.assert_not_called()
                directory.assert_not_called()

    def test_batch_modes_write_paired_outputs_and_preserve_previous_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                Path("menu.txt").write_text("Badlands\tPop Pop\t6.5%\tIPA\n")
                Path("beers.txt").write_text("Badlands Pop Pop\n")
                for mode, source, html in (("--menu", "menu.txt", True),
                                            ("--file", "beers.txt", True),
                                            ("--file", "beers.txt", False)):
                    argv = ["untap.py", mode, source] + (["--html"] if html else [])
                    with mock.patch.object(sys, "argv", argv), \
                         mock.patch.object(untap, "untappd_browser_page", return_value=contextlib.nullcontext(object())), \
                         mock.patch.object(untap, "run_batch", return_value=[]) as batch, \
                         contextlib.redirect_stdout(io.StringIO()) as output:
                        untap.main()
                    self.assertNotIn("resume_rows", batch.call_args.kwargs)
                    self.assertIn("Run outputs:", output.getvalue())
                folders = list(Path("results").iterdir())
                self.assertEqual(len(folders), 3)
                self.assertEqual(len(list(Path("results").glob("*/results.csv"))), 3)
                self.assertEqual(len(list(Path("results").glob("*/results.html"))), 2)
                self.assertFalse(Path("results.csv").exists())
                self.assertFalse(Path("results.html").exists())
            finally:
                os.chdir(previous)
