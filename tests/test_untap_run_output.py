"""Saved-run output contracts independent of search and directory allocation."""
import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import untap.run_output as output
from untap.report import render_html_report
from untap.snapshot import build_snapshot, save_snapshot
from tests.test_untap_decision_characterization import FIXTURE, characterization_cases, observe
import json
import hashlib


class RunOutputTests(unittest.TestCase):
    def snapshot(self):
        snapshot = build_snapshot([{'query': 'Beer', 'status': 'failed', 'reason': 'No match'}], 'Menu')
        snapshot['report']['date'] = '2026-01-01'
        return snapshot

    def test_outputs_match_existing_serialization_without_changing_snapshot(self):
        snapshot = self.snapshot()
        before = copy.deepcopy(snapshot)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            actual, expected = root / 'actual', root / 'expected'
            actual.mkdir(); expected.mkdir()
            output.write_run_outputs(snapshot, actual, csv_requested=True)
            results = [i['result'] for i in snapshot['items']]
            save_snapshot(snapshot, expected / 'results.json')
            (expected / 'results.html').write_text(render_html_report(results, 'Menu', '2026-01-01', source_created_at=snapshot['created_at']), encoding='utf-8')
            output.save_csv(results, str(expected / 'results.csv'))
            for name in ('results.json', 'results.html', 'results.csv'):
                self.assertEqual((actual / name).read_bytes(), (expected / name).read_bytes())
            self.assertEqual({p.name for p in actual.iterdir()}, {'results.json', 'results.html', 'results.csv'})
        self.assertEqual(snapshot, before)

    def test_csv_bytes_match_frozen_pre_extraction_cases(self):
        expected = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            path = Path(tmp) / 'results.csv'
            for case in characterization_cases():
                result = observe(case)['result']
                output.save_csv([result], str(path))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected[case['name']]['csv_sha256'])

    def test_supplied_html_is_used_without_rendering_and_existing_snapshot_is_not_overwritten(self):
        snapshot = self.snapshot()
        with tempfile.TemporaryDirectory() as tmp, patch.object(output, 'render_html_report', side_effect=AssertionError('rendered')):
            root = Path(tmp)
            output.write_run_outputs(snapshot, root, html='pre-rendered')
            self.assertEqual((root / 'results.html').read_text(), 'pre-rendered')
            before = (root / 'results.json').read_bytes()
            with self.assertRaises(FileExistsError):
                output.write_run_outputs(snapshot, root, html='replacement')
            self.assertEqual((root / 'results.json').read_bytes(), before)
            self.assertEqual((root / 'results.html').read_text(), 'pre-rendered')

    def test_failure_preserves_caller_recovery_files_and_save_order(self):
        for csv_first in (True, False):
            with self.subTest(csv_first=csv_first), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                root = Path(tmp)
                for name in ('results.input.json', 'results.partial.jsonl'):
                    (root / name).write_text('recovery')
                with patch.object(output, 'render_html_report', side_effect=OSError('failed')):
                    with self.assertRaises(OSError):
                        output.write_run_outputs(self.snapshot(), root, csv_requested=True, csv_first=csv_first)
                self.assertTrue((root / 'results.json').exists())
                self.assertEqual((root / 'results.csv').exists(), csv_first)
                self.assertFalse((root / 'results.html').exists())
                for name in ('results.input.json', 'results.partial.jsonl'):
                    self.assertEqual((root / name).read_text(), 'recovery')

    def test_batch_date_policy_preserves_renderer_default(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(output, 'render_html_report', return_value='html') as render:
            output.write_run_outputs(self.snapshot(), Path(tmp), use_snapshot_date=False)
            self.assertIsNone(render.call_args.args[2])
