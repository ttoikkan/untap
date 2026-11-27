"""Regressions for detail evidence and complete, reversible review choices."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_untap_review_corrections import capture, hit, search, DetailPage
from untap import matcher
from untap.refresh import apply_selection_payload, refresh
from untap.local_review import ReviewSession
from untap.report import render_html_report
from untap.review_policy import selection_report_id
from untap.snapshot import build_snapshot, save_snapshot, load_snapshot

URL = 'https://untappd.com/b/green-fields/123'
OTHER = 'https://untappd.com/b/other/456'


def payload(snapshot, selections=(), pending=()):
    return dict(format='untap-manual-review-trial-v1',
                report_id=selection_report_id([i['result'] for i in snapshot['items']],
                    snapshot['report']['title'], snapshot['report']['date']),
                selections=list(selections), pending_candidates=list(pending))


def review_snapshot(status='ambiguous'):
    return build_snapshot([dict(query='Badlands Green Fields', status=status, input_abv=5.,
        alternatives=[dict(name='Green Fields', brewery='Badlands', url=URL, abv=5., rating=4.)])], 'Menu')


class ReviewFixTests(unittest.TestCase):
    def test_detail_abv_rechecks_missing_or_stale_search_abv(self):
        for search_abv in (None, 5.):
            for detail_abv, status in ((9., 'failed'), (6., 'failed'), (5.9, 'ok'), (5., 'ok')):
                with self.subTest(search_abv=search_abv, detail_abv=detail_abv):
                    captured, _ = capture(hit(beer_abv=search_abv, rating_score=None))
                    with patch.object(matcher, '_run_page0_search_transport', return_value=captured):
                        result = search(DetailPage(body=f'{detail_abv}% ABV'))
                    self.assertEqual(result['status'], status)
                    if status == 'failed':
                        self.assertIn('ABV conflict', result['reason'])
                        self.assertEqual(result['excluded_candidates'][0]['abv'], detail_abv)
                        self.assertFalse(result.get('alternatives'))

    def test_export_deselection_reopens_saved_result_and_keeps_added_candidates(self):
        snapshot = review_snapshot()
        apply_selection_payload(snapshot, payload(snapshot, [dict(row=0, url=URL)]))
        snapshot['items'][0]['result']['alternatives'].append(
            dict(name='Other', url=OTHER, abv=5., user_added=True))
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source = root / 'source'; source.mkdir()
            save_snapshot(snapshot, source / 'results.json')
            before = (source / 'results.json').read_bytes()
            choices = root / 'choices.json'
            choices.write_text(json.dumps(payload(snapshot)))
            output = refresh(source, selections=choices)
            saved = load_snapshot(output / 'results.json')
            self.assertEqual((source / 'results.json').read_bytes(), before)
        result = saved['items'][0]['result']
        self.assertEqual(result['status'], 'ambiguous')
        self.assertFalse(result.get('manually_confirmed'))
        self.assertEqual([c['url'] for c in result['alternatives']], [URL, OTHER])
        self.assertEqual(saved['manual_decisions'][-1]['action'], 'reopen')

    def test_reopen_validation_precedes_candidate_fetch_and_mutation(self):
        snapshot = review_snapshot()
        apply_selection_payload(snapshot, payload(snapshot, [dict(row=0, url=URL)]))
        snapshot['manual_decisions'] = []
        before = copy.deepcopy(snapshot)
        pending = [dict(item_id=snapshot['items'][0]['id'], url=OTHER)]
        with patch('untap.refresh.fetch_candidates') as fetch:
            with self.assertRaisesRegex(ValueError, 'Original alternatives'):
                apply_selection_payload(snapshot, payload(snapshot, pending=pending), fetch_pending=True)
        fetch.assert_not_called()
        self.assertEqual(snapshot, before)

    def test_low_confidence_candidate_can_be_selected_and_reopened(self):
        row = dict(name='Weak Beer', brewery='Badlands', score=.1, abv=None,
                   url=URL, text='Badlands Weak Beer')
        result = matcher._resolve_discovered_candidates(None, 'Badlands Beer', .425, False,
            'Beer', 'Badlands', 5., None, [row], None, [], {}, {}, None, False, None)
        self.assertEqual(result['status'], 'low_confidence')
        self.assertEqual(result['alternatives'][0]['url'], URL)
        snapshot = build_snapshot([result], 'Menu')
        apply_selection_payload(snapshot, payload(snapshot, [dict(row=0, url=URL)]))
        self.assertTrue(snapshot['items'][0]['result']['manually_confirmed'])
        apply_selection_payload(snapshot, payload(snapshot))
        self.assertEqual(snapshot['items'][0]['result']['status'], 'low_confidence')

    def test_legacy_low_confidence_can_fetch_and_save_a_candidate_locally(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            snapshot = build_snapshot([dict(query='Beer', status='low_confidence', match='Guess', url=OTHER)], 'Menu')
            save_snapshot(snapshot, root / 'results.json')
            session = ReviewSession(root)
            pending = [dict(item_id=snapshot['items'][0]['id'], url=URL)]
            choice = dict(name='Green Fields', brewery='Badlands', url=URL, abv=5., user_added=True)
            with patch('untap.refresh.fetch_candidates', return_value={'123': choice}):
                session.action(dict(action='fetch', payload=payload(session.snapshot, pending=pending)))
            response = session.action(dict(action='save', payload=payload(session.snapshot, [dict(row=0, url=URL)])))
            result = load_snapshot(Path(response['saved']) / 'results.json')['items'][0]['result']
            self.assertEqual(result['status'], 'ok')
            self.assertTrue(result['manually_confirmed'])


@unittest.skipUnless(os.environ.get('UNTAP_BROWSER_TESTS') == '1', 'opt-in offline browser checks')
class ReviewBrowserTests(unittest.TestCase):
    def test_low_confidence_controls_and_exported_deselection(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.set_default_timeout(5000)
                # All requests are blocked: these are local report controls only.
                page.route('**/*', lambda route: route.abort())
                snapshot = review_snapshot('low_confidence')
                snapshot['items'][0]['result']['alternatives'][0]['type_name'] = 'IPA - American'
                def show(current):
                    page.set_content(render_html_report([i['result'] for i in current['items']],
                        current['report']['title'], current['report']['date']))
                show(snapshot)
                self.assertEqual(page.get_by_role('button', name='Add candidate by URL').count(), 1)
                page.get_by_text('Low confidence', exact=True).click()
                card = page.locator('.results-list > *')
                self.assertTrue(card.is_visible())
                page.get_by_text('Failed', exact=True).click()
                self.assertFalse(card.is_visible())
                page.get_by_text('Low confidence', exact=True).click()
                style = page.get_by_text('IPA', exact=True)
                style.click()
                self.assertFalse(card.is_visible())
                style.click()
                self.assertTrue(card.is_visible())
                page.get_by_role('button', name='Confirm this beer').click()
                self.assertEqual(card.get_attribute('data-status'), 'ok')
                # Confirmation focuses the card under All results; the low filter must exclude it.
                page.get_by_text('Low confidence', exact=True).click()
                self.assertFalse(card.is_visible())
                page.get_by_text('All results', exact=True).click()
                page.get_by_role('button', name='Change selection').click()
                page.get_by_text('Low confidence', exact=True).click()
                self.assertTrue(card.is_visible())
                self.assertEqual(page.locator('.results-list > *').get_attribute('data-status'), 'low_confidence')
                page.get_by_role('button', name='Confirm this beer').click()
                with page.expect_download() as downloaded:
                    page.get_by_role('button', name='Export selections').click()
                apply_selection_payload(snapshot, json.loads(Path(downloaded.value.path()).read_text()))
                self.assertTrue(snapshot['items'][0]['result']['manually_confirmed'])
                show(snapshot)
                page.get_by_role('button', name='Change selection').click()
                with page.expect_download() as downloaded:
                    page.get_by_role('button', name='Export selections').click()
                apply_selection_payload(snapshot, json.loads(Path(downloaded.value.path()).read_text()))
                self.assertEqual(snapshot['items'][0]['result']['status'], 'low_confidence')
                legacy = build_snapshot([dict(query='Beer', status='low_confidence', match='Guess', url=OTHER)], 'Menu')
                show(legacy)
                self.assertEqual(page.get_by_role('button', name='Confirm this beer').count(), 0)
                self.assertEqual(page.get_by_role('button', name='Add candidate by URL').count(), 1)
            finally:
                browser.close()
