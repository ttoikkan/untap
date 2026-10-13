"""Shared review decisions stay pure and independent of HTML presentation."""
import copy
import unittest

from untap.review_policy import review_candidates, sorted_review_results, available_review_candidate, selection_report_id
from untap.report import render_html_report


def candidate(name, score, identifier, **metadata):
    return dict(name=name, score=score, url=f'https://untappd.com/b/beer/{identifier}', **metadata)


class ReviewPolicyTests(unittest.TestCase):
    def test_family_precedence_stable_order_cap_and_user_additions(self):
        family = [candidate(f'Beer {i:02}', 1., i) for i in range(12)]
        added = candidate('Added', .1, 99, user_added=True)
        result = dict(status='ambiguous', same_abv_variants=list(reversed(family)) + [added],
                      alternatives=[candidate('Other', 2., 100)],
                      excluded_candidates=[candidate('Excluded', 3., 101)])
        before = copy.deepcopy(result)
        self.assertEqual(review_candidates(result), family[:10] + [added])
        self.assertEqual(result, before)
        self.assertIs(available_review_candidate(result, added['url']), added)
        self.assertIsNone(available_review_candidate(result, family[11]['url']))
        self.assertIsNone(available_review_candidate(result, result['alternatives'][0]['url']))
        self.assertIsNone(available_review_candidate(result, result['excluded_candidates'][0]['url']))

    def test_selection_status_and_url_contract(self):
        choice = candidate('Beer', 1., 1)
        for status in ('ok', 'ambiguous', 'failed', 'not_attempted', 'rate_limited', 'low_confidence'):
            result = dict(status=status, alternatives=[choice])
            self.assertEqual(available_review_candidate(result, choice['url']) is choice, status in ('ok', 'ambiguous'))
            for url in (None, 1, 'javascript:alert(1)', 'https://www.untappd.com/b/beer/1'):
                self.assertIsNone(available_review_candidate(result, url))

    def test_row_order_is_stable_and_matches_renderer(self):
        rows = [dict(query='Unknown', status='failed'),
                dict(query='Confirmed', beer='Confirmed', status='ok', rating=4.),
                dict(query='Review', status='ambiguous', alternatives=[candidate('Sibling', 1., 2, rating='4.5')]),
                dict(query='Tied', beer='Tied', status='ok', rating=4.)]
        before = copy.deepcopy(rows)
        ordered = sorted_review_results(rows)
        self.assertEqual([r['query'] for r in ordered], ['Review', 'Confirmed', 'Tied', 'Unknown'])
        html = render_html_report(rows, 'Menu', '2026-01-01')
        positions = [html.index('>' + row['query'] + '</h3>') for row in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(rows, before)

    def test_identity_preserves_title_normalization_and_detects_changed_evidence(self):
        rows = [dict(query='Beer', status='failed')]
        self.assertEqual(selection_report_id(rows, ' Menu ', '2026-01-01'), selection_report_id(rows, 'Menu', '2026-01-01'))
        self.assertEqual(selection_report_id(rows, ' ', '2026-01-01'), selection_report_id(rows, 'Untap Results', '2026-01-01'))
        self.assertNotEqual(selection_report_id(rows, 'Menu', '2026-01-01'), selection_report_id(rows, 'Menu', '2026-01-02'))
        changed = copy.deepcopy(rows)
        changed[0]['status'] = 'ambiguous'
        self.assertNotEqual(selection_report_id(rows, 'Menu', '2026-01-01'), selection_report_id(changed, 'Menu', '2026-01-01'))
