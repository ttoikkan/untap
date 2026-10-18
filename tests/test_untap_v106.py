"""Behavioral equivalence for unified and standalone command forms."""
import builtins
import contextlib
import io
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import untap.run as untap
import untap.cli as untap_cli
import untap.inspect as untap_inspect
import untap.local_review as untap_local_review
import untap.refresh as untap_refresh
import untap.smoke as untap_smoke
from untap.snapshot import build_snapshot, save_snapshot
from untap.version import __version__


def invoke(main, args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(args) or 0
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class UnifiedCommandTests(unittest.TestCase):
    def test_help_version_and_subcommand_help_never_import_playwright(self):
        real_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == 'playwright' or name.startswith('playwright.'):
                raise AssertionError('local command imported Playwright')
            return real_import(name, *args, **kwargs)
        with mock.patch('builtins.__import__', side_effect=guarded):
            code, text, err = invoke(untap_cli.main, ['--help'])
            self.assertEqual(code, 0, err)
            root_help = text
            for command in untap_cli.COMMANDS:
                self.assertIn(command, root_help)
                code, text, err = invoke(untap_cli.main, [command, '--help'])
                self.assertEqual(code, 0, err)
                self.assertIn('usage: untap ' + command, text)
            self.assertEqual(invoke(untap_cli.main, ['--version']), (0, f'untap {__version__}\n', ''))

    def test_empty_run_shows_help_without_browser(self):
        with mock.patch.object(untap, 'untappd_browser_page', side_effect=AssertionError('browser opened')):
            for args in ([], ['run']):
                code, text, err = invoke(untap_cli.main, args)
                self.assertEqual(code, 1, err)
                self.assertIn('usage:', text)

    def test_validation_and_invalid_arguments_preserve_local_preflight(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(untap, 'untappd_browser_page', side_effect=AssertionError('browser opened')):
            menu = Path(tmp) / 'menu.tsv'
            menu.write_text('Kin\tKinetic Hazy\t6.5%\tIPA\n', encoding='utf-8')
            args = ['--validate-menu', str(menu), '--show-queries']
            self.assertEqual(invoke(untap.main, args), invoke(untap_cli.main, ['run', *args]))
            for args, expected in [(['--menu', str(menu), '--debg'], 2),
                                   (['--menu', str(menu), '--csv', 'old.csv'], 2),
                                   (['--min-score', 'nan', 'Beer'], 2),
                                   (['--continue', tmp, '--menu', str(menu)], 2)]:
                legacy = invoke(untap.main, args)
                unified = invoke(untap_cli.main, ['run', *args])
                self.assertEqual(legacy[0], expected)
                self.assertEqual(unified[0], expected)
                self.assertEqual(legacy[2].split('error:')[-1], unified[2].split('error:')[-1])

    def test_single_search_and_reserved_word_escape_preserve_matching_arguments(self):
        page = object()
        result = {'query': 'review Brewery Beer', 'status': 'failed', 'reason': 'No matches'}
        with mock.patch.object(untap, 'untappd_browser_page', return_value=contextlib.nullcontext(page)), mock.patch.object(untap, 'search_one', return_value=result) as search:
            expected = invoke(untap.main, ['review', '--min-score', '0.6', 'Brewery', 'Beer'])
            calls = [search.call_args]
            for args in (['run', 'review', '--min-score', '0.6', 'Brewery', 'Beer'],
                         ['--min-score', '0.6', 'review', 'Brewery', 'Beer']):
                self.assertEqual(invoke(untap_cli.main, args), expected)
                calls.append(search.call_args)
            self.assertEqual(invoke(untap_cli.main, ['--min-score', '0.6', '--', 'review', 'Brewery', 'Beer']), expected)
            calls.append(search.call_args)
            self.assertTrue(all(call == calls[0] for call in calls))

    def test_menu_execution_forwards_identical_inputs_and_output_options(self):
        page = object()
        with tempfile.TemporaryDirectory() as tmp:
            menu = Path(tmp) / 'menu.tsv'
            menu.write_text('Kin\tKinetic Hazy\t6.5%\tIPA\n', encoding='utf-8')
            args = ['--menu', str(menu), '--csv', '--debug', '--report-title', 'My menu', '--min-score', '0.6']
            with mock.patch.object(untap, 'untappd_browser_page', return_value=contextlib.nullcontext(page)), mock.patch.object(untap, 'create_run_directory', return_value=Path(tmp)/'output'), mock.patch.object(untap, '_run_and_save_batch') as batch:
                legacy = invoke(untap.main, args)
                expected = batch.call_args
                self.assertEqual(invoke(untap_cli.main, ['run', *args]), legacy)
                self.assertEqual(batch.call_args, expected)

    def test_continuation_preserves_arguments_and_exit_status(self):
        import untap.continue_run as untap_continue
        with mock.patch.object(untap_continue, 'continue_run', return_value=Path('/tmp/continued')) as resume:
            args = ['--continue', '/tmp/source', '--csv', '--debug', '--min-score', '0.6']
            expected = invoke(untap.main, args)
            call = resume.call_args
            self.assertEqual(invoke(untap_cli.main, ['run', *args]), expected)
            self.assertEqual(resume.call_args, call)
            resume.side_effect = ValueError('Invalid snapshot')
            self.assertEqual(invoke(untap_cli.main, ['run', *args]), invoke(untap.main, args))

    def test_smoke_uses_same_live_check_and_all_exit_codes(self):
        page = object()
        with mock.patch.object(untap, 'untappd_browser_page', return_value=contextlib.nullcontext(page)), mock.patch.object(untap_smoke, 'run_live_smoke_test') as smoke:
            for code in range(8):
                with self.subTest(code=code):
                    smoke.return_value = code
                    self.assertEqual(invoke(untap.main, ['--smoke-test']), invoke(untap_cli.main, ['smoke']))
                    smoke.assert_called_with(page)
            smoke.reset_mock()
            self.assertEqual(invoke(untap_cli.main, ['smoke', '--menu', 'menu.tsv'])[0], 1)
            self.assertEqual(invoke(untap_cli.main, ['smoke', 'Beer'])[0], 1)
            smoke.assert_not_called()

    def test_refresh_writes_identical_html_json_and_csv(self):
        from tests.test_untap_decision_characterization import FixedDatetime
        with tempfile.TemporaryDirectory() as tmp, mock.patch('untap.refresh.datetime', FixedDatetime):
            root = Path(tmp)
            source = root / 'results.json'
            save_snapshot(build_snapshot([{'query': 'Beer', 'status': 'failed', 'reason': 'No matches'}], 'My menu'), source)
            legacy, unified = root/'legacy', root/'unified'
            self.assertEqual(invoke(untap_refresh.main, [str(source), '--output', str(legacy), '--csv'])[0], 0)
            self.assertEqual(invoke(untap_cli.main, ['refresh', str(source), '--output', str(unified), '--csv'])[0], 0)
            for filename in ('results.html', 'results.json', 'results.csv'):
                self.assertEqual((legacy/filename).read_bytes(), (unified/filename).read_bytes())

    def test_inspect_reuses_query_scope_and_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            item = {'query': 'Brewery Beer', 'transport': 'ui-bootstrap', 'error': None,
                    'nbHits': 1, 'nbPages': 1, 'hitsPerPage': 5, 'hits': [{'beer_name': 'Beer'}]}
            with mock.patch.object(untap_inspect, '_reserve_output_directory', return_value=output), mock.patch.object(untap_inspect, 'untappd_browser_page', return_value=contextlib.nullcontext(object())), mock.patch.object(untap_inspect, 'inspect_query', return_value=item):
                legacy = invoke(untap_inspect.main, ['--query', 'Brewery Beer', '--all-pages'])
                expected = (output/'hits.json').read_bytes(), (output/'summary.txt').read_bytes()
                self.assertEqual(invoke(untap_cli.main, ['inspect', '--query', 'Brewery Beer', '--all-pages']), legacy)
                self.assertEqual(((output/'hits.json').read_bytes(), (output/'summary.txt').read_bytes()), expected)

    def test_review_missing_source_is_same_local_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = str(Path(tmp)/'missing.json')
            self.assertEqual(invoke(untap_cli.main, ['review', source, '--no-open']), invoke(untap_local_review.main, [source, '--no-open']))

    def test_offline_command_errors_preserve_status_and_detail(self):
        import untap.publish as untap_publish
        for command, standalone, args in [('refresh', untap_refresh.main, ['--fetch-candidates', 'missing.json']),
                                           ('publish', untap_publish.main, ['missing.html', '/tmp/archive']),
                                           ('inspect', untap_inspect.main, ['--file', 'missing.txt'])]:
            with self.subTest(command=command):
                legacy = invoke(standalone, args)
                unified = invoke(untap_cli.main, [command, *args])
                self.assertEqual(legacy[0], unified[0])
                self.assertEqual(legacy[2].split('error:')[-1], unified[2].split('error:')[-1])


if __name__ == '__main__':
    unittest.main()
