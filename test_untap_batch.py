import contextlib
import csv
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap_batch


class BatchContractTests(unittest.TestCase):
    def _temp_path(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        path = handle.name
        handle.close()
        return path

    def test_csv_round_trip_preserves_confirmed_resume_identity_and_type(self):
        path = self._temp_path()
        try:
            result = {
                'original_menu_text': 'Badlands\tFazy (2026)\t6,5%\tIPA',
                'input_brewery': 'Badlands',
                'input_beer': 'Fazy (2026)',
                'input_abv': '6.5',
                'input_style': 'IPA',
                'query': 'Badlands Fazy (2026)',
                'status': 'ok',
                'beer': 'Fazy (2026)',
                'brewery': 'Badlands Brewing Company',
                'rating': 4.30,
                'ratings': 109,
                'abv': '6.5%',
                'ibu': None,
                'type_name': 'IPA - New England / Hazy',
                'score': 1.0,
                'url': 'https://untappd.com/b/example/1',
            }
            with mock.patch('builtins.print'):
                untap_batch.save_csv([result], path)
            loaded = untap_batch.load_resume_csv(path)
            key = untap_batch._menu_resume_identity(
                'Badlands', 'Fazy (2026)', 6.5, 'IPA'
            )
            restored = loaded['by_identity'][key][0]
            self.assertEqual(restored['status'], 'ok')
            self.assertEqual(restored['beer'], 'Fazy (2026)')
            self.assertEqual(restored['type_name'], 'IPA - New England / Hazy')
            self.assertEqual(restored['rating'], 4.30)
            self.assertEqual(restored['ratings'], 109)
        finally:
            os.unlink(path)

    def test_resume_ignores_uncertain_rows(self):
        path = self._temp_path()
        try:
            fields = [
                'original_menu_text', 'input_brewery', 'input_beer',
                'input_abv', 'input_style', 'query', 'status', 'beer', 'brewery'
            ]
            with open(path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    'original_menu_text': 'Brujos\tPopulus w/ Citra\t7,5%\tIPA',
                    'input_brewery': 'Brujos',
                    'input_beer': 'Populus w/ Citra',
                    'input_abv': '7.5',
                    'input_style': 'IPA',
                    'query': 'Brujos Populus w/ Citra',
                    'status': 'ambiguous',
                    'beer': 'Populus W/ CITRA',
                    'brewery': 'Brujos Brewing',
                })
            loaded = untap_batch.load_resume_csv(path)
            self.assertEqual(untap_batch.reusable_resume_count(loaded), 0)
        finally:
            os.unlink(path)

    def test_resume_is_occurrence_aware(self):
        identity = untap_batch._menu_resume_identity('B', 'Beer', 5.0, 'IPA')
        resume_rows = {
            'by_identity': {
                identity: [
                    {'status': 'ok', 'beer': 'Beer', 'brewery': 'Brewery', 'rating': 4.0},
                    {'status': 'ok', 'beer': 'Beer', 'brewery': 'Brewery', 'rating': 4.1},
                ]
            },
            'by_original_legacy': {},
        }
        items = [
            {'query': 'B Beer', 'original': 'row1', 'brewery': 'B', 'beer': 'Beer', 'menu_abv': 5.0, 'style': 'IPA'},
            {'query': 'B Beer', 'original': 'row2', 'brewery': 'B', 'beer': 'Beer', 'menu_abv': 5.0, 'style': 'IPA'},
        ]
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'), \
             mock.patch.object(untap_batch, 'search_one') as search, \
             mock.patch('builtins.print'):
            results = untap_batch.run_batch(object(), items, resume_rows=resume_rows)
        search.assert_not_called()
        self.assertEqual([r['rating'] for r in results], [4.0, 4.1])
        self.assertEqual([r['original_menu_text'] for r in results], ['row1', 'row2'])

    def test_rate_limit_stops_remaining_batch(self):
        items = ['one', 'two', 'three']
        responses = [
            {'query': 'one', 'status': 'ok', 'beer': 'One'},
            {'query': 'two', 'status': 'rate_limited', 'reason': 'HTTP 429'},
        ]
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'), \
             mock.patch.object(untap_batch, 'search_one', side_effect=responses) as search, \
             mock.patch('builtins.print'):
            results = untap_batch.run_batch(object(), items)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[-1]['status'], 'rate_limited')
        self.assertEqual(results[-1]['batch_remaining'], 1)

    def test_search_exception_becomes_failed_result(self):
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'), \
             mock.patch.object(untap_batch, 'search_one', side_effect=RuntimeError('boom')), \
             mock.patch('builtins.print'):
            results = untap_batch.run_batch(object(), ['query'])
        self.assertEqual(results[0]['status'], 'failed')
        self.assertEqual(results[0]['reason'], 'boom')

    def test_architecture_boundary_keeps_batch_and_cli_responsibilities_separate(self):
        cli_source = Path(__file__).with_name('untap.py').read_text()
        batch_source = Path(__file__).with_name('untap_batch.py').read_text()

        self.assertNotIn('import csv', cli_source)
        self.assertNotIn('def load_resume_csv(', cli_source)
        self.assertNotIn('def save_csv(', cli_source)
        self.assertNotIn('def run_batch(', cli_source)

        # Batch consumes normalized records/query strings; it must not parse raw menus
        # or directly operate on Playwright pages / Algolia network primitives.
        self.assertNotIn('read_validated_menu', batch_source)
        self.assertNotIn('parse_menu_lines', batch_source)
        for token in ('page.goto(', 'page.on(', 'page.evaluate(', 'page.locator('):
            self.assertNotIn(token, batch_source)

    def test_batch_timing_reports_per_item_and_whole_batch(self):
        items = ['one', 'two']
        responses = [
            {'query': 'one', 'status': 'ok', 'beer': 'One'},
            {'query': 'two', 'status': 'ok', 'beer': 'Two'},
        ]
        output = io.StringIO()
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'), \
             mock.patch.object(untap_batch, 'debug_timing_enabled', return_value=True), \
             mock.patch.object(untap_batch, 'search_one', side_effect=responses), \
             mock.patch.object(
                 untap_batch, 'perf_counter',
                 side_effect=[0.0, 1.0, 1.4, 2.0, 2.7, 3.0],
             ), contextlib.redirect_stdout(output):
            results = untap_batch.run_batch(object(), items)
            untap_batch.print_batch_timing_summary()

        self.assertEqual(len(results), 2)
        stats = untap_batch.get_batch_timing_stats()
        self.assertEqual(stats['count'], 2)
        self.assertAlmostEqual(stats['total_item_seconds'], 1.1)
        self.assertAlmostEqual(stats['min_item_seconds'], 0.4)
        self.assertAlmostEqual(stats['max_item_seconds'], 0.7)
        self.assertAlmostEqual(stats['batch_seconds'], 3.0)
        text = output.getvalue()
        self.assertIn('[timing] item total: 0.400s | one', text)
        self.assertIn('[timing] item total: 0.700s | two', text)
        self.assertIn('Timed batch items: 2', text)
        self.assertIn('Whole batch elapsed time: 3.000s', text)

    def test_batch_timing_disabled_does_not_read_perf_counter(self):
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'), \
             mock.patch.object(untap_batch, 'debug_timing_enabled', return_value=False), \
             mock.patch.object(
                 untap_batch, 'search_one',
                 return_value={'query': 'one', 'status': 'ok', 'beer': 'One'},
             ), mock.patch.object(untap_batch, 'perf_counter') as clock, \
             mock.patch('builtins.print'):
            untap_batch.run_batch(object(), ['one'])
        clock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
