"""Packaging boundaries and optional installed-wheel acceptance checks.

Run installed checks with UNTAP_TEST_ENV pointing at a fresh wheel installation.
"""

import ast
import re
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from importlib.resources import files
import untap.run as untap
import untap.setup as untap_setup
import untap.transport as untap_untappd
from untap.version import __version__


class PackagingBoundaryTests(unittest.TestCase):
    def test_all_runtime_modules_are_declared_without_building_a_wheel(self):
        root = Path(__file__).parent.parent
        text = (root / 'pyproject.toml').read_text(encoding='utf-8')
        section = re.search(r'(?ms)^\[tool\.setuptools\]\s*$(.*?)(?=^\[|\Z)', text).group(1)
        declared = ast.literal_eval(re.search(r'(?ms)^packages\s*=\s*(\[.*?\])', section).group(1))
        actual = {str(p.parent.relative_to(root)).replace('/', '.') for p in (root / 'untap').rglob('__init__.py')}
        self.assertEqual(set(declared), actual)
        modules = ast.literal_eval(re.search(r'(?ms)^py-modules\s*=\s*(\[.*?\])', section).group(1))
        self.assertEqual(set(modules), {p.stem for p in root.glob('untap_*.py')})
        self.assertEqual(len(declared), len(set(declared)))

    def test_legacy_scripts_and_package_entry_point_remain_usable(self):
        root = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as cwd:
            for script in ('untap.py', 'untap_cli.py', 'untap_local_review.py', 'untap_refresh.py',
                           'untap_publish.py', 'untap_inspect.py', 'untap_setup.py'):
                result = subprocess.run([sys.executable, '-B', str(root / script), '--help'],
                                        cwd=cwd, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, (script, result.stderr))
                self.assertIn('usage:', result.stdout)
        result = subprocess.run([sys.executable, '-B', '-m', 'untap', '--version'],
                                cwd=root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.stdout, f'untap {__version__}\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_exits_without_browser(self):
        with mock.patch.object(untap, 'untappd_browser_page', side_effect=AssertionError('browser opened')), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exited:
                untap.main(['--version'])
        self.assertEqual(exited.exception.code, 0)
        self.assertEqual(output.getvalue(), f'untap {__version__}\n')

    def test_installer_uses_current_environment_and_propagates_exit_code(self):
        with mock.patch.object(untap_setup.subprocess, 'call', return_value=7) as invoke:
            self.assertEqual(untap_setup.main([]), 7)
        invoke.assert_called_once_with([sys.executable, '-m', 'playwright', 'install', 'chromium'])

    def test_installer_help_does_not_download(self):
        with mock.patch.object(untap_setup.subprocess, 'call') as invoke, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exited:
                untap_setup.main(['--help'])
        self.assertEqual(exited.exception.code, 0)
        invoke.assert_not_called()

    def test_browser_install_diagnostic_is_specific_to_missing_executable(self):
        class BrowserError(Exception):
            pass
        module = types.ModuleType('playwright.sync_api')
        module.Error = BrowserError
        browser = mock.Mock()
        manager = mock.MagicMock()
        manager.__enter__.return_value.chromium = browser
        module.sync_playwright = mock.Mock(return_value=manager)
        with mock.patch.dict(sys.modules, {'playwright.sync_api': module}):
            browser.launch.side_effect = BrowserError("Executable doesn't exist at /missing/chromium")
            with self.assertRaises(untap_untappd.BrowserUnavailableError) as exited:
                with untap_untappd.untappd_browser_page():
                    self.fail('missing browser yielded a page')
            self.assertIn('untap-install-browser', str(exited.exception))
            self.assertIn('python3 -m playwright install chromium', str(exited.exception))
            manager.__exit__.assert_called_once()
            browser.launch.side_effect = BrowserError('Host system is missing dependencies')
            with self.assertRaisesRegex(BrowserError, 'Host system'):
                with untap_untappd.untappd_browser_page():
                    self.fail('failed launch yielded a page')

    def test_review_asset_is_readable_as_a_resource(self):
        from untap.report import render_html_report
        script = files('untap.assets').joinpath('untap_review.js').read_text(encoding='utf-8')
        self.assertTrue(script.strip())
        self.assertIn('<script id="manual-review-script">' + script + '</script>', render_html_report([]))


@unittest.skipUnless(os.environ.get('UNTAP_TEST_ENV'), 'set UNTAP_TEST_ENV for installed-wheel checks')
class InstalledDistributionTests(unittest.TestCase):
    def setUp(self):
        self.bin = Path(os.environ['UNTAP_TEST_ENV']) / ('Scripts' if os.name == 'nt' else 'bin')
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.cwd = Path(self.workspace.name)
        self.env = os.environ.copy()
        self.env.pop('PYTHONPATH', None)
        self.env['PYTHONNOUSERSITE'] = '1'
        self.env['PLAYWRIGHT_BROWSERS_PATH'] = str(self.cwd / 'no-browsers')

    def run_command(self, name, *args):
        return subprocess.run([str(self.bin / name), *args], cwd=self.cwd, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_all_entry_points_help_and_distribution_version(self):
        for name in ('untap', 'untap-review', 'untap-refresh', 'untap-publish', 'untap-inspect', 'untap-install-browser'):
            with self.subTest(name=name):
                result = self.run_command(name, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)
        for module in ('untap', 'untap_cli', 'untap_local_review', 'untap_refresh', 'untap_publish', 'untap_inspect', 'untap_setup'):
            result = self.run_command('python', '-I', '-m', module, '--help')
            self.assertEqual(result.returncode, 0, (module, result.stderr))
        result = self.run_command('untap', '--version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f'untap {__version__}\n')
        result = self.run_command('python', '-I', '-c', 'from importlib.metadata import version; print(version("untap"))')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), __version__)

    def test_unified_help_and_validation_work_outside_checkout(self):
        for command in ('run', 'review', 'refresh', 'publish', 'inspect', 'smoke'):
            with self.subTest(command=command):
                result = self.run_command('untap', command, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage: untap ' + command, result.stdout)
        menu = self.cwd / 'menu.tsv'
        menu.write_text('Kin\tKinetic Hazy\t6.5%\tIPA\n', encoding='utf-8')
        legacy = self.run_command('untap', '--validate-menu', str(menu), '--show-queries')
        unified = self.run_command('untap', 'run', '--validate-menu', str(menu), '--show-queries')
        self.assertEqual((legacy.returncode, legacy.stdout, legacy.stderr),
                         (unified.returncode, unified.stdout, unified.stderr))
        smoke = self.run_command('untap', 'smoke')
        self.assertNotEqual(smoke.returncode, 0)
        self.assertIn('untap-install-browser', smoke.stderr)
        self.assertNotIn('Traceback', smoke.stderr)

    def test_installed_refresh_and_publish_commands_produce_identical_files(self):
        from untap.snapshot import build_snapshot, save_snapshot
        source = self.cwd / 'results.json'
        save_snapshot(build_snapshot([{'query': 'Beer', 'status': 'failed', 'reason': 'No matches'}], 'My menu'), source)
        legacy, unified = self.cwd / 'legacy', self.cwd / 'unified'
        result = self.run_command('untap-refresh', str(source), '--output', str(legacy), '--csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_command('untap', 'refresh', str(source), '--output', str(unified), '--csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        for filename in ('results.html', 'results.json', 'results.csv'):
            self.assertEqual((legacy / filename).read_bytes(), (unified / filename).read_bytes())
        old_archive, new_archive = self.cwd / 'old-archive', self.cwd / 'new-archive'
        for archive in (old_archive, new_archive):
            (archive / "reports").mkdir(parents=True)
        result = self.run_command('untap-publish', str(legacy), str(old_archive))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_command('untap', 'publish', str(unified), str(new_archive))
        self.assertEqual(result.returncode, 0, result.stderr)
        old_files = {str(p.relative_to(old_archive)): p.read_bytes() for p in old_archive.rglob('*') if p.is_file()}
        new_files = {str(p.relative_to(new_archive)): p.read_bytes() for p in new_archive.rglob('*') if p.is_file()}
        self.assertEqual(old_files, new_files)
        result = self.run_command('untap', 'publish', str(unified), str(new_archive), '--replace')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_distribution_contains_every_runtime_module_and_only_public_assets(self):
        result = self.run_command('python', '-I', '-c',
                                  'import json; from importlib.metadata import files; print(json.dumps([str(f) for f in files("untap")]))')
        self.assertEqual(result.returncode, 0, result.stderr)
        contents = json.loads(result.stdout)
        root = Path(__file__).parent.parent
        expected_modules = {str(path.relative_to(root)) for path in (root / 'untap').rglob('*.py')}
        expected_modules.update(path.name for path in root.glob('untap_*.py'))
        self.assertTrue(expected_modules.issubset(contents))
        self.assertIn('untap/assets/untap_review.js', contents)
        self.assertFalse(any(path.startswith('test') or 'refresh-reports.json' in path for path in contents))

    def test_local_validation_and_missing_browser_from_foreign_directory(self):
        menu = self.cwd / 'menu.tsv'
        menu.write_text('Kin\tKinetic Hazy\t6.5%\tIPA\n', encoding='utf-8')
        result = self.run_command('untap', '--validate-menu', str(menu))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Menu validation succeeded.', result.stdout)
        self.assertFalse((self.cwd / 'no-browsers').exists())
        result = self.run_command('untap', 'Kin Kinetic Hazy')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('untap-install-browser', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((self.cwd / 'no-browsers').exists())

    def test_installed_outputs_equal_source_outputs_byte_for_byte(self):
        from tests.test_untap_report import HtmlReportTests
        from untap.report import render_html_report
        from untap.snapshot import build_snapshot
        from untap.batch import save_csv
        from datetime import datetime, timezone
        results = HtmlReportTests()._results()
        (self.cwd / 'inputs.json').write_text(json.dumps(results), encoding='utf-8')
        expected_html = render_html_report(results, title='Packaging regression', report_date='2026-10-11').encode('utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            save_csv(results, str(self.cwd / 'source.csv'))
        with mock.patch('untap.snapshot.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
            expected_json = json.dumps(build_snapshot(results, 'Packaging regression'), ensure_ascii=False, indent=2).encode('utf-8')
        code = '''
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from untap.report import render_html_report
from untap.snapshot import build_snapshot
from untap.batch import save_csv
results = json.loads(Path('inputs.json').read_text())
Path('installed.html').write_text(render_html_report(results, title='Packaging regression', report_date='2026-10-11'), encoding='utf-8')
save_csv(results, 'installed.csv')
with patch('untap.snapshot.datetime') as clock:
    clock.now.return_value = datetime(2026,10,11,12,tzinfo=timezone.utc)
    Path('installed.json').write_text(json.dumps(build_snapshot(results, 'Packaging regression'), ensure_ascii=False, indent=2), encoding='utf-8')
'''
        result = self.run_command('python', '-I', '-c', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.cwd / 'installed.html').read_bytes(), expected_html)
        self.assertEqual((self.cwd / 'installed.csv').read_bytes(), (self.cwd / 'source.csv').read_bytes())
        self.assertEqual((self.cwd / 'installed.json').read_bytes(), expected_json)


if __name__ == '__main__':
    unittest.main()
