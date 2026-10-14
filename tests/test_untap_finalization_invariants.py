"""Seeded missing-metadata invariants at the decision/finalization boundary."""
import copy
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
        rng = random.Random(112)
        fields = ['url', 'abv', 'brewery', 'rating_score', 'rating_count']
        expected = dict(beer='Beer', brewery='Brewery', abv=5., style=None)
        counts = {'selected': 0, 'low_confidence': 0, 'detail': 0}
        for index in range(1000):
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
            with self.subTest(seed=112, case=index, row=row):
                decision = matcher.decide_candidates([row], expected, .425, {})
                if decision['kind'] in counts:
                    counts[decision['kind']] += 1
                with patch.object(matcher, 'extract_beer_info', side_effect=detail_response):
                    result = matcher._finalize_decision(page, 'Brewery Beer', decision, {}, None)
                self.assertIn(result['status'], matcher.MATCH_RESULT_STATUSES)
                self.assertEqual(row, before)
                if not row.get('url'):
                    self.assertFalse(page.visits)
                    self.assertNotEqual(result['status'], 'ok')
                counts['detail'] += bool(page.visits)
        self.assertTrue(all(counts.values()), counts)
