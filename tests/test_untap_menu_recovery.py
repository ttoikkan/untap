"""Review-only recovery for the identities missed by the November 27 menu run."""
import copy
import json
from pathlib import Path
import unittest

import untap.matcher as matcher
from tests.corpus_tools import replay_case

CASES = {
    'live_recovery_harvest': 'https://untappd.com/b/crak-brewery-harvest-crak-2026/6961463',
    'recovery_harvest_zero': 'https://untappd.com/b/crak-brewery-harvest-crak-2026/6961463',
    'recovery_tyranny_annotation': 'https://untappd.com/b/ill-will-brewing-tyranny/6701913',
    'recovery_broccoli_spelling': 'https://untappd.com/b/messorem-broccoli-fauche-tout-xt/6920064',
    'recovery_hyperion_annotation': 'https://untappd.com/b/varietal-beer-company-hyperion-2026/6847063',
}


def load(name):
    return json.loads((Path(__file__).parent / 'testdata/search_corpus' / (name + '.json')).read_text())


def candidate(**changes):
    return dict(dict(name='Harvest Crak 2026', brewery='CRAK Brewery', abv=0., score=.6,
                     url='https://untappd.com/b/test/1', text='Harvest Crak 2026'), **changes)


class MenuRecoveryTests(unittest.TestCase):
    def test_all_four_expected_beers_are_selectable_but_never_auto_confirmed(self):
        for name, url in CASES.items():
            with self.subTest(case=name):
                case = load(name)
                before = copy.deepcopy(case)
                result, page, problems = replay_case(case)
                self.assertEqual(problems, [])
                self.assertEqual(result['status'], 'ambiguous')
                self.assertIn(url, [row.get('url') for row in result['alternatives']])
                self.assertEqual(case, before)
                self.assertFalse(page.exchanges)

    def test_429_during_each_recovery_stops_without_further_requests(self):
        for name in CASES:
            with self.subTest(case=name):
                case = load(name)
                case['exchanges'][-1].update(status=429, payload={'message': 'rate limited'})
                case['expected'] = {'status': 'rate_limited'}
                result, page, problems = replay_case(case)
                self.assertEqual(problems, [])
                self.assertEqual(result['status'], 'rate_limited')
                self.assertEqual(len(page.requests), len(case['exchanges']))

    def test_annotation_retries_are_bounded_and_only_added_after_zero_hits(self):
        beer, brewery = 'Hyperion - Wet Hop', 'Varietal x Structures'
        plain = matcher.build_search_fallback_queries('Varietal Structures Hyperion Wet Hop',
                    expected_beer=beer, expected_brewery=brewery)
        expanded = matcher.build_search_fallback_queries('Varietal Structures Hyperion Wet Hop',
                    expected_beer=beer, expected_brewery=brewery, enable_trailing_relaxation=True)
        self.assertNotIn('Varietal Hyperion', plain)
        self.assertEqual(expanded[-2:], ['Varietal Hyperion', 'Structures Hyperion'])
        self.assertIsNone(matcher.annotation_recovery_base('Tyranny (2026)'))
        self.assertEqual(matcher.annotation_recovery_base('Tyranny (Pulp Fiction-themed)'), 'Tyranny')
        self.assertFalse(matcher.plausible_review_identity(candidate(name='Hyperion 0038'), 'Hyperion 0037', 'CRAK'))
        self.assertFalse(matcher.plausible_review_identity(candidate(brewery='Other Brewery'), 'Harvest Crak 2026', 'CRAK'))
        self.assertFalse(matcher.plausible_review_identity(candidate(brewery=None), 'Harvest Crak 2026', 'CRAK'))

    def test_trailing_spelling_review_requires_same_abv_and_numeric_identity(self):
        row = candidate(name='Broccoli Fauche Tout XT', brewery='Messorem', abv=7.9)
        args = ('Brocoli Fauche Tout - XTRM Turbo', 'Messorem x Other Half', 7.9)
        self.assertTrue(matcher.candidate_needs_spelling_review(row, *args))
        for changes in ({'abv': 7.}, {'brewery': 'Unrelated Brewery'}, {'name': 'Broccoli Fauche Cherry XT'}):
            self.assertFalse(matcher.candidate_needs_spelling_review(dict(row, **changes), *args))
        self.assertFalse(matcher.candidate_needs_spelling_review(
            dict(row, name='Demoliri 0038 XT'), 'Demoliri 0037 - XTRM Turbo', 'Messorem', 7.9))

    def test_zero_abv_is_only_review_evidence_not_unknown_or_confirmation(self):
        row = candidate()
        expected = dict(beer='Crak Harvest 2026', brewery='Crak', abv=6.5, style=None)
        self.assertFalse(matcher._exclude_abv_conflicts([row], 6.5))
        result = matcher.decide_candidates([row], expected, .425, {})
        self.assertEqual(result['kind'], 'ambiguous')
        self.assertEqual(result['rule'], 'zero_abv_review')
        self.assertIn('can also mean unknown', result['reason'])
        self.assertEqual(row['abv'], 0.)
        for changes in ({'name': 'Unrelated'}, {'score': .1}, {'brewery': None}, {'brewery': 'Other'}):
            result = matcher.decide_candidates([dict(row, **changes)], expected, .425, {})
            self.assertEqual(result['kind'], 'failed')
        zero = dict(expected, beer='Zero Beer', abv=0.)
        result = matcher.decide_candidates([candidate(name='Zero Beer', score=1.)], zero, .425, {})
        self.assertEqual(result['kind'], 'selected')
        known = candidate(name='Crak Harvest 2026', abv=6.5, score=1.)
        result = matcher.decide_candidates([known, row], expected, .425, {})
        self.assertEqual(result['kind'], 'selected')
