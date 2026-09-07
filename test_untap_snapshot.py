import json
import tempfile
import unittest
from pathlib import Path

import test_untap_report
from untap_report import render_html_report
from untap_snapshot import build_snapshot, load_snapshot, save_snapshot


class SnapshotTests(unittest.TestCase):
    def test_full_round_trip_and_identical_report(self):
        results = test_untap_report.HtmlReportTests()._results()
        results[2]["search_warning"] = "Search incomplete"
        candidate = results[2]["alternatives"][0]
        candidate.update(image_url="https://assets.untappd.com/a.png",
                         image_hd_url="https://assets.untappd.com/hd.png",
                         in_production=False)
        snapshot = build_snapshot(results, "Test menu")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            save_snapshot(snapshot, path)
            restored = load_snapshot(path)
            recovered = [item["result"] for item in restored["items"]]
            self.assertEqual(recovered, results)
            self.assertEqual(
                render_html_report(results, "Test menu", restored["report"]["date"]),
                render_html_report(recovered, "Test menu", restored["report"]["date"]),
            )
            with self.assertRaises(FileExistsError):
                save_snapshot(snapshot, path)
            self.assertEqual(load_snapshot(path), restored)

    def test_ids_survive_reordering_and_score_changes(self):
        a = {"query": "One", "status": "ok", "rating": 4.0}
        b = {"query": "Two", "status": "failed"}
        first = build_snapshot([a, b, a], "Title")
        second = build_snapshot([b, dict(a, rating=3.0), a], "New title")
        self.assertEqual(first["items"][0]["id"], second["items"][1]["id"])
        self.assertEqual(first["items"][1]["id"], second["items"][0]["id"])
        self.assertNotEqual(first["items"][0]["id"], first["items"][2]["id"])

    def test_rejects_future_schema_and_duplicate_ids(self):
        snapshot = build_snapshot([{"query": "One"}], "Title")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            snapshot["version"] = 99
            path.write_text(json.dumps(snapshot))
            with self.assertRaises(ValueError):
                load_snapshot(path)
            snapshot["version"] = 1
            snapshot["items"] *= 2
            path.write_text(json.dumps(snapshot))
            with self.assertRaises(ValueError):
                load_snapshot(path)

    def test_snapshot_is_independent_of_input(self):
        result = {"query": "One", "alternatives": [{"name": "Original"}]}
        snapshot = build_snapshot([result], "Title")
        result["alternatives"][0]["name"] = "Changed"
        self.assertEqual(snapshot["items"][0]["result"]["alternatives"][0]["name"], "Original")
