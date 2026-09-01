import csv
import unicodedata
from time import perf_counter
from typing import Any, List, Mapping, Optional, Sequence, TypedDict, Union, cast

from untap_types import MatchResult, NormalizedMenuRecord

from untap_matcher import (
    DEFAULT_MIN_SCORE,
    search_one,
    get_last_matcher_timing_seconds,
    reset_matcher_timing_stats,
)
from untap_untappd import _reset_run_algolia_debug_stats, debug_timing_enabled


CSV_FIELDS = (
    "original_menu_text",
    "input_brewery",
    "input_beer",
    "input_abv",
    "input_style",
    "query",
    "status",
    "beer",
    "brewery",
    "rating",
    "ratings",
    "abv",
    "ibu",
    "type_name",
    "score",
    "reason",
    "alternatives",
    "url",
)

class _BatchTimingStats(TypedDict):
    count: int
    total_item_seconds: float
    min_item_seconds: Optional[float]
    max_item_seconds: Optional[float]
    batch_seconds: float
    outside_matcher_seconds: float


_BATCH_TIMING_STATS: _BatchTimingStats = {
    "count": 0,
    "total_item_seconds": 0.0,
    "min_item_seconds": None,
    "max_item_seconds": None,
    "batch_seconds": 0.0,
    "outside_matcher_seconds": 0.0,
}


def reset_batch_timing_stats() -> None:
    _BATCH_TIMING_STATS.update({
        "count": 0,
        "total_item_seconds": 0.0,
        "min_item_seconds": None,
        "max_item_seconds": None,
        "batch_seconds": 0.0,
        "outside_matcher_seconds": 0.0,
    })


def get_batch_timing_stats():
    return dict(_BATCH_TIMING_STATS)


def _record_item_timing(
    query: str,
    elapsed_seconds: float,
    resumed: bool = False,
    matcher_seconds: Optional[float] = None,
) -> None:
    stats = _BATCH_TIMING_STATS
    stats["count"] += 1
    stats["total_item_seconds"] += elapsed_seconds
    current_min = stats["min_item_seconds"]
    current_max = stats["max_item_seconds"]
    stats["min_item_seconds"] = (
        elapsed_seconds if current_min is None else min(current_min, elapsed_seconds)
    )
    stats["max_item_seconds"] = (
        elapsed_seconds if current_max is None else max(current_max, elapsed_seconds)
    )
    status_suffix = " [resumed]" if resumed else ""
    if matcher_seconds is not None:
        outside_matcher = max(0.0, elapsed_seconds - matcher_seconds)
        stats["outside_matcher_seconds"] += outside_matcher
        print(
            f"[timing] batch overhead outside matcher: {outside_matcher:.3f}s | {query}"
        )
    print(f"[timing] item total: {elapsed_seconds:.3f}s{status_suffix} | {query}")


def print_batch_timing_summary() -> None:
    if not debug_timing_enabled():
        return

    stats = _BATCH_TIMING_STATS
    count = stats["count"]
    print()
    print("Batch timing summary")
    print("=" * 70)
    if not count:
        print("No timed batch items.")
        return

    total = stats["total_item_seconds"]
    print(f"Timed batch items: {count}")
    print(f"Total per-item elapsed time: {total:.3f}s")
    print(f"Average item elapsed time: {total / count:.3f}s")
    print(f"Fastest item elapsed time: {stats['min_item_seconds']:.3f}s")
    print(f"Slowest item elapsed time: {stats['max_item_seconds']:.3f}s")
    print(f"Whole batch elapsed time: {stats['batch_seconds']:.3f}s")
    print(f"Batch overhead outside matcher: {stats['outside_matcher_seconds']:.3f}s")


# ============================================================
# Batch / persistence layer
# ============================================================
# v59: batch iteration, CSV persistence, and occurrence-aware resume/cache
# handling moved here from untap.py without intended behavior changes.
# This module consumes already-normalized menu records or plain query strings;
# it does not parse raw menu text and it does not perform direct browser or
# Algolia transport operations.


def _format_candidate_list(items):
    """
    Render a list of candidate dicts (as produced for "alternatives" /
    "same_abv_variants") into a single readable CSV cell, e.g.:
      "Fresh (0.612, 6.5%); Fresh - Hazy (0.598, 6.5%)"
    """
    if not items:
        return ""

    parts = []

    for item in items[:5]:
        name = item.get("name") or ""
        score = item.get("score")
        abv = item.get("abv")

        score_str = f"{score:.3f}" if score is not None else "N/A"
        abv_str = f"{abv:g}%" if abv is not None else "N/A"

        parts.append(f"{name} ({score_str}, {abv_str})")

    return "; ".join(parts)


def _csv_float(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _csv_int(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _resume_text_key(value):
    return " ".join(
        unicodedata.normalize("NFC", str(value or "")).split()
    ).casefold()


def _resume_abv_key(value):
    if value is None or str(value).strip() == "":
        return ""
    try:
        return f"{float(str(value).replace(',', '.').replace('%', '').strip()):.4f}"
    except ValueError:
        return _resume_text_key(value)


def _menu_resume_identity(brewery, beer, menu_abv, style):
    return (
        _resume_text_key(brewery),
        _resume_text_key(beer),
        _resume_abv_key(menu_abv),
        _resume_text_key(style),
    )


def load_resume_csv(filename):
    """Load confirmed rows from an earlier CSV for occurrence-aware reuse.

    v52 CSVs carry the parsed menu identity explicitly. Older v51 CSVs can
    still be reused via exact original_menu_text, but only status=ok rows are
    restored because ambiguity alternatives are not losslessly serialized.
    """
    by_identity = {}
    by_original_legacy = {}

    with open(filename, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"original_menu_text", "status", "beer", "brewery"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                "resume CSV is missing required columns: "
                + ", ".join(sorted(required - set(reader.fieldnames or [])))
            )

        identity_fields = {
            "input_brewery", "input_beer", "input_abv", "input_style"
        }
        has_identity_columns = identity_fields.issubset(
            set(reader.fieldnames or [])
        )

        for row in reader:
            if (row.get("status") or "").strip() != "ok":
                continue

            original = (row.get("original_menu_text") or "").strip()
            if not original:
                continue

            result = {
                "original_menu_text": original,
                "query": row.get("query") or "",
                "status": "ok",
                "beer": row.get("beer") or "Unknown",
                "brewery": row.get("brewery") or "Unknown",
                "rating": _csv_float(row.get("rating")),
                "ratings": _csv_int(row.get("ratings")),
                "abv": row.get("abv") or None,
                "ibu": row.get("ibu") or None,
                "type_name": row.get("type_name") or None,
                "score": _csv_float(row.get("score")),
                "url": row.get("url") or None,
                "resumed": True,
            }

            if has_identity_columns:
                identity = _menu_resume_identity(
                    row.get("input_brewery"),
                    row.get("input_beer"),
                    row.get("input_abv"),
                    row.get("input_style"),
                )
                by_identity.setdefault(identity, []).append(result)
            else:
                by_original_legacy.setdefault(original, []).append(result)

    return {
        "by_identity": by_identity,
        "by_original_legacy": by_original_legacy,
    }


def save_csv(results: Sequence[MatchResult], filename: str) -> None:
    fields = CSV_FIELDS

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for r in results:
            # CSV_FIELDS is dynamic at runtime, so view the TypedDict through a
            # generic mapping for schema-driven serialization.
            r_mapping = cast(Mapping[str, Any], r)
            row = {
                field: r_mapping.get(
                    field,
                    "",
                )
                for field in fields
            }

            # "ok" results already have a confirmed "beer" field. Everything
            # else (ambiguous / low_confidence / failed) only ever stored the
            # best guess under "match" -- surface it in "beer" instead of
            # leaving the row blank.
            if not row["beer"] and r.get("match"):
                row["beer"] = r["match"]

            # Prefer same-ABV-family variants when present (they are the
            # more specific ambiguity explanation); fall back to the
            # general "alternatives" list otherwise.
            row["alternatives"] = _format_candidate_list(
                r.get("same_abv_variants") or r.get("alternatives") or []
            )

            writer.writerow(row)

    print()
    print(
        f"Saved CSV: {filename}"
    )


# ============================================================
# Input modes
# ============================================================

def read_queries_from_file(filename: str) -> List[str]:
    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as f:
        return [
            line.strip()
            for line in f
            if line.strip()
        ]


def run_batch(
    page: Any,
    items: Sequence[Union[NormalizedMenuRecord, str]],
    min_score: float = DEFAULT_MIN_SCORE,
    debug: bool = False,
    resume_rows: Optional[Mapping[str, Any]] = None,
) -> List[MatchResult]:
    _reset_run_algolia_debug_stats()
    reset_batch_timing_stats()
    reset_matcher_timing_stats()
    timing_enabled = debug_timing_enabled()
    batch_started = perf_counter() if timing_enabled else None
    results = []
    resume_rows = resume_rows or {}
    resume_by_identity = {
        key: list(value)
        for key, value in (resume_rows.get("by_identity") or {}).items()
    }
    resume_by_original_legacy = {
        key: list(value)
        for key, value in (
            resume_rows.get("by_original_legacy") or {}
        ).items()
    }

    total = len(items)

    for i, item in enumerate(
        items,
        start=1,
    ):
        item_started = perf_counter() if timing_enabled else None
        if isinstance(item, dict):
            query = item["query"]
            original = item.get("original")
            expected_beer = item.get("beer")
            expected_brewery = item.get("brewery")
            expected_abv = item.get("menu_abv")
            expected_style = item.get("style")
        else:
            query = item
            original = None
            expected_beer = None
            expected_brewery = None
            expected_abv = None
            expected_style = None

        input_identity = None
        if isinstance(item, dict):
            input_identity = _menu_resume_identity(
                expected_brewery, expected_beer, expected_abv, expected_style
            )

        resumed_result = None
        if input_identity is not None and resume_by_identity.get(input_identity):
            resumed_result = resume_by_identity[input_identity].pop(0)
        elif original and resume_by_original_legacy.get(original):
            resumed_result = resume_by_original_legacy[original].pop(0)

        if resumed_result is not None:
            print(
                f"[{i}/{total}] "
                f"Resuming: {query} (already confirmed)"
            )
            # Keep the current parser-generated query/original text authoritative
            # while reusing the previously confirmed Untappd result payload.
            resumed_result["query"] = query
            resumed_result["original_menu_text"] = original
            resumed_result["input_brewery"] = expected_brewery or ""
            resumed_result["input_beer"] = expected_beer or ""
            resumed_result["input_abv"] = (
                "" if expected_abv is None else f"{expected_abv:g}"
            )
            resumed_result["input_style"] = expected_style or ""
            results.append(resumed_result)
            if item_started is not None:
                _record_item_timing(
                    query, perf_counter() - item_started, resumed=True
                )
            continue

        print(
            f"[{i}/{total}] "
            f"Searching: {query}"
        )

        result: MatchResult
        try:
            result = search_one(
                page,
                query,
                min_score=min_score,
                debug=debug,
                expected_beer=expected_beer,
                expected_brewery=expected_brewery,
                expected_abv=expected_abv,
                expected_style=expected_style,
            )

        except Exception as e:
            result = {
                "query": query,
                "status": "failed",
                "reason": str(e),
            }

        if original:
            result[
                "original_menu_text"
            ] = original

        if isinstance(item, dict):
            result["input_brewery"] = expected_brewery or ""
            result["input_beer"] = expected_beer or ""
            result["input_abv"] = (
                "" if expected_abv is None else f"{expected_abv:g}"
            )
            result["input_style"] = expected_style or ""

        if result.get("status") == "rate_limited":
            result["batch_remaining"] = total - i
            results.append(result)
            if item_started is not None:
                _record_item_timing(
                    query,
                    perf_counter() - item_started,
                    matcher_seconds=get_last_matcher_timing_seconds(),
                )
            break

        results.append(result)
        if item_started is not None:
            _record_item_timing(
                query,
                perf_counter() - item_started,
                matcher_seconds=get_last_matcher_timing_seconds(),
            )

    if batch_started is not None:
        _BATCH_TIMING_STATS["batch_seconds"] = perf_counter() - batch_started

    return results


def reusable_resume_count(resume_rows):
    """Return the number of confirmed cached rows available for reuse."""
    resume_rows = resume_rows or {}
    return sum(
        len(rows)
        for bucket in resume_rows.values()
        for rows in bucket.values()
    )
