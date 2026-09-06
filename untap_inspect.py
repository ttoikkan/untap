"""Read-only inspection of Untappd Algolia beer-search responses."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence

from untap_matcher import _run_page0_search_transport
from untap_parser import MenuValidationError, normalize, read_validated_menu
from untap_untappd import (
    MAX_ALGOLIA_EXPANSION_PAGES,
    _fetch_algolia_page,
    _matching_algolia_initial_page,
    reset_search_transport_authority_state,
    untappd_browser_page,
)


INTERESTING_FIELDS = (
    "beer_name", "brewery_name", "beer_abv", "type_name",
    "rating_score", "rating_count", "in_production", "index_date",
    "popularity", "alias_alt", "spelling_alt", "beer_label",
    "beer_label_hd", "brewery_label", "homebrew", "beer_ibu",
    "parent_style_id", "parent_style_is_beer", "has_community_award",
    "community_awards",
)


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _compact(value: Any, limit: int = 180) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= limit else rendered[:limit - 1] + "…"


def field_inventory(inspections: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Summarize presence and raw JSON types without interpreting semantics."""
    hits = [hit for item in inspections for hit in item.get("hits", [])]
    fields = sorted({key for hit in hits for key in hit})
    inventory = []
    for field in fields:
        values = [hit[field] for hit in hits if field in hit]
        samples = []
        for value in values:
            sample = _compact(value)
            if sample not in samples:
                samples.append(sample)
            if len(samples) == 3:
                break
        inventory.append({
            "field": field,
            "present": len(values),
            "hits": len(hits),
            "types": sorted({_value_type(value) for value in values}),
            "samples": samples,
        })
    return inventory


def render_summary(inspections: Sequence[Dict[str, Any]]) -> str:
    lines = ["Untappd Algolia inspection", "=" * 27, ""]
    for item in inspections:
        lines.append(f"Query: {item['query']}")
        lines.append(f"Transport: {item['transport']}")
        if item.get("error"):
            lines.append(f"Error: {item['error']}")
        else:
            lines.append(
                f"Pages inspected: {item.get('pages_inspected', 1)}/{item['nbPages']} · "
                f"{len(item['hits'])}/{item['nbHits']} hits captured"
                + (" · capped" if item.get("capped") else "")
            )
            for index, hit in enumerate(item["hits"], start=1):
                lines.append(
                    f"  {index}. {hit.get('brewery_name') or 'Unknown brewery'} — "
                    f"{hit.get('beer_name') or 'Unknown beer'}"
                )
                for field in INTERESTING_FIELDS:
                    if field in hit:
                        value = hit[field]
                        lines.append(
                            f"     {field} [{_value_type(value)}]: {_compact(value)}"
                        )
        lines.append("")

    lines.extend(["Field inventory", "=" * 15])
    for inventory_item in field_inventory(inspections):
        lines.append(
            f"{inventory_item['field']}: {inventory_item['present']}/{inventory_item['hits']} hits · "
            f"types {', '.join(inventory_item['types']) or 'none'}"
        )
        for sample in inventory_item["samples"]:
            lines.append(f"  sample: {sample}")
    return "\n".join(lines) + "\n"


def _matching_replay_result(payload: Any, request_event: Any, query: str,
                            page_number: int) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(request_event, dict):
        return None
    requests = request_event.get("algolia_requests") or []
    results = payload.get("results") or []
    target = normalize(query)
    for index, request in enumerate(requests):
        if normalize(request.get("query") or "") != target or index >= len(results):
            continue
        result = results[index]
        if not isinstance(result, dict) or result.get("page") != page_number:
            continue
        request_index = request.get("indexName")
        if request_index and result.get("index") not in (None, request_index):
            continue
        return result
    return None


def inspect_query(page: Any, query: str, all_pages: bool = False) -> Dict[str, Any]:
    transport = _run_page0_search_transport(page, query)
    page_zero = _matching_algolia_initial_page(transport.get("events"), query)
    if page_zero is None:
        response_status = next(
            (event.get("status") for event in reversed(transport.get("events") or [])
             if event.get("kind") == "response"),
            None,
        )
        error = transport.get("error")
        if not error and response_status is not None:
            error = f"Algolia response HTTP {response_status}"
        return {
            "query": query,
            "transport": transport.get("transport"),
            "error": error or "No validated page-0 beer response",
            "hits": [],
        }
    hits = list(page_zero["hits"])
    pages_inspected = 1
    error = transport.get("error")
    requested_pages = min(page_zero["nbPages"], MAX_ALGOLIA_EXPANSION_PAGES)
    if all_pages and page_zero["nbPages"] > 1:
        request_event = transport.get("request_event")
        if request_event is None:
            error = "Cannot inspect additional pages without the captured request"
        else:
            for page_number in range(1, requested_pages):
                payload, page_error = _fetch_algolia_page(page, request_event, page_number)
                if page_error:
                    error = f"Page {page_number}: {page_error}"
                    break
                result = _matching_replay_result(payload, request_event, query, page_number)
                if result is None or not isinstance(result.get("hits"), list):
                    error = f"Page {page_number}: response could not be validated"
                    break
                if (result.get("nbHits") != page_zero["nbHits"]
                        or result.get("nbPages") != page_zero["nbPages"]
                        or result.get("hitsPerPage") != page_zero["hitsPerPage"]):
                    error = f"Page {page_number}: pagination metadata changed"
                    break
                hits.extend(result["hits"])
                pages_inspected += 1
    return {
        "query": query,
        "transport": transport.get("transport"),
        "error": error,
        "nbHits": page_zero["nbHits"],
        "nbPages": page_zero["nbPages"],
        "hitsPerPage": page_zero["hitsPerPage"],
        "pages_inspected": pages_inspected,
        "page_limit": MAX_ALGOLIA_EXPANSION_PAGES,
        "capped": bool(all_pages and page_zero["nbPages"] > MAX_ALGOLIA_EXPANSION_PAGES),
        "hits": hits,
    }


def _reserve_output_directory(label: str) -> Path:
    slug = re.sub(r"[^\w-]+", "-", label.lower())
    slug = re.sub(r"-+", "-", slug).strip("-_")[:80].rstrip("-_") or "inspection"
    root = Path("inspections")
    root.mkdir(exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d_%H%M%S}_{slug}"
    suffix = 0
    while True:
        destination = root / (stem if suffix == 0 else f"{stem}-{suffix}")
        try:
            destination.mkdir()
            return destination.resolve()
        except FileExistsError:
            suffix += 1


def _file_queries(filename: str) -> List[str]:
    return [line.strip() for line in Path(filename).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _menu_queries(filename: str) -> List[str]:
    _format, records = read_validated_menu(filename)
    return [record["query"] for record in records]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect raw page-zero beer hits without running the matcher."
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--query", action="append", help="search query; repeatable")
    inputs.add_argument("--file", help="UTF-8 file containing one query per line")
    inputs.add_argument("--menu", help="validated Untap menu file")
    parser.add_argument(
        "--all-pages", action="store_true",
        help=f"inspect serial result pages up to the {MAX_ALGOLIA_EXPANSION_PAGES}-page safety cap",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.query:
            queries = [query.strip() for query in args.query if query.strip()]
            label = queries[0] if len(queries) == 1 else "queries"
        elif args.file:
            queries = _file_queries(args.file)
            label = Path(args.file).stem
        else:
            queries = _menu_queries(args.menu)
            label = Path(args.menu).stem
    except (OSError, UnicodeDecodeError, MenuValidationError) as exc:
        print(f"Could not read inspection input: {exc}", file=sys.stderr)
        return 2
    if not queries:
        print("Inspection input contains no queries.", file=sys.stderr)
        return 2

    output = _reserve_output_directory(label)
    reset_search_transport_authority_state()
    inspections = []
    with untappd_browser_page() as page:
        for index, query in enumerate(queries, start=1):
            print(f"[{index}/{len(queries)}] Inspecting: {query}")
            item = inspect_query(page, query, all_pages=args.all_pages)
            inspections.append(item)
            if item.get("error"):
                print(f"  {item['error']}")
            if "429" in str(item.get("error") or ""):
                print("Stopping after HTTP 429.")
                break

    payload = {
        "format": "untap-algolia-inspection-v1",
        "scope": (
            f"beer hits from up to {MAX_ALGOLIA_EXPANSION_PAGES} serial pages; "
            "no matching or detail pages"
            if args.all_pages else
            "page-0 beer hits only; no matching, expansion, or detail pages"
        ),
        "queries": inspections,
        "field_inventory": field_inventory(inspections),
    }
    json_path = output / "hits.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    summary = render_summary(inspections)
    (output / "summary.txt").write_text(summary, encoding="utf-8")
    print()
    print(summary, end="")
    print(f"Inspection outputs: {output}")
    return 1 if any(item.get("error") for item in inspections) else 0


if __name__ == "__main__":
    raise SystemExit(main())
