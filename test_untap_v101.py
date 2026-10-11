"""Exact name + brewery + ABV regressions from Tripla's October cans."""
import copy
import unittest

import untap_matcher as matcher
import test_untap_v86 as fixtures


class ExactIdentityTests(unittest.TestCase):
    def broccoli(self):
        return [fixtures.candidate("Broccoli World", "Other Half Brewing Co.", 8.2, 1., 3908668),
                fixtures.candidate("Broccoli World: NYC Rampage", "Other Half Brewing Co.", 9., .750, 3919882),
                fixtures.candidate("Broccoli World Special Reserve (8th Anniversary Edition)",
                                   "Other Half Brewing Co.", 8.6, .722, 4685166)]

    def ghost(self):
        return [fixtures.candidate("Ghost In The Machine", "Parish Brewing Co.", 8., 1., 593083),
                fixtures.candidate("DDH Ghost In the Machine", "Parish Brewing Co.", 8., .903, 2422658),
                fixtures.candidate("DDH Ghost In the Machine(Beijing Limited Edition)",
                                   "Parish Brewing Co.", 8.5, .746, 4),
                fixtures.candidate("Ghost In the Machine (Freaky Friday)", "Omnipollo", 8., .450, 6437661)]

    def test_confirm_both_exact_identities_without_mutating_candidates(self):
        for rows in [self.broccoli(), self.ghost()]:
            before = copy.deepcopy(rows)
            best = rows[0]
            result, _ = fixtures.MatcherV86Tests().run_search(rows, best['name'], best['brewery'], best['abv'])
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['url'], best['url'])
            self.assertEqual(result['score'], best['score'])
            self.assertEqual([c['url'] for c in result['alternatives']], [c['url'] for c in rows])
            self.assertEqual(rows, before)

    def test_incomplete_discovery_cannot_be_overridden(self):
        for diagnostics in [{'capped': True}, {'errors': ['offline']},
                            {'ambiguity_early_stopped': True}, {'ambiguity_established': True}]:
            rows = self.broccoli()
            result, _ = fixtures.MatcherV86Tests().run_search(rows, 'Broccoli World',
                'Other Half Brewing Co.', 8.2, diagnostics=diagnostics)
            self.assertEqual(result['status'], 'ambiguous')

    def test_only_duplicate_all_three_identifiers_stays_ambiguous(self):
        for name, abv in [('Broccoli World', 8.2), ('Broccoli World', 8.6),
                          ('Broccoli World (2022)', 8.2), ('Broccoli World (2022)', 8.6),
                          ('Broccoli World Batch 2', 8.6)]:
            rows = self.broccoli()[:1] + [fixtures.candidate(name, 'Other Half Brewing Co.', abv, .95, 2)]
            result, _ = fixtures.MatcherV86Tests().run_search(rows, 'Broccoli World', 'Other Half Brewing Co.', 8.2)
            self.assertEqual(result['status'], 'ambiguous' if name == 'Broccoli World' and abv == 8.2 else 'ok')

    def test_missing_or_conflicting_evidence_fails_closed(self):
        for fields in [{'brewery': None}, {'brewery': 'Unknown'}, {'name': None},
                       {'abv': None}, {'abv': float('nan')}]:
            rows = self.broccoli()
            rows[1].update(name='Broccoli World', abv=8.2)
            rows[1].update(fields)
            self.assertIsNone(matcher.unique_exact_identity_candidate(rows, 'Broccoli World', 'Other Half', 8.2))
        for beer, brewery, abv in [(None, 'Other Half', 8.2), ('Broccoli World', None, 8.2),
                                  ('Broccoli World', 'Other Half', None), ('Broccoli World', 'Other Half', 8.6),
                                  ('Broccoli World', 'Other Half', float('nan'))]:
            self.assertIsNone(matcher.unique_exact_identity_candidate(self.broccoli(), beer, brewery, abv))

    def test_other_brewery_does_not_create_identity_tie(self):
        rows = self.ghost()
        rows[-1]['name'] = rows[0]['name']
        self.assertIs(matcher.unique_exact_identity_candidate(rows, 'Ghost In The Machine', 'Parish', 8.), rows[0])

    def test_different_qualifiers_do_not_block_and_candidate_need_not_rank_first(self):
        rows = self.broccoli()
        rows[1]['abv'] = 8.2
        self.assertIs(matcher.unique_exact_identity_candidate(rows, 'Broccoli World', 'Other Half', 8.2), rows[0])
        rows = self.broccoli()[::-1]
        rows[-1]['score'] = .3
        self.assertIs(matcher.unique_exact_identity_candidate(rows, 'Broccoli World', 'Other Half', 8.2), rows[-1])
        result, _ = fixtures.MatcherV86Tests().run_search(rows, 'Broccoli World', 'Other Half', 8.2)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['url'], rows[-1]['url'])
        self.assertEqual(result['score'], .3)

    def test_missing_metadata_on_differently_named_candidate_does_not_block(self):
        rows = self.broccoli()
        rows[1].update(brewery=None, abv=None)
        self.assertIs(matcher.unique_exact_identity_candidate(rows, 'Broccoli World', 'Other Half', 8.2), rows[0])


class AutomaticSelectionReviewTests(unittest.TestCase):
    def test_manual_override_and_reopen_restore_automatic_selection(self):
        import tempfile
        from pathlib import Path
        from untap_snapshot import build_snapshot, save_snapshot, load_snapshot
        from untap_local_review import ReviewSession
        from untap_report import selection_report_id
        rows = ExactIdentityTests().broccoli()
        result, _ = fixtures.MatcherV86Tests().run_search(rows, rows[0]['name'], rows[0]['brewery'], rows[0]['abv'])
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()
            save_snapshot(build_snapshot([result], 'Menu'), source / 'results.json')
            original_bytes = (source / 'results.json').read_bytes()
            def payload(session, selections):
                snap = session.snapshot
                return {'format': 'untap-manual-review-trial-v1',
                        'report_id': selection_report_id([i['result'] for i in snap['items']], snap['report']['title'], snap['report']['date']),
                        'selections': selections, 'pending_candidates': []}
            session = ReviewSession(source)
            saved = session.action({'action': 'save', 'payload': payload(session, [{'row': 0, 'url': rows[1]['url']}])})['saved']
            changed = load_snapshot(Path(saved) / 'results.json')['items'][0]['result']
            self.assertTrue(changed['manually_confirmed'])
            self.assertEqual(changed['url'], rows[1]['url'])
            reopened = ReviewSession(saved)
            restored_path = reopened.action({'action': 'save', 'payload': payload(reopened, [])})['saved']
            restored = load_snapshot(Path(restored_path) / 'results.json')['items'][0]['result']
            self.assertEqual(restored['status'], 'ok')
            self.assertEqual(restored['url'], rows[0]['url'])
            self.assertFalse(restored.get('manually_confirmed'))
            self.assertEqual(restored['alternatives'], result['alternatives'])
            self.assertEqual((source / 'results.json').read_bytes(), original_bytes)
