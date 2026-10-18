"""Refresh lifecycle is visible without pretending offline rebuilds fetch ratings."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from untap.refresh import refresh, main
from untap.publish import publish_report, read_report_metadata
from untap.snapshot import build_snapshot, save_snapshot, load_snapshot
from untap.report import render_html_report
from untap.report_model import format_timestamp


class ReportVisibilityTests(unittest.TestCase):
    def source(self, root):
        source = root / 'source'
        source.mkdir()
        snapshot = build_snapshot([dict(query='Beer', beer='Beer', status='ok', abv='5%',
                                       url='https://untappd.com/b/beer/1', rating=4., ratings=50)], 'Menu')
        snapshot['created_at'] = '2026-01-01T12:30:00+00:00'
        snapshot['report']['date'] = '2026-01-01'
        save_snapshot(snapshot, source / 'results.json')
        return source

    def test_rebuild_preserves_data_age_and_menu_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.source(Path(tmp))
            before = (source / 'results.json').read_bytes()
            output = refresh(source)
            snapshot = load_snapshot(output / 'results.json')
            self.assertEqual(snapshot['created_at'], '2026-01-01T12:30:00+00:00')
            self.assertEqual(snapshot['report']['date'], '2026-01-01')
            self.assertEqual(snapshot['items'], load_snapshot(source / 'results.json')['items'])
            html = (output / 'results.html').read_text()
            self.assertIn('<dt>Source data saved</dt>', html)
            self.assertIn('2026-01-01 12:30 UTC</time>', html)
            self.assertIn('<dt>Report rebuilt</dt>', html)
            self.assertIn('does not fetch new ratings', html)
            self.assertEqual((source / 'results.json').read_bytes(), before)
            metadata = read_report_metadata(output / 'results.html')
            self.assertEqual(metadata.source_created_at, snapshot['created_at'])
            self.assertEqual(metadata.rebuilt_at, snapshot['report']['rebuilt_at'])

    def test_archive_failure_preserves_report_and_is_visible_then_clears(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp)
            source = self.source(root)
            archive = root / 'archive'
            (archive / 'reports').mkdir(parents=True)
            first = refresh(source)
            report = publish_report(first, archive)
            published = archive / 'reports' / report.filename
            old = published.read_bytes()
            with patch('untap.refresh.refresh', side_effect=OSError('Controlled failure')):
                self.assertEqual(main([str(source), '--archive', str(archive), '--replace']), 2)
            self.assertEqual(published.read_bytes(), old)
            self.assertIn('refresh failed — previous report retained', (archive / 'index.html').read_text())
            self.assertEqual(json.loads((source / 'refresh-status.json').read_text())['outcome'], 'failed')
            self.assertEqual(main([str(source), '--archive', str(archive), '--replace']), 0)
            index = (archive / 'index.html').read_text()
            self.assertIn('Source data saved: 2026-01-01 12:30 UTC', index)
            self.assertIn('Latest report refresh succeeded', index)
            self.assertNotIn('previous report retained', index)
            self.assertEqual(json.loads((source / 'refresh-status.json').read_text())['outcome'], 'succeeded')
            self.assertEqual([p.name for p in (archive / 'reports').glob('*.html')], [report.filename])

    def test_publish_failure_does_not_change_old_report(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp)
            source = self.source(root)
            archive = root / 'archive'
            (archive / 'reports').mkdir(parents=True)
            report = publish_report(refresh(source), archive)
            path = archive / 'reports' / report.filename
            old = path.read_bytes()
            # No --replace: publication refuses replacement, and reports a failed attempt.
            self.assertEqual(main([str(source), '--archive', str(archive)]), 2)
            self.assertEqual(path.read_bytes(), old)
            self.assertIn('Latest report refresh failed', (archive / 'index.html').read_text())

    def test_legacy_and_untrusted_timestamps_are_safe(self):
        html = render_html_report([], report_date='2026-01-01')
        self.assertNotIn('<dt>Source data saved</dt>', html)
        html = render_html_report([], source_created_at='<script>bad</script>', rebuilt_at='2026-01-01')
        self.assertNotIn('<script>bad</script>', html)
        self.assertNotIn('<dt>Report rebuilt</dt>', html)
        self.assertIsNone(format_timestamp('2026-01-01'))
        self.assertEqual(format_timestamp('2026-01-01T14:30:00+02:00'), '2026-01-01 12:30 UTC')

    def test_status_write_error_does_not_hide_refresh_error(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            source = self.source(Path(tmp))
            with patch('untap.refresh.refresh', side_effect=ValueError('Original error')), patch('tempfile.NamedTemporaryFile', side_effect=OSError('Status write error')):
                self.assertEqual(main([str(source)]), 2)
            self.assertIn('Original error', errors.getvalue())
            self.assertIn('Status write error', errors.getvalue())
