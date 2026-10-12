"""Frozen v107 decision, debug, persistence and rendering contracts."""
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import untap_matcher as matcher
from untap_batch import save_csv
from untap_report import render_html_report
from untap_snapshot import build_snapshot
from tests.test_untap_v86 import candidate
from tests import test_untap_v100
from tests import test_untap_v101

FIXTURE = Path(__file__).with_name('testdata') / 'decision_v107.json'


def characterization_cases():
    cases = []
    def add(name, rows, beer, brewery, abv, **context):
        cases.append(dict(name=name, candidates=rows, beer=beer, brewery=brewery,
                          abv=abv, style='IPA', context=context))
    add('Banishing 3', test_untap_v100.NumberedNameTests().rows(), 'Banishing 3', 'Third Moon', 7.)
    add('Tripla Broccoli World', test_untap_v101.ExactIdentityTests().broccoli(), 'Broccoli World', 'Other Half Brewing Co.', 8.2)
    add('Tripla Ghost', test_untap_v101.ExactIdentityTests().ghost(), 'Ghost In The Machine', 'Parish Brewing Co.', 8.)
    for beer, brewery, abv, other in [('Boston Lager', 'Samuel Adams', 5., 'Boston Lager (1985–2022)'),
            ('Schmoojee Peach Pear Dragonfruit', 'Imprint Beer Co.', 6.5, 'Schmoojee Peach Pear Apricot Dragonfruit')]:
        add(beer, [candidate(beer, brewery, abv, 1., 1), candidate(other, brewery, abv, .965, 2)], beer, brewery, abv)
    add('Humble Sea ABV conflict', [candidate('A7Y7 X Humble Sea', 'Messorem', 7.5)], 'A7Y7 X Humble Sea', 'Messorem', 6.5)
    retired = candidate('Boston Lager', 'Samuel Adams', 5., 1., 1)
    retired['in_production'] = False
    vintage = candidate('Boston Lager (2025)', 'Samuel Adams', 5., .9, 2)
    vintage['in_production'] = True
    for incomplete in (False, True):
        add('Production conflict ' + str(incomplete), [retired, vintage], 'Boston Lager', 'Samuel Adams', 5.,
            expansion_diagnostics={'errors': ['offline']} if incomplete else None)
    add('Exact base', [candidate('PB&J Mixtape', 'Xül', 6.5), candidate('PB&J Mixtape Peach', 'Xül', 6.5, .9, 2)], 'PB&J Mixtape', 'Xül', 6.5)
    add('DDH', [candidate('Double Dry Hopped Fort Point', 'Trillium', 6.6), candidate('Mosaic Dry Hopped Fort Point', 'Trillium', 6.6, .8, 2)], 'DDH Fort Point', 'Trillium', 6.6)
    for flag in ('capped', 'errors', 'ambiguity_early_stopped', 'ambiguity_established'):
        add('Incomplete ' + flag, [candidate('Green Fields 2025', 'Badlands', 5.)], 'Green Fields', 'Badlands', 5.,
            expansion_diagnostics={flag: ['offline'] if flag == 'errors' else True}, expanded=True)
    add('Review-only fallback', [candidate('A7Y7 X Fidens X Freestyle Hops', 'Messorem', 7.5)],
        'A7Y7 X Fidens - XTRM Turbo', 'Messorem', 7.5, fallback_review_required=True, fallback_query_used='Messorem A7Y7 X Fidens')
    add('No candidates', [], 'Beer', 'Brewery', 5.)
    add('Brewery conflict', [candidate('Beer', 'Unrelated', 5.)], 'Beer', 'Badlands', 5.)
    add('Low confidence', [candidate('Weak Beer', 'Badlands', None, .1)], 'Beer', 'Badlands', 5.)
    add('Same ABV family', [candidate('Daily Serving Peach', 'Trillium', 5.), candidate('Daily Serving Cherry', 'Trillium', 5., .9, 2)], 'Daily Serving', 'Trillium', 5.)
    add('Near tie', [candidate('Beer Alpha', 'Badlands', 5.), candidate('Beer Beta', 'Badlands', 5., .99, 2)], 'Beer', 'Badlands', 5., ambiguity_reason='Top candidates are too close')
    missing = candidate('Beer', 'Badlands', 5.)
    missing['rating_score'] = None
    for mode in ('ok', 'failed', 'rate_limited'):
        add('Detail ' + mode, [missing], 'Beer', 'Badlands', 5., detail_mode=mode)
    recovered = candidate('Beer', 'Unknown', 5.)
    recovered['type_name'] = None
    add('Captured metadata recovery', [recovered], 'Beer', None, 5., primary_algolia_page={
        'hits': [{'bid': 1, 'beer_name': 'Beer', 'brewery_name': 'Badlands', 'type_name': 'IPA'}]})
    return cases


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 11, 12, tzinfo=timezone.utc)
        return value if tz is None else value.astimezone(tz)


def observe(case):
    rows = copy.deepcopy(case['candidates'])
    before = copy.deepcopy(rows)
    context = case['context']
    detail = dict(beer=case['beer'], brewery=case['brewery'], abv='5%', ibu=None,
                  rating=None, ratings=None, url=rows[0]['url'] if rows else None)
    mode = context.get('detail_mode', 'ok')
    error = matcher.BeerDetailError('Controlled detail failure', 429 if mode == 'rate_limited' else 403)
    stats_before = matcher.get_algolia_confirmation_stats()
    with patch.object(matcher, 'extract_beer_info', return_value=detail, side_effect=None if mode == 'ok' else error), \
         contextlib.redirect_stdout(io.StringIO()) as debug:
        result = matcher._resolve_discovered_candidates(
            object(), ' '.join(x for x in (case['brewery'], case['beer']) if x), .425, True,
            case['beer'], case['brewery'], case['abv'], case['style'], rows,
            context.get('ambiguity_reason'), rows if context.get('expanded') else [],
            context.get('expansion_diagnostics'), context.get('abv_sorted_diagnostics'),
            context.get('fallback_query_used'), context.get('fallback_review_required', False),
            context.get('primary_algolia_page'))
    assert rows == before, case['name']
    stats = matcher.get_algolia_confirmation_stats()
    delta = {key: stats[key] - stats_before[key] for key in stats}
    with patch('untap_snapshot.datetime', FixedDatetime):
        snapshot = build_snapshot([result], 'Decision characterization')
    html = render_html_report([result], 'Decision characterization', report_date='2026-10-11')
    snapshot_bytes = (json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        path = Path(tmp) / 'results.csv'
        save_csv([result], str(path))
        csv_bytes = path.read_bytes()
    digest = lambda value: hashlib.sha256(value).hexdigest()
    return dict(result=result, debug=debug.getvalue(), counters=delta,
                html_sha256=digest(html.encode()), csv_sha256=digest(csv_bytes), json_sha256=digest(snapshot_bytes))


class DecisionCharacterizationTests(unittest.TestCase):
    def test_v107_results_debug_counters_and_output_bytes(self):
        expected = json.loads(FIXTURE.read_text())
        # Explicit output changes: conflict inspection links and continuation guidance.
        overlay = json.loads(FIXTURE.with_name('decision_review_links.json').read_text())
        self.assertEqual(set(overlay), {'Humble Sea ABV conflict', 'Brewery conflict', 'Detail rate_limited'})
        expected.update(overlay)
        for case in characterization_cases():
            with self.subTest(case=case['name']):
                self.assertEqual(observe(case), expected[case['name']])
