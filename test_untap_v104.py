"""Continuation preserves completed decisions and durable interruption progress."""
import contextlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import untap
from untap_batch import unattempted_result
from untap_continue import continue_run, load_continuation
from untap_snapshot import build_snapshot, save_snapshot, load_snapshot


class ContinuationTests(unittest.TestCase):
    def source(self, root):
        source = root / 'source'
        source.mkdir()
        inputs = [{'query': f'Brewery Beer {i}', 'original': f'Brewery\tBeer {i}\t5%\tIPA',
                   'brewery': 'Brewery', 'beer': f'Beer {i}', 'menu_abv': 5., 'style': 'IPA'} for i in range(4)]
        results = [unattempted_result(item, 'unfinished') for item in inputs]
        results[0].update(status='ok', beer='Manually selected', manually_confirmed=True, abv='5%', rating=4., ratings=1, url='https://untappd.com/b/beer/1')
        results[1].update(status='ambiguous', alternatives=[{'name': 'Beer 1', 'url': 'https://untappd.com/b/beer/2'}])
        results[2].update(status='rate_limited', batch_remaining=1)
        snapshot = build_snapshot(results, 'Original menu title')
        snapshot['manual_decisions'] = [{'item_id': snapshot['items'][0]['id'], 'url': results[0]['url'], 'original_result': {'status': 'ambiguous'}}]
        snapshot['candidate_additions'] = [{'item_id': snapshot['items'][0]['id'], 'url': results[0]['url']}]
        save_snapshot(snapshot, source / 'results.json')
        return source, inputs, snapshot

    def test_continue_searches_only_unfinished_and_preserves_review_history(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source, inputs, original = self.source(root)
            before = (source / 'results.json').read_bytes()
            searched = []
            def search(page, query, **kwargs):
                searched.append(query)
                return {'query': query, 'status': 'ok', 'beer': query, 'rating': 4., 'ratings': 1, 'abv': '5%'}
            with patch('untap_continue.untappd_browser_page', return_value=contextlib.nullcontext(object())), patch('untap_batch.search_one', side_effect=search):
                output = continue_run(source, csv_requested=True)
            saved = load_snapshot(output / 'results.json')
            self.assertEqual(searched, [inputs[2]['query'], inputs[3]['query']])
            self.assertEqual(saved['items'][:2], original['items'][:2])
            self.assertEqual(saved['manual_decisions'], original['manual_decisions'])
            self.assertEqual(saved['candidate_additions'], original['candidate_additions'])
            self.assertEqual([i['id'] for i in saved['items']], [i['id'] for i in original['items']])
            self.assertEqual(saved['report']['title'], 'Original menu title')
            self.assertEqual((source / 'results.json').read_bytes(), before)
            self.assertTrue((output / 'results.csv').exists())
            self.assertFalse((output / 'results.partial.jsonl').exists())
            self.assertFalse((output / 'results.input.json').exists())

    def test_repeated_rate_limit_retains_journal_and_can_continue_again(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            source, inputs, original = self.source(Path(tmp))
            with patch('untap_continue.untappd_browser_page', return_value=contextlib.nullcontext(object())), patch('untap_batch.search_one', return_value={'query': inputs[2]['query'], 'status': 'rate_limited'}) as search:
                output = continue_run(source)
            self.assertEqual(search.call_count, 1)
            self.assertTrue((output / 'results.partial.jsonl').exists())
            self.assertTrue((output / 'results.input.json').exists())
            saved = load_snapshot(output / 'results.json')
            self.assertEqual([i['result']['status'] for i in saved['items']], ['ok', 'ambiguous', 'rate_limited', 'not_attempted'])
            self.assertEqual(saved['items'][:2], original['items'][:2])
            recovered = load_continuation(output)
            self.assertEqual(recovered['items'], saved['items'])

    def test_interrupt_preserves_progress_and_new_recovery_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source, inputs, original = self.source(root)
            def search(page, query, **kwargs):
                if query == inputs[3]['query']:
                    raise KeyboardInterrupt()
                return {'query': query, 'status': 'failed', 'reason': 'no match'}
            with patch('untap_continue.untappd_browser_page', return_value=contextlib.nullcontext(object())), patch('untap_batch.search_one', side_effect=search):
                with self.assertRaises(KeyboardInterrupt):
                    continue_run(source)
            output = next(root.glob('source_continue_*'))
            saved = load_snapshot(output / 'results.json')
            self.assertEqual([i['result']['status'] for i in saved['items']], ['ok', 'ambiguous', 'failed', 'not_attempted'])
            # Simulate abrupt shutdown before final snapshot: journal recovery keeps the completed row.
            (output / 'results.json').unlink()
            recovered = load_continuation(output)
            self.assertEqual([i['result']['status'] for i in recovered['items']], ['ok', 'ambiguous', 'failed', 'not_attempted'])
            self.assertEqual(recovered['manual_decisions'], original['manual_decisions'])

    def test_successful_normal_run_cleans_journal_only_after_all_saves(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                root = Path(tmp)
                with patch.object(untap, 'run_batch', return_value=[]), patch('untap_run_output.render_html_report', side_effect=OSError('save failed') if fail else None, return_value='<html>report</html>'):
                    if fail:
                        with self.assertRaises(OSError):
                            untap._run_and_save_batch(object(), [], root, min_score=.425, debug=False, report_title='Menu')
                    else:
                        untap._run_and_save_batch(object(), [], root, min_score=.425, debug=False, report_title='Menu')
                self.assertEqual((root / 'results.partial.jsonl').exists(), fail)
                self.assertEqual((root / 'results.input.json').exists(), fail)

    def test_recovery_validates_identity_and_ignores_only_torn_final_line(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source, inputs, snapshot = self.source(root)
            (source / 'results.json').rename(source / 'results.input.json')
            item = snapshot['items'][2]
            recovered = deepcopy(item['result'])
            recovered.update(status='failed', reason='no match')
            journal = source / 'results.partial.jsonl'
            journal.write_text(json.dumps({'item_id': item['id'], 'result': recovered}) + '\n{"torn":')
            self.assertEqual(load_continuation(source)['items'][2]['result']['status'], 'failed')
            journal.write_text('{"broken":\n')
            with self.assertRaisesRegex(ValueError, 'Invalid journal'):
                load_continuation(source)
            recovered['input_beer'] = 'Wrong menu'
            journal.write_text(json.dumps({'item_id': item['id'], 'result': recovered}) + '\n')
            with self.assertRaisesRegex(ValueError, 'menu identity'):
                load_continuation(source)

    def test_legacy_journal_recovery_requires_matching_original_tsv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            menu = root / 'menu.tsv'
            menu.write_text('Brewery\tBeer 0\t5%\tIPA\nBrewery\tBeer 1\t5%\tIPA\n')
            source = root / 'legacy'
            source.mkdir()
            from untap_parser import read_validated_menu
            _, items = read_validated_menu(str(menu))
            result = unattempted_result(items[0], 'no match')
            result['status'] = 'failed'
            (source / 'results.partial.jsonl').write_text(json.dumps(result) + '\n')
            with self.assertRaisesRegex(ValueError, 'recovery-menu'):
                load_continuation(source)
            recovered = load_continuation(source, menu)
            self.assertEqual([i['result']['status'] for i in recovered['items']], ['failed', 'not_attempted'])

    def test_complete_or_invalid_sources_stop_before_browser_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, inputs, snapshot = self.source(root)
            for item in snapshot['items']:
                item['result']['status'] = 'failed'
                item['result'].pop('batch_remaining', None)
            (source / 'results.json').unlink()
            save_snapshot(snapshot, source / 'results.json')
            with patch('untap_continue.untappd_browser_page') as browser:
                with self.assertRaisesRegex(ValueError, 'no rate-limited'):
                    continue_run(source)
                browser.assert_not_called()
            self.assertEqual(list(root.glob('source_continue_*')), [])

    def test_cli_continuation_dispatch_and_conflicting_flags(self):
        import sys
        for args in [['--continue', 'run', '--menu', 'menu.tsv'], ['--continue', 'run', 'Beer'], ['--recovery-menu', 'menu.tsv']]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                untap._parse_cli_args(args)
        with patch.object(sys, 'argv', ['untap.py', '--continue', '/tmp/run', '--csv']), patch('untap_continue.continue_run', return_value=Path('/tmp/new-run')) as run, contextlib.redirect_stdout(io.StringIO()):
            untap.main()
        self.assertEqual(run.call_args.args, (Path('/tmp/run'),))
        self.assertTrue(run.call_args.kwargs['csv_requested'])


class RecoveryEdgeTests(unittest.TestCase):
    def test_torn_final_snapshot_recovers_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            source, inputs, snapshot = ContinuationTests().source(Path(tmp))
            (source / 'results.json').rename(source / 'results.input.json')
            (source / 'results.json').write_text('{"torn":')
            item = snapshot['items'][2]
            result = deepcopy(item['result'])
            result.update(status='failed', reason='completed before crash')
            (source / 'results.partial.jsonl').write_text(json.dumps({'item_id': item['id'], 'result': result}) + '\n')
            recovered = load_continuation(source)
            self.assertEqual(recovered['items'][2]['result']['status'], 'failed')
            self.assertEqual(recovered['manual_decisions'], snapshot['manual_decisions'])

    def test_continuation_debug_transcript_and_save_failure_keep_recovery_files(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                root = Path(tmp)
                source, inputs, snapshot = ContinuationTests().source(root)
                def search(page, query, **kwargs):
                    print('continued row diagnostic')
                    return {'query': query, 'status': 'failed', 'reason': 'no match'}
                with patch('untap_continue.untappd_browser_page', return_value=contextlib.nullcontext(object())), patch('untap_batch.search_one', side_effect=search), patch('untap_run_output.render_html_report', side_effect=OSError('save failed') if fail else None, return_value='<html>report</html>'):
                    if fail:
                        with self.assertRaises(OSError):
                            continue_run(source, debug=True)
                    else:
                        continue_run(source, debug=True)
                output = next(root.glob('source_continue_*'))
                self.assertIn('continued row diagnostic', (output / 'debug.txt').read_text())
                self.assertEqual((output / 'results.partial.jsonl').exists(), fail)
                self.assertEqual((output / 'results.input.json').exists(), fail)
