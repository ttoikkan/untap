"""Rate-limit completeness and manual-selection integrity regressions."""
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from untap_batch import run_batch, save_csv
from untap_snapshot import build_snapshot, save_snapshot, load_snapshot
from untap_report import render_html_report, selection_report_id
from untap_publish import publish_report, PublishError
from untap_registry import register_run
from untap_refresh import apply_selection_payload


class CompletenessTests(unittest.TestCase):
    def test_rate_limit_preserves_full_menu_in_all_outputs_and_blocks_publication(self):
        items = [{'query': f'Brewery Beer {i}', 'original': f'Brewery\tBeer {i}\t5%\tIPA',
                  'brewery': 'Brewery', 'beer': f'Beer {i}', 'menu_abv': 5., 'style': 'IPA'} for i in range(5)]
        with patch('untap_batch.search_one', side_effect=[{'query': items[0]['query'], 'status': 'ok', 'beer': 'Beer 0'},
                                                        {'query': items[1]['query'], 'status': 'rate_limited', 'reason': 'HTTP 429'}]) as search, contextlib.redirect_stdout(io.StringIO()):
            results = run_batch(object(), items)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(results), 5)
        for result, item in zip(results[2:], items[2:]):
            self.assertEqual(result['status'], 'not_attempted')
            self.assertEqual(result['original_menu_text'], item['original'])
            self.assertEqual(result['input_beer'], item['beer'])
            self.assertEqual(result['input_abv'], '5')
            self.assertEqual(result['input_brewery'], 'Brewery')
            self.assertEqual(result['input_style'], 'IPA')
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            save_snapshot(build_snapshot(results, 'Menu'), root / 'results.json')
            self.assertEqual(len(load_snapshot(root / 'results.json')['items']), 5)
            html = render_html_report(results, 'Menu')
            self.assertIn('5 beers', html)
            self.assertIn('3 menu rows were not searched', html)
            self.assertEqual(html.count('data-status="not_attempted"'), 3)
            (root / 'results.html').write_text(html)
            save_csv(results, str(root / 'results.csv'))
            with (root / 'results.csv').open() as source:
                self.assertEqual(len(list(csv.DictReader(source))), 5)
            with self.assertRaisesRegex(PublishError, 'Incomplete run'):
                publish_report(root / 'results.html', root / 'archive')
            self.assertFalse((root / 'archive').exists())
            config = root / 'refresh.json'
            config.write_text('{"reports": []}')
            before = config.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Incomplete run'):
                register_run(config, root)
            self.assertEqual(config.read_bytes(), before)

    def test_last_row_rate_limit_and_legacy_remainder_still_block_publication(self):
        for remaining in (0, 3):
            with self.subTest(remaining=remaining), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                results = [{'query': 'Beer', 'status': 'rate_limited', 'batch_remaining': remaining}]
                html = render_html_report(results, 'Menu')
                self.assertIn(f'{remaining} menu rows were not searched', html)
                path = root / 'results.html'
                path.write_text(html)
                with self.assertRaises(PublishError):
                    publish_report(path, root / 'archive')


class SelectionIntegrityTests(unittest.TestCase):
    def test_selection_clears_old_beer_fields_and_retains_history(self):
        candidate = {'name': 'Sibling', 'url': 'https://untappd.com/b/sibling/2', 'brewery': 'Brewery', 'abv': 6.5}
        original = {'query': 'Brewery Beer', 'status': 'ok', 'beer': 'Beer', 'url': 'https://untappd.com/b/beer/1',
                    'abv': '5%', 'ibu': '45', 'search_text': 'old snippet', 'search_fallback': 'old fallback',
                    'match': 'Old beer', 'input_beer': 'Beer', 'alternatives': [candidate]}
        snapshot = build_snapshot([original], 'Menu')
        payload = {'format': 'untap-manual-review-trial-v1', 'report_id': selection_report_id([original], snapshot['report']['title'], snapshot['report']['date']),
                   'selections': [{'row': 0, 'url': candidate['url']}]}
        apply_selection_payload(snapshot, payload)
        result = snapshot['items'][0]['result']
        self.assertEqual(result['beer'], 'Sibling')
        self.assertEqual(result['abv'], '6.5%')
        self.assertIsNone(result['ibu'])
        self.assertEqual(result['input_beer'], 'Beer')
        for key in ('search_text', 'search_fallback', 'match'):
            self.assertNotIn(key, result)
        self.assertEqual(snapshot['manual_decisions'][0]['original_result'], original)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            path = Path(tmp) / 'results.csv'
            save_csv([result], str(path))
            with path.open() as source:
                row = next(csv.DictReader(source))
            self.assertEqual(row['ibu'], '')
            self.assertEqual(row['abv'], '6.5%')


class CliArgumentTests(unittest.TestCase):
    def test_invalid_options_stop_before_browser_or_output(self):
        import sys
        import untap
        cases = [(['--menu', 'menu.txt', '--debg'], 'unrecognized arguments'),
                 (['--file', 'beers.txt', '--debg'], 'unrecognized arguments'),
                 (['--menu', 'menu.txt', '--csv', 'results.csv'], 'takes no filename'),
                 (['--file', 'beers.txt', '--csv', 'results.csv'], 'takes no filename'),
                 (['--menu', 'menu.txt', '--csv=x'], 'ignored explicit argument'),
                 (['--deb'], 'unrecognized arguments'),
                 (['--menu'], 'expected one argument'),
                 (['--min-score', 'NaN', 'Beer'], 'finite number'),
                 (['--shadow-search-transport', '0', 'Beer'], 'positive integer')]
        for args, message in cases:
            with self.subTest(args=args), patch.object(sys, 'argv', ['untap.py'] + args), patch.object(untap, 'untappd_browser_page') as browser, patch.object(untap, 'create_run_directory') as directory, patch.object(untap, 'read_validated_menu') as menu, contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exc:
                    untap.main()
                self.assertEqual(exc.exception.code, 2)
                self.assertIn(message, output.getvalue())
                self.assertNotIn('v87', output.getvalue())
                browser.assert_not_called()
                directory.assert_not_called()
                menu.assert_not_called()

    def test_single_beer_query_and_existing_options_are_preserved(self):
        import untap
        args = untap._parse_cli_args(['Badlands', '--debug', 'Fazy', '(2026)', '--min-score', '.8'])
        self.assertEqual(args.query, ['Badlands', 'Fazy', '(2026)'])
        self.assertTrue(args.debug)
        self.assertEqual(args.min_score, .8)
        batch = untap._parse_cli_args(['--menu', 'menu.txt', '--csv', '--html', '--report-title', ' Menu '])
        self.assertTrue(batch.csv)
        self.assertEqual(batch.report_title, 'Menu')


class AdditionalIntegrityTests(unittest.TestCase):
    def test_brewery_matching_requires_complete_tokens(self):
        from untap_parser import join_brewery_and_beer
        for brewery, beer, expected in [('Kin', 'Kinetic Hazy', 'Kin Kinetic Hazy'),
                                        ('Hop', 'Hoppy Boi', 'Hop Hoppy Boi'),
                                        ('Kin', 'Kin Hazy', 'Kin Hazy'),
                                        ('Other Half', 'Other Half IPA', 'Other Half IPA'),
                                        ('Other Half', 'Other Halftime IPA', 'Other Half Other Halftime IPA')]:
            with self.subTest(brewery=brewery, beer=beer):
                self.assertEqual(join_brewery_and_beer(brewery, beer), expected)

    def test_missing_registry_source_is_skipped_but_retained(self):
        import json
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as warnings:
            root = Path(tmp)
            run = root / 'run'
            run.mkdir()
            save_snapshot(build_snapshot([], 'New menu'), run / 'results.json')
            config = root / 'refresh.json'
            config.write_text(json.dumps({'reports': [{'source': 'deleted/results.json'}]}))
            self.assertTrue(register_run(config, run))
            entries = json.loads(config.read_text())['reports']
            self.assertEqual(entries, [{'source': 'deleted/results.json'}, {'source': 'run'}])
            self.assertIn('skipping missing source', warnings.getvalue())

    def test_interrupted_batch_preserves_journal_and_full_snapshot(self):
        import json
        import untap
        for failure in (KeyboardInterrupt(), RuntimeError('unexpected shutdown')):
            with self.subTest(failure=type(failure)), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                root = Path(tmp)
                items = [{'query': f'Beer {i}', 'original': f'row {i}', 'brewery': 'Brewery', 'beer': f'Beer {i}', 'menu_abv': 5., 'style': 'IPA'} for i in range(3)]
                def interrupted(page, rows, *, min_score, debug, on_result):
                    on_result({'query': 'Beer 0', 'status': 'ok', 'beer': 'Beer 0'})
                    # Persisted before the next row starts, not buffered until exit.
                    self.assertEqual(len((root / 'results.partial.jsonl').read_text().splitlines()), 1)
                    raise failure
                with patch.object(untap, 'run_batch', side_effect=interrupted):
                    with self.assertRaises(type(failure)):
                        untap._run_and_save_batch(object(), items, root, min_score=.75, debug=False, report_title='Menu')
                snap = load_snapshot(root / 'results.json')
                self.assertEqual([i['result']['status'] for i in snap['items']], ['ok', 'not_attempted', 'not_attempted'])
                self.assertEqual(snap['items'][1]['result']['input_beer'], 'Beer 1')
                journal = [json.loads(line) for line in (root / 'results.partial.jsonl').read_text().splitlines()]
                self.assertEqual(len(journal), 1)
                self.assertEqual(journal[0]['beer'], 'Beer 0')
                self.assertIn('Incomplete run:', (root / 'results.html').read_text())

    def test_real_batch_checkpoints_before_next_search(self):
        recorded = []
        def search(page, query, **kwargs):
            if query == 'second':
                self.assertEqual(len(recorded), 1)
                raise KeyboardInterrupt()
            return {'query': query, 'status': 'failed', 'reason': 'no match'}
        with patch('untap_batch.search_one', side_effect=search), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                run_batch(object(), ['first', 'second'], on_result=recorded.append)
        self.assertEqual(recorded[0]['query'], 'first')


class LowPriorityIntegrityTests(unittest.TestCase):
    def test_repeated_result_object_has_distinct_consistent_ids(self):
        import re
        shared = {'query': 'Beer', 'status': 'ambiguous'}
        results = [shared, shared]
        snap = build_snapshot(results, 'Menu')
        ids = re.findall(r'data-item-id="([^"]+)"', render_html_report(results, 'Menu'))
        self.assertEqual(ids, [i['id'] for i in snap['items']])
        self.assertEqual(len(set(ids)), 2)

    def test_parser_retains_empty_style_tab_and_rejects_ambiguous_precision(self):
        from untap_parser import parse_menu_lines, MenuValidationError
        text = 'Brewery\tBeer\t6,5%\t'
        self.assertEqual(parse_menu_lines([text])[0]['original'], text)
        with self.assertRaises(MenuValidationError):
            parse_menu_lines(['Brewery\tBeer\t1,000%\tIPA'])
        with self.assertRaisesRegex(MenuValidationError, 'Style may be empty; keep its tab'):
            parse_menu_lines(['Brewery\tBeer\t6%'])

    def test_review_injection_requires_exactly_one_marker(self):
        from untap_local_review import ReviewSession
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_snapshot(build_snapshot([], 'Menu'), root / 'results.json')
            session = ReviewSession(root)
            for html in ['<html></html>', '<script id="manual-review-script">' * 2]:
                with patch('untap_local_review.render_html_report', return_value=html), self.assertRaisesRegex(ValueError, 'marker'):
                    session.html()

    def test_review_server_returns_json_500_for_unexpected_exceptions(self):
        import json
        from types import SimpleNamespace
        from untap_local_review import make_server
        session = SimpleNamespace(token='test-token')
        session.action = lambda request: (_ for _ in ()).throw(AttributeError('internal detail'))
        with patch('untap_local_review.HTTPServer', side_effect=lambda address, handler: handler):
            handler_type = make_server(session)
        handler = object.__new__(handler_type)
        handler.server = SimpleNamespace(server_port=1234)
        handler.path = '/test-token/action'
        handler.headers = {'Host': '127.0.0.1:1234', 'Origin': 'http://127.0.0.1:1234', 'X-Untap-Token': 'test-token', 'Content-Type': 'application/json', 'Content-Length': '2'}
        handler.rfile = io.BytesIO(b'{}')
        handler.reply = lambda *args: responses.append(args)
        responses = []
        handler.do_POST()
        self.assertEqual(responses[0][0], 500)
        self.assertEqual(json.loads(responses[0][1]), {'error': 'Unexpected local review error'})

    def test_reviewed_run_permissions_match_normal_directories(self):
        from untap_refresh import refresh
        import stat
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            normal = root / 'normal'
            normal.mkdir()
            save_snapshot(build_snapshot([], 'Menu'), source / 'results.json')
            output = refresh(source)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), stat.S_IMODE(normal.stat().st_mode))

    def test_tee_exposes_terminal_attributes(self):
        from untap import _TeeOutput
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as terminal:
            log = io.StringIO()
            tee = _TeeOutput(terminal, log)
            self.assertEqual(tee.encoding, terminal.encoding)
            self.assertEqual(tee.isatty(), terminal.isatty())
            self.assertEqual(tee.fileno(), terminal.fileno())
            tee.write('hello')
            self.assertEqual(log.getvalue(), 'hello')


class FetchRefactorTests(unittest.TestCase):
    def test_all_replay_paths_share_the_browser_json_post(self):
        import untap_untappd as transport
        event = {'url': 'https://example.algolia.net/queries', 'algolia_requests': [{'indexName': 'beer', 'params': {'query': 'Fazy', 'page': '0'}, 'query': 'Fazy'}]}
        page = type('Page', (), {'evaluate': lambda self, script, args: calls.append((script, args)) or {'status': 200, 'ok': True, 'payload': {'results': []}}})()
        calls = []
        exact = transport._fetch_algolia_exact_request(page, event)
        ordinary = transport._fetch_algolia_page(page, event, 1)
        sorted_page = transport._fetch_algolia_sorted_page(page, event, 'Fazy', 2, 'beer')
        self.assertEqual(exact, (200, {'results': []}, None))
        self.assertEqual(ordinary, ({'results': []}, None))
        self.assertEqual(sorted_page, ({'results': []}, None))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len({call[0] for call in calls}), 1)
        self.assertTrue(all(args['url'] == event['url'] for _, args in calls))

    def test_browser_post_preserves_http_and_malformed_response_errors(self):
        import untap_untappd as transport
        event = {'url': 'https://example.algolia.net/queries', 'algolia_requests': [{'indexName': 'beer', 'params': {'query': 'Fazy'}, 'query': 'Fazy'}]}
        for response, error in [({'status': 429, 'ok': False}, 'HTTP 429'), ({'status': 200, 'ok': True, 'payload': None}, 'response payload was not JSON')]:
            page = type('Page', (), {'evaluate': lambda self, script, args: response})()
            self.assertEqual(transport._fetch_algolia_page(page, event, 0), (None, error))
            self.assertEqual(transport._fetch_algolia_exact_request(page, event)[2], error)


class SearchDiagnosticRefactorTests(unittest.TestCase):
    def test_debug_search_still_prints_captured_candidates(self):
        import untap_matcher as matcher
        from test_untap_v86 import MatcherV86Tests, candidate
        original = matcher.search_one
        def debug_search(*args, **kwargs):
            kwargs['debug'] = True
            return original(*args, **kwargs)
        with patch.object(matcher, 'search_one', side_effect=debug_search), contextlib.redirect_stdout(io.StringIO()) as output:
            result, _ = MatcherV86Tests().run_search([candidate('Fazy', 'Badlands', 5)], 'Fazy', 'Badlands', 5)
        self.assertEqual(result['status'], 'ok')
        self.assertIn('Algolia page-0 candidate diagnostics:', output.getvalue())
        self.assertIn('Candidates:', output.getvalue())


class ProductionVintageGuardTests(unittest.TestCase):
    def rows(self, base=False, sibling=True, suffix=' (2026)', brewery='Samuel Adams', abv=5):
        from test_untap_v86 import candidate
        rows = [candidate('Boston Lager', 'Samuel Adams', 5, 1., 1), candidate('Boston Lager' + suffix, brewery, abv, .9, 2)]
        rows[0].update(in_production=base, rating_count=999999)
        rows[1].update(in_production=sibling, rating_count=1)
        return rows

    def test_retired_exact_and_current_same_abv_vintage_require_review(self):
        import untap_matcher as matcher
        from test_untap_v86 import MatcherV86Tests
        for base, sibling in [(False, True), (0, 1), ('false', 'true'), ('0', '1')]:
            rows = self.rows(base, sibling)
            with self.subTest(base=base, sibling=sibling):
                self.assertIsNone(matcher.unique_exact_identity_candidate(rows, 'Boston Lager', 'Samuel Adams', 5))
                result, _ = MatcherV86Tests().run_search(rows, 'Boston Lager', 'Samuel Adams', 5)
                self.assertEqual(result['status'], 'ambiguous')
                self.assertIn('out of production', result['reason'])
                self.assertEqual({c['url'] for c in result['alternatives']}, {c['url'] for c in rows})
                self.assertIn('Confirm the release manually', render_html_report([result]))

    def test_unknown_status_and_other_identity_differences_do_not_trigger(self):
        import untap_matcher as matcher
        for kwargs in [dict(base=None), dict(sibling=None), dict(base=True), dict(sibling=False),
                       dict(brewery='Other Brewery'), dict(abv=6), dict(suffix=' DDH (2026)'),
                       dict(suffix=' Batch 2'), dict(suffix=' Peach (2026)')]:
            rows = self.rows(**kwargs)
            with self.subTest(kwargs=kwargs):
                self.assertFalse(matcher.production_vintage_conflict(rows, 'Boston Lager', 'Samuel Adams', 5))
                self.assertIs(matcher.unique_exact_identity_candidate(rows, 'Boston Lager', 'Samuel Adams', 5), rows[0])

    def test_explicit_vintage_preserves_exact_identity_rule(self):
        import untap_matcher as matcher
        rows = self.rows()
        rows[0]['name'] = 'Boston Lager (2025)'
        rows[1]['name'] = 'Boston Lager (2025) (2026)'
        self.assertFalse(matcher.production_vintage_conflict(rows, 'Boston Lager (2025)', 'Samuel Adams', 5))
        self.assertIs(matcher.unique_exact_identity_candidate(rows, 'Boston Lager (2025)', 'Samuel Adams', 5), rows[0])

    def test_conflict_cannot_be_bypassed_by_score_or_incomplete_discovery(self):
        from test_untap_v86 import MatcherV86Tests
        rows = self.rows()
        for diagnostics in [None, {'capped': True}]:
            with self.subTest(diagnostics=diagnostics):
                result, _ = MatcherV86Tests().run_search(rows, 'Boston Lager', 'Samuel Adams', 5, diagnostics=diagnostics)
                self.assertEqual(result['status'], 'ambiguous')
                self.assertIn('in-production vintage', result['reason'])
