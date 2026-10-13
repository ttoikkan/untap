"""Report model semantics and byte-identical pre-extraction HTML contracts."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from untap.report_model import prepare_report_rows
from untap.report import render_html_report
from untap.snapshot import menu_item_ids


class ReportModelTests(unittest.TestCase):
    def fixtures(self):
        return json.loads(Path(__file__).with_name('testdata').joinpath('report_model_v109.json').read_text())

    def test_html_bytes_match_pre_extraction_renderer(self):
        fixtures = self.fixtures()
        self.assertEqual(len(fixtures), 40)
        for case in fixtures:
            with self.subTest(case=case['name']):
                before = copy.deepcopy(case['results'])
                html = render_html_report(case['results'], 'Model baseline', '2026-10-12')
                self.assertEqual(hashlib.sha256(html.encode()).hexdigest(), case['html_sha256'])
                self.assertEqual(case['results'], before)

    def test_duplicate_object_occurrences_keep_distinct_ids(self):
        result = {'query': 'Beer', 'status': 'failed'}
        rows = prepare_report_rows([result, result])
        self.assertEqual([row.item_id for row in rows], menu_item_ids([result, result]))
        self.assertNotEqual(rows[0].item_id, rows[1].item_id)

    def test_display_notes_and_excluded_links_are_separate_plain_data(self):
        result = dict(query='<Query>', status='ambiguous', input_abv='5', input_brewery='Brewery',
                      alternatives=[dict(name='<Beer>', url='https://untappd.com/b/beer/1',
                                         abv=6., user_added=True)],
                      excluded_candidates=[dict(name='Excluded', abv=8., exclusion_reason='<Conflict>')])
        before = copy.deepcopy(result)
        row = prepare_report_rows([result])[0]
        self.assertEqual(row.query, '<Query>')
        self.assertEqual(row.candidates[0].name, '<Beer>')
        self.assertTrue(row.candidates[0].abv_mismatch)
        self.assertEqual(row.candidates[0].score, 'User-added')
        self.assertEqual(row.excluded[0].reason, '<Conflict>')
        self.assertEqual(len(row.candidates), 1)
        self.assertEqual(result, before)
        result['alternatives'][0]['name'] = 'Changed'
        self.assertEqual(row.candidates[0].name, '<Beer>')

    def test_manual_and_automatic_selection_labels_remain_distinct(self):
        choice = dict(name='Sibling', url='https://untappd.com/b/beer/2')
        result = dict(query='Beer', beer='Beer', status='ok', url='https://untappd.com/b/beer/1', alternatives=[choice])
        automatic = prepare_report_rows([result])[0]
        self.assertIsNone(automatic.confirmed)
        self.assertEqual(automatic.automatic_selection, result['url'])
        manual = prepare_report_rows([dict(result, manually_confirmed=True)])[0]
        self.assertEqual(manual.status, 'Ambiguous')
        self.assertEqual(manual.status_key, 'ambiguous')
        self.assertEqual(manual.initial_selection, result['url'])
        self.assertEqual(manual.automatic_selection, '')
