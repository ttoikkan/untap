import re
import json
from time import perf_counter
from urllib.parse import parse_qsl, urlencode, urlsplit
from typing import Any, Dict, List, Optional, Tuple

from untap.parser import normalize
from untap.types import AlgoliaRequestRecord, AlgoliaTransportEvent

# ============================================================
# Untappd transport / browser layer
# ============================================================
# Extracted from the validated v57 matcher as an architecture-only change.
# This module owns browser/Algolia transport primitives, captured-network
# decoding, replay requests, DOM diagnostics, detail-page extraction, and
# transport instrumentation. It does not decide beer identity.

RATE_LIMIT_HTTP_STATUS = 429
MAX_ALGOLIA_EXPANSION_PAGES = 20
ABV_ASC_ALGOLIA_INDEX = "beer_order_by_abv"
ABV_DESC_ALGOLIA_INDEX = "beer_order_by_abv_desc"
SEARCH_RESPONSE_TIMEOUT_MS = 10000
DETAIL_CONTENT_TIMEOUT_MS = 10000
BROWSER_REQUEST_TIMEOUT_MS = 10000


class BrowserUnavailableError(RuntimeError):
    """The installed browser is unavailable; service callers may recover."""


class BeerDetailError(RuntimeError):
    """Navigation did not produce the selected beer's detail page."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status

# Debug-only Algolia traffic accounting. Searches run serially.
_ALGOLIA_DEBUG_STATS = {
    "total_requests": 0,
    "beer_requests": 0,
    "beer_expansion_pages": 0,
    "beer_expansion_pages_succeeded": 0,
    "beer_expansion_raw_hits": 0,
    "beer_expansion_reused_pages": 0,
    "beer_expansion_reused_hits": 0,
    "beer_expansion_capped": False,
}

# Optional v65 timing diagnostics. These remain measurement-only and do not
# affect matching or request strategy. Search timing measures Enter submission
# to the exact matching Algolia response. Detail timing separately measures
# navigation-to-usable-content and local detail extraction.
_SEARCH_TIMING_ENABLED = False
_SEARCH_TIMING_STATS = {
    "count": 0,
    "total_seconds": 0.0,
    "min_seconds": None,
    "max_seconds": None,
}
_DETAIL_TIMING_STATS = {
    "count": 0,
    "navigation_total_seconds": 0.0,
    "navigation_min_seconds": None,
    "navigation_max_seconds": None,
    "extraction_count": 0,
    "extraction_total_seconds": 0.0,
    "extraction_min_seconds": None,
    "extraction_max_seconds": None,
}


def configure_search_timing(enabled=False):
    """Enable/disable lightweight search-response timing and reset its stats."""
    global _SEARCH_TIMING_ENABLED
    _SEARCH_TIMING_ENABLED = bool(enabled)
    reset_search_timing_stats()
    reset_detail_timing_stats()


def debug_timing_enabled():
    """Return whether opt-in timing diagnostics are active for this run."""
    return _SEARCH_TIMING_ENABLED


def reset_search_timing_stats():
    _SEARCH_TIMING_STATS.update({
        "count": 0,
        "total_seconds": 0.0,
        "min_seconds": None,
        "max_seconds": None,
    })


def reset_detail_timing_stats():
    _DETAIL_TIMING_STATS.update({
        "count": 0,
        "navigation_total_seconds": 0.0,
        "navigation_min_seconds": None,
        "navigation_max_seconds": None,
        "extraction_count": 0,
        "extraction_total_seconds": 0.0,
        "extraction_min_seconds": None,
        "extraction_max_seconds": None,
    })


def get_search_timing_stats():
    """Return a copy of the current run's search-response timing summary."""
    return dict(_SEARCH_TIMING_STATS)


def get_detail_timing_stats():
    """Return a copy of the current run's detail-page timing summary."""
    return dict(_DETAIL_TIMING_STATS)


def _record_search_timing(query, elapsed_seconds, outcome="ok"):
    stats = _SEARCH_TIMING_STATS
    stats["count"] += 1
    stats["total_seconds"] += elapsed_seconds
    current_min = stats["min_seconds"]
    current_max = stats["max_seconds"]
    stats["min_seconds"] = (
        elapsed_seconds if current_min is None else min(current_min, elapsed_seconds)
    )
    stats["max_seconds"] = (
        elapsed_seconds if current_max is None else max(current_max, elapsed_seconds)
    )

    status_suffix = "" if outcome == "ok" else f" [{outcome}]"
    print(
        f'[timing] search -> Algolia response: {elapsed_seconds:.3f}s'
        f'{status_suffix} | {query}'
    )


def _update_min_max(stats, min_key, max_key, elapsed_seconds):
    current_min = stats[min_key]
    current_max = stats[max_key]
    stats[min_key] = (
        elapsed_seconds if current_min is None else min(current_min, elapsed_seconds)
    )
    stats[max_key] = (
        elapsed_seconds if current_max is None else max(current_max, elapsed_seconds)
    )


def _record_detail_navigation_timing(beer_url, elapsed_seconds, outcome="ok"):
    stats = _DETAIL_TIMING_STATS
    stats["count"] += 1
    stats["navigation_total_seconds"] += elapsed_seconds
    _update_min_max(
        stats, "navigation_min_seconds", "navigation_max_seconds", elapsed_seconds
    )
    status_suffix = "" if outcome == "ok" else f" [{outcome}]"
    print(
        f'[timing] detail navigation -> usable content: {elapsed_seconds:.3f}s'
        f'{status_suffix} | {beer_url}'
    )


def _record_detail_extraction_timing(label, elapsed_seconds):
    stats = _DETAIL_TIMING_STATS
    stats["extraction_count"] += 1
    stats["extraction_total_seconds"] += elapsed_seconds
    _update_min_max(
        stats, "extraction_min_seconds", "extraction_max_seconds", elapsed_seconds
    )
    print(f'[timing] detail extraction: {elapsed_seconds:.3f}s | {label}')


def print_search_timing_summary():
    """Print aggregate transport timing when --debug-timing is enabled."""
    if not _SEARCH_TIMING_ENABLED:
        return

    stats = _SEARCH_TIMING_STATS
    count = stats["count"]
    print()
    print("Search timing summary")
    print("=" * 70)
    if not count:
        print("No timed Untappd search submissions.")
    else:
        total = stats["total_seconds"]
        print(f"Timed search submissions: {count}")
        print(f"Total submit-to-response time: {total:.3f}s")
        print(f"Average submit-to-response time: {total / count:.3f}s")
        print(f"Fastest submit-to-response time: {stats['min_seconds']:.3f}s")
        print(f"Slowest submit-to-response time: {stats['max_seconds']:.3f}s")

    detail = _DETAIL_TIMING_STATS
    detail_count = detail["count"]
    print()
    print("Detail-page timing summary")
    print("=" * 70)
    if not detail_count:
        print("No timed Untappd detail pages.")
        return

    nav_total = detail["navigation_total_seconds"]
    extraction_count = detail["extraction_count"]
    extraction_total = detail["extraction_total_seconds"]
    print(f"Timed detail pages: {detail_count}")
    print(f"Total navigation-to-content time: {nav_total:.3f}s")
    print(f"Average navigation-to-content time: {nav_total / detail_count:.3f}s")
    print(f"Fastest navigation-to-content time: {detail['navigation_min_seconds']:.3f}s")
    print(f"Slowest navigation-to-content time: {detail['navigation_max_seconds']:.3f}s")
    print(f"Timed detail extractions: {extraction_count}")
    print(f"Total detail-extraction time: {extraction_total:.3f}s")
    if extraction_count:
        print(f"Average detail-extraction time: {extraction_total / extraction_count:.3f}s")
        print(f"Fastest detail-extraction time: {detail['extraction_min_seconds']:.3f}s")
        print(f"Slowest detail-extraction time: {detail['extraction_max_seconds']:.3f}s")



# v73 authoritative search transport state. The first successful UI-triggered
# search captures the exact Algolia request shape. Subsequent primary and
# fallback searches reuse that shape through serial browser-context fetch().
# Matching semantics remain downstream and unchanged.
_SEARCH_TRANSPORT_TEMPLATE_EVENT = None
_SEARCH_TRANSPORT_AUTHORITY_STATS = {
    "ui_bootstrap_searches": 0,
    "ui_recovery_searches": 0,
    "template_invalidations": 0,
    "successful_recoveries": 0,
    "failed_recoveries": 0,
    "direct_searches": 0,
    "template_unavailable_fallbacks": 0,
    "direct_errors": 0,
    "direct_rate_limited": 0,
    "direct_total_seconds": 0.0,
}


def reset_search_transport_authority_state():
    global _SEARCH_TRANSPORT_TEMPLATE_EVENT
    _SEARCH_TRANSPORT_TEMPLATE_EVENT = None
    _SEARCH_TRANSPORT_AUTHORITY_STATS.update({
        "ui_bootstrap_searches": 0,
        "ui_recovery_searches": 0,
        "template_invalidations": 0,
        "successful_recoveries": 0,
        "failed_recoveries": 0,
        "direct_searches": 0,
        "template_unavailable_fallbacks": 0,
        "direct_errors": 0,
        "direct_rate_limited": 0,
        "direct_total_seconds": 0.0,
    })


def remember_search_transport_template(request_event: Optional[AlgoliaTransportEvent], *, recovery: bool = False) -> bool:
    """Store one validated captured Algolia request as the run template.

    ``recovery`` distinguishes the initial bootstrap from a mid-batch
    self-healing recapture after a direct transport failure.
    """
    global _SEARCH_TRANSPORT_TEMPLATE_EVENT
    if _SEARCH_TRANSPORT_TEMPLATE_EVENT is not None or not request_event:
        return False
    parsed = request_event.get("algolia_requests") or []
    url = request_event.get("url")
    if not url or not parsed:
        return False
    if not any(req.get("query") is not None for req in parsed):
        return False
    _SEARCH_TRANSPORT_TEMPLATE_EVENT = {
        "kind": "request",
        "method": "POST",
        "url": url,
        "algolia_requests": [
            {
                "indexName": req.get("indexName"),
                "query": req.get("query"),
                "page": req.get("page"),
                "hitsPerPage": req.get("hitsPerPage"),
                "filters": req.get("filters"),
                "params": dict(req.get("params") or {}),
            }
            for req in parsed
        ],
    }
    key = "ui_recovery_searches" if recovery else "ui_bootstrap_searches"
    _SEARCH_TRANSPORT_AUTHORITY_STATS[key] += 1
    return True


def invalidate_search_transport_template() -> bool:
    """Discard the cached request shape after a non-429 direct failure."""
    global _SEARCH_TRANSPORT_TEMPLATE_EVENT
    if _SEARCH_TRANSPORT_TEMPLATE_EVENT is None:
        return False
    _SEARCH_TRANSPORT_TEMPLATE_EVENT = None
    _SEARCH_TRANSPORT_AUTHORITY_STATS["template_invalidations"] += 1
    return True


def note_search_transport_recovery(success: bool) -> None:
    key = "successful_recoveries" if success else "failed_recoveries"
    _SEARCH_TRANSPORT_AUTHORITY_STATS[key] += 1


def search_transport_template_available() -> bool:
    return _SEARCH_TRANSPORT_TEMPLATE_EVENT is not None


def get_search_transport_authority_stats() -> Dict[str, Any]:
    """Return a copy of the current run's authoritative transport counters."""
    return dict(_SEARCH_TRANSPORT_AUTHORITY_STATS)


def _query_request_event_from_template(search_query: str) -> Optional[AlgoliaTransportEvent]:
    template = _SEARCH_TRANSPORT_TEMPLATE_EVENT
    if not template:
        return None
    requests: List[AlgoliaRequestRecord] = []
    changed = False
    for req in template.get("algolia_requests") or []:
        params = dict(req.get("params") or {})
        if req.get("query") is not None or "query" in params:
            params["query"] = search_query
            changed = True
        # Primary/fallback searches always need page 0. Preserve the rest of
        # the captured request shape exactly, including hitsPerPage/filters.
        params["page"] = "0"
        requests.append({
            "indexName": req.get("indexName"),
            "query": params.get("query"),
            "page": params.get("page"),
            "hitsPerPage": params.get("hitsPerPage"),
            "filters": params.get("filters"),
            "params": params,
        })
    if not changed or not requests:
        return None
    return {
        "kind": "request",
        "method": "POST",
        "url": template.get("url"),
        "algolia_requests": requests,
    }


def fetch_authoritative_algolia_search(page: Any, search_query: str) -> Tuple[Optional[AlgoliaTransportEvent], Optional[AlgoliaTransportEvent], Optional[str]]:
    """Issue one serial page-0 search from the captured browser request shape.

    Returns (request_event, response_event, error). HTTP 429 is surfaced and
    never retried through the UI. No matcher logic lives here.
    """
    request_event = _query_request_event_from_template(search_query)
    if request_event is None:
        _SEARCH_TRANSPORT_AUTHORITY_STATS["template_unavailable_fallbacks"] += 1
        return None, None, "search transport template unavailable"

    _note_algolia_request()
    started = perf_counter()
    status, payload, error = _fetch_algolia_exact_request(page, request_event)
    elapsed = perf_counter() - started
    stats = _SEARCH_TRANSPORT_AUTHORITY_STATS
    stats["direct_searches"] += 1
    stats["direct_total_seconds"] += elapsed

    if _SEARCH_TIMING_ENABLED:
        _record_search_timing(
            search_query,
            elapsed,
            outcome=("ok" if error is None else ("429" if status == RATE_LIMIT_HTTP_STATUS else "error")),
        )

    if error is not None:
        stats["direct_errors"] += 1
        if status == RATE_LIMIT_HTTP_STATUS:
            stats["direct_rate_limited"] += 1
        response_event: AlgoliaTransportEvent = {
            "kind": "response",
            "method": "POST",
            "status": status,
            "url": request_event.get("url"),
            "algolia_requests": request_event.get("algolia_requests") or [],
            "algolia_response": [],
        }
        return request_event, response_event, error

    if payload is None:
        stats["direct_errors"] += 1
        response_event = {
            "kind": "response",
            "method": "POST",
            "status": status,
            "url": request_event.get("url"),
            "algolia_requests": request_event.get("algolia_requests") or [],
            "algolia_response": [],
        }
        return request_event, response_event, "direct transport returned no payload"

    response_event = {
        "kind": "response",
        "method": "POST",
        "status": status,
        "url": request_event.get("url"),
        "algolia_requests": request_event.get("algolia_requests") or [],
        "algolia_response": _summarize_algolia_response(payload),
    }
    return request_event, response_event, None


def print_search_transport_authority_summary():
    if not _SEARCH_TIMING_ENABLED:
        return
    stats = _SEARCH_TRANSPORT_AUTHORITY_STATS
    print()
    print("Search transport authority summary")
    print("=" * 70)
    print(f"UI bootstrap searches: {stats['ui_bootstrap_searches']}")
    print(f"UI recovery searches: {stats['ui_recovery_searches']}")
    print(f"Template invalidations: {stats['template_invalidations']}")
    print(f"Successful self-healing recoveries: {stats['successful_recoveries']}")
    print(f"Failed self-healing recoveries: {stats['failed_recoveries']}")
    print(f"Authoritative browser-fetch searches: {stats['direct_searches']}")
    print(f"Template-unavailable UI fallbacks: {stats['template_unavailable_fallbacks']}")
    print(f"Direct transport errors: {stats['direct_errors']}")
    print(f"Direct transport HTTP 429s: {stats['direct_rate_limited']}")
    if stats["direct_searches"]:
        print(f"Total direct transport time: {stats['direct_total_seconds']:.3f}s")
        print(
            f"Average direct transport time: "
            f"{stats['direct_total_seconds'] / stats['direct_searches']:.3f}s"
        )
    print("Searches remained serial; non-429 direct failures self-heal through one UI recapture.")
    print("HTTP 429 remains fail-fast; matcher scoring and ambiguity policy were unchanged.")


# Optional v71 primary-search transport shadow diagnostics. This is strictly
# opt-in because each shadow comparison issues one additional serial Algolia
# request through the existing browser context. Matcher decisions always use
# the normal UI-triggered response.
_SEARCH_TRANSPORT_SHADOW_ENABLED = False
_SEARCH_TRANSPORT_SHADOW_LIMIT = 0
_SEARCH_TRANSPORT_SHADOW_STATS = {
    "attempted": 0,
    "exact": 0,
    "mismatch": 0,
    "errors": 0,
    "rate_limited": 0,
    "total_seconds": 0.0,
}


def configure_search_transport_shadow(limit=0):
    """Enable bounded v71 UI-vs-browser-fetch search transport shadowing."""
    global _SEARCH_TRANSPORT_SHADOW_ENABLED, _SEARCH_TRANSPORT_SHADOW_LIMIT
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError):
        parsed_limit = 0
    _SEARCH_TRANSPORT_SHADOW_LIMIT = max(0, parsed_limit)
    _SEARCH_TRANSPORT_SHADOW_ENABLED = _SEARCH_TRANSPORT_SHADOW_LIMIT > 0
    reset_search_transport_shadow_stats()


def reset_search_transport_shadow_stats():
    _SEARCH_TRANSPORT_SHADOW_STATS.update({
        "attempted": 0,
        "exact": 0,
        "mismatch": 0,
        "errors": 0,
        "rate_limited": 0,
        "total_seconds": 0.0,
    })


def get_search_transport_shadow_stats():
    return dict(_SEARCH_TRANSPORT_SHADOW_STATS)


def _shadow_budget_available():
    return (
        _SEARCH_TRANSPORT_SHADOW_ENABLED
        and _SEARCH_TRANSPORT_SHADOW_STATS["attempted"] < _SEARCH_TRANSPORT_SHADOW_LIMIT
    )


def _build_algolia_exact_replay_body(parsed_requests: List[AlgoliaRequestRecord]) -> Dict[str, Any]:
    return {
        "requests": [
            {
                "indexName": req.get("indexName"),
                "params": urlencode(dict(req.get("params") or {})),
            }
            for req in parsed_requests
        ]
    }


def _browser_json_post(page: Any, url: str, body: Dict[str, Any]) -> Any:
    """POST JSON in the browser; callers retain response/error policy."""
    return page.evaluate(
        """
        async ({url, body, timeoutMs}) => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            try {
                const response = await fetch(url, {
                    method: 'POST', headers: {'content-type': 'application/json'},
                    body: JSON.stringify(body), credentials: 'omit',
                    signal: controller.signal
                });
                const text = await response.text();
                let payload = null;
                try { payload = JSON.parse(text); } catch (_) {}
                return {status: response.status, ok: response.ok, payload, text};
            } catch (error) {
                if (controller.signal.aborted) {
                    throw new Error(`Browser request timed out after ${timeoutMs} ms`);
                }
                throw error;
            } finally {
                clearTimeout(timer);
            }
        }
        """,
        {"url": url, "body": body, "timeoutMs": BROWSER_REQUEST_TIMEOUT_MS},
    )


def _fetch_algolia_exact_request(page: Any, request_event: AlgoliaTransportEvent) -> Tuple[Optional[int], Optional[Dict[str, Any]], Optional[str]]:
    parsed_requests = request_event.get("algolia_requests") or []
    url = request_event.get("url")
    if not parsed_requests or not url:
        return None, None, "no parsed Algolia request available"
    body = _build_algolia_exact_replay_body(parsed_requests)
    try:
        result = _browser_json_post(page, url, body)
    except Exception as exc:
        return None, None, str(exc)
    if not result:
        return None, None, "browser fetch returned no result"
    status = result.get("status")
    if not result.get("ok"):
        return status, None, f"HTTP {status}"
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return status, None, "response payload was not JSON"
    return status, payload, None


def _shadow_hit_signature(hit):
    if not isinstance(hit, dict):
        return None
    return (
        hit.get("bid"),
        hit.get("beer_slug"),
        hit.get("beer_name"),
        hit.get("brewery_name"),
        hit.get("beer_abv"),
        hit.get("rating_score"),
        hit.get("rating_count"),
        hit.get("type_name"),
    )


def _shadow_page_signature(page0):
    if not page0:
        return None
    return (
        page0.get("nbHits"),
        page0.get("page"),
        page0.get("nbPages"),
        page0.get("hitsPerPage"),
        tuple(_shadow_hit_signature(hit) for hit in (page0.get("hits") or [])),
    )


def shadow_compare_search_transport(page, request_event, search_query, ui_initial_page) -> bool:
    """Compare one UI-triggered page-0 result with an exact browser-fetch replay.

    Replay candidates never affect matching. Return True on HTTP 429 so the
    caller stops further traffic. Other failures remain diagnostic-only.
    The extra request is bounded by the CLI shadow limit and never retried.
    """
    if not _shadow_budget_available() or request_event is None:
        return False

    stats = _SEARCH_TRANSPORT_SHADOW_STATS
    stats["attempted"] += 1
    started = perf_counter()
    status, payload, error = _fetch_algolia_exact_request(page, request_event)
    elapsed = perf_counter() - started
    stats["total_seconds"] += elapsed

    if error is not None or payload is None:
        error = error or "response payload was not JSON"
        stats["errors"] += 1
        if status == RATE_LIMIT_HTTP_STATUS:
            stats["rate_limited"] += 1
        print(
            f"[transport-shadow] ERROR: {error} | {elapsed:.3f}s | {search_query}"
        )
        return status == RATE_LIMIT_HTTP_STATUS

    fake_event = {
        "kind": "response",
        "status": status,
        "url": request_event.get("url"),
        "algolia_requests": request_event.get("algolia_requests") or [],
        "algolia_response": _summarize_algolia_response(payload),
    }
    shadow_page = _matching_algolia_initial_page([fake_event], search_query)
    if _shadow_page_signature(ui_initial_page) == _shadow_page_signature(shadow_page):
        stats["exact"] += 1
        print(f"[transport-shadow] PARITY | {elapsed:.3f}s | {search_query}")
    else:
        stats["mismatch"] += 1
        ui_hits = len((ui_initial_page or {}).get("hits") or [])
        shadow_hits = len((shadow_page or {}).get("hits") or [])
        print(
            f"[transport-shadow] DIFF: ui_hits={ui_hits} shadow_hits={shadow_hits} "
            f"| {elapsed:.3f}s | {search_query}"
        )
    return False


def print_search_transport_shadow_summary():
    if not _SEARCH_TRANSPORT_SHADOW_ENABLED:
        return
    stats = _SEARCH_TRANSPORT_SHADOW_STATS
    print()
    print("UI / browser-fetch search transport shadow summary")
    print("=" * 70)
    print(f"Shadow request limit: {_SEARCH_TRANSPORT_SHADOW_LIMIT}")
    print(f"Shadow requests attempted: {stats['attempted']}")
    print(f"Exact page-0 parity: {stats['exact']}/{stats['attempted']}")
    print(f"Mismatches: {stats['mismatch']}")
    print(f"Shadow errors: {stats['errors']}")
    print(f"Shadow HTTP 429s: {stats['rate_limited']}")
    print(f"Total shadow fetch time: {stats['total_seconds']:.3f}s")
    if stats["attempted"]:
        print(f"Average shadow fetch time: {stats['total_seconds'] / stats['attempted']:.3f}s")
    print("Shadow replay never supplies matching candidates; HTTP 429 stops the run.")

def _looks_search_related_url(url):
    if not url:
        return False

    u = url.lower()
    return (
        "algolia.net/1/indexes" in u
        or "/search" in u
    )

def _parse_algolia_request_body(body: Optional[str]) -> List[AlgoliaRequestRecord]:
    if not body:
        return []

    try:
        payload = json.loads(body)
    except Exception:
        return []

    parsed: List[AlgoliaRequestRecord] = []

    for req in payload.get("requests") or []:
        index_name = req.get("indexName")
        params = req.get("params") or ""
        fields = dict(parse_qsl(params, keep_blank_values=True))

        parsed.append({
            "indexName": index_name,
            "query": fields.get("query"),
            "page": fields.get("page"),
            "hitsPerPage": fields.get("hitsPerPage"),
            "filters": fields.get("filters"),
            "params": fields,
        })

    return parsed

# Required shape shared with the sanitized replay corpus. Optional fields and
# additional service fields are deliberately tolerated; this is diagnostic only.
_ALGOLIA_REQUIRED_RESULT_FIELDS = {"hits": list, "nbHits": int, "page": int, "nbPages": int}
_ALGOLIA_REQUIRED_HIT_FIELDS: Dict[str, Any] = {"beer_name": str, "brewery_name": str, "beer_abv": (int, float),
                                "bid": int}
_ALGOLIA_CONFIRMATION_HIT_FIELDS: Dict[str, Any] = {"beer_slug": str, "rating_score": (int, float),
                                                   "rating_count": int, "type_name": str}
_RESPONSE_SHAPE_ISSUES: set[str] = set()
_RESPONSE_SHAPE_OBSERVATIONS = 0
_RESPONSE_METADATA_DIAGNOSTICS: set[str] = set()


def reset_response_shape_observations() -> None:
    global _RESPONSE_SHAPE_OBSERVATIONS
    _RESPONSE_SHAPE_ISSUES.clear()
    _RESPONSE_METADATA_DIAGNOSTICS.clear()
    _RESPONSE_SHAPE_OBSERVATIONS = 0


def response_shape_observations() -> tuple[int, List[str]]:
    return _RESPONSE_SHAPE_OBSERVATIONS, sorted(_RESPONSE_SHAPE_ISSUES)


def algolia_response_shape_issues(payload: Any) -> List[str]:
    """Compare required fields/types with the replay shape, without reading values."""
    issues = set()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return ["results must be a list"]
    for result in payload["results"]:
        if not isinstance(result, dict):
            issues.add("result must be an object")
            continue
        for key, kind in _ALGOLIA_REQUIRED_RESULT_FIELDS.items():
            if not isinstance(result.get(key), kind) or isinstance(result.get(key), bool):
                issues.add(f"result.{key}: missing or unexpected type")
        hits = result.get("hits")
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                issues.add("hit must be an object")
                continue
            for key, kinds in {**_ALGOLIA_REQUIRED_HIT_FIELDS, **_ALGOLIA_CONFIRMATION_HIT_FIELDS}.items():
                if key in _ALGOLIA_CONFIRMATION_HIT_FIELDS and hit.get(key) is None:
                    continue
                value = hit.get(key)
                if not isinstance(value, kinds) or isinstance(value, bool):
                    issues.add(f"hit.{key}: missing or unexpected type")
    return sorted(issues)



def algolia_response_metadata_diagnostics(payload: Any) -> List[str]:
    """Locate incomplete confirmation metadata without treating it as schema drift."""
    diagnostics: List[str] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return diagnostics
    for result_index, result in enumerate(payload["results"]):
        if not isinstance(result, dict) or not isinstance(result.get("hits"), list):
            continue
        for hit_index, hit in enumerate(result["hits"]):
            if not isinstance(hit, dict):
                continue
            for field in _ALGOLIA_CONFIRMATION_HIT_FIELDS:
                value = hit.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    diagnostics.append(f"result[{result_index}].hit[{hit_index}] bid={hit.get('bid')}: "
                                       f"{field} unavailable")
    return diagnostics


def response_metadata_observations() -> List[str]:
    return sorted(_RESPONSE_METADATA_DIAGNOSTICS)


def _summarize_algolia_response(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    global _RESPONSE_SHAPE_OBSERVATIONS
    _RESPONSE_SHAPE_OBSERVATIONS += 1
    _RESPONSE_SHAPE_ISSUES.update(algolia_response_shape_issues(payload))
    _RESPONSE_METADATA_DIAGNOSTICS.update(algolia_response_metadata_diagnostics(payload))
    summaries = []

    for result in payload.get("results") or []:
        hits = result.get("hits") or []

        hit_keys = sorted({
            key
            for hit in hits[:3]
            if isinstance(hit, dict)
            for key in hit.keys()
        })

        sample_hits = []
        for hit in hits[:10]:
            if not isinstance(hit, dict):
                continue

            sample_hits.append({
                "beer_name": hit.get("beer_name"),
                "brewery_name": hit.get("brewery_name"),
                "beer_abv": hit.get("beer_abv"),
                "type_name": hit.get("type_name"),
                "rating_score": hit.get("rating_score"),
                "rating_count": hit.get("rating_count"),
                "bid": hit.get("bid"),
                "beer_slug": hit.get("beer_slug"),
            })

        summaries.append({
            "index": result.get("index"),
            "nbHits": result.get("nbHits"),
            "page": result.get("page"),
            "nbPages": result.get("nbPages"),
            "hitsPerPage": result.get("hitsPerPage"),
            "hitsReturned": len(hits),
            "hitKeys": hit_keys,
            "sampleHits": sample_hits,
            # Internal-only copy used by v34 to reuse an already captured
            # primary page 0 during conditional expansion. Debug output still
            # prints only the compact sample above.
            "rawHits": hits,
        })

    return summaries

def _build_algolia_replay_body(parsed_requests, page_number=1):
    requests_out = []

    for req in parsed_requests:
        params = dict(req.get("params") or {})
        params["page"] = str(page_number)

        requests_out.append({
            "indexName": req.get("indexName"),
            "params": urlencode(params),
        })

    return {"requests": requests_out}

def _fetch_algolia_page(page, request_event, page_number):
    parsed_requests = request_event.get("algolia_requests") or []
    if not parsed_requests:
        return None, "no parsed Algolia request available"

    url = request_event.get("url")
    body = _build_algolia_replay_body(
        parsed_requests,
        page_number=page_number,
    )

    try:
        result = _browser_json_post(page, url, body)

        if not result:
            return None, "browser fetch returned no result"

        if not result.get("ok"):
            return None, f"HTTP {result.get('status')}"

        payload = result.get("payload")
        if not isinstance(payload, dict):
            return None, "response payload was not JSON"

        return payload, None

    except Exception as exc:
        return None, str(exc)

def _reset_run_algolia_debug_stats():
    _ALGOLIA_DEBUG_STATS["total_requests"] = 0
    _reset_beer_algolia_debug_stats()

def _reset_beer_algolia_debug_stats():
    _ALGOLIA_DEBUG_STATS["beer_requests"] = 0
    _ALGOLIA_DEBUG_STATS["beer_expansion_pages"] = 0
    _ALGOLIA_DEBUG_STATS["beer_expansion_pages_succeeded"] = 0
    _ALGOLIA_DEBUG_STATS["beer_expansion_raw_hits"] = 0
    _ALGOLIA_DEBUG_STATS["beer_expansion_reused_pages"] = 0
    _ALGOLIA_DEBUG_STATS["beer_expansion_reused_hits"] = 0
    _ALGOLIA_DEBUG_STATS["beer_expansion_capped"] = False

def _note_algolia_request(expansion=False):
    _ALGOLIA_DEBUG_STATS["total_requests"] += 1
    _ALGOLIA_DEBUG_STATS["beer_requests"] += 1
    if expansion:
        _ALGOLIA_DEBUG_STATS["beer_expansion_pages"] += 1

def _print_algolia_network_summary(rate_limited_query=None):
    print()
    print("Network summary:")
    print(
        f"  Algolia requests this beer: "
        f"{_ALGOLIA_DEBUG_STATS['beer_requests']}"
    )
    print(
        f"  Algolia requests total run: "
        f"{_ALGOLIA_DEBUG_STATS['total_requests']}"
    )
    print(
        f"  expansion pages requested: "
        f"{_ALGOLIA_DEBUG_STATS['beer_expansion_pages']}"
    )
    print(
        f"  expansion pages succeeded: "
        f"{_ALGOLIA_DEBUG_STATS['beer_expansion_pages_succeeded']}"
    )
    print(
        f"  expansion raw hits fetched: "
        f"{_ALGOLIA_DEBUG_STATS['beer_expansion_raw_hits']}"
    )
    print(
        f"  primary expansion pages reused: "
        f"{_ALGOLIA_DEBUG_STATS['beer_expansion_reused_pages']}"
    )
    print(
        f"  primary hits reused: "
        f"{_ALGOLIA_DEBUG_STATS['beer_expansion_reused_hits']}"
    )
    print(
        "  expansion capped: "
        + ("yes" if _ALGOLIA_DEBUG_STATS["beer_expansion_capped"] else "no")
    )
    if rate_limited_query:
        print(
            f"  HTTP 429 query: {rate_limited_query}"
        )
        print(
            f"  HTTP 429 request this beer: "
            f"{_ALGOLIA_DEBUG_STATS['beer_requests']}"
        )
        print(
            f"  HTTP 429 request total run: "
            f"{_ALGOLIA_DEBUG_STATS['total_requests']}"
        )

def _build_algolia_sorted_replay_body(
    request_event,
    search_query,
    page_number,
    index_name,
):
    """Build one replay request for the exact query using another replica."""
    target = normalize(search_query)
    for req in request_event.get("algolia_requests") or []:
        if normalize(req.get("query") or "") != target:
            continue
        params = dict(req.get("params") or {})
        params["page"] = str(page_number)
        return {
            "requests": [{
                "indexName": index_name,
                "params": urlencode(params),
            }]
        }
    return None

def _fetch_algolia_sorted_page(
    page,
    request_event,
    search_query,
    page_number,
    index_name,
):
    body = _build_algolia_sorted_replay_body(
        request_event,
        search_query,
        page_number,
        index_name,
    )
    if not body:
        return None, "no matching parsed Algolia request available"

    url = request_event.get("url")
    try:
        result = _browser_json_post(page, url, body)
        if not result:
            return None, "browser fetch returned no result"
        if not result.get("ok"):
            return None, f"HTTP {result.get('status')}"
        payload = result.get("payload")
        if not isinstance(payload, dict):
            return None, "response payload was not JSON"
        return payload, None
    except Exception as exc:
        return None, str(exc)



def _matching_algolia_response_status(network_events, search_query):
    """Return the HTTP status for the captured Algolia response, if known."""
    for event in reversed(network_events or []):
        if event.get("kind") != "response":
            continue

        if "algolia.net/1/indexes" not in event.get("url", "").lower():
            continue

        if any(
            normalize(req.get("query") or "") == normalize(search_query)
            for req in (event.get("algolia_requests") or [])
        ):
            return event.get("status")

    return None

def _matching_algolia_nb_hits(network_events, search_query):
    """Return nbHits for the captured Algolia response matching search_query."""
    for event in reversed(network_events or []):
        if event.get("kind") != "response":
            continue
        summary = _matching_algolia_result(
            event.get("algolia_response"), event.get("algolia_requests"), search_query)
        if summary is not None and type(summary.get("nbHits")) is int:
            return summary["nbHits"]
    return None


def _matching_algolia_result(results: Any, requests: Any, query: str,
                             page_number: Optional[int] = None,
                             index_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Pair each result with its request and validate the expected page/index."""
    if not isinstance(results, list) or not isinstance(requests, list):
        return None
    for index, request in enumerate(requests):
        if (not isinstance(request, dict) or normalize(request.get("query") or "") != normalize(query)
                or index >= len(results)):
            continue
        result = results[index]
        if not isinstance(result, dict):
            continue
        if page_number is not None and result.get("page") != page_number:
            continue
        expected_index = index_name or request.get("indexName")
        if expected_index and result.get("index") not in (None, expected_index):
            continue
        return result
    return None


def _matching_replay_result(payload: Any, request_event: Any, query: str,
                            page_number: int, index_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(request_event, dict):
        return None
    return _matching_algolia_result(payload.get("results"), request_event.get("algolia_requests"),
                                    query, page_number, index_name)

def _matching_algolia_initial_page(network_events, search_query):
    """Return a conservatively validated captured Algolia page 0.

    Response payloads can contain multiple Algolia requests/results, so pair
    request and result entries by their original order and only reuse the
    result whose request query exactly matches this search. If anything about
    the page metadata is incomplete or inconsistent, return None and let the
    normal expansion path fetch page 0 itself.
    """
    target = normalize(search_query)

    for event in reversed(network_events or []):
        if event.get("kind") != "response":
            continue
        if event.get("status") != 200:
            continue

        requests = event.get("algolia_requests") or []
        summaries = event.get("algolia_response") or []

        for index, req in enumerate(requests):
            if normalize(req.get("query") or "") != target:
                continue
            if index >= len(summaries):
                continue

            summary = summaries[index]
            raw_hits = summary.get("rawHits")
            page_number = summary.get("page")
            nb_hits = summary.get("nbHits")
            nb_pages = summary.get("nbPages")
            hits_per_page = summary.get("hitsPerPage")

            if page_number != 0:
                continue
            if not isinstance(raw_hits, list):
                continue
            if not isinstance(nb_hits, int) or nb_hits < 0:
                continue
            if not isinstance(nb_pages, int) or nb_pages < 0:
                continue
            if not isinstance(hits_per_page, int) or hits_per_page <= 0:
                continue
            if len(raw_hits) != summary.get("hitsReturned"):
                continue
            if nb_hits > 0 and not raw_hits:
                continue

            request_index = req.get("indexName")
            response_index = summary.get("index")
            if (
                request_index
                and response_index
                and request_index != response_index
            ):
                continue

            request_page = req.get("page")
            if request_page not in (None, "", "0", 0):
                continue

            request_hpp = req.get("hitsPerPage")
            if request_hpp not in (None, ""):
                try:
                    if int(request_hpp) != hits_per_page:
                        continue
                except Exception:
                    continue

            return {
                "hits": raw_hits,
                "nbHits": nb_hits,
                "nbPages": nb_pages,
                "page": page_number,
                "hitsPerPage": hits_per_page,
            }

    return None

def extract_beer_info(
    page,
    beer_url,
    brewery_from_search=None,
    expected_beer=None,
):
    navigation_started = perf_counter() if _SEARCH_TIMING_ENABLED else None
    navigation_outcome = "ok"

    response = page.goto(
        beer_url,
        wait_until="domcontentloaded",
        timeout=30000,
    )
    status = response.status if response is not None else None
    if status is None or not 200 <= status < 300:
        raise BeerDetailError(f"Beer detail navigation failed: HTTP {status}", status)
    selected_id = re.search(r"/b/[^/]+/(\d+)(?:[/?#]|$)", beer_url)
    current_url = page.url
    current_id = re.search(r"/b/[^/]+/(\d+)(?:[/?#]|$)", current_url)
    parsed_url = urlsplit(current_url)
    if (parsed_url.scheme != "https" or parsed_url.hostname not in {"untappd.com", "www.untappd.com"}
            or selected_id is None or current_id is None or selected_id.group(1) != current_id.group(1)):
        raise BeerDetailError("Beer detail navigation left the selected beer page")

    heading = page.locator("h1").first
    try:
        heading.wait_for(
            state="visible",
            timeout=DETAIL_CONTENT_TIMEOUT_MS,
        )
    except Exception:
        # A late heading may still be readable; the identity checks below
        # reject missing or unrelated content before it can be confirmed.
        navigation_outcome = "heading-timeout"
        pass

    if navigation_started is not None:
        _record_detail_navigation_timing(
            beer_url,
            perf_counter() - navigation_started,
            outcome=navigation_outcome,
        )

    extraction_started = perf_counter() if _SEARCH_TIMING_ENABLED else None

    body = page.locator(
        "body"
    ).inner_text()

    try:
        beer_name = (
            heading
            .inner_text()
            .strip()
        )
    except Exception:
        beer_name = "Unknown"

    if not beer_name or normalize(beer_name) == "unknown":
        raise BeerDetailError("Beer detail page has no usable beer heading")
    if expected_beer and normalize(beer_name) != normalize(expected_beer):
        raise BeerDetailError("Beer detail heading does not match the selected candidate")

    brewery = (
        brewery_from_search
        or "Unknown"
    )

    rating_match = re.search(
        r"\((\d\.\d{1,3})\)"
        r"\s*"
        r"([\d,]+)"
        r"\s+Ratings",
        body,
        re.IGNORECASE,
    )

    if rating_match:
        rating = float(
            rating_match.group(1)
        )

        ratings_count = int(
            rating_match
            .group(2)
            .replace(",", "")
        )
    else:
        rating = None
        ratings_count = None

    abv_match = re.search(
        r"(\d+(?:\.\d+)?)%"
        r"\s+ABV",
        body,
        re.IGNORECASE,
    )

    abv = (
        abv_match.group(1) + "%"
        if abv_match
        else None
    )

    ibu_match = re.search(
        r"(\d+(?:\.\d+)?)"
        r"\s+IBU",
        body,
        re.IGNORECASE,
    )

    ibu = (
        ibu_match.group(1)
        if ibu_match
        else None
    )

    info = {
        "beer": beer_name,
        "brewery": brewery,
        "rating": rating,
        "ratings": ratings_count,
        "abv": abv,
        "ibu": ibu,
        "url": beer_url,
    }

    if extraction_started is not None:
        _record_detail_extraction_timing(
            beer_name,
            perf_counter() - extraction_started,
        )

    return info

def probe_algolia_sort(page, query, target_label="Highest ABV"):
    """Diagnostic-only probe for Untappd's browser-exposed search sort.

    Performs one normal search, then selects the requested sort option from
    the page UI and reports the sanitized Algolia request difference. This is
    intentionally separate from matching logic: v36 uses it only to discover
    how Untappd expresses a supported sort before we rely on it.
    """
    events = []

    def record_request(request):
        try:
            if (
                "algolia.net/1/indexes" not in request.url.lower()
                or request.method.upper() != "POST"
            ):
                return
            parsed = _parse_algolia_request_body(request.post_data)
            events.append({
                "url": request.url,
                "requests": parsed,
            })
        except Exception:
            pass

    page.on("request", record_request)
    try:
        page.goto(
            "https://untappd.com/search",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        search_box = page.locator(
            'input[placeholder*="Search beers"], '
            'input[placeholder*="Find a drink"]'
        ).last
        if search_box.count() == 0:
            print("Sort probe failed: search box not found")
            return False

        search_box.fill(query)
        _run_and_wait_for_algolia_response(
            page,
            query,
            lambda: search_box.press("Enter"),
        )

        def matching_request(start=0):
            target = normalize(query)
            for event in reversed(events[start:]):
                for req in event.get("requests") or []:
                    if normalize(req.get("query") or "") == target:
                        return req
            return None

        baseline = matching_request()
        before_count = len(events)

        sort_select = None
        available_options = []
        selects = page.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            try:
                options = sel.locator("option")
                labels = [
                    (options.nth(j).inner_text() or "").strip()
                    for j in range(options.count())
                ]
            except Exception:
                continue
            if target_label in labels:
                sort_select = sel
                available_options = labels
                break

        print()
        print("Algolia sort probe")
        print(f"  query: {query}")
        if baseline:
            print("  baseline request:")
            print(f"    index: {baseline.get('indexName')!r}")
            print(f"    page: {baseline.get('page')!r}")
            print(f"    hitsPerPage: {baseline.get('hitsPerPage')!r}")
            print(f"    filters: {baseline.get('filters')!r}")
        else:
            print("  baseline request: not captured")

        if sort_select is None:
            print(f"  sort control with option {target_label!r}: not found")
            if available_options:
                print(f"  observed options: {available_options}")
            return False

        print(f"  sort option found: {target_label}")
        print(f"  available sort options: {', '.join(available_options)}")

        _run_and_wait_for_algolia_response(
            page,
            query,
            lambda: sort_select.select_option(label=target_label),
        )
        sorted_req = matching_request(before_count)

        if not sorted_req:
            print("  sorted Algolia request: not captured")
            return False

        print("  sorted request:")
        print(f"    index: {sorted_req.get('indexName')!r}")
        print(f"    page: {sorted_req.get('page')!r}")
        print(f"    hitsPerPage: {sorted_req.get('hitsPerPage')!r}")
        print(f"    filters: {sorted_req.get('filters')!r}")

        base_params = baseline.get("params") if baseline else {}
        sorted_params = sorted_req.get("params") or {}
        changed = []
        for key in sorted(set(base_params) | set(sorted_params)):
            a = base_params.get(key)
            b = sorted_params.get(key)
            if a != b:
                changed.append((key, a, b))

        print("  request differences:")
        if baseline and baseline.get("indexName") != sorted_req.get("indexName"):
            print(
                f"    indexName: {baseline.get('indexName')!r} -> "
                f"{sorted_req.get('indexName')!r}"
            )
        if changed:
            for key, a, b in changed:
                print(f"    {key}: {a!r} -> {b!r}")
        elif baseline and baseline.get("indexName") == sorted_req.get("indexName"):
            print("    no parsed index/parameter change detected")

        print()
        print(
            "Probe complete. No matcher scoring, ambiguity, or expansion "
            "behavior was changed."
        )
        return True
    finally:
        try:
            page.remove_listener("request", record_request)
        except Exception:
            pass


def open_search_box(page):
    """Open Untappd search and return the current search-box locator, if any."""
    page.goto(
        "https://untappd.com/search",
        wait_until="domcontentloaded",
        timeout=30000,
    )

    search_box = page.locator(
        'input[placeholder*="Search beers"], '
        'input[placeholder*="Find a drink"]'
    ).last

    if search_box.count() == 0:
        return None

    return search_box


def start_search_network_capture(page, include_search_urls=False):
    """Attach the same request/response capture used by the validated matcher."""
    request_events = []
    response_events = []
    network_events = []

    def _is_relevant(url):
        if include_search_urls:
            return _looks_search_related_url(url)
        return bool(url) and "algolia.net/1/indexes" in url.lower()

    def _record_request(request):
        try:
            if not _is_relevant(request.url):
                return
            if (
                not include_search_urls
                and request.method.upper() != "POST"
            ):
                return

            event = {
                "kind": "request",
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
            }

            if (
                "algolia.net/1/indexes" in request.url.lower()
                and request.method.upper() == "POST"
            ):
                try:
                    event["algolia_requests"] = _parse_algolia_request_body(
                        request.post_data
                    )
                except Exception:
                    event["algolia_requests"] = []

                try:
                    event["headers"] = {
                        k.lower(): v
                        for k, v in request.headers.items()
                    }
                except Exception:
                    event["headers"] = {}

                _note_algolia_request()

            request_events.append(event)
            network_events.append(event)
        except Exception:
            pass

    def _record_response(response):
        try:
            if not _is_relevant(response.url):
                return
            if (
                not include_search_urls
                and response.request.method.upper() != "POST"
            ):
                return

            event = {
                "kind": "response",
                "method": response.request.method,
                "url": response.url,
                "status": response.status,
                "resource_type": response.request.resource_type,
            }

            if (
                "algolia.net/1/indexes" in response.url.lower()
                and response.request.method.upper() == "POST"
            ):
                try:
                    event["algolia_requests"] = _parse_algolia_request_body(
                        response.request.post_data
                    )
                except Exception:
                    event["algolia_requests"] = []

                try:
                    event["algolia_response"] = _summarize_algolia_response(
                        response.json()
                    )
                except Exception as exc:
                    event["algolia_response"] = []
                    if include_search_urls:
                        event["algolia_response_error"] = str(exc)

            response_events.append(event)
            network_events.append(event)
        except Exception:
            pass

    page.on("request", _record_request)
    page.on("response", _record_response)

    return {
        "request_events": request_events,
        "response_events": response_events,
        "network_events": network_events,
        "request_listener": _record_request,
        "response_listener": _record_response,
    }


def stop_search_network_capture(page, capture):
    try:
        page.remove_listener("request", capture["request_listener"])
        page.remove_listener("response", capture["response_listener"])
    except Exception:
        pass


def _is_matching_algolia_response(response, query):
    """Return True for the Algolia POST response belonging to *query*."""
    try:
        request = response.request
        if (
            "algolia.net/1/indexes" not in response.url.lower()
            or request.method.upper() != "POST"
        ):
            return False
        target = normalize(query)
        return any(
            normalize(req.get("query") or "") == target
            for req in _parse_algolia_request_body(request.post_data)
        )
    except Exception:
        return False


def _run_and_wait_for_algolia_response(page, query, action):
    """Run a UI action and wait for its exact Algolia search response."""
    with page.expect_response(
        lambda response: _is_matching_algolia_response(response, query),
        timeout=SEARCH_RESPONSE_TIMEOUT_MS,
    ):
        action()


def submit_search(page, search_box, query):
    def _submit_action():
        # Untappd may issue its live Algolia request while the field is being
        # filled, before Enter is pressed. Keep the response listener active
        # across the whole UI action so that fast live-search responses cannot
        # race ahead of expect_response().
        search_box.fill(query)
        search_box.press("Enter")

    if not _SEARCH_TIMING_ENABLED:
        _run_and_wait_for_algolia_response(
            page,
            query,
            _submit_action,
        )
        return

    started = perf_counter()
    try:
        _run_and_wait_for_algolia_response(
            page,
            query,
            _submit_action,
        )
    except Exception:
        _record_search_timing(
            query,
            perf_counter() - started,
            outcome="error",
        )
        raise
    else:
        _record_search_timing(
            query,
            perf_counter() - started,
        )




def untappd_browser_page():
    """Context manager yielding the configured Untappd Playwright page."""
    from contextlib import contextmanager

    @contextmanager
    def _open():
        # Deliberately imported lazily so local parser/preflight workflows remain
        # browser-free and malformed menus fail before Playwright is loaded.
        from playwright.sync_api import Error, sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Error as exc:
                if "Executable doesn't exist" not in str(exc):
                    raise
                raise BrowserUnavailableError(
                    "Untap's Chromium browser is not installed. "
                    "Run untap-install-browser, then retry. "
                    "From a source checkout, run python3 -m playwright install chromium "
                    "using the same Python environment as Untap."
                ) from None
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/126 Safari/537.36"
                )
            )
            try:
                yield page
            finally:
                browser.close()

    return _open()
