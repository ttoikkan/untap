import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from untap_manual_candidates import parse_beer_url, candidate_from_hit, fetch_candidates
from untap_snapshot import build_snapshot, save_snapshot, load_snapshot
from untap_report import selection_report_id, render_html_report
from untap_refresh import apply_selections, refresh


URL = "https://untappd.com/b/emporium-microbrasserie-lager-de-riz/6684380"


class ManualCandidateTests(unittest.TestCase):
    def fixture(self):
        snapshot = build_snapshot([{"query": "EMPORIUM RICE LAGER", "status": "failed",
            "input_brewery": "EMPORIUM X LA FOSSE X JACKALHOP", "input_beer": "RICE LAGER",
            "input_abv": "4.5", "reason": "No matching beer found"}], "Menu")
        result = snapshot["items"][0]["result"]
        payload = {"format": "untap-manual-review-trial-v1",
            "report_id": selection_report_id([result], "Menu", snapshot["report"]["date"]),
            "selections": [], "pending_candidates": [{"item_id": snapshot["items"][0]["id"], "url": URL}]}
        candidate = candidate_from_hit({"bid": 6684380, "beer_name": "LAGER DE RIZ",
            "brewery_name": "Emporium Microbrasserie", "beer_abv": 4.5,
            "rating_score": 3.98, "rating_count": 39, "type_name": "Lager - Japanese Rice"}, URL)
        return snapshot, payload, candidate

    def test_strict_urls_and_id_validation(self):
        self.assertEqual(parse_beer_url(URL)[0], "6684380")
        for url in ("http://untappd.com/b/beer/1", "https://untappd.com.evil/b/beer/1",
                    "https://user@untappd.com/b/beer/1", URL + "?foo=1", "file:///tmp/x"):
            with self.assertRaises(ValueError):
                parse_beer_url(url)
        with self.assertRaises(ValueError):
            candidate_from_hit({"bid": 1}, URL)

    def test_requires_permission_and_validates_before_network(self):
        snapshot, payload, _ = self.fixture()
        before = json.dumps(snapshot)
        with tempfile.TemporaryDirectory() as tmp, patch("untap_refresh.fetch_candidates") as fetch:
            path = Path(tmp) / "export.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "--fetch-candidates"):
                apply_selections(snapshot, path)
            payload["pending_candidates"].append({"item_id": "wrong", "url": URL})
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                apply_selections(snapshot, path, True)
            fetch.assert_not_called()
            self.assertEqual(json.dumps(snapshot), before)

    def test_add_then_confirm_in_separate_export(self):
        snapshot, payload, candidate = self.fixture()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            save_snapshot(snapshot, source / "results.json")
            path = root / "export.json"
            path.write_text(json.dumps(payload))
            with patch("untap_refresh.fetch_candidates", return_value={"6684380": candidate}):
                output = refresh(source, root / "output", path, True)
            updated = load_snapshot(output / "results.json")
            result = updated["items"][0]["result"]
            self.assertEqual(result["status"], "ambiguous")
            self.assertNotIn("score", result["alternatives"][0])
            self.assertEqual(updated["candidate_additions"][0]["original_result"]["status"], "failed")
            html = (output / "results.html").read_text()
            self.assertIn("User-added", html)
            self.assertIn("EMPORIUM X LA FOSSE X JACKALHOP", html)
            self.assertEqual(load_snapshot(source / "results.json"), snapshot)
            payload.update(report_id=selection_report_id([result], "Menu", updated["report"]["date"]),
                           pending_candidates=[], selections=[{"row": 0, "url": URL}])
            path.write_text(json.dumps(payload))
            apply_selections(updated, path)
            self.assertTrue(result["manually_confirmed"])
            self.assertEqual(result["beer"], "LAGER DE RIZ")

    def test_failed_retrieval_leaves_no_output(self):
        snapshot, payload, _ = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_snapshot(snapshot, root / "results.json")
            path = root / "export.json"
            path.write_text(json.dumps(payload))
            with patch("untap_refresh.fetch_candidates", side_effect=ValueError("Not found")):
                with self.assertRaises(ValueError):
                    refresh(root / "results.json", root / "output", path, True)
            self.assertFalse((root / "output").exists())

    def test_fetch_uses_exact_id_not_first_hit(self):
        with patch("untap_untappd.untappd_browser_page") as browser, patch("untap_inspect.inspect_query") as inspect:
            inspect.return_value = {"hits": [{"bid": 1, "beer_name": "Wrong"},
                {"bid": 6684380, "beer_name": "LAGER DE RIZ", "brewery_name": "Emporium"}]}
            result = fetch_candidates([URL, URL])
            self.assertEqual(result["6684380"]["name"], "LAGER DE RIZ")
            self.assertEqual(inspect.call_count, 1)
