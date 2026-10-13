"""Default HTML/JSON and opt-in CSV output regressions."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import untap.run as untap
from untap.refresh import refresh, main as refresh_main
from untap.local_review import ReviewSession
from untap.snapshot import build_snapshot, save_snapshot
from untap.report import selection_report_id


class OutputTests(unittest.TestCase):
    def test_batch_csv_flag_and_default_html(self):
        for csv in (False, True):
            with self.subTest(csv=csv), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                menu = root / 'menu.txt'
                menu.write_text('Brewery\tBeer\t5%\tIPA\n')
                output = root / 'run'
                output.mkdir()
                args = ['untap.py', '--menu', str(menu), '--report-title', 'Menu'] + (['--csv'] if csv else [])
                with patch.object(sys, 'argv', args), patch.object(untap, 'create_run_directory', return_value=output), patch.object(untap, 'untappd_browser_page', return_value=contextlib.nullcontext(object())), patch.object(untap, 'run_batch', return_value=[]), contextlib.redirect_stdout(io.StringIO()):
                    untap.main()
                self.assertTrue((output / 'results.html').exists())
                self.assertTrue((output / 'results.json').exists())
                self.assertEqual((output / 'results.csv').exists(), csv)

    def test_refresh_and_local_review_csv_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            snapshot = build_snapshot([{'query': 'Beer', 'status': 'failed', 'reason': 'No match'}], 'Menu')
            save_snapshot(snapshot, source / 'results.json')
            before = (source / 'results.json').read_bytes()
            for csv in (False, True):
                refreshed = refresh(source, csv_requested=csv)
                self.assertEqual((refreshed / 'results.csv').exists(), csv)
                session = ReviewSession(source, csv_requested=csv)
                payload = {'format': 'untap-manual-review-trial-v1', 'report_id': selection_report_id([snapshot['items'][0]['result']], snapshot['report']['title'], snapshot['report']['date']), 'selections': [], 'pending_candidates': []}
                reviewed = Path(session.action({'action': 'save', 'payload': payload})['saved'])
                self.assertEqual((reviewed / 'results.csv').exists(), csv)
                for output in (refreshed, reviewed):
                    self.assertTrue((output / 'results.html').exists())
                    self.assertTrue((output / 'results.json').exists())
            self.assertEqual((source / 'results.json').read_bytes(), before)

    def test_csv_without_batch_input_is_rejected_before_browser(self):
        with patch.object(sys, 'argv', ['untap.py', '--csv', 'Brewery Beer']), patch.object(untap, 'untappd_browser_page') as browser, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                untap.main()
            browser.assert_not_called()

    def test_refresh_cli_csv_option(self):
        with patch('untap.refresh.refresh', return_value=Path('/tmp/reviewed')) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(refresh_main(['/tmp/source', '--csv']), 0)
            self.assertTrue(run.call_args.args[-1])
