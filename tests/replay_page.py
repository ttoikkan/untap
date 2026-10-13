"""Strict Playwright I/O replay; request construction and matching stay real."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

URL = "https://recorded.algolia.net/1/indexes/*/queries"

class ReplayPage:
    def __init__(self, exchanges):
        self.exchanges = list(exchanges)
        self.requests = []
        self.listeners = {"request": [], "response": []}
        self.errors = []
        self.predicate = None
        self.last = self

    def _exchange(self, mode, body):
        requests = (json.loads(body) if isinstance(body, str) else body)["requests"]
        actual = [{"index": r["indexName"], "params": {k: v[-1] for k, v in parse_qs(r["params"], keep_blank_values=True).items()}} for r in requests]
        self.requests.append({"mode": mode, "requests": actual})
        if not self.exchanges:
            self.errors.append(f"Unexpected request: {self.requests[-1]}")
            raise AssertionError(self.errors[-1])
        expected = self.exchanges.pop(0)
        if self.requests[-1] != expected["request"]:
            self.errors.append(f"Expected {expected['request']}, got {self.requests[-1]}")
            raise AssertionError(self.errors[-1])
        return expected

    def evaluate(self, script, args):
        if args["url"] != URL:
            self.errors.append(f"Unexpected URL: {args['url']}")
            raise AssertionError(self.errors[-1])
        exchange = self._exchange("fetch", args["body"])
        status = exchange.get("status", 200)
        return {"status": status, "ok": status == 200, "payload": exchange["payload"], "text": ""}

    def goto(self, url, **kwargs):
        if url != "https://untappd.com/search":
            self.errors.append(f"Unexpected navigation: {url}")
            raise AssertionError(self.errors[-1])

        # Untappd bootstraps the search UI before text is entered.
        if self.exchanges:
            upcoming = self.exchanges[0]["request"]
            if upcoming.get("mode") == "ui" and all(
                not entry["params"].get("query") for entry in upcoming["requests"]
            ):
                body = json.dumps({"requests": [
                    {"indexName": entry["index"], "params": urlencode(entry["params"])}
                    for entry in upcoming["requests"]
                ]})
                exchange = self._exchange("ui", body)
                request = SimpleNamespace(url=URL, method="POST", resource_type="xhr", post_data=body, headers={})
                response = SimpleNamespace(url=URL, status=exchange.get("status", 200), request=request,
                                           json=lambda: exchange["payload"])
                for callback in list(self.listeners["request"]):
                    callback(request)
                for callback in list(self.listeners["response"]):
                    callback(response)

    def locator(self, selector):
        return self

    def count(self):
        return 1

    def on(self, event, callback):
        self.listeners[event].append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    @contextmanager
    def expect_response(self, predicate, **kwargs):
        self.predicate = predicate
        yield
        self.predicate = None

    def fill(self, query):
        requests = [{"indexName": "beer", "params": urlencode({"query": query, "page": "0", "hitsPerPage": "5"})}]
        upcoming = self.exchanges[0]["request"] if self.exchanges else None
        if upcoming and upcoming.get("mode") == "ui":
            # Browser-selected indexes/parameters are captured data. Override each
            # search query with the actual typed text so query regressions still fail.
            requests = []
            for recorded in upcoming["requests"]:
                params = dict(recorded["params"])
                if "query" in params:
                    params["query"] = query
                requests.append({"indexName": recorded["index"], "params": urlencode(params)})
        body = json.dumps({"requests": requests})
        exchange = self._exchange("ui", body)
        request = SimpleNamespace(url=URL, method="POST", resource_type="xhr", post_data=body, headers={})
        response = SimpleNamespace(url=URL, status=exchange.get("status", 200), request=request, json=lambda: exchange["payload"])
        if self.predicate is None or not self.predicate(response):
            self.errors.append("UI response did not match the waiting predicate")
        for callback in list(self.listeners["request"]):
            callback(request)
        for callback in list(self.listeners["response"]):
            callback(response)

    def press(self, key):
        assert key == "Enter"

    def assert_complete(self, test):
        test.assertFalse(self.errors, self.errors)
        test.assertFalse(self.exchanges, f"Unused responses: {self.exchanges}")
        test.assertFalse(any(self.listeners.values()), "Capture listeners leaked")
