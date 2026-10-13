"""Offline tooling for turning real search flows into strict replay corpus cases.

Workflow (see tests/testdata/search_corpus/README.md):
  record    one live run of the real flow -> sanitized `<name>.json.draft` (no expected values)
  finalize  offline: add explicit expected values, replay strictly, write `<name>.json`

Live traffic happens only in `record`, once per case, and never for HTTP 429: rate-limit cases stay
synthetic. Recorded exchanges include every response the flow requested (primary, fallbacks,
expansion pages), so a replay needs nothing else.
"""
import argparse
from contextlib import redirect_stdout
import datetime
import io
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import untap.matcher as matcher
import untap.transport as transport
from untap.types import MatchResult
from tests.replay_page import ReplayPage

CORPUS = Path(__file__).parent / "testdata" / "search_corpus"
# Result fields are copied verbatim (never derived from the saved hits).
RESULT_FIELDS = ("index", "page", "nbPages", "nbHits", "hitsPerPage")
# Every hit field read by runtime code; test_untap_corpus_tools derives the consumed set from the
# code and fails when a consumer is added without extending this list.
ALLOWED_HIT_FIELDS = (
    "alias_alt", "beer_abv", "beer_ibu", "beer_label", "beer_label_hd", "beer_name", "beer_slug",
    "bid", "brewery", "brewery_name", "in_production", "rating_count", "rating_score", "type_name",
)
MASKED_COUNT, MASKED_SCORE = 100, 4.0
LABEL_HOST = "assets.untappd.com"


class CaptureRefused(ValueError):
    """The recording cannot become a corpus case (rate limit, non-200, shape issue, no expectation)."""


def _mask_count(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value                      # unexpected types stay visible to the shape canary
    return value if value <= 0 else MASKED_COUNT


def _mask_score(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return value if value <= 0 else MASKED_SCORE


def _label_url(value: Any) -> Any:
    if value is None:
        return None
    parsed = urlparse(value) if isinstance(value, str) else None
    return value if parsed and parsed.scheme == "https" and parsed.netloc == LABEL_HOST else None


def sanitize_payload(payload: Dict[str, Any], keep_ratings: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Keep identity evidence and paging unchanged; mask only rating values (None/zero/positive kept)."""
    dropped, labels_removed = set(), 0
    results = []
    for result in payload.get("results") or []:
        clean = {key: result[key] for key in RESULT_FIELDS if key in result}
        dropped.update(set(result) - set(RESULT_FIELDS) - {"hits"})
        hits = []
        for hit in result.get("hits") or []:
            kept = {key: hit[key] for key in ALLOWED_HIT_FIELDS if key in hit}
            dropped.update(set(hit) - set(ALLOWED_HIT_FIELDS))
            for key in ("beer_label", "beer_label_hd"):
                if kept.get(key) is not None and _label_url(kept[key]) is None:
                    kept[key] = None
                    labels_removed += 1
            if not keep_ratings:
                if "rating_count" in kept:
                    kept["rating_count"] = _mask_count(kept["rating_count"])
                if "rating_score" in kept:
                    kept["rating_score"] = _mask_score(kept["rating_score"])
            hits.append(kept)
        clean["hits"] = hits
        results.append(clean)
    return {"results": results}, {"dropped_fields": sorted(dropped), "labels_removed": labels_removed}


def request_entries(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"index": r["indexName"], "params": {k: v[-1] for k, v in parse_qs(r["params"], keep_blank_values=True).items()}}
            for r in body["requests"]]


class RecordingPage:
    """Wrap a real Playwright page and record Algolia exchanges in request order.

    Direct fetches are recorded from `evaluate` (their network events are ignored while it runs);
    the UI exchange is recorded from the page's response event.
    """

    def __init__(self, page: Any) -> None:
        self._page, self._fetching = page, 0
        self.exchanges: List[Dict[str, Any]] = []
        self._refusal: Optional[str] = None
        page.on("response", self._on_response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)

    def close(self) -> None:
        self._page.remove_listener("response", self._on_response)

    def _check_capture(self) -> None:
        if self._refusal:
            raise CaptureRefused(self._refusal)

    def goto(self, *args: Any, **kwargs: Any) -> Any:
        self._check_capture()
        return self._page.goto(*args, **kwargs)

    def _append(self, mode: str, body: Any, status: Any, payload: Any) -> None:
        try:
            entries = request_entries(body)
        except Exception:
            entries = []
            self._refusal = "Could not decode a recorded Algolia request"
        # Keep even non-JSON responses: status must never disappear on decode failure.
        self.exchanges.append({"request": {"mode": mode, "requests": entries},
                               "status": status, "payload": payload})
        if status == 429:
            self._refusal = "HTTP 429 during capture; stop and wait, do not retry in a loop"
        elif status != 200 or not isinstance(payload, dict):
            self._refusal = "Recorded response is not usable HTTP 200 JSON"

    def evaluate(self, script: str, args: Any = None) -> Any:
        self._check_capture()
        is_fetch = isinstance(args, dict) and "algolia.net/1/indexes" in str(args.get("url"))
        if is_fetch:
            self._fetching += 1
        try:
            result = self._page.evaluate(script, args)
        except Exception:
            if is_fetch:
                self._append("fetch", args.get("body"), None, None)
            raise
        finally:
            if is_fetch:
                self._fetching -= 1
        if is_fetch:
            response = result if isinstance(result, dict) else {}
            self._append("fetch", args.get("body"), response.get("status"), response.get("payload"))
        return result

    def _on_response(self, response: Any) -> None:
        if self._fetching or "algolia.net/1/indexes" not in response.url or response.request.method.upper() != "POST":
            return
        try:
            body = json.loads(response.request.post_data)
        except Exception:
            body = None
        try:
            payload = response.json()
        except Exception:
            payload = None
        self._append("ui", body, response.status, payload)


def _validated_exchanges(exchanges: Any, sanitize: bool) -> List[Dict[str, Any]]:
    """The same fail-closed boundary applies to recording and edited draft promotion."""
    if not isinstance(exchanges, list) or not exchanges:
        raise CaptureRefused("nothing was recorded")
    cleaned = []
    for number, exchange in enumerate(exchanges, start=1):
        if not isinstance(exchange, dict):
            raise CaptureRefused(f"exchange {number} is not an object")
        if exchange.get("status") == 429:
            raise CaptureRefused("HTTP 429 recorded: rate-limit cases stay synthetic; do not provoke Untappd")
        if exchange.get("status") != 200 or not isinstance(exchange.get("payload"), dict):
            raise CaptureRefused(f"exchange {number} is not a usable HTTP 200 JSON response")
        request = exchange.get("request")
        entries = request.get("requests") if isinstance(request, dict) else None
        if (not isinstance(request, dict) or request.get("mode") not in ("ui", "fetch")
                or not isinstance(entries, list) or not entries):
            raise CaptureRefused(f"exchange {number} has an invalid recorded request")
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get("index"), str) or not entry["index"]
                    or not isinstance(entry.get("params"), dict)
                    or not all(isinstance(k, str) and isinstance(v, str) for k, v in entry["params"].items())):
                raise CaptureRefused(f"exchange {number} has invalid request parameters")
        issues = transport.algolia_response_shape_issues(exchange["payload"])
        if issues:
            raise CaptureRefused(f"exchange {number} has response-shape issues {issues}; live captures must pass the canary")
        payload, _report = sanitize_payload(exchange["payload"], keep_ratings=not sanitize)
        if not sanitize and payload != exchange["payload"]:
            raise CaptureRefused(f"exchange {number} contains unsanitized response fields or labels")
        cleaned.append({"request": request, "status": 200, "payload": payload})
    return cleaned


def build_draft(exchanges: List[Dict[str, Any]], search: Dict[str, Any], captured_on: Optional[str] = None) -> Dict[str, Any]:
    """Sanitize a recording into a draft case. Expected values are never inferred."""
    cleaned = _validated_exchanges(exchanges, sanitize=True)
    day = captured_on or datetime.date.today().isoformat()
    draft: Dict[str, Any] = {
        "provenance": f"Live capture on {day} (tests/corpus_tools.py record); sanitized to consumed fields; "
                      "ratings masked (None/zero/positive kept); paging and identity evidence unchanged.",
        "search": search, "exchanges": cleaned, "expected": None, "excluded_urls": []}
    return draft


def replay_case(case: Dict[str, Any]) -> Tuple[MatchResult, ReplayPage, List[str]]:
    transport.reset_search_transport_authority_state()
    page = ReplayPage(case["exchanges"])
    problems: List[str] = []
    try:
        with redirect_stdout(io.StringIO()):
            result = matcher._search_one_impl(page, **case["search"])
    finally:
        transport.reset_search_transport_authority_state()
    problems += page.errors
    if page.exchanges:
        problems.append(f"{len(page.exchanges)} recorded response(s) were never requested")
    if any(page.listeners.values()):
        problems.append("capture listeners leaked")
    for key, value in (case.get("expected") or {}).items():
        if result.get(key) != value:
            problems.append(f"expected {key}={value!r}, got {result.get(key)!r}")
    urls = [row["url"] for row in result.get("excluded_candidates") or []]
    if urls != case.get("excluded_urls", []):
        problems.append(f"excluded_urls {urls} != {case.get('excluded_urls', [])}")
    return result, page, problems


def finalize(draft: Dict[str, Any], expected: Dict[str, Any], excluded_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    if not isinstance(expected, dict) or "status" not in expected:
        raise CaptureRefused("expected values must include an explicitly declared status (use --expect status=...)")
    if not isinstance(expected["status"], str) or expected["status"] not in matcher.MATCH_RESULT_STATUSES:
        raise CaptureRefused("expected status is not a recognized match status")
    if not isinstance(draft, dict):
        raise CaptureRefused("draft must be an object")
    if not all(isinstance(key, str) for key in expected):
        raise CaptureRefused("expected field names must be strings")
    unknown = set(expected) - set(MatchResult.__annotations__)
    if unknown:
        raise CaptureRefused(f"unknown expected result fields: {sorted(unknown)}")
    exchanges = _validated_exchanges(draft.get("exchanges"), sanitize=False)
    case = {**draft, "exchanges": exchanges, "expected": expected, "excluded_urls": list(excluded_urls or [])}
    try:
        _result, _page, problems = replay_case(case)
    except Exception as exc:
        raise CaptureRefused("strict replay failed: the search flow raised an exception") from exc
    if problems:
        raise CaptureRefused("strict replay failed: " + "; ".join(problems))
    return case


def _parse_expect(items: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items:
        key, separator, raw = item.partition("=")
        if not key or not separator:
            raise CaptureRefused("expected values must use KEY=VALUE")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="one live run of the real flow -> <name>.json.draft")
    rec.add_argument("name")
    rec.add_argument("--brewery", required=True)
    rec.add_argument("--beer", required=True)
    rec.add_argument("--abv", type=float, required=True)
    rec.add_argument("--style")
    fin = sub.add_parser("finalize", help="offline: add expected values, replay strictly, write <name>.json")
    fin.add_argument("name")
    fin.add_argument("--expect", action="append", default=[], metavar="KEY=VALUE")
    fin.add_argument("--excluded-url", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            from untap.parser import join_brewery_and_beer
            search = {"query": join_brewery_and_beer(args.brewery, args.beer), "expected_beer": args.beer,
                      "expected_brewery": args.brewery, "expected_abv": args.abv}
            if args.style:
                search["expected_style"] = args.style
            transport.reset_search_transport_authority_state()
            with transport.untappd_browser_page() as live:
                page = RecordingPage(live)
                try:
                    try:
                        result = matcher.search_one(page, **search)
                    except CaptureRefused:
                        raise
                    except Exception as exc:
                        raise CaptureRefused("Search flow did not complete; no draft was saved") from exc
                    page._check_capture()
                finally:
                    try:
                        page.close()
                    finally:
                        transport.reset_search_transport_authority_state()
            if result.get("status") == "rate_limited":
                raise CaptureRefused("HTTP 429 during capture; stop and wait, do not retry in a loop")
            draft = build_draft(page.exchanges, search)
            target = CORPUS / f"{args.name}.json.draft"
            target.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Recorded {len(draft['exchanges'])} exchange(s); flow result: "
                  f"{result.get('status')} {result.get('beer') or result.get('reason') or ''}\nReview {target}, then run: "
                  f"python3 -m tests.corpus_tools finalize {args.name} --expect status=...")
        else:
            source = CORPUS / f"{args.name}.json.draft"
            case = finalize(json.loads(source.read_text(encoding="utf-8")), _parse_expect(args.expect), args.excluded_url)
            (CORPUS / f"{args.name}.json").write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            source.unlink()
            print(f"Wrote {args.name}.json after a clean strict replay")
    except (CaptureRefused, OSError, json.JSONDecodeError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
