import contextlib
import csv
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import untap.batch as untap_batch
class BatchContractTests(unittest.TestCase):
    def _temp_path(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        path = handle.name
        handle.close()
        return path




    def test_rate_limit_stops_remaining_batch(self):
        items = ['one', 'two', 'three']
        responses = [
            {'query': 'one', 'status': 'ok', 'beer': 'One'},
            {'query': 'two', 'status': 'rate_limited', 'reason': 'HTTP 429'},
        ]
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'),\
             mock.patch.object(untap_batch, 'search_one', side_effect=responses) as search,\
             mock.patch('builtins.print'):
            results = untap_batch.run_batch(object(), items)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[1]['status'], 'rate_limited')
        self.assertEqual(results[2]['status'], 'not_attempted')
        self.assertEqual(results[2]['query'], 'three')
        self.assertEqual(results[1]['batch_remaining'], 1)

    def test_search_exception_becomes_failed_result(self):
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'),\
             mock.patch.object(untap_batch, 'search_one', side_effect=RuntimeError('boom')),\
             mock.patch('builtins.print'):
            results = untap_batch.run_batch(object(), ['query'])
        self.assertEqual(results[0]['status'], 'failed')
        self.assertEqual(results[0]['reason'], 'boom')

    def test_architecture_boundary_keeps_batch_and_cli_responsibilities_separate(self):
        import untap.run as untap
        self.assertEqual(untap.run_batch.__module__, 'untap.batch')
        self.assertEqual(untap.save_csv.__module__, 'untap.run_output')
        self.assertFalse(hasattr(untap_batch, 'load_resume_csv'))

    def test_batch_timing_reports_per_item_and_whole_batch(self):
        items = ['one', 'two']
        responses = [
            {'query': 'one', 'status': 'ok', 'beer': 'One'},
            {'query': 'two', 'status': 'ok', 'beer': 'Two'},
        ]
        output = io.StringIO()
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'),\
             mock.patch.object(untap_batch, 'debug_timing_enabled', return_value=True),\
             mock.patch.object(untap_batch, 'search_one', side_effect=responses),\
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
        with mock.patch.object(untap_batch, '_reset_run_algolia_debug_stats'),\
             mock.patch.object(untap_batch, 'debug_timing_enabled', return_value=False),\
             mock.patch.object(
                 untap_batch, 'search_one',
                 return_value={'query': 'one', 'status': 'ok', 'beer': 'One'},
             ), mock.patch.object(untap_batch, 'perf_counter') as clock,\
             mock.patch('builtins.print'):
            untap_batch.run_batch(object(), ['one'])
        clock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
