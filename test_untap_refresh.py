import contextlib
import json
import io
import tempfile
import unittest
from pathlib import Path

from untap_refresh import refresh, main, apply_selections
from untap_report import selection_report_id
from untap_snapshot import build_snapshot, save_snapshot, load_snapshot
from untap_publish import publish_report


class RefreshTests(unittest.TestCase):
    def test_batch_continues_after_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as log, contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp)
            self.source(root)
            config = root / "batch.json"
            config.write_text(json.dumps({"reports": [{"source": "missing"}, {"source": "run"}]}))
            self.assertEqual(main(["--batch", str(config)]), 2)
            self.assertIn("1 succeeded, 1 failed", log.getvalue())
            self.assertEqual(len(list(root.glob("run_refresh_*"))), 1)

    def test_invalid_batch_is_rejected_before_any_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp)
            self.source(root)
            config = root / "batch.json"
            config.write_text(json.dumps({"reports": [{"source": "run"}, {"source": "run", "replace": "yes"}]}))
            self.assertEqual(main(["--batch", str(config)]), 2)
            self.assertEqual(list(root.glob("run_refresh_*")), [])

    def test_selections_validate_all_rows_then_apply(self):
        snapshot = build_snapshot([{"query": "Beer", "status": "ambiguous",
            "alternatives": [{"name": "Chosen", "url": "https://untappd.com/b/chosen/1", "rating": 4.2}]}], "Menu")
        result = snapshot["items"][0]["result"]
        payload = {"format": "untap-manual-review-trial-v1",
            "report_id": selection_report_id([result], snapshot["report"]["title"], snapshot["report"]["date"]),
            "selections": [{"row": 0, "url": "https://untappd.com/b/chosen/1"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "choices.json"
            bad = dict(payload, selections=payload["selections"] + [{"row": 999, "url": "bad"}])
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                apply_selections(snapshot, path)
            self.assertEqual(result["status"], "ambiguous")
            path.write_text(json.dumps(payload))
            apply_selections(snapshot, path)
            self.assertEqual(result["beer"], "Chosen")
            self.assertTrue(result["manually_confirmed"])
            self.assertEqual(snapshot["manual_decisions"][0]["original_result"]["status"], "ambiguous")

    def source(self, root):
        source = root / "run"
        source.mkdir()
        save_snapshot(build_snapshot([{"query": "Beer", "status": "failed"}], "Test menu"), source / "results.json")
        return source

    def test_refresh_preserves_snapshot_and_source(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            source = self.source(Path(tmp))
            before = (source / "results.json").read_bytes()
            output = refresh(source)
            self.assertNotEqual(output, source)
            self.assertEqual((source / "results.json").read_bytes(), before)
            self.assertEqual(load_snapshot(output / "results.json"), load_snapshot(source / "results.json"))
            self.assertTrue((output / "results.csv").is_file())
            self.assertIn("manual-review-script", (output / "results.html").read_text())
            with self.assertRaises(FileExistsError):
                refresh(source, output)

    def test_publish_replace_preserves_url(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source = self.source(root)
            output = refresh(source)
            archive = root / "archive"
            (archive / "reports").mkdir(parents=True)
            original = publish_report(output / "results.html", archive)
            self.assertEqual(main([str(source), "--archive", str(archive), "--replace"]), 0)
            self.assertEqual([p.name for p in (archive / "reports").glob("*.html")], [original.filename])

    def test_invalid_snapshot_creates_no_output(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp)
            source = root / "bad.json"
            source.write_text("{}")
            output = root / "output"
            self.assertEqual(main([str(source), "--output", str(output)]), 2)
            self.assertFalse(output.exists())
