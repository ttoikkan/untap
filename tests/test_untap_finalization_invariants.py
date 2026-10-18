"""Seeded missing-metadata invariants at the decision/finalization boundary."""
import copy
import os
import random
import unittest
from unittest.mock import patch

import untap.matcher as matcher


class StrictDetailPage:
    def __init__(self):
        self.visits = []

    def goto(self, url):
        if not isinstance(url, str) or not url.startswith('https://untappd.com/b/'):
            raise AssertionError(f'Invalid detail navigation: {url!r}')
        self.visits.append(url)


def detail_response(page, url, **kwargs):
    page.goto(url)
    return dict(beer='Beer', brewery='Brewery', abv='5%', rating=4., ratings=100, url=url)


class FinalizationInvariantTests(unittest.TestCase):
    def test_missing_metadata_never_raises_or_navigates_without_url(self):
        seed = int(os.environ.get("UNTAP_FINALIZATION_SEED", "112"))
        count = int(os.environ.get("UNTAP_FINALIZATION_CASES", "1000"))
        self.assertGreater(count, 0, "UNTAP_FINALIZATION_CASES must be positive")
        rng = random.Random(seed)
        fields = ['url', 'abv', 'brewery', 'rating_score', 'rating_count']
        expected = dict(beer='Beer', brewery='Brewery', abv=5., style=None)
        for index in range(count):
            row = dict(name='Beer', text='Brewery Beer 5% ABV', score=rng.choice([1., .1]),
                       brewery='Brewery', abv=5., bid=index+1,
                       url=f'https://untappd.com/b/beer/{index+1}', rating_score=4., rating_count=100)
            for field in fields:
                mode = rng.randrange(3)
                if mode == 0:
                    row.pop(field)
                elif mode == 1:
                    row[field] = None
            before = copy.deepcopy(row)
            page = StrictDetailPage()
            with self.subTest(seed=seed, case=index, row=row):
                decision = matcher.decide_candidates([row], expected, .425, {})
                with patch.object(matcher, 'extract_beer_info', side_effect=detail_response):
                    result = matcher._finalize_decision(page, 'Brewery Beer', decision, {}, None)
                self.assertIn(result['status'], matcher.MATCH_RESULT_STATUSES)
                self.assertEqual(row, before)
                if not row.get('url'):
                    self.assertFalse(page.visits)
                    self.assertNotEqual(result['status'], 'ok')

    def test_multicandidate_ambiguity_preserves_incomplete_alternatives(self):
        for production_conflict in (False, True):
            for field in ('url', 'abv', 'brewery', 'rating_score', 'rating_count'):
                with self.subTest(production_conflict=production_conflict, field=field):
                    rows = [dict(name='Beer', text='Brewery Beer 5% ABV', brewery='Brewery',
                                 abv=5., score=1., bid=1, url='https://untappd.com/b/beer/1',
                                 rating_score=4., rating_count=100, in_production=False),
                            dict(name='Beer 2026', text='Brewery Beer 2026 5% ABV', brewery='Brewery',
                                 abv=5., score=.99, bid=2, url='https://untappd.com/b/beer-2026/2',
                                 rating_score=4., rating_count=100, in_production=True)]
                    for row in rows:
                        row.pop(field)
                    before = copy.deepcopy(rows)
                    decision = dict(kind='ambiguous', rule='production_conflict' if production_conflict else 'ambiguity',
                                    candidate=rows[0], reason='Review candidates', alternatives=rows,
                                    same_abv_variants=rows[1:], search_warning=None,
                                    diagnostics=[], excluded_candidates=[])
                    page = StrictDetailPage()
                    result = matcher._finalize_decision(page, 'Brewery Beer', decision, {}, None)
                    self.assertEqual(result['status'], 'ambiguous')
                    self.assertEqual([item['name'] for item in result['alternatives']], ['Beer', 'Beer 2026'])
                    self.assertEqual(len(result['same_abv_variants']), 0 if production_conflict else 1)
                    self.assertFalse(page.visits)
                    self.assertEqual(rows, before)

    def test_selected_metadata_falls_back_only_with_a_url(self):
        for url in (None, 'https://untappd.com/b/beer/1'):
            row = dict(name='Beer', text='Brewery Beer 5% ABV', score=1., bid=1, url=url)
            decision = dict(kind='selected', rule='score', candidate=row, alternatives=[row],
                            reason=None, same_abv_variants=[], search_warning=None,
                            diagnostics=[], excluded_candidates=[])
            page = StrictDetailPage()
            with patch.object(matcher, 'extract_beer_info', side_effect=detail_response):
                result = matcher._finalize_decision(page, 'Brewery Beer', decision, {}, None)
            self.assertEqual(result['status'], 'ok' if url else 'low_confidence')
            self.assertEqual(page.visits, [url] if url else [])
