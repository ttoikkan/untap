"""Frozen request order and outcomes around search recovery orchestration."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import untap.matcher as matcher
from tests.test_untap_v86 import candidate

CASES = ('strong_primary', 'zero_hit_recovery', 'nonzero_weak_recovery',
         'strongest_weak', 'ambiguous_recovery', 'primary_429', 'transport_error',
         'expansion_429', 'fallback_429')


def observe_flow(mode):
    trace = []
    selected_fallback = None
    strong = mode == 'strong_primary'
    rows = [candidate('Different', 'Brewery', 5., .9 if strong else .1)]
    if mode == 'zero_hit_recovery':
        rows = []
    def transport(*args, **kwargs):
        trace.append('primary')
        return dict(request_event=None, events=[], error='broken' if mode == 'transport_error' else None)
    def evaluate(*args, **kwargs):
        trace.append('expansion')
        return dict(candidates=rows, ambiguity_reason=None, release_qualifier_trigger=False,
                    needs_expansion=False, expanded_candidates=[], expansion_diagnostics=None,
                    rate_limited=mode == 'expansion_429')
    def queries(*args, **kwargs):
        trace.append('fallback plan: trailing=' + str(kwargs['enable_trailing_relaxation']))
        return ['Recovery One', 'Recovery Two', 'Recovery Three']
    def fallback(page, query, **kwargs):
        trace.append('fallback: ' + query)
        if mode == 'fallback_429':
            return dict(rate_limited=True)
        index = ['Recovery One', 'Recovery Two', 'Recovery Three'].index(query)
        scores = [.2, .8, .9] if mode != 'strongest_weak' else [.2, .3, .25]
        return dict(candidates=[candidate('Different', 'Brewery', 5., scores[index], index + 2)],
                    weak_match=scores[index] < .425,
                    ambiguity_reason='Multiple candidates' if mode == 'ambiguous_recovery' else None,
                    initial_algolia_page={'source': query}, expanded_candidates=[])
    original_resolve = matcher._resolve_discovered_candidates
    def resolve(*args, **kwargs):
        nonlocal selected_fallback
        selected_fallback = args[13]
        trace.append('finalization')
        return original_resolve(*args, **kwargs)
    with ExitStack() as stack, redirect_stdout(io.StringIO()) as debug:
        values = {'_run_page0_search_transport': transport,
                  'evaluate_and_expand_candidates': evaluate,
                  'build_search_fallback_queries': queries,
                  'run_search_fallback_attempt': fallback,
                  '_resolve_discovered_candidates': resolve}
        for name, callback in values.items():
            stack.enter_context(patch.object(matcher, name, side_effect=callback))
        for name, value in {'_matching_algolia_response_status': 429 if mode == 'primary_429' else 200,
                            '_matching_algolia_nb_hits': 0 if mode == 'zero_hit_recovery' else 2,
                            '_matching_algolia_initial_page': None,
                            '_algolia_page0_candidates': rows}.items():
            stack.enter_context(patch.object(matcher, name, return_value=value))
        result = matcher._search_one_impl(object(), 'Brewery Beer', expected_beer='Beer',
                                          expected_brewery='Brewery', expected_abv=5.)
    return dict(trace=trace, result=result, debug=debug.getvalue(), selected_fallback=selected_fallback)


class SearchPhaseTests(unittest.TestCase):
    def test_request_sequences_and_results_match_pre_extraction_baseline(self):
        fixture = Path(__file__).with_name('testdata') / 'search_recovery_v109.json'
        expected = json.loads(fixture.read_text())
        self.assertEqual(set(expected), set(CASES))
        for mode in CASES:
            with self.subTest(mode=mode):
                self.assertEqual(observe_flow(mode), expected[mode])

    def test_429_stops_at_each_phase_without_finalization_or_later_requests(self):
        for mode, trace in (('primary_429', ['primary']),
                            ('expansion_429', ['primary', 'expansion']),
                            ('fallback_429', ['primary', 'expansion', 'fallback plan: trailing=False', 'fallback: Recovery One'])):
            with self.subTest(mode=mode):
                observed = observe_flow(mode)
                self.assertEqual(observed['trace'], trace)
                self.assertEqual(observed['result']['status'], 'rate_limited')
                self.assertEqual(observed['result']['http_status'], 429)

    def test_strong_primary_skips_fallback_and_only_zero_hits_enable_trailing(self):
        self.assertEqual(observe_flow('strong_primary')['trace'], ['primary', 'expansion', 'finalization'])
        self.assertIn('fallback plan: trailing=True', observe_flow('zero_hit_recovery')['trace'])
        self.assertIn('fallback plan: trailing=False', observe_flow('nonzero_weak_recovery')['trace'])

    def test_ambiguity_stops_immediately_and_weak_attempts_continue_in_order(self):
        self.assertEqual(observe_flow('ambiguous_recovery')['trace'][-2:], ['fallback: Recovery One', 'finalization'])
        weak = observe_flow('strongest_weak')
        self.assertEqual(weak['trace'][-4:], ['fallback: Recovery One', 'fallback: Recovery Two', 'fallback: Recovery Three', 'finalization'])
        self.assertEqual(weak['selected_fallback'], 'Recovery Two')

    def test_primary_phase_preserves_matched_request_page_and_candidate_order(self):
        request = {'kind': 'request', 'url': 'captured'}
        events = [{'kind': 'response', 'status': 200}]
        page0 = {'hits': [], 'nbHits': 2}
        rows = [candidate('Beer A', 'Brewery', 5., .9, 1), candidate('Beer B', 'Brewery', 5., .8, 2)]
        with patch.object(matcher, '_run_page0_search_transport', return_value={'request_event': request, 'events': events}) as transport,\
             patch.object(matcher, '_matching_algolia_response_status', return_value=200),\
             patch.object(matcher, '_matching_algolia_nb_hits', return_value=2),\
             patch.object(matcher, '_matching_algolia_initial_page', return_value=page0),\
             patch.object(matcher, '_algolia_page0_candidates', return_value=rows) as construct:
            primary, terminal = matcher._retrieve_primary_discovery(object(), 'Brewery Beer', False, 'Beer', 'Brewery', 5.)
        self.assertIsNone(terminal)
        self.assertIs(primary.candidates, rows)
        self.assertIs(primary.algolia_request, request)
        self.assertIs(primary.primary_algolia_page, page0)
        self.assertEqual(primary.primary_nb_hits, 2)
        self.assertTrue(transport.call_args.kwargs['include_search_urls'])
        construct.assert_called_once_with(page0, 'Brewery Beer', expected_beer='Beer', expected_brewery='Brewery', expected_abv=5.)

    def test_expansion_phase_passes_original_metadata_and_retains_both_diagnostics(self):
        page0 = {'hits': [], 'nbHits': 2}
        request = {'kind': 'request'}
        primary = matcher._PrimaryDiscovery([], request, 2, page0)
        rows = [candidate('Beer', 'Brewery', 5.)]
        ordinary = {'errors': ['offline']}
        sorted_scan = {'capped': True}
        evaluation = dict(candidates=rows, ambiguity_reason='Incomplete', release_qualifier_trigger=False,
                          needs_expansion=True, expanded_candidates=rows,
                          expansion_diagnostics=ordinary, abv_sorted_diagnostics=sorted_scan)
        with patch.object(matcher, 'evaluate_and_expand_candidates', return_value=evaluation) as expand:
            discovery, terminal = matcher._expand_primary_discovery(object(), 'Brewery Beer', primary, .425, False, 'Beer', 'Brewery', 5.)
        self.assertIsNone(terminal)
        self.assertIs(discovery.candidates, rows)
        self.assertIs(discovery.primary_algolia_page, page0)
        self.assertIs(discovery.expansion_diagnostics, ordinary)
        self.assertIs(discovery.abv_sorted_diagnostics, sorted_scan)
        self.assertEqual(discovery.ambiguity_reason, 'Incomplete')
        self.assertIs(expand.call_args.args[3], request)
        self.assertIs(expand.call_args.kwargs['initial_algolia_page'], page0)
        self.assertEqual(expand.call_args.kwargs['initial_nb_hits'], 2)
