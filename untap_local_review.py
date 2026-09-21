"""Open one saved run for local review; save new runs without export/import."""
import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sys
import webbrowser

from untap_refresh import apply_selection_payload, write_reviewed_run
from untap_report import render_html_report, _sorted_report_results
from untap_snapshot import load_snapshot


class ReviewSession:
    def __init__(self, source):
        source = Path(source).resolve()
        self.source = source / "results.json" if source.is_dir() else source
        self.snapshot = load_snapshot(self.source)
        self.token = secrets.token_urlsafe(32)
        self.last_saved = None
        self.has_unsaved_candidates = False

    def html(self):
        snapshot = self.snapshot
        html = render_html_report([i["result"] for i in snapshot["items"]],
                                  snapshot["report"]["title"], snapshot["report"]["date"])
        config = json.dumps({"endpoint": f"/{self.token}/action", "token": self.token,
                             "unsavedCandidates": self.has_unsaved_candidates})
        return html.replace('<script id="manual-review-script">',
            '<script>window.untapLocalReview = ' + config + ';</script>\n<script id="manual-review-script">')

    def action(self, request):
        if not isinstance(request, dict) or request.get("action") not in ("fetch", "save"):
            raise ValueError("Unknown local review action")
        payload = request.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Invalid review payload")
        if request["action"] == "save" and payload.get("pending_candidates"):
            raise ValueError("Fetch or remove pending URLs before saving")
        if request["action"] == "fetch" and not payload.get("pending_candidates"):
            raise ValueError("No candidate URL supplied")
        updated = deepcopy(self.snapshot)
        ordered = _sorted_report_results([i["result"] for i in updated["items"]])
        # The shared validator runs before any network or filesystem mutation.
        apply_selection_payload(updated, payload, fetch_pending=request["action"] == "fetch")
        chosen_rows = {entry["row"] for entry in payload["selections"]}
        for row, result in enumerate(ordered):
            if row in chosen_rows or not result.get("manually_confirmed"):
                continue
            item = next(i for i in updated["items"] if i["result"] is result)
            previous = next((decision["original_result"] for decision in reversed(updated["manual_decisions"])
                             if decision["item_id"] == item["id"]
                             and not decision["original_result"].get("manually_confirmed")), None)
            if previous is None:
                raise ValueError("Original alternatives are unavailable for this manual decision")
            restored = deepcopy(previous)
            # Retain any candidates added since the original decision.
            for field in ("alternatives", "same_abv_variants"):
                if field in result:
                    restored[field] = deepcopy(result[field])
            restored.pop("manually_confirmed", None)
            updated["manual_decisions"].append({"item_id": item["id"], "action": "reopen",
                                                "url": None, "original_result": deepcopy(result)})
            item["result"] = restored
        if request["action"] == "fetch":
            self.snapshot = updated
            self.has_unsaved_candidates = True
            return {"reload": True}
        output = write_reviewed_run(updated, self.source)
        self.last_saved = output
        self.has_unsaved_candidates = False
        return {"saved": str(output.resolve())}


def make_server(session, port=0):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            pass  # Do not log the session capability URL.

        def reply(self, status, body, content_type="application/json"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.allowed_host() or self.path != f"/{session.token}/":
                self.reply(404, '{"error":"Not found"}')
                return
            self.reply(200, session.html(), "text/html")

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (not self.allowed_host() or self.path != f"/{session.token}/action"
                    or self.headers.get("Origin") != origin
                    or not secrets.compare_digest(self.headers.get("X-Untap-Token", ""), session.token)):
                self.reply(403, '{"error":"Local review authorization failed"}')
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1000000 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError("Invalid request size or content type")
                request = json.loads(self.rfile.read(size))
                result = session.action(request)
                self.reply(200, json.dumps(result))
            except (ValueError, TypeError, KeyError, OSError) as exc:
                self.reply(400, json.dumps({"error": str(exc)}))

    return HTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="run directory or results.json")
    parser.add_argument("--no-open", action="store_true", help="print the local URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        session = ReviewSession(args.source)
        with make_server(session) as server:
            url = f"http://127.0.0.1:{server.server_port}/{session.token}/"
            print(f"Local review: {url}", flush=True)
            print("Only this computer can connect. Save reviewed run before stopping. Ctrl-C to stop.", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nLocal review stopped.")
            if session.last_saved:
                print(f"Last saved run: {session.last_saved}")
            if session.has_unsaved_candidates:
                print("Warning: candidates fetched since the last save were not saved.")
    except (OSError, ValueError) as exc:
        print(f"Could not open local review: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
