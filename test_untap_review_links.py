"""Conflict evidence is inspectable but never implicitly selectable."""
import copy
import tempfile
import unittest
from pathlib import Path

from test_untap_decision_characterization import observe
from test_untap_v86 import candidate
from untap_report import render_html_report, selection_report_id, _review_candidates
from untap_refresh import apply_selection_payload
from untap_snapshot import build_snapshot, save_snapshot, load_snapshot


def conflict(rows, brewery='Badlands', abv=5.):
    return observe(dict(name='Conflict', candidates=rows, beer='Beer', brewery=brewery,
                        abv=abv, style='IPA', context={}))['result']


class ConflictReviewLinksTests(unittest.TestCase):
    def test_identity_conflicts_preserve_inspection_evidence(self):
        for rows, brewery, reason in [
            ([candidate('Beer', 'Badlands', 8.)], 'Badlands', 'ABV conflicts'),
            ([candidate('Beer', 'Unrelated', 5.)], 'Badlands', 'Brewery does not match'),
            ([candidate('Beer', 'Brasserie du Bas-Canada', 5.)], 'BBC', 'Brewery does not match')]:
            with self.subTest(brewery=brewery, rows=rows):
                before = copy.deepcopy(rows)
                result = conflict(rows, brewery)
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result.get('alternatives'))
                self.assertFalse(_review_candidates(result))
                self.assertEqual(result['excluded_candidates'][0]['url'], rows[0]['url'])
                self.assertIn(reason, result['excluded_candidates'][0]['exclusion_reason'])
                self.assertEqual(rows, before)

    def test_mixed_conflicts_retain_order_and_individual_reasons(self):
        result = conflict([candidate('Beer', 'Badlands', 8., bid=1),
                           candidate('Beer', 'Other', 5., .9, 2)])
        excluded = result['excluded_candidates']
        self.assertEqual([c['url'] for c in excluded], ['https://untappd.com/b/fixture/1', 'https://untappd.com/b/fixture/2'])
        self.assertIn('ABV conflicts', excluded[0]['exclusion_reason'])
        self.assertIn('Brewery does not match', excluded[1]['exclusion_reason'])

    def test_snapshot_roundtrip_retains_links(self):
        snapshot = build_snapshot([conflict([candidate('Beer', 'Other', 5.)])], 'Menu')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'results.json'
            save_snapshot(snapshot, path)
            loaded = load_snapshot(path)
        self.assertEqual(loaded, snapshot)
        html = render_html_report([loaded['items'][0]['result']], 'Menu')
        self.assertIn('href="https://untappd.com/b/fixture/1"', html)
        self.assertIn('class="excluded-candidate"', html)
        self.assertNotIn('class="candidate-card"', html)
        self.assertIn('links for inspection only', html)

    def test_excluded_links_cannot_be_selected_even_with_other_alternatives(self):
        original = conflict([candidate('Beer', 'Other', 5.)])
        for status in ('failed', 'ambiguous'):
            result = copy.deepcopy(original)
            result['status'] = status
            result['alternatives'] = [candidate('Beer', 'Badlands', 5., bid=2)] if status == 'ambiguous' else []
            snapshot = build_snapshot([result], 'Menu')
            before = copy.deepcopy(snapshot)
            payload = {'format': 'untap-manual-review-trial-v1',
                       'report_id': selection_report_id([result], snapshot['report']['title'], snapshot['report']['date']),
                       'selections': [{'row': 0, 'url': original['excluded_candidates'][0]['url']}]}
            with self.assertRaisesRegex(ValueError, 'not an available review candidate'):
                apply_selection_payload(snapshot, payload)
            self.assertEqual(snapshot, before)

    def test_excluded_metadata_is_escaped_and_unsafe_links_are_not_rendered(self):
        result = conflict([candidate('Beer', 'Other', 5.)])
        excluded = result['excluded_candidates'][0]
        excluded.update(name='<img src=x onerror=alert(1)>', url='javascript:alert(1)',
                        exclusion_reason='<script>unsafe</script>')
        html = render_html_report([result], 'Menu')
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertIn('&lt;script&gt;unsafe&lt;/script&gt;', html)
        self.assertNotIn('href="javascript:', html)

    def test_incomplete_report_recommends_continuation(self):
        html = render_html_report([{'query': 'Beer', 'status': 'not_attempted'}], 'Menu')
        self.assertIn('untap run --continue', html)
        self.assertNotIn('Rerun the menu', html)
