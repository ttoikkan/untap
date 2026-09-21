import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from untap_local_review import ReviewSession
from untap_snapshot import build_snapshot, save_snapshot, load_snapshot
from untap_report import selection_report_id


URL = "https://untappd.com/b/example-beer/1234"


class LocalReviewTests(unittest.TestCase):
    def session(self, root):
        source = root / "source"
        source.mkdir()
        snapshot = build_snapshot([{"query": "Example", "status": "failed",
                                   "reason": "No match"}], "Menu")
        save_snapshot(snapshot, source / "results.json")
        return ReviewSession(source)

    def payload(self, session):
        snapshot = session.snapshot
        return {"format": "untap-manual-review-trial-v1",
                "report_id": selection_report_id([i["result"] for i in snapshot["items"]],
                    snapshot["report"]["title"], snapshot["report"]["date"]),
                "selections": [], "pending_candidates": []}

    def add(self, session):
        payload = self.payload(session)
        payload["pending_candidates"] = [{"item_id": session.snapshot["items"][0]["id"], "url": URL}]
        with patch("untap_refresh.fetch_candidates", return_value={"1234": {
                "name": "Example Beer", "brewery": "Example", "abv": 5.0,
                "rating": 4.0, "url": URL, "user_added": True}}):
            session.action({"action": "fetch", "payload": payload})

    def test_fetch_and_save_preserve_source(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            session = self.session(Path(tmp))
            before = session.source.read_bytes()
            self.add(session)
            self.assertTrue(session.has_unsaved_candidates)
            self.assertEqual(session.snapshot["items"][0]["result"]["status"], "ambiguous")
            payload = self.payload(session)
            payload["selections"] = [{"row": 0, "url": URL}]
            response = session.action({"action": "save", "payload": payload})
            saved = Path(response["saved"])
            result = load_snapshot(saved / "results.json")["items"][0]["result"]
            self.assertTrue(result["manually_confirmed"])
            self.assertEqual(session.source.read_bytes(), before)
            self.assertNotIn("window.untapLocalReview =", (saved / "results.html").read_text())
            self.assertNotIn(session.token, (saved / "results.html").read_text())

    def test_reopen_saved_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            session = self.session(Path(tmp))
            self.add(session)
            payload = self.payload(session)
            payload["selections"] = [{"row": 0, "url": URL}]
            saved = session.action({"action": "save", "payload": payload})["saved"]
            reviewed = ReviewSession(saved)
            output = reviewed.action({"action": "save", "payload": self.payload(reviewed)})["saved"]
            result = load_snapshot(Path(output) / "results.json")["items"][0]["result"]
            self.assertEqual(result["status"], "ambiguous")
            self.assertFalse(result.get("manually_confirmed"))
            self.assertEqual(result["alternatives"][0]["url"], URL)

    def test_failed_fetch_and_stale_payload_are_non_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.session(Path(tmp))
            before = session.html()
            payload = self.payload(session)
            payload["pending_candidates"] = [{"item_id": session.snapshot["items"][0]["id"], "url": URL}]
            with patch("untap_refresh.fetch_candidates", side_effect=ValueError("offline")):
                with self.assertRaises(ValueError):
                    session.action({"action": "fetch", "payload": payload})
            self.assertEqual(session.html(), before)
            payload["report_id"] = "wrong"
            with patch("untap_refresh.fetch_candidates") as fetch:
                with self.assertRaises(ValueError):
                    session.action({"action": "fetch", "payload": payload})
                fetch.assert_not_called()
            self.assertEqual([path.resolve() for path in Path(tmp).iterdir()], [session.source.parent])

    def test_save_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.session(Path(tmp))
            payload = self.payload(session)
            payload["pending_candidates"] = [{"item_id": session.snapshot["items"][0]["id"], "url": URL}]
            with patch("untap_refresh.fetch_candidates") as fetch:
                with self.assertRaises(ValueError):
                    session.action({"action": "save", "payload": payload})
                fetch.assert_not_called()
