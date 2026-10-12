"""Seeded whole-chain invariants, with reproducible candidate-list shrinking."""
import builtins
import copy
import json
import os
import random
import unittest
from typing import get_type_hints
from unittest.mock import patch
from contextlib import ExitStack

import untap_matcher as matcher
from untap_types import Decision
import test_untap_decision_characterization as characterization


def expected_for(case):
    return {key: case[key] for key in ('beer', 'brewery', 'abv', 'style')}


def eligible(rows, expected):
    return [row for row in matcher._exclude_abv_conflicts(rows, expected['abv'])
            if matcher.candidate_has_brewery_overlap(row, expected['brewery'])]


def coherent_discovery(rows, expected, context):
    context = copy.deepcopy(context)
    context['ambiguity_reason'] = matcher.detect_candidate_ambiguity(
        eligible(rows, expected), expected['beer'], expected['abv'])
    return context


def make_candidate(name, brewery, abv, identifier, expected):
    parts = [name, brewery or 'Unknown']
    if abv is not None:
        parts.append(f'{abv:g}% ABV')
    row = dict(name=name, brewery=brewery, abv=abv, text='\n'.join(parts),
               url=f'https://untappd.com/b/generated/{identifier}', bid=identifier,
               rating_score=4., rating_count=100, type_name='IPA')
    query = ' '.join(value for value in (expected['brewery'], expected['beer']) if value)
    row['score'] = matcher.score_candidate(query, name, row['text'],
        expected_beer=expected['beer'], expected_brewery=expected['brewery'], expected_abv=expected['abv'])
    return row


def generated_case(rng):
    beer = rng.choice(['Green Fields', 'Boston Lager', 'Banishing 3', 'PB&J Mixtape', 'DDH Fort Point'])
    expected = dict(beer=beer, brewery=rng.choice(['Badlands', 'Samuel Adams', 'Third Moon', None]),
                    abv=rng.choice([0., 5., 6.5, 8., None]), style=rng.choice(['IPA', 'Stout', None]))
    variants = [beer, beer + ' 2025', beer + ' Peach', beer + ' DDH', beer + ' 2', 'Unrelated Nebula']
    target = expected['abv'] if expected['abv'] is not None else 5.
    rows = []
    for index in range(rng.randrange(8)):
        row = make_candidate(rng.choice(variants), rng.choice([expected['brewery'], 'Other Brewery', 'Unknown', None]),
            rng.choice([target, max(0., target - .99), target + .01, target + .99, target + 1., None]), index + 1, expected)
        state = rng.choice([True, False, None])
        if state is not None:
            row['in_production'] = state
        if rng.randrange(4) == 0:
            row.pop(rng.choice(['rating_score', 'rating_count', 'type_name']))
        rows.append(row)
    # Directed generation ensures rare precedence interactions are exercised.
    mode = rng.randrange(8)
    if mode < 6:
        expected['brewery'] = expected['brewery'] or 'Badlands'
        expected['abv'] = target
        if mode == 3:
            expected.update(beer='Banishing 3', brewery='Third Moon', abv=7.)
        beer, brewery, target = expected['beer'], expected['brewery'], expected['abv']
        rows = [make_candidate(beer, brewery, target, 1, expected)]
        if mode in (0, 1):
            rows.append(make_candidate(beer + ' 2025', brewery, target, 2, expected))
            if mode == 0:
                rows[0]['in_production'], rows[1]['in_production'] = False, True
        elif mode == 2:
            rows.append(make_candidate(beer + ' Peach', brewery, target, 2, expected))
        elif mode == 3:
            rows.append(make_candidate('Banishing 2', brewery, target, 2, expected))
        elif mode == 4:
            expected['beer'] = 'Green Fields'
            rows = [make_candidate('Green Fields ' + flavor, brewery, target, index, expected)
                    for index, flavor in enumerate(('Peach', 'Cherry'), 1)]
        else:
            rows = [make_candidate('Unrelated Nebula', brewery, target, 1, expected)]
    rows.sort(key=lambda row: row['score'], reverse=True)  # Stable ties, as in production.
    flag = rng.choice([None, None, 'capped', 'errors', 'ambiguity_early_stopped', 'ambiguity_established'])
    diagnostics = {flag: ['generated error'] if flag == 'errors' else True} if flag else None
    context = dict(expansion_diagnostics=diagnostics if rng.randrange(2) else None,
                   abv_sorted_diagnostics=None, fallback_review_required=rng.randrange(8) == 0,
                   fallback_query_used=None, expanded=bool(diagnostics), expanded_total_hits=len(rows))
    if diagnostics and context['expansion_diagnostics'] is None:
        context['abv_sorted_diagnostics'] = diagnostics
    if context['fallback_review_required']:
        context['fallback_query_used'] = 'generated recovery'
    return dict(rows=rows, expected=expected, min_score=.75 if mode == 5 else rng.choice([.425, .6, .75]),
                discovery=coherent_discovery(rows, expected, context))


def decide(case):
    return matcher.decide_candidates(case['rows'], case['expected'], case['min_score'], case['discovery'])


def check_case(case):
    before = copy.deepcopy(case)
    decision = decide(case)
    assert decision == decide(case), 'I1: identical input must be deterministic'
    assert case == before, 'I1: inputs must remain unchanged'
    if decision['kind'] == 'selected':
        selected = decision['candidate']
        assert matcher._exclude_abv_conflicts([selected], case['expected']['abv']), 'I3: selected ABV conflict'
        assert matcher.candidate_has_brewery_overlap(selected, case['expected']['brewery']), 'I3: selected brewery conflict'
    # I4 is stronger than the initial proposal: no selection at all when incomplete.
    incomplete = copy.deepcopy(case)
    incomplete['discovery']['expansion_diagnostics'] = {'errors': ['invariant interruption']}
    assert decide(incomplete)['kind'] != 'selected', 'I4: incomplete discovery selected a candidate'
    if decision['rule'] == 'unique_exact_identity':
        duplicate = copy.deepcopy(case)
        extra = copy.deepcopy(decision['candidate'])
        extra['url'] += '-distinct'
        extra['bid'] = 'distinct'
        duplicate['rows'].append(extra)
        duplicate['rows'].sort(key=lambda row: row['score'], reverse=True)
        duplicate['discovery'] = coherent_discovery(duplicate['rows'], duplicate['expected'], duplicate['discovery'])
        assert decide(duplicate)['rule'] != 'unique_exact_identity', 'I5: duplicate exact identity stayed unique'
        for field in ('abv', 'brewery'):
            missing = copy.deepcopy(case)
            for row in missing['rows']:
                if row['url'] == decision['candidate']['url']:
                    row[field] = None
            missing['discovery'] = coherent_discovery(missing['rows'], missing['expected'], missing['discovery'])
            assert decide(missing)['rule'] != 'unique_exact_identity', 'I6: missing evidence stayed unique'
    unknown = copy.deepcopy(case)
    for row in unknown['rows']:
        row.pop('in_production', None)
    assert decide(unknown)['rule'] != 'production_conflict', 'I7: absent production evidence established conflict'
    conflict = matcher.production_vintage_conflict(eligible(case['rows'], case['expected']),
        case['expected']['beer'], case['expected']['brewery'], case['expected']['abv'])
    if conflict:
        assert decision['kind'] == 'ambiguous' and decision['rule'] == 'production_conflict', 'I8: production conflict overridden'
    # I9 only covers explicitly excluded distractors, with coherent initial ambiguity.
    target = case['expected']['abv']
    if target is not None and eligible(case['rows'], case['expected']):
        distracted = copy.deepcopy(case)
        extra = make_candidate('Unrelated Nebula', case['expected']['brewery'], target + 2., 999, case['expected'])
        distracted['rows'].append(extra)
        distracted['rows'].sort(key=lambda row: row['score'], reverse=True)
        assert decide(distracted) == decision, 'I9: excluded distractor changed decision'
    # I11: the score gate is inclusive; exact acceptance rules remain exempt.
    if decision['rule'] == 'score':
        assert decision['candidate']['score'] >= case['min_score'], 'I11: score selection below minimum'
    if decision['kind'] == 'low_confidence':
        assert decision['candidate']['score'] < case['min_score'], 'I11: low confidence at/above minimum'
        boundary = copy.deepcopy(case)
        boundary['min_score'] = decision['candidate']['score']
        assert decide(boundary)['kind'] == 'selected', 'I11: score threshold boundary is not inclusive'
    # I12: family review wins over generic ambiguity/score, after higher-priority guards.
    survivors = eligible(case['rows'], case['expected'])
    family = matcher.same_abv_family_variants(survivors, case['expected']['beer'], case['expected']['abv'])
    if (len(family) >= 2 and not case['discovery'].get('fallback_review_required')
            and decision['rule'] not in {'production_conflict', 'exact_base', 'exact_numbered', 'unique_exact_identity'}):
        assert decision['kind'] == 'ambiguous' and decision['rule'] == 'same_abv_family', 'I12: same-ABV family did not require review'
        assert decision['same_abv_variants'] == family, 'I12: family variants lost or reordered'
    statuses = {'failed': {'failed'}, 'ambiguous': {'ambiguous'},
                'low_confidence': {'low_confidence'}, 'selected': {'ok', 'failed', 'rate_limited'}}
    assert statuses[decision['kind']] <= matcher.MATCH_RESULT_STATUSES, 'I10: unsupported finalization status'


def shrink_failure(case, invariant):
    """Delete candidates and optional metadata, retaining the same failing invariant."""
    current = copy.deepcopy(case)
    def fails(proposal):
        proposal['discovery'] = coherent_discovery(proposal['rows'], proposal['expected'], proposal['discovery'])
        try:
            check_case(proposal)
        except AssertionError as error:
            return str(error).split(':', 1)[0] == invariant
        return False
    index = 0
    while index < len(current['rows']):
        proposal = copy.deepcopy(current)
        del proposal['rows'][index]
        if fails(proposal):
            current = proposal
            index = 0
        else:
            index += 1
    for index in range(len(current['rows'])):
        for field in ('in_production', 'rating_score', 'rating_count', 'type_name'):
            if field not in current['rows'][index]:
                continue
            proposal = copy.deepcopy(current)
            proposal['rows'][index].pop(field)
            if fails(proposal):
                current = proposal
    return current


class DecisionInvariantTests(unittest.TestCase):
    def test_seeded_whole_chain_invariants(self):
        seed = int(os.environ.get('UNTAP_INVARIANT_SEED', '107'))
        count = int(os.environ.get('UNTAP_INVARIANT_CASES', '2000'))
        self.assertGreater(count, 0, 'UNTAP_INVARIANT_CASES must be positive')
        rng = random.Random(seed)
        for index in range(count):
            case = generated_case(rng)
            try:
                check_case(case)
            except AssertionError as error:
                invariant = str(error).split(':', 1)[0]
                reduced = shrink_failure(case, invariant)
                self.fail(f'{error}; seed={seed}; case={index}; shrunk={json.dumps(reduced, ensure_ascii=False, sort_keys=True)}')

    def test_pure_stage_forbids_io_globals_and_printing_even_with_diagnostics(self):
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == 'playwright' or name.startswith('playwright.'):
                raise AssertionError('decision imported Playwright')
            return original_import(name, *args, **kwargs)
        stats = matcher.get_algolia_confirmation_stats()
        with ExitStack() as stack:
            stack.enter_context(patch('builtins.__import__', side_effect=guarded_import))
            stack.enter_context(patch('builtins.print', side_effect=AssertionError('decision printed')))
            for name in ('extract_beer_info', '_record_algolia_confirmation', '_timed_matcher_call',
                         '_brewery_from_algolia_initial_page', '_type_name_from_algolia_initial_page'):
                stack.enter_context(patch.object(matcher, name, side_effect=AssertionError('impure decision dependency: ' + name)))
            for case in characterization.characterization_cases():
                context = dict(case['context'])
                before = copy.deepcopy((case['candidates'], expected_for(case), context))
                decision = matcher.decide_candidates(case['candidates'], expected_for(case), .425, context, collect_diagnostics=True)
                self.assertEqual((case['candidates'], expected_for(case), context), before)
                self.assertIsInstance(decision['diagnostics'], list)
        self.assertEqual(matcher.get_algolia_confirmation_stats(), stats)

    def test_tie_order_remains_v107_input_order_without_a_new_tiebreaker(self):
        expected = dict(beer='Banishing 3', brewery='Third Moon', abv=7., style='IPA')
        rows = [make_candidate('Banishing 3', 'Third Moon', 7., 3, expected),
                make_candidate('Banishing 2', 'Third Moon', 7., 2, expected)]
        # Equalize an observed score tie; this specifically characterizes rule precedence.
        for row in rows:
            row['score'] = 1.
        decisions = [matcher.decide_candidates(order, expected, .425, {}) for order in (rows, rows[::-1])]
        self.assertEqual([d['rule'] for d in decisions], ['exact_numbered', 'unique_exact_identity'])
        self.assertEqual([d['candidate']['url'] for d in decisions], [rows[0]['url']] * 2)

    def test_selected_identity_can_finalize_as_failure_or_rate_limit(self):
        for case in characterization.characterization_cases():
            if not case['name'].startswith('Detail '):
                continue
            decision = matcher.decide_candidates(case['candidates'], expected_for(case), .425, {})
            self.assertEqual(decision['kind'], 'selected')
            expected = {'Detail ok': 'ok', 'Detail failed': 'failed', 'Detail rate_limited': 'rate_limited'}
            self.assertEqual(characterization.observe(case)['result']['status'], expected[case['name']])

    def test_directed_unique_and_production_properties_are_exercised(self):
        expected = dict(beer='Boston Lager', brewery='Samuel Adams', abv=5., style='Lager')
        rows = [make_candidate('Boston Lager', 'Samuel Adams', 5., 1, expected),
                make_candidate('Boston Lager 2025', 'Samuel Adams', 5., 2, expected)]
        case = dict(rows=rows, expected=expected, min_score=.425,
                    discovery=coherent_discovery(rows, expected, {}))
        self.assertEqual(decide(case)['rule'], 'unique_exact_identity')
        check_case(case)  # Includes duplicate and missing-evidence transformations.
        rows[0]['in_production'], rows[1]['in_production'] = False, True
        self.assertEqual(decide(case)['rule'], 'production_conflict')
        check_case(case)
        case['discovery']['fallback_review_required'] = True
        case['discovery']['expansion_diagnostics'] = {'capped': True}
        self.assertEqual(decide(case)['rule'], 'production_conflict')
        check_case(case)

    def test_shrinker_retains_the_failing_invariant_and_input_preconditions(self):
        expected = dict(beer='Boston Lager', brewery='Samuel Adams', abv=5., style='Lager')
        rows = [make_candidate(name, 'Samuel Adams', 5., index, expected)
                for index, name in enumerate(('Distractor', 'Sentinel', 'Another'), 1)]
        for row in rows:
            row['in_production'] = True
        rows.sort(key=lambda row: row['score'], reverse=True)
        case = dict(rows=rows, expected=expected, min_score=.425,
                    discovery=coherent_discovery(rows, expected, {}))
        before = copy.deepcopy(case)
        def fails_on_sentinel(proposal):
            if any(row['name'] == 'Sentinel' for row in proposal['rows']):
                raise AssertionError('I9: controlled shrinking failure')
        with patch(__name__ + '.check_case', side_effect=fails_on_sentinel):
            reduced = shrink_failure(case, 'I9')
        self.assertEqual([row['name'] for row in reduced['rows']], ['Sentinel'])
        self.assertNotIn('in_production', reduced['rows'][0])
        self.assertEqual(reduced['discovery'], coherent_discovery(reduced['rows'], expected, reduced['discovery']))
        self.assertEqual(case, before)

    def test_minimum_score_and_family_properties_are_exercised(self):
        expected = dict(beer='Green Fields', brewery='Badlands', abv=5., style='IPA')
        for names, minimum, rule in ((['Unrelated Nebula'], .75, 'low_confidence'),
                                     (['Green Fields Peach', 'Green Fields Cherry'], .425, 'same_abv_family')):
            rows = [make_candidate(name, 'Badlands', 5., index, expected) for index, name in enumerate(names, 1)]
            rows.sort(key=lambda row: row['score'], reverse=True)
            case = dict(rows=rows, expected=expected, min_score=minimum,
                        discovery=coherent_discovery(rows, expected, {}))
            self.assertEqual(decide(case)['rule'], rule)
            check_case(case)

    def test_decision_type_is_internal_and_checked(self):
        self.assertIs(get_type_hints(matcher.decide_candidates)['return'], Decision)
        self.assertNotIn('rule', matcher.MatchResult.__annotations__)
